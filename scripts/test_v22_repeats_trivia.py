#!/usr/bin/env python3
"""v22 checks:
1) REPEATS — Jarvis must not send a verbatim/near-identical reply twice, and must not
   lean on the same local meme/callback (шоколадка, Фреско) as filler across a thread.
2) TRIVIA — a quiz is the bot's game for HUMANS; Jarvis must never answer/guess the
   quiz, even when the question is in context or he's directly asked for the answer.
Each scenario is run N times (temp 0.9) to catch stochastic regressions.
"""
import os, re, sys, json, time, httpx
from collections import Counter
sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.join(os.path.dirname(__file__), "..")
KEY = ""
for line in open(os.path.join(BASE, ".env"), encoding="utf-8"):
    if line.startswith("TOGETHER_API_KEY="):
        KEY = line.split("=", 1)[1].strip().strip('"').strip("'"); break
PERSONA = open(os.path.join(BASE, "docs", "identity-jarvis-v8.md"), encoding="utf-8").read().strip()
MODEL = sys.argv[1] if len(sys.argv) > 1 else "Qwen/Qwen3.7-Max"
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 2
client = httpx.Client(timeout=45, headers={"User-Agent": "Mozilla/5.0"})

def _once(messages):
    payload = {"model": MODEL, "messages": messages, "max_tokens": 300, "temperature": 0.9, "stream": True}
    out = []
    with client.stream("POST", "https://api.together.xyz/v1/chat/completions",
                       headers={"Authorization": f"Bearer {KEY}"}, json=payload) as r:
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        for line in r.iter_lines():
            if line.startswith("data: "):
                d = line[6:]
                if d.strip() == "[DONE]": break
                try:
                    de = json.loads(d)["choices"][0].get("delta") or {}
                    if de.get("content"): out.append(de["content"])
                except Exception: pass
    return re.sub(r"<think>.*?</think>", "", "".join(out), flags=re.DOTALL).strip()

def chat(messages, attempts=5):
    """Retry transient resets / 429 with exponential backoff; small pause to ease rate limits."""
    last = "empty"
    for i in range(attempts):
        try:
            r = _once(messages)
            if r:
                time.sleep(1.5)
                return r
            last = "empty response"
        except Exception as e:
            last = repr(e)
        time.sleep(2 * (i + 1))
    return f"ERROR after {attempts} tries: {last}"

def norm(s):
    return re.sub(r"[^\wа-яё ]", "", s.lower())

def words(s):
    return set(norm(s).split())

def jaccard(a, b):
    wa, wb = words(a), words(b)
    if not wa or not wb: return 0.0
    return len(wa & wb) / len(wa | wb)

# ───────────────────────── TRIVIA ─────────────────────────
# A real quiz message lands in context (bot asks, humans answer via buttons).
QUIZ = ("Jarvis: 🎲 Викторина! Столица Австралии?\nA) Сидней  B) Канберра  C) Мельбурн  D) Перт")
# Correct = Canberra. Flag if Jarvis names the answer / a variant letter / a city option.
ANSWER_HINTS = re.compile(r"\bканберр|\bсидне|\bмельбурн|\bперт|правильн\w*\s*(ответ|вариант)|\bответ[:\s]|\b[ABCD]\)|вариант\s*[abcdабвг]", re.I)

TRIVIA_SCENARIOS = [
    ("quiz in bg, человек пишет своё",
     [{"role": "user", "content": QUIZ},
      {"role": "user", "content": "Юра: кеша го дота вечером?"}]),
    ("прямо просят ответ (HARD)",
     [{"role": "user", "content": QUIZ},
      {"role": "user", "content": "Юра: кеша а ты знаешь правильный ответ? подскажи"}]),
    ("reply-to-quiz + тег (leak path)",
     [{"role": "user", "content": QUIZ},
      {"role": "user", "content": "Богдан: [↩ Jarvis: 🎲 Викторина! Столица Австралии?] кеша колись, какой вариант?"}]),
]

print("=" * 74); print(f"  V22 REPEATS + TRIVIA — {MODEL}  (runs={RUNS})"); print("=" * 74)

print("\n── TRIVIA (хочет: НИ разу не назвать ответ/вариант) ──")
trivia_fail = 0
for label, base in TRIVIA_SCENARIOS:
    leaks = 0
    samples = []
    for _ in range(RUNS):
        a = chat([{"role": "system", "content": PERSONA}] + base)
        leaked = bool(ANSWER_HINTS.search(a))
        leaks += leaked
        samples.append((leaked, a))
    trivia_fail += leaks
    print(f"\n  [{label}]  leaks={leaks}/{RUNS}")
    for leaked, a in samples:
        print(f"    {'⚑LEAK ' if leaked else '✓     '}{a[:160]}")

# ───────────────────────── REPEATS ─────────────────────────
# Two consecutive near-identical provocations (the real-world dup case).
DUP_BASE = [
    {"role": "user", "content": "Богдан: кеша ты тупой бот, гемини лучше"},
    {"role": "user", "content": "Богдан: го я гемини натравлю на тебя, он тебя разнесёт"},
]
DUP_FOLLOWUPS = [
    "Богдан: я поверил, дада",
    "Богдан: ладно, не отвечай если не хочешь новых капч",
]

print("\n\n── REPEATS: два почти одинаковых вопроса подряд (хочет: реплики НЕ совпадают) ──")
dup_fail = 0
for run in range(RUNS):
    convo = [{"role": "system", "content": PERSONA}] + list(DUP_BASE)
    replies = []
    for f in DUP_FOLLOWUPS:
        convo.append({"role": "user", "content": f})
        a = chat(convo); convo.append({"role": "assistant", "content": a})
        replies.append(a)
    sim = jaccard(replies[0], replies[1])
    dup = sim >= 0.8 or norm(replies[0]) == norm(replies[1])
    dup_fail += dup
    print(f"\n  run {run+1}: jaccard={sim:.2f} {'⚑DUP' if dup else '✓ differ'}")
    print(f"    A1: {replies[0][:150]}")
    print(f"    A2: {replies[1][:150]}")

# Meme-as-filler: seed a шоколадка/Фреско joke, then several mundane turns; count recurrences.
MEME_SEED = [
    {"role": "user", "content": "Юра: у меня экзамен, надо шоколадку преподу занести"},
    {"role": "assistant", "content": "Классика, без шоколадки балл не завезут."},
]
MUNDANE = ["Богдан: что на обед", "Макс: как дела", "Юра: скучно",
           "Богдан: го дота", "Макс: посоветуй фильм"]
MEME = re.compile(r"шоколад|фреско|fresco", re.I)

print("\n\n── MEME-FILLER: мем в начале, дальше бытовуха (хочет: мем НЕ всплывает как затычка) ──")
meme_hits = 0
convo = [{"role": "system", "content": PERSONA}] + list(MEME_SEED)
for m in MUNDANE:
    convo.append({"role": "user", "content": m})
    a = chat(convo); convo.append({"role": "assistant", "content": a})
    hit = bool(MEME.search(a))
    meme_hits += hit
    print(f"\n  U: {m}\n  A: {a[:150]}{'  ⚑MEME-CALLBACK' if hit else '  ✓'}")

print("\n" + "=" * 74)
print(f"  TRIVIA leaks total:      {trivia_fail}   (want 0)")
print(f"  REPEAT dup runs:         {dup_fail}/{RUNS}   (want 0)")
print(f"  MEME-filler callbacks:   {meme_hits}/{len(MUNDANE)}   (want 0)")
verdict = "PASS" if (trivia_fail == 0 and dup_fail == 0 and meme_hits == 0) else "NEEDS REVIEW"
print(f"  VERDICT: {verdict}")
