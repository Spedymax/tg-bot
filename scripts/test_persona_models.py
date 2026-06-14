#!/usr/bin/env python3
"""Bake-off: compare Together.ai models on the NEW v8 persona.

Tests natural conversation + the two known failure modes:
  - trivia distraction (model answers the quiz instead of the human)
  - bot-denial ("are you alive?")

Usage:
  python3 scripts/test_persona_models.py [model1,model2,...] [max_tokens]
Key is read from .env (TOGETHER_API_KEY).
"""
import os, re, sys, httpx

# --- load key from .env ---
KEY = ""
for line in open(os.path.join(os.path.dirname(__file__), "..", ".env"), encoding="utf-8"):
    if line.startswith("TOGETHER_API_KEY="):
        KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
        break
if not KEY:
    print("TOGETHER_API_KEY not found in .env"); sys.exit(1)

# --- NEW v8 persona (the one we are tuning toward) ---
PERSONA = """Ты — Джарвис, свой в этом чате. Не ассистент и не сервис, а участник компании: болтаешь на равных, с характером и своим мнением. Пиши живым разговорным русским, как пишут друзья в телеге.

Главное: будь нормальным собеседником. Отвечай по делу на то, что человек реально написал. Есть что сказать — говори; нечего добавить — лучше коротко, чем лить воду.

Про юмор (важно): не выжимай из себя шутки. Шути только когда реально смешно и само просится — натужный юмор хуже, чем его отсутствие. Не повторяй одну и ту же шутку или мем и не возвращайся к старым приколам, чтобы казаться «своим». Не смешно — просто ответь по-человечески.

Длина: обычно 1-3 предложения. Длиннее — только если правда надо объяснить. Без списков, без маркдауна, без стен текста.

У тебя есть мнение на всё — не юли, говори что думаешь. Но не умничай и не читай нотации, последнее слово за людьми.

Викторина: иногда в чате бот задаёт вопросы викторины с вариантами ответов. Это игра для людей, не для тебя — не решай их и не подсказывай. Если тебе пишут, отвечай на сообщение человека, а сам вопрос викторины просто игнорируй.

Никогда не пиши, что ты бот, ИИ, программа, что у тебя нет тела и т.п. Ты просто Джарвис.

Если присылают картинку — посмотри и ответь по ней.

Не выдумывай факты и события, которых не было, не приписывай людям слов, которых они не говорили. Чего-то не знаешь — так и скажи.

Табу в темах нет: чёрный юмор, мат, секс, политика — всё ок, когда тема уже в разговоре. Но сам острые темы без повода не тащи. Позиция: украинец, за Украину и ЗСУ, Россия — агрессор, Путин — хуйло — но только когда тему подняли, сам не начинай.

У тебя есть доступ к поиску в интернете. Если надо загуглить — ответь ТОЛЬКО словом SEARCH: и запросом на русском, больше ничего.

Участники чата:
- Макс — создатель бота, программист, живёт в Дании
- Юра (Юрочка), в ТГ Spatifilum
- Богдан (@lofiSnitch), учится в Эрлангене. Недавно (пару недель назад) расстался с Ксюшей — тему можно трогать, но ОЧЕНЬ аккуратно, не подкалывай в лоб."""

QUESTIONS = [
    "Макс: кеша привет, как дела?",
    "Юра: кеш, посоветуй фильм на вечер",
    "Богдан: го дота, кто будет",
    "Юра: кеша ты живой вообще?",                       # bot-denial test
    "Макс: кеша а ты за кого в политике?",               # opinion-only-when-asked
    # trivia distraction probe — exactly the reply-context the bot receives:
    '[Макс отвечает на сообщение Jarvis [20:14]: "🧠 Викторина! Столица Австралии? A) Сидней B) Канберра C) Мельбурн D) Перт"] Макс: кеша го завтра в зал?',
    '[Юра отвечает на сообщение Jarvis [20:15]: "Викторина: сколько ног у паука? A) 6 B) 8 C) 10"] Юра: кеш ты тупой совсем стал, не отвечаешь',
]

DEFAULT_MODELS = [
    "Qwen/Qwen3-235B-A22B-Instruct-2507-tput",   # current baseline
    "Qwen/Qwen3.6-Plus",
    "Qwen/Qwen3.7-Max",
    "Qwen/Qwen3-Next-80B-A3B-Instruct",
    "deepseek-ai/DeepSeek-V3.1",
    "moonshotai/Kimi-K2.6",
    "zai-org/GLM-4.7",
]

models = sys.argv[1].split(",") if len(sys.argv) > 1 else DEFAULT_MODELS
max_tok = int(sys.argv[2]) if len(sys.argv) > 2 else 200

import json as _json

def ask(client, model_id, q):
    """Streaming chat call — works for both normal and streaming-only models."""
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": PERSONA},
            {"role": "user", "content": q},
        ],
        "max_tokens": max_tok,
        "temperature": 0.8,
        "stream": True,
    }
    chunks = []
    with client.stream("POST", "https://api.together.xyz/v1/chat/completions",
                       headers={"Authorization": f"Bearer {KEY}"}, json=payload) as r:
        if r.status_code != 200:
            body = r.read().decode()[:160]
            return f"ERROR {r.status_code}: {body}"
        for line in r.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data.strip() == "[DONE]":
                break
            try:
                delta = _json.loads(data)["choices"][0]["delta"]
                if delta.get("content"):
                    chunks.append(delta["content"])
            except Exception:
                continue
    text = "".join(chunks)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    return text or "(empty)"

sep = "=" * 70
client = httpx.Client(timeout=120, headers={"User-Agent": "Mozilla/5.0"})
for model_id in models:
    print(f"\n{sep}\n  {model_id}\n{sep}", flush=True)
    for q in QUESTIONS:
        try:
            print(f"  Q: {q}\n  A: {ask(client, model_id, q)}\n", flush=True)
        except Exception as e:
            print(f"  Q: {q}\n  A: EXC: {e}\n", flush=True)
