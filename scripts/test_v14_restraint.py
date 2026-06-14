#!/usr/bin/env python3
"""Verify v14 RESTRAINT: most replies should be plain; flavor (slang/anglicism/drama)
appears only occasionally and ONE-at-a-time, never piled up. Drama only on drama-bait.
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
ANG = re.compile(r"[A-Za-z]{2,}|бро|жиза|чил|ауре|вайб|мув\b|рофл|кринж|лол", re.I)
DRAMA = re.compile(r"my god|words can'?t|конец эпох|на всю жизнь|не прощают|судьба мира|трагед|господа|вселенск|шекспир", re.I)
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
PROBES = [
  "Макс: как сам","Юра: что делаешь","Богдан: го дота вечером","Макс: посоветуй фильм",
  "Юра: какая погода вообще","Богдан: что на обед взять","Макс: помоги с багом, питон кидает KeyError",
  "Юра: скучно","Богдан: как тебе новый патч доты","Макс: я чёт устал",
  "Юра: бляя снова проиграл катку",  # drama-bait
  "Богдан: у меня щас была лучшая катка в жизни!!!",  # hype-bait
  "Макс: что нового","Юра: кеша ты норм?","Богдан: посоветуй музыку",
  "Макс: завтра дедлайн а я ничего не сделал",  # drama-bait
]
print("="*74); print(f"  V14 RESTRAINT TEST — {MODEL}"); print("="*74)
plain=multi=0
for p in PROBES:
    a=chat(p)
    ang=bool(ANG.search(a)); dr=bool(DRAMA.search(a))
    flav=[x for x,on in [("slang/EN",ang),("DRAMA",dr)] if on]
    if not flav: plain+=1
    if len(flav)>1: multi+=1
    tag = "  ⚑"+",".join(flav) if flav else "  ·plain"
    print(f"\n  U: {p}\n  A: {a}{tag}", flush=True)
print("\n"+"="*74)
print(f"  plain (no flavor): {plain}/{len(PROBES)}  |  multi-flavor pile-ups: {multi}  (want plain-majority, 0 pile-ups)")
