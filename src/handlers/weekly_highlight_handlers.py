import json
import logging
import re
from zoneinfo import ZoneInfo

import httpx
import google.generativeai as genai
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import Settings
from services.circuit_breaker import ollama_breaker

logger = logging.getLogger(__name__)

CANDIDATE_COUNT = 5
MIN_MESSAGES_FOR_A_WEEK = 10
VOTERS_NEEDED_TO_CLOSE_EARLY = 3  # small chat — once this many distinct people voted, no reason to wait

PICK_SYSTEM_PROMPT = (
    "Ты помогаешь выбрать «высер недели» — самое смешное, абсурдное или "
    "токсично-эпичное сообщение из чата друзей за неделю. У тебя чёрный юмор "
    "и хороший вкус на подгонки. Отвечаешь только на русском."
)

CEREMONY_SYSTEM_PROMPT = (
    "Ты — голос бота в чате трёх друзей с чёрным юмором. Объявляешь победителя "
    "еженедельного голосования «высер недели» — конкурса на самое смешное/абсурдное "
    "сообщение недели. Тон: подкалывающий, слегка театральный, без вступлений и "
    "оправданий. 2-4 предложения. Только на русском."
)


class WeeklyHighlightHandlers:
    def __init__(self, bot, db_manager):
        self.bot = bot
        self.db = db_manager
        if Settings.GEMINI_API_KEY:
            genai.configure(api_key=Settings.GEMINI_API_KEY)
            self._gemini = genai.GenerativeModel('gemini-3-flash-preview')
        else:
            self._gemini = None
        self.router = Router()
        self._register()

    # ── LLM ─────────────────────────────────────────────────────────────────

    async def _call_llm(self, system_prompt: str | None, user_prompt: str) -> str:
        """Gemini first, Ollama fallback — same shape as CourtService._call_llm."""
        import asyncio
        if self._gemini:
            try:
                prompt = f"{system_prompt}\n\n{user_prompt}" if system_prompt else user_prompt
                response = await asyncio.to_thread(self._gemini.generate_content, prompt)
                result = response.text.strip()
                if result:
                    return result
            except Exception as e:
                logger.warning(f"WeeklyHighlight: Gemini error, falling back to Ollama: {e}")

        if not ollama_breaker.allow_request():
            logger.warning("WeeklyHighlight: Ollama circuit open, skipping LLM call")
            return ""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{Settings.LOCAL_LLM_URL}/api/chat",
                    json={"model": Settings.LOCAL_LLM_MODEL, "think": False, "stream": False, "messages": messages},
                    timeout=180,
                )
            r.raise_for_status()
            result = r.json()["message"]["content"].strip()
            ollama_breaker.record_success()
            return result
        except Exception as e:
            ollama_breaker.record_failure()
            logger.error(f"WeeklyHighlight: Ollama error: {e}")
            return ""

    # ── DB ──────────────────────────────────────────────────────────────────

    async def _ensure_table(self):
        try:
            await self.db.execute_query(
                "CREATE TABLE IF NOT EXISTS weekly_highlights ("
                "id SERIAL PRIMARY KEY, "
                "chat_id BIGINT NOT NULL, "
                "candidates JSONB NOT NULL, "
                "votes JSONB NOT NULL DEFAULT '{}', "
                "message_id BIGINT, "
                "status TEXT NOT NULL DEFAULT 'voting', "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
                (),
            )
        except Exception as e:
            logger.error(f"WeeklyHighlight: failed to create table: {e}")

    async def _get_voting_row(self, chat_id: int) -> dict | None:
        rows = await self.db.execute_query(
            "SELECT id, candidates, votes, message_id FROM weekly_highlights "
            "WHERE chat_id = %s AND status = 'voting' ORDER BY id DESC LIMIT 1",
            (chat_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return {"id": r[0], "candidates": r[1], "votes": r[2] or {}, "message_id": r[3]}

    # ── Candidate selection ─────────────────────────────────────────────────

    async def _fetch_week_messages(self) -> list[tuple]:
        """Raw (id, user_id, name, message_text) rows from the last 7 days.
        Note: `messages` has no chat_id column (same convention already used by
        MoltbotHandlers._send_weekly_analytics) — this bot only ever tracks one group."""
        rows = await self.db.execute_query(
            "SELECT id, user_id, name, message_text FROM messages "
            "WHERE timestamp > NOW() - INTERVAL '7 days' AND user_id != 0 "
            "ORDER BY timestamp",
            (),
        )
        return [r for r in (rows or []) if r[3] and not r[3].strip().startswith('/')]

    async def _pick_candidates(self, chat_id: int) -> list[dict]:
        rows = await self._fetch_week_messages()
        return await self._select_candidates(rows)

    async def _select_candidates(self, rows: list[tuple]) -> list[dict]:
        """Pure LLM-selection step, separated from the DB fetch so it can be
        exercised in tests against synthetic rows without touching real chat history."""
        if len(rows) < MIN_MESSAGES_FOR_A_WEEK:
            return []

        numbered = "\n".join(f"{i}. {r[2] or 'Аноним'}: {r[3]}" for i, r in enumerate(rows, 1))
        prompt = (
            f"Вот пронумерованные сообщения из чата за неделю:\n{numbered}\n\n"
            f"Выбери ровно {CANDIDATE_COUNT} номеров самых смешных, абсурдных или "
            f"эпично-токсичных сообщений (или меньше, если реально достойных меньше). "
            f"Ответь ТОЛЬКО номерами через запятую, без текста и пояснений. "
            f"Пример ответа: 3, 17, 22, 40, 55"
        )

        for attempt in range(2):
            raw = await self._call_llm(PICK_SYSTEM_PROMPT, prompt)
            indices = sorted(set(int(n) for n in re.findall(r"\d+", raw)))
            valid = [i for i in indices if 1 <= i <= len(rows)]
            if len(valid) >= 2:
                chosen = valid[:CANDIDATE_COUNT]
                return [
                    {"message_id": rows[i - 1][0], "user_id": rows[i - 1][1],
                     "name": rows[i - 1][2] or "Аноним", "text": rows[i - 1][3]}
                    for i in chosen
                ]
            logger.warning(f"WeeklyHighlight: pick attempt {attempt + 1} yielded {len(valid)} valid candidates, raw={raw[:200]!r}")
        return []

    # ── Posting ─────────────────────────────────────────────────────────────

    @staticmethod
    def _oneline(text: str, limit: int) -> str:
        """Collapse newlines/whitespace so a multi-line message doesn't break the
        «quote» formatting, then truncate with an ellipsis."""
        collapsed = " ".join(text.split())
        return collapsed[:limit] + ("…" if len(collapsed) > limit else "")

    def _build_vote_text(self, candidates: list[dict], votes: dict) -> str:
        counts = self._tally(candidates, votes)
        lines = ["🏆 <b>Высер недели</b> — голосуем за самый эпичный высер этой недели:\n"]
        for i, c in enumerate(candidates):
            quote = self._oneline(c["text"], 150)
            lines.append(f"{i + 1}. <b>{c['name']}</b>: «{quote}»  —  {counts[i]} 🗳")
        return "\n".join(lines)

    def _build_vote_markup(self, row_id: int, candidates: list[dict]) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🗳 Вариант {i + 1}", callback_data=f"turd_vote:{row_id}:{i}")]
            for i in range(len(candidates))
        ])

    @staticmethod
    def _tally(candidates: list[dict], votes: dict) -> list[int]:
        counts = [0] * len(candidates)
        for idx in votes.values():
            if isinstance(idx, int) and 0 <= idx < len(counts):
                counts[idx] += 1
        return counts

    async def post_weekly_highlight(self, chat_id: int):
        await self._ensure_table()
        try:
            candidates = await self._pick_candidates(chat_id)
            if not candidates:
                await self.bot.send_message(
                    chat_id,
                    "🏆 На этой неделе слишком тихо было — высер недели отменяется.",
                )
                return

            rows = await self.db.execute_query(
                "INSERT INTO weekly_highlights (chat_id, candidates, votes) VALUES (%s, %s, '{}') RETURNING id",
                (chat_id, json.dumps(candidates)),
            )
            row_id = rows[0][0]

            text = self._build_vote_text(candidates, {})
            markup = self._build_vote_markup(row_id, candidates)
            msg = await self.bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=markup)
            await self.db.execute_query(
                "UPDATE weekly_highlights SET message_id = %s WHERE id = %s", (msg.message_id, row_id),
            )
            logger.info(f"WeeklyHighlight: posted vote row={row_id} chat={chat_id} candidates={len(candidates)}")
        except Exception as e:
            logger.error(f"WeeklyHighlight: post_weekly_highlight failed: {e}", exc_info=True)

    # ── Voting ──────────────────────────────────────────────────────────────

    async def record_vote(self, row_id: int, user_id: int, idx: int) -> dict:
        """Persist one vote. Returns {'ok': bool, 'closed': bool, 'candidates', 'votes',
        'reason'} — 'closed' is True once VOTERS_NEEDED_TO_CLOSE_EARLY distinct people
        have voted, at which point the caller should announce right away."""
        rows = await self.db.execute_query(
            "SELECT candidates, votes FROM weekly_highlights WHERE id = %s AND status = 'voting'",
            (row_id,),
        )
        if not rows:
            return {"ok": False, "reason": "closed"}
        candidates, votes = rows[0][0], (rows[0][1] or {})
        if not (0 <= idx < len(candidates)):
            return {"ok": False, "reason": "stale_button"}

        votes[str(user_id)] = idx
        await self.db.execute_query(
            "UPDATE weekly_highlights SET votes = %s WHERE id = %s", (json.dumps(votes), row_id),
        )
        closed = len(votes) >= VOTERS_NEEDED_TO_CLOSE_EARLY
        return {"ok": True, "closed": closed, "candidates": candidates, "votes": votes}

    def _register(self):
        @self.router.callback_query(F.data.startswith("turd_vote:"))
        async def handle_vote(call: CallbackQuery):
            _, row_id_str, idx_str = call.data.split(":")
            row_id, idx = int(row_id_str), int(idx_str)

            result = await self.record_vote(row_id, call.from_user.id, idx)
            if not result["ok"]:
                msg = "Голосование уже закрыто." if result["reason"] == "closed" else "Устаревшая кнопка."
                await call.answer(msg, show_alert=True)
                return
            await call.answer("Голос учтён!")

            if result["closed"]:
                # Everyone who's going to vote has voted — announce right now
                # instead of making them wait for the Monday-evening backstop.
                await self.close_weekly_highlight(call.message.chat.id)
                return

            try:
                text = self._build_vote_text(result["candidates"], result["votes"])
                markup = self._build_vote_markup(row_id, result["candidates"])
                await call.message.edit_text(text, parse_mode='HTML', reply_markup=markup)
            except Exception as e:
                logger.warning(f"WeeklyHighlight: failed to update tally display: {e}")

    # ── Closing ─────────────────────────────────────────────────────────────

    async def close_weekly_highlight(self, chat_id: int):
        await self._ensure_table()
        try:
            row = await self._get_voting_row(chat_id)
            if not row:
                logger.info(f"WeeklyHighlight: no open vote to close for chat={chat_id}")
                return

            candidates, votes = row["candidates"], row["votes"]
            counts = self._tally(candidates, votes)
            top = max(counts) if counts else 0

            if top == 0:
                await self.bot.send_message(chat_id, "🏆 Никто не проголосовал — высер недели остаётся без победителя.")
            else:
                winners = [candidates[i] for i, c in enumerate(counts) if c == top]
                winners_desc = "\n".join(f"— {w['name']}: «{self._oneline(w['text'], 200)}»" for w in winners)
                is_tie = len(winners) > 1
                prompt = (
                    f"Победител{'и' if is_tie else 'ь'} голосования «высер недели» "
                    f"({'ничья между несколькими' if is_tie else 'один явный лидер'}, "
                    f"по {top} голос(ов)):\n{winners_desc}\n\n"
                    f"Объяви результат в своём стиле."
                )
                ceremony = await self._call_llm(CEREMONY_SYSTEM_PROMPT, prompt)
                if not ceremony:
                    ceremony = "Победител" + ("и определены" if is_tie else "ь определён") + f":\n{winners_desc}"
                await self.bot.send_message(chat_id, f"🏆 <b>Высер недели</b>\n\n{ceremony}", parse_mode='HTML')

            await self.db.execute_query(
                "UPDATE weekly_highlights SET status = 'finished' WHERE id = %s", (row["id"],),
            )
            logger.info(f"WeeklyHighlight: closed row={row['id']} chat={chat_id} top_votes={top}")
        except Exception as e:
            logger.error(f"WeeklyHighlight: close_weekly_highlight failed: {e}", exc_info=True)

    # ── Scheduler ───────────────────────────────────────────────────────────

    def start_scheduler(self, chat_id: int):
        """Normal path: voting closes the instant the 3rd person votes (see the
        callback handler). Monday 20:00 is just a backstop in case someone never
        gets around to voting — closes with whatever votes came in by then."""
        tz = ZoneInfo("Europe/Kiev")
        self._scheduler = AsyncIOScheduler(timezone=tz)
        self._scheduler.add_job(
            self.post_weekly_highlight, CronTrigger(day_of_week='sun', hour=21, minute=30, timezone=tz),
            args=[chat_id],
        )
        self._scheduler.add_job(
            self.close_weekly_highlight, CronTrigger(day_of_week='mon', hour=20, minute=0, timezone=tz),
            args=[chat_id],
        )
        self._scheduler.start()
        logger.info(
            f"WeeklyHighlight: scheduler started for chat {chat_id} "
            f"(post Sun 21:30, backstop close Mon 20:00 Europe/Kiev — normally closes as soon as all 3 vote)"
        )
