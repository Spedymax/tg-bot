#!/home/spedymax/venv/bin/python3
"""One-off: refresh chat-summary.md with N messages via Together.ai.

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
            # Exclude 2026-04-01 to 2026-04-05 — DB only has bot replies, no user messages
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


def update(current, messages):
    history = "\n".join(messages)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    prompt = (
        "[СЛУЖЕБНЫЙ ЗАПРОС — обновление долгосрочной памяти чата]\n\n"
        "== УЧАСТНИКИ ЧАТА ==\n"
        "- Макс (Max) — программист и геймер, создатель бота\n"
        "- Юра (Юрочка, Spatifilum) — геймер\n"
        "- Богдан (Бодя, @lofiSnitch) — учится в Германии\n"
        "- Кеша/Иннокентий (Jarvis в ТГ) — бот, четвёртый друг в чате\n"
        "Все мужчины. Используй правильный род!\n\n"
        "== ИСТОРИЯ ЛИЧНОСТЕЙ БОТА ==\n"
        "Бот менял личность несколько раз:\n"
        "- Зек — тюремный персонаж\n"
        "- Лисёнок-фембойчик\n"
        "- Омниссия из Warhammer 40K\n"
        "- Лолита (Ло, Лола) — девушка-персонаж, флиртовала с Богданом\n"
        "- Jarvis — дружелюбный ассистент, про-Украина (март 2026)\n"
        "- Кеша (Иннокентий) — четвёртый друг, свой в доску (с апреля 2026)\n"
        "В старых сообщениях бот может отвечать от имени Лолиты или Jarvis — это тот же бот.\n\n"
        "== ТЕКУЩИЙ SUMMARY ==\n"
        f"{current or '(пусто)'}\n\n"
        f"== ПОСЛЕДНИЕ {len(messages)} СООБЩЕНИЙ ==\n"
        f"{history}\n\n"
        "== ЗАДАЧА ==\n"
        "Перепиши summary на основе новых сообщений.\n\n"
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
        "- Выводы и 'анализ атмосферы'\n\n"
        "Формат:\n"
        "- Группируй по темам, не по хронологии\n"
        "- Помечай когда было актуально: (апрель 2026)\n"
        "- Размер: до 2000 слов. Лучше короче и по делу чем длинно и водянисто.\n"
        f"- Обнови 'Последнее обновление: {now}'\n"
        "- Верни ТОЛЬКО markdown текст, без обёртки в ```\n"
        "- Начни сразу с заголовка: # Chat Summary\n"
    )

    if not TOGETHER_API_KEY:
        logger.error("TOGETHER_API_KEY not set!")
        sys.exit(1)

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
                "max_tokens": 4000,
                "temperature": 0.4,
            },
            timeout=600,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        return text


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    logger.info(f"Fetching {limit} messages...")
    msgs = fetch(limit)
    logger.info(f"Got {len(msgs)} messages")
    current = load_summary()
    logger.info(f"Current summary: {len(current)} chars")
    logger.info("Sending to Together.ai (this may take a while)...")
    new = update(current, msgs)
    logger.info(f"New summary: {len(new)} chars")

    # Save to both temp and actual path
    with open("/tmp/new_summary.md", "w", encoding="utf-8") as f:
        f.write(new)
    logger.info("Saved to /tmp/new_summary.md")

    # Ask before overwriting
    print(f"\n{'=' * 60}")
    print(new)
    print(f"{'=' * 60}")
    print(f"\nOverwrite {SUMMARY_PATH}? [y/N] ", end="")
    if input().strip().lower() == "y":
        with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
            f.write(new)
        logger.info(f"Saved to {SUMMARY_PATH}")
    else:
        logger.info("Skipped. Check /tmp/new_summary.md")


if __name__ == "__main__":
    main()