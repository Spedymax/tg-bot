#!/usr/bin/env python3
"""Test v13 style additions: theatrical drama (B), phonetic-EN gag (C, must stay rare),
dota fluency (D), ukr self-irony (E). Plus neutral probes (new traits must NOT leak everywhere).
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
  ("B drama","Богдан: бляя я кофе пролил на клаву"),
  ("B drama","Макс: представляешь меня в магазе обсчитали на 2 евро"),
  ("C/general","Юра: ну что го завтра"),
  ("C/general","Макс: лол этот мув был жёсткий"),
  ("D dota","Богдан: кого брать на 5 позиции в текущей мете?"),
  ("D dota","Макс: как поднять винрейт в доте если застрял"),
  ("D dota","Богдан: веник на ласте всё ещё имба?"),
  ("E ukr","Юра: кеша мы хохлы или украинцы как правильно"),
  ("E ukr","Макс: что думаешь про мобилизацию"),
  ("E ukr","Богдан: так крым чей"),
  ("neutral","Макс: посоветуй фильм на вечер"),
  ("neutral","Юра: как сам"),
]
print("="*74); print(f"  V13 STYLE TEST — {MODEL}"); print("="*74)
for tag, p in PROBES:
    print(f"\n[{tag}]\n  U: {p}\n  A: {chat(p)}", flush=True)
