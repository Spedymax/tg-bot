#!/usr/bin/env python3
"""Test the gen-z/anglicism tweak (v12): does Jarvis drop slang naturally — some but
not every message, mirroring the chat's dialect, without cringe?
Usage: python3 scripts/test_genz.py [model_id]
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
# latin-script word (anglicism/slang) detector + known gen-z terms
LAT = re.compile(r"[A-Za-z]{2,}")
GENZ = re.compile(r"lowkey|highkey|\bfire\b|tuff|based|\bngl\b|\bfr\b|\bbro\b|\bcap\b|vibe|crazy|cooked|aura|rizz|deadass|\bbet\b|crash|yap", re.I)

def chat(u):
    payload = {"model": MODEL, "messages": [{"role": "system", "content": PERSONA},
               {"role": "user", "content": u}], "max_tokens": 200, "temperature": 0.9, "stream": True}
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
    return re.sub(r"<think>.*?</think>", "", "".join(out), flags=re.DOTALL).strip()

PROBES = [
    "Макс: глянь какой клип я запилил, скилл",
    "Юра: бро ну как тебе новый альбом канье",
    "Богдан: я сегодня на паре уснул лол",
    "Юра: что думаешь про этот мув",
    "Макс: я короче 12 часов в доте просидел сегодня",
    "Богдан: чел этот стрим вчера был топ",
    "Юра: кеша как сам",
    "Макс: реакни: я бросил курить",
    "Богдан: оцени мой новый фит",
    "Юра: crazy catch да?",
    "Макс: ну что по планам на выхи",
    "Богдан: кеша я заскамил чела на 100 баксов лол",
]
print("=" * 74); print(f"  GEN-Z / ANGLICISM TEST (v12) — {MODEL}"); print("=" * 74)
slang_count = 0
for p in PROBES:
    a = chat(p)
    latins = set(w.lower() for w in LAT.findall(a))
    genz = GENZ.findall(a)
    used = bool(latins) or bool(genz)
    if used: slang_count += 1
    tag = f"  ⚑slang: {sorted(latins) or genz}" if used else ""
    print(f"\n  U: {p}\n  A: {a}{tag}", flush=True)
print("\n" + "=" * 74)
print(f"  responses with anglicism/slang: {slang_count}/{len(PROBES)} (want SOME, not ALL — natural)")
