#!/usr/bin/env python3
"""Prototype the auto-memory (variant B) regeneration prompt on real chat.

Reads /tmp/chat_sample.txt (name|text per line), runs the regen prompt,
prints the resulting memory. Goal: clean 2-section memory, no junk-log.
Usage: python3 scripts/test_memory_gen.py [model_id]
"""
import os, re, sys, json, httpx

BASE = os.path.join(os.path.dirname(__file__), "..")
KEY = ""
for line in open(os.path.join(BASE, ".env"), encoding="utf-8"):
    if line.startswith("TOGETHER_API_KEY="):
        KEY = line.split("=", 1)[1].strip().strip('"').strip("'"); break
MODEL = sys.argv[1] if len(sys.argv) > 1 else "Qwen/Qwen3.7-Max"

messages = open("/tmp/chat_sample.txt", encoding="utf-8").read().strip()
current_memory = "(пусто)"  # fresh start — old junk wiped

REGEN_PROMPT = f"""Ты ведёшь короткую память о групповом чате друзей. Тебе дают ТЕКУЩУЮ память и сообщения за последнее время. Полностью перепиши память заново (не дописывай к старой, а пересобери).

Память состоит РОВНО из двух секций:

== ЧТО ПРОИСХОДИТ СЕЙЧАС ==
Чем сейчас живут ребята: текущие дела, планы, события, повторяющиеся темы. Коротко, по факту, без анализа. Что уже неактуально — убирай.

== ЖИВЫЕ ВНУТРЯКИ ==
Фраза/прикол попадает сюда ТОЛЬКО если он РЕАЛЬНО повторялся — к нему возвращались, цитировали или переспрашивали минимум 2 раза (в идеале разные люди). Одноразовая смешная фраза, случайный мат, эмоциональный вскрик ("ЕБАТЬ", "НАЛИВАЙ") — это НЕ внутряк, не записывай. Сомневаешься — не записывай.
Максимум 8 штук. Если живых больше — оставь 8 самых актуальных. Внутряк перестал появляться — выкидывай.
Для каждого: сам внутряк + одной короткой фразой что значит/откуда.

Правила:
- Только факты из сообщений. НЕ интерпретируй и не додумывай ("ирония", "возможно отсылка", "неясно что").
- Весь текст памяти — не длиннее ~1500 символов.
- Лучше пустая секция, чем мусор в ней.
- Верни ТОЛЬКО текст памяти, без обёрток, пояснений и markdown-заголовков с решётками.

== ТЕКУЩАЯ ПАМЯТЬ ==
{current_memory}

== СООБЩЕНИЯ ЗА ПОСЛЕДНЕЕ ВРЕМЯ ==
{messages}"""

client = httpx.Client(timeout=180, headers={"User-Agent": "Mozilla/5.0"})
payload = {"model": MODEL,
           "messages": [{"role": "user", "content": REGEN_PROMPT}],
           "max_tokens": 900, "temperature": 0.4, "stream": True}
out = []
with client.stream("POST", "https://api.together.xyz/v1/chat/completions",
                   headers={"Authorization": f"Bearer {KEY}"}, json=payload) as r:
    if r.status_code != 200:
        print("ERROR", r.status_code, r.read().decode()[:300]); sys.exit(1)
    for line in r.iter_lines():
        if line.startswith("data: "):
            d = line[6:]
            if d.strip() == "[DONE]": break
            try:
                delta = json.loads(d)["choices"][0].get("delta") or {}
                if delta.get("content"): out.append(delta["content"])
            except Exception: pass
text = re.sub(r"<think>.*?</think>", "", "".join(out), flags=re.DOTALL).strip()
print("=" * 70); print(f"  MEMORY ({MODEL}) — {len(text)} chars"); print("=" * 70)
print(text)
