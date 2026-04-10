#!/home/spedymax/venv/bin/python3
"""Refresh chat-summary.md with N messages via Together.ai.
Splits into batches if too large for context window.

Usage:
    python update_summary_2k.py              # default 2000 messages
    python update_summary_2k.py 5000         # last 5000 messages
    python update_summary_2k.py 20000        # ~6 months
"""
import os
import re
import sys
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "server-tg-pisunchik"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "5432") or "5432"),
}
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY", "")
TOGETHER_MODEL = os.getenv("TOGETHER_MODEL", "Qwen/Qwen3-235B-A22B-Instruct-2507-tput")
SUMMARY_PATH = os.getenv("SUMMARY_PATH", "/home/spedymax/tg-bot/data/chat-summary.md")
CPH = ZoneInfo("Europe/Copenhagen")

BATCH_SIZE = 800  # messages per batch (~25K tokens, safe for 32K context)

MEMBERS_BLOCK = (
    "== УЧАСТНИКИ ЧАТА ==\n"
    "- Макс (Max) — программист и геймер, создатель бота, живёт в Дании\n"
    "- Юра (Юрочка, Spatifilum) — геймер\n"
    "- Богдан (Бодя, @lofiSnitch) — учится в Германии (Эрланген)\n"
    "- Шева — друг, иногда играет в доту с ребятами, не в чате\n"
    "- Кеша/Иннокентий (Jarvis в ТГ) — бот, четвёртый друг в чате\n"
    "Все мужчины. Используй правильный род!\n"
)

PERSONALITY_BLOCK = (
    "== ИСТОРИЯ ЛИЧНОСТЕЙ БОТА ==\n"
    "Бот менял личность несколько раз:\n"
    "- Зек — тюремный персонаж\n"
    "- Лисёнок-фембойчик\n"
    "- Омниссия из Warhammer 40K\n"
    "- Лолита (Ло, Лола) — девушка-персонаж, флиртовала с Богданом\n"
    "- Jarvis — дружелюбный ассистент, про-Украина (март 2026)\n"
    "- Кеша (Иннокентий) — четвёртый друг, свой в доску (с апреля 2026)\n"
    "В старых сообщениях бот может отвечать от имени Лолиты или Jarvis — это тот же бот.\n"
)

STYLE_BLOCK = (
    "Стиль:\n"
    "- Пиши как заметки для себя, не как статью. Коротко и по делу.\n"
    "- Без академизма, канцелярита и анализа 'динамики общения'\n"
    "- Формат: буллеты и короткие абзацы, не простыни текста\n\n"
    "Что сохранять:\n"
    "- Внутренние шутки, мемы, приколы — это самое важное\n"
    "- Кто что сказал если это важно или смешно\n"
    "- Пари, споры, незакрытые темы\n"
    "- Важные события (игры, фильмы, новости которые обсуждали)\n\n"
    "Что НЕ надо:\n"
    "- Бытовой мусор (привет/пока, тесты бота, технические сообщения)\n"
    "- Пересказ каждого сообщения — только суть\n"
    "- Выводы и 'анализ атмосферы'\n"
    "- НЕ интерпретируй и НЕ додумывай. Не пиши 'ирония', 'возможно отсылка к', 'неясно что именно'. Записывай факт как есть, без догадок.\n"
)


def fmt_ts(dt):
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(CPH).strftime("[%H:%M %d.%m]")


def fetch(limit=2000):
    conn = psycopg.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT name, message_text, timestamp FROM messages
                   WHERE NOT (timestamp >= '2026-04-01' AND timestamp < '2026-04-06')
                   ORDER BY timestamp DESC LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
        return [f"{fmt_ts(r[2])} {r[0] or 'Аноним'}: {r[1]}" for r in reversed(rows)]
    finally:
        conn.close()


def load_summary():
    try:
        with open(SUMMARY_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def call_together(prompt, max_tokens=4000):
    """Single Together.ai API call."""
    with httpx.Client() as client:
        r = client.post(
            "https://api.together.xyz/v1/chat/completions",
            headers={"Authorization": f"Bearer {TOGETHER_API_KEY}"},
            json={
                "model": TOGETHER_MODEL,
                "messages": [
                    {"role": "system", "content": "Ты обновляешь файл заметок о групповом чате. Пиши коротко и по делу."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.4,
            },
            timeout=600,
        )
        if r.status_code != 200:
            logger.error(f"Together.ai error {r.status_code}: {r.text[:500]}")
            r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        return text


def summarize_batch(messages, batch_num, total_batches):
    """Summarize a single batch of messages into compact notes."""
    history = "\n".join(messages)
    prompt = (
        f"[Батч {batch_num}/{total_batches} — извлеки ключевое из сообщений]\n\n"
        f"{MEMBERS_BLOCK}\n"
        f"{PERSONALITY_BLOCK}\n"
        f"== {len(messages)} СООБЩЕНИЙ ==\n"
        f"{history}\n\n"
        "== ЗАДАЧА ==\n"
        "Извлеки из этих сообщений всё важное и интересное.\n\n"
        f"{STYLE_BLOCK}\n"
        "Формат:\n"
        "- Группируй по темам\n"
        "- Помечай даты когда было актуально\n"
        "- Размер: до 800 слов\n"
        "- Верни ТОЛЬКО буллеты с заметками, без заголовков и обёрток\n"
    )
    return call_together(prompt, max_tokens=2000)


def merge_summaries(batch_summaries, current_summary):
    """Merge batch summaries + current summary into final summary."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    all_notes = "\n\n---\n\n".join(
        f"[Батч {i+1}]\n{s}" for i, s in enumerate(batch_summaries)
    )
    prompt = (
        "[СЛУЖЕБНЫЙ ЗАПРОС — финальная сборка summary]\n\n"
        f"{MEMBERS_BLOCK}\n"
        f"{PERSONALITY_BLOCK}\n"
        "== ТЕКУЩИЙ SUMMARY ==\n"
        f"{current_summary or '(пусто)'}\n\n"
        "== ЗАМЕТКИ ИЗ БАТЧЕЙ (хронологический порядок) ==\n"
        f"{all_notes}\n\n"
        "== ЗАДАЧА ==\n"
        "Собери финальный summary из заметок + текущего summary.\n"
        "Старое из текущего summary НЕ удаляй если оно не явно устарело. Добавь новое из батчей.\n\n"
        f"{STYLE_BLOCK}\n"
        "Формат:\n"
        "- Группируй по темам, не по хронологии\n"
        "- Помечай когда было актуально: (апрель 2026)\n"
        "- Объединяй дубликаты, убирай устаревшее\n"
        "- Размер: до 2000 слов\n"
        f"- Обнови 'Последнее обновление: {now}'\n"
        "- Верни ТОЛЬКО markdown текст, без обёртки в ```\n"
        "- Начни сразу с заголовка: # Chat Summary\n"
    )
    return call_together(prompt, max_tokens=4000)


def update(current, messages):
    """Process messages — single pass if small, batched if large."""
    if len(messages) <= BATCH_SIZE:
        logger.info(f"Small batch ({len(messages)} msgs), single pass")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        history = "\n".join(messages)
        prompt = (
            "[СЛУЖЕБНЫЙ ЗАПРОС — обновление долгосрочной памяти чата]\n\n"
            f"{MEMBERS_BLOCK}\n"
            f"{PERSONALITY_BLOCK}\n"
            "== ТЕКУЩИЙ SUMMARY ==\n"
            f"{current or '(пусто)'}\n\n"
            f"== ПОСЛЕДНИЕ {len(messages)} СООБЩЕНИЙ ==\n"
            f"{history}\n\n"
            "== ЗАДАЧА ==\n"
            "Перепиши summary на основе новых сообщений.\n\n"
            f"{STYLE_BLOCK}\n"
            "Формат:\n"
            "- Группируй по темам, не по хронологии\n"
            "- Помечай когда было актуально: (апрель 2026)\n"
            "- Размер: до 2000 слов. Лучше короче и по делу чем длинно и водянисто.\n"
            f"- Обнови 'Последнее обновление: {now}'\n"
            "- Верни ТОЛЬКО markdown текст, без обёртки в ```\n"
            "- Начни сразу с заголовка: # Chat Summary\n"
        )
        return call_together(prompt)

    # Split into batches
    batches = [messages[i:i + BATCH_SIZE] for i in range(0, len(messages), BATCH_SIZE)]
    logger.info(f"Large input ({len(messages)} msgs), splitting into {len(batches)} batches of ~{BATCH_SIZE}")

    batch_summaries = []
    for i, batch in enumerate(batches):
        logger.info(f"Processing batch {i+1}/{len(batches)} ({len(batch)} msgs)...")
        summary = summarize_batch(batch, i + 1, len(batches))
        logger.info(f"Batch {i+1} done: {len(summary)} chars")
        batch_summaries.append(summary)

    logger.info("Merging all batches into final summary...")
    return merge_summaries(batch_summaries, current)


def main():
    if not TOGETHER_API_KEY:
        logger.error("TOGETHER_API_KEY not set!")
        sys.exit(1)

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    logger.info(f"Fetching {limit} messages...")
    msgs = fetch(limit)
    logger.info(f"Got {len(msgs)} messages")
    current = load_summary()
    logger.info(f"Current summary: {len(current)} chars")
    logger.info("Processing...")
    new = update(current, msgs)
    logger.info(f"New summary: {len(new)} chars")

    with open("/home/spedymax/tg-bot/data/new_summary.md", "w", encoding="utf-8") as f:
        f.write(new)
    logger.info("Saved to /home/spedymax/tg-bot/data/new_summary.md")

    print(f"\n{'=' * 60}")
    print(new)
    print(f"{'=' * 60}")
    print(f"\nOverwrite {SUMMARY_PATH}? [y/N] ", end="")
    if input().strip().lower() == "y":
        with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
            f.write(new)
        logger.info(f"Saved to {SUMMARY_PATH}")
    else:
        logger.info("Skipped. Check /home/spedymax/tg-bot/data/new_summary.md")


if __name__ == "__main__":
    main()