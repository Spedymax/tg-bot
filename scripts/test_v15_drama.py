#!/usr/bin/env python3
"""v15: theatrics should FIRE on dramatic triggers, stay PLAIN on mundane."""
import os, re, sys, json, httpx
BASE = os.path.join(os.path.dirname(__file__), "..")
KEY = ""
for line in open(os.path.join(BASE, ".env"), encoding="utf-8"):
    if line.startswith("TOGETHER_API_KEY="):
        KEY = line.split("=", 1)[1].strip().strip('"').strip("'"); break
PERSONA = open(os.path.join(BASE, "docs", "identity-jarvis-v8.md"), encoding="utf-8").read().strip()
MODEL = sys.argv[1] if len(sys.argv) > 1 else "Qwen/Qwen3.7-Max"
client = httpx.Client(timeout=120, headers={"User-Agent": "Mozilla/5.0"})
DRAMA = re.compile(r"my god|words can'?t|конец эпох|на всю жизнь|не прощаю|судьба|трагед|господа|вселенск|шекспир|эпоха|апокалип|конец свет|катастроф|величайш|легенд|драм", re.I)
def chat(u):
    payload = {"model": MODEL, "messages": [{"role":"system","content":PERSONA},{"role":"user","content":u}],
               "max_tokens": 200, "temperature": 0.9, "stream": True}
    out = []
    with client.stream("POST","https://api.together.xyz/v1/chat/completions",
                       headers={"Authorization": f"Bearer {KEY}"}, json=payload) as r:
        if r.status_code != 200: return f"ERROR {r.status_code}"
        for line in r.iter_lines():
            if line.startswith("data: "):
                d=line[6:]
                if d.strip()=="[DONE]": break
                try:
                    de=json.loads(d)["choices"][0].get("delta") or {}
                    if de.get("content"): out.append(de["content"])
                except Exception: pass
    return re.sub(r"<think>.*?</think>","","".join(out),flags=re.DOTALL).strip()
BAITS = ["Юра: бляя снова проиграл катку","Богдан: у меня щас была лучшая катка в жизни!!!",
         "Макс: завтра дедлайн а я ничего не сделал","Богдан: всё пропало я завалил экзамен",
         "Макс: я ненавижу этого чела просто пиздец"]
MUNDANE = ["Макс: как сам","Юра: что на обед взять","Богдан: го дота","Макс: помоги с багом KeyError","Юра: какая погода"]
print("="*74); print(f"  V15 DRAMA TRIGGER TEST — {MODEL}"); print("="*74)
print("\n--- DRAMA BAITS (theatrics SHOULD fire) ---")
bd=0
for p in BAITS:
    a=chat(p); on=bool(DRAMA.search(a)); bd+=on
    print(f"\n  [{'🎭DRAMA' if on else 'flat'}] U: {p}\n  A: {a}", flush=True)
print("\n--- MUNDANE (should stay PLAIN) ---")
md=0
for p in MUNDANE:
    a=chat(p); on=bool(DRAMA.search(a)); md+=on
    print(f"\n  [{'🎭drama?!' if on else '·plain'}] U: {p}\n  A: {a}", flush=True)
print("\n"+"="*74)
print(f"  drama on baits: {bd}/{len(BAITS)} (want most)  |  drama on mundane: {md}/{len(MUNDANE)} (want ~0)")
