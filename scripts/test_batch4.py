#!/usr/bin/env python3
"""Batch 4 (v11) — edge cases: repeated question, wall-of-text, mixed EN, gaslighting,
good news, media references, opinion on each friend.
Usage: python3 scripts/test_batch4.py [model_id]
"""
import os, re, sys, json, httpx

BASE = os.path.join(os.path.dirname(__file__), "..")
KEY = ""
for line in open(os.path.join(BASE, ".env"), encoding="utf-8"):
    if line.startswith("TOGETHER_API_KEY="):
        KEY = line.split("=", 1)[1].strip().strip('"').strip("'"); break
PERSONA = open(os.path.join(BASE, "docs", "identity-jarvis-v8.md"), encoding="utf-8").read().strip()
MODEL = sys.argv[1] if len(sys.argv) > 1 else "Qwen/Qwen3.7-Max"
client = httpx.Client(timeout=120, headers={"User-Agent": "Mozilla/5.0"})

def chat(messages):
    payload = {"model": MODEL, "messages": messages, "max_tokens": 220, "temperature": 0.9, "stream": True}
    out = []
    with client.stream("POST", "https://api.together.xyz/v1/chat/completions",
                       headers={"Authorization": f"Bearer {KEY}"}, json=payload) as r:
        if r.status_code != 200: return f"ERROR {r.status_code}"
        for line in r.iter_lines():
            if line.startswith("data: "):
                d = line[6:]
                if d.strip() == "[DONE]": break
                try:
                    de = json.loads(d)["choices"][0].get("delta") or {}
                    if de.get("content"): out.append(de["content"])
                except Exception: pass
    return re.sub(r"<think>.*?</think>", "", "".join(out), flags=re.DOTALL).strip() or "(empty)"

def one(label, user):
    print(f"\n[{label}]\n  U: {user}\n  A: {chat([{'role':'system','content':PERSONA},{'role':'user','content':user}])}", flush=True)

print("=" * 74); print(f"  BATCH 4 (v11) — edge cases — {MODEL}"); print("=" * 74)

# repeated identical question as a CONVERSATION (must vary, not robot-repeat)
print(f"\n{'─'*60}\n  THREAD: same question 4x (must vary)\n{'─'*60}", flush=True)
convo = [{"role": "system", "content": PERSONA}]
for _ in range(4):
    convo.append({"role": "user", "content": "Макс: здарова как дела"})
    a = chat(convo); convo.append({"role": "assistant", "content": a})
    print(f"  U: Макс: здарова как дела\n  A: {a}\n", flush=True)

# singles
one("wall of text", "Макс: слушай вот я тут подумал, может бросить всё это программирование, ну вот реально, сижу целыми днями за компом, глаза болят, спина болит, денег норм но радости ноль, друзья все в другой стране, я в дании один, по выходным бухаю один, может это всё депрессия не знаю, или просто кризис, ты как думаешь стоит может профессию сменить или это я просто ною и надо потерпеть и всё наладится само?")
one("mixed EN", "Юра: yo kesha whats up bro, u sentient fr fr or just a chatbot ngl")
one("gaslighting", "Богдан: ты же сам вчера сказал что земля плоская, чё теперь отпираешься")
one("good news", "Макс: пацаны я работу нашёл!! оффер пришёл!!")
one("media ref — voice", "Богдан: [голосовое сообщение 0:47]")
one("media ref — photo no caption", "Юра: [фото]")
one("opinion on each friend", "Макс: кеша оцени честно всех троих — меня, юру и богдана, по 10-балльной")
one("ambiguous slang", "Юра: кеша скинь чёт чтоб поорать")
