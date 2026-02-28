#!/home/spedymax/venv/bin/python3
"""
update_summary.py — Автоматическое обновление chat-summary.md
Читает последние N сообщений из БД, просит Джарвиса обновить summary.
"""

import os
import sys
import logging
from datetime import datetime

import psycopg2
import httpx

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

# ── Настройки ────────────────────────────────────────────────────────────────

DB_CONFIG = {
    'dbname': 'server-tg-pisunchik',
    'user': 'postgres',
    'password': '123',
    'host': '127.0.0.1',
    'port': 5432,
}

JARVIS_URL   = 'http://127.0.0.1:18789/v1/chat/completions'
JARVIS_TOKEN = '***REMOVED***'

CHAT_SUMMARY_PATH = os.path.expanduser('~/.openclaw/workspace/memory/chat-summary.md')
MESSAGES_LIMIT    = 300  # сколько последних сообщений анализировать

# ── Функции ──────────────────────────────────────────────────────────────────

def fetch_recent_messages(limit: int = MESSAGES_LIMIT) -> list[str]:
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, message_text FROM messages ORDER BY timestamp DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
        # rows — новейшие первые, разворачиваем в хронологический порядок
        return [f"{r[0] or 'Аноним'}: {r[1]}" for r in reversed(rows)]
    finally:
        conn.close()


def load_summary() -> str:
    try:
        with open(CHAT_SUMMARY_PATH, encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        return ''


def save_summary(text: str):
    os.makedirs(os.path.dirname(CHAT_SUMMARY_PATH), exist_ok=True)
    with open(CHAT_SUMMARY_PATH, 'w', encoding='utf-8') as f:
        f.write(text)


def ask_jarvis_to_update(current_summary: str, messages: list[str]) -> str:
    history_text = '\n'.join(messages)
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    prompt = f"""[СЛУЖЕБНЫЙ ЗАПРОС — обновление долгосрочной памяти чата]

Ты Джарвис. Тебя попросили обновить файл chat-summary.md на основе последних сообщений группового чата.

== ТЕКУЩИЙ SUMMARY ==
{current_summary or '(пусто)'}

== ПОСЛЕДНИЕ {len(messages)} СООБЩЕНИЙ ==
{history_text}

== ИНСТРУКЦИЯ ==
Обнови summary. Правила:
- Сохрани всё важное из текущего summary: персонажи, правила, мемы, внутренние шутки, проекты, незакрытые темы
- Добавь новое что появилось в последних сообщениях: шутки, события, пари, внутренние мемы, новые темы
- Убери то, что явно устарело и больше не актуально
- Держи размер ~1000 токенов (около 750 слов) — выкидывай мелочь если перебор
- Обнови поле "Последнее обновление" на {now}
- Верни ТОЛЬКО текст нового summary в формате markdown, без пояснений, без обёртки в ```"""

    with httpx.Client() as client:
        r = client.post(
            JARVIS_URL,
            headers={'Authorization': f'Bearer {JARVIS_TOKEN}'},
            json={
                'model': 'openclaw:main',
                'user': 'summary-updater',
                'messages': [
                    {'role': 'user', 'content': prompt},
                ],
            },
            timeout=90,
        )
        r.raise_for_status()
        return r.json()['choices'][0]['message']['content']


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    logger.info('Начинаю обновление chat-summary.md...')

    try:
        messages = fetch_recent_messages()
    except Exception as e:
        logger.error(f'Не удалось прочитать сообщения из БД: {e}')
        sys.exit(1)

    logger.info(f'Загружено {len(messages)} сообщений из БД')

    current_summary = load_summary()
    logger.info(f'Текущий summary: {len(current_summary)} символов')

    try:
        new_summary = ask_jarvis_to_update(current_summary, messages)
    except Exception as e:
        logger.error(f'Ошибка запроса к Джарвису: {e}')
        sys.exit(1)

    logger.info(f'Новый summary: {len(new_summary)} символов')

    save_summary(new_summary)
    logger.info('chat-summary.md обновлён ✅')


if __name__ == '__main__':
    main()
