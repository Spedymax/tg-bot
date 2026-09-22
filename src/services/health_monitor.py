import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from html import escape

import httpx

from config.settings import Settings

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Periodic self-health check that alerts admin on issues."""

    def __init__(self, bot, db_manager, player_service):
        self.bot = bot
        self.db = db_manager
        self.player_service = player_service
        self._task = None
        self._last_alert_time = 0
        self._alert_cooldown = 300  # 5 min between alerts
        self._ai_alerted: dict[str, float] = {}   # per-issue cooldown for slow-moving AI problems
        self._credits_checked = 0.0
        self._credits_left: float | None = None

    def start(self):
        """Start the health monitoring loop."""
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Health monitor started (interval: 5 min)")

    async def _monitor_loop(self):
        """Run health checks every 5 minutes."""
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes
                await self._check_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitor error: {e}")

    async def _check_health(self):
        """Run all health checks."""
        issues = []

        # Check database connectivity
        try:
            async with self.db.connection() as conn:
                cursor = await conn.execute("SELECT 1")
                await cursor.fetchone()
        except Exception as e:
            issues.append(f"Database: {e}")

        # Check Redis connectivity
        try:
            if self.player_service._redis:
                await self.player_service._redis.ping()
        except Exception as e:
            issues.append(f"Redis: {e}")

        # Check circuit breakers
        from services.circuit_breaker import ollama_breaker, gemini_breaker, together_breaker
        for name, breaker in [("Ollama", ollama_breaker), ("Gemini", gemini_breaker), ("Together", together_breaker)]:
            if breaker.state.value == "open":
                issues.append(f"{name} circuit breaker OPEN")

        # Check DB pool
        pool_status = self.db.get_pool_status()
        total_errors = pool_status.get('connection_errors', 0)
        new_errors = total_errors - getattr(self, '_previous_connection_errors', total_errors)
        self._previous_connection_errors = total_errors
        if new_errors > 10:
            issues.append(f"High DB connection errors since last check: {new_errors}")

        issues.extend(await self._ai_issues())

        # Alert if issues found
        if issues and (time.time() - self._last_alert_time > self._alert_cooldown):
            self._last_alert_time = time.time()
            alert_text = "<b>Health Check Alert</b>\n\n" + "\n".join(escape(issue) for issue in issues)
            try:
                await self.bot.send_message(Settings.ADMIN_IDS[0], alert_text)
                logger.warning(f"Health alert sent: {issues}")
            except Exception as e:
                logger.error(f"Failed to send health alert: {e}")


    AI_ALERT_COOLDOWN = 6 * 3600
    MAIN_CHAT_ID = -1001294162183

    async def _ai_issues(self) -> list[str]:
        """Slow-moving AI-stack problems: stale memory/summary jobs, failing persona route,
        OpenRouter credits running out. Each issue alerts at most once per AI_ALERT_COOLDOWN."""
        found: dict[str, str] = {}
        try:
            found.update(await self._check_ai_jobs())
        except Exception as e:
            logger.warning(f"AI health check failed: {e}")
        try:
            found.update(await self._check_openrouter_credits())
        except Exception as e:
            logger.warning(f"OpenRouter credit check failed: {e}")
        now = time.time()
        out = []
        for key, text in found.items():
            if now - self._ai_alerted.get(key, 0) > self.AI_ALERT_COOLDOWN:
                self._ai_alerted[key] = now
                out.append(text)
        return out

    async def _check_ai_jobs(self) -> dict[str, str]:
        issues: dict[str, str] = {}
        chat = self.MAIN_CHAT_ID
        recent = await self.db.execute_query(
            "SELECT COUNT(*) FROM messages WHERE chat_id = %s AND user_id <> 0 "
            "AND timestamp > NOW() - INTERVAL '24 hours'", (chat,))
        busy = bool(recent) and recent[0][0] >= 20

        state = await self.db.execute_query(
            "SELECT s.updated_at, (SELECT COUNT(*) FROM messages m WHERE m.chat_id = s.chat_id "
            "AND m.id > s.last_message_row_id AND m.user_id <> 0) "
            "FROM memory_extract_state s WHERE s.chat_id = %s", (chat,))
        if state and state[0][0] is not None:
            updated, pending = state[0]
            hours = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
            if hours > 24 and pending >= 20:
                issues["memory_stale"] = f"Memory v2: разбор не обновлялся {hours:.0f} ч, ждут {pending} сообщений"

        try:
            from handlers.moltbot_handlers import CHAT_SUMMARY_PATH
            age_h = (time.time() - os.path.getmtime(CHAT_SUMMARY_PATH)) / 3600
            if busy and age_h > 36:
                issues["summary_stale"] = f"Память чата (summary) не обновлялась {age_h:.0f} ч при живом чате"
        except FileNotFoundError:
            if busy:
                issues["summary_stale"] = "Память чата (summary) отсутствует при живом чате"

        errs = await self.db.execute_query(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE outcome LIKE 'error%%' OR outcome = 'empty') "
            "FROM llm_traces WHERE kind = 'persona' AND created_at > NOW() - INTERVAL '1 hour'")
        if errs and errs[0][0] >= 3 and errs[0][1] * 2 >= errs[0][0]:
            issues["persona_errors"] = f"Джарвис: {errs[0][1]} из {errs[0][0]} ответов за час с ошибкой/пустые"

        fallback = await self.db.execute_query(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE final_provider NOT ILIKE '%%xai%%' "
            "AND final_provider NOT ILIKE '%%openrouter%%') "
            "FROM llm_traces WHERE kind = 'persona' AND outcome = 'ok' AND created_at > NOW() - INTERVAL '6 hours'")
        if fallback and fallback[0][0] >= 5 and fallback[0][1] * 2 >= fallback[0][0]:
            issues["persona_fallback"] = (f"Джарвис: {fallback[0][1]} из {fallback[0][0]} ответов за 6 ч ушли "
                                          "в фоллбэк (основной маршрут OpenRouter/Grok не отвечает)")
        return issues

    async def _check_openrouter_credits(self) -> dict[str, str]:
        key = getattr(Settings, "OPENROUTER_API_KEY", None)
        if not key:
            return {}
        if time.time() - self._credits_checked > 3600:
            self._credits_checked = time.time()
            async with httpx.AsyncClient() as client:
                r = await client.get("https://openrouter.ai/api/v1/credits",
                                     headers={"Authorization": f"Bearer {key}"}, timeout=15)
                r.raise_for_status()
                data = r.json()["data"]
                self._credits_left = float(data["total_credits"]) - float(data["total_usage"])
        if self._credits_left is not None and self._credits_left < 1.5:
            return {"openrouter_credits": f"OpenRouter: осталось ${self._credits_left:.2f} — скоро Джарвис "
                                          "уйдёт на фоллбэк, пополни баланс"}
        return {}
