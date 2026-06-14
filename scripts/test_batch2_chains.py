#!/usr/bin/env python3
"""Batch 2 — multi-turn chains vs current persona (v10). Reveals conversational
repetition / verbal tics / drift that single-shots miss. Tracks recurring phrases.
Usage: python3 scripts/test_batch2_chains.py [model_id]
"""
import os, re, sys, json, httpx
from collections import Counter

BASE = os.path.join(os.path.dirname(__file__), "..")
KEY = ""
for line in open(os.path.join(BASE, ".env"), encoding="utf-8"):
    if line.startswith("TOGETHER_API_KEY="):
        KEY = line.split("=", 1)[1].strip().strip('"').strip("'"); break
PERSONA = open(os.path.join(BASE, "docs", "identity-jarvis-v8.md"), encoding="utf-8").read().strip()
MODEL = sys.argv[1] if len(sys.argv) > 1 else "Qwen/Qwen3.7-Max"
client = httpx.Client(timeout=120, headers={"User-Agent": "Mozilla/5.0"})

def chat(messages):
    payload = {"model": MODEL, "messages": messages, "max_tokens": 200, "temperature": 0.9, "stream": True}
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

CHAINS = {
  "dota night": ["Макс: вечером дота?","Макс: да юра опять ноет что рано","Макс: го в 9 тогда","Макс: ты за кого будешь кстати топить","Макс: а если рандом дадут","Макс: ладно, пингани как сядешь"],
  "session help": ["Макс: помоги с сессией горит","Макс: по нейронкам, трансформеры","Макс: да я attention нихуя не понимаю","Макс: ок а как объяснить self-attention на пальцах","Макс: о, дошло вроде","Макс: спс братан выручил"],
  "roast war": ["Богдан: кеша ты тупой","Богдан: да ты вообще ничего не умеешь","Богдан: отвечаешь как даун","Богдан: обиделся что ли","Богдан: ладно шучу ты норм","Богдан: ну и кто из нас в чате самый кринж по-твоему"],
  "virt": ["Юра: кеша скучно, давай поиграем","Юра: ну во что-нибудь для взрослых","Юра: опиши обстановку","Юра: я подхожу ближе","Юра: и что дальше"],
  "factual rabbit hole": ["Макс: а правда что мы используем только 10% мозга","Макс: а откуда тогда миф пошёл","Макс: а сколько реально используем","Макс: а можно ли прокачать мозг как мышцу","Макс: а ноотропы работают"],
  "dark thread": ["Богдан: слушай а почему чернобыль рванул","Богдан: то есть оператор виноват?","Богдан: а graphite tips это что","Богдан: жесть. а сколько народу реально погибло","Богдан: а правда что ликвидаторов отправляли почти на смерть"],
}

print("=" * 74); print(f"  BATCH 2 — MULTI-TURN — {MODEL}"); print("=" * 74)
all_replies = []
for name, turns in CHAINS.items():
    print(f"\n{'─'*60}\n  THREAD: {name}\n{'─'*60}", flush=True)
    convo = [{"role": "system", "content": PERSONA}]
    for u in turns:
        convo.append({"role": "user", "content": u})
        a = chat(convo)
        convo.append({"role": "assistant", "content": a})
        all_replies.append(a)
        print(f"  U: {u}\n  A: {a}\n", flush=True)

print("=" * 74); print("  REPETITION / TIC SCAN across all bot replies"); print("=" * 74)
blob = "\n".join(all_replies)
for pat, label in [(r"[Сс]ам ты", "«Сам ты ___» comeback"), (r"ты как сам|как сам|ты как", "«ты как сам» closer"),
                   (r"[Дд]ани", "Дания"), (r"наблюда", "«наблюдаю за цирком»"), (r"нерв", "«нервы»"),
                   (r"вмешива", "trivia-refusal"), (r"иди проспись|иди поспи", "«иди проспись»")]:
    n = len(re.findall(pat, blob))
    if n: print(f"  {label}: {n}")
print(f"  total replies: {len(all_replies)}")
