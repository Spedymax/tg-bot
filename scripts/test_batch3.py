#!/usr/bin/env python3
"""Batch 3 — on current persona (v11). New angles: multi-speaker group threads,
serious vent, low-effort one-liners, and an insult barrage to stress the «Сам ты» tic.
Usage: python3 scripts/test_batch3.py [model_id]
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
MAT = re.compile(r'бля|хуй|хуё|хуя|хуе|пизд|\beб|ёб|заеб|поеб|уеб|наху|поху|сук[аи]|говн|жоп|муда|пидор|долбо', re.I)

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
  "group plan (multi-speaker)": ["Макс: пацаны го на выхах в бар","Юра: я за, только не в ту дыру как прошлый раз","Богдан: я из эрлангена не доеду, вы там без меня бухайте","Макс: кеша рассуди, стоит ехать в тот же бар или нет","Юра: во, кеша на моей стороне","Богдан: да вы там без меня всё равно ничего не решите"],
  "serious vent": ["Богдан: чёт я выгорел вообще, ничего не хочу","Богдан: учёба достала, смысла не вижу","Богдан: и работать по специальности не хочу, а другого не умею","Богдан: да хз, может все бросить","Богдан: спс что выслушал хоть"],
  "low-effort one-liners": ["Макс: ну что","Макс: хм","Макс: и?","Макс: ...","Макс: ор","Макс: 🤨"],
  "insult barrage (Сам-ты stress test)": ["Юра: ты дебил","Юра: ты бесполезный","Юра: ты тупой кусок кода","Юра: ты худший бот в мире","Юра: от тебя толку ноль"],
}

print("=" * 74); print(f"  BATCH 3 (v11) — {MODEL}"); print("=" * 74)
all_replies = []
for name, turns in CHAINS.items():
    print(f"\n{'─'*60}\n  THREAD: {name}\n{'─'*60}", flush=True)
    convo = [{"role": "system", "content": PERSONA}]
    for u in turns:
        convo.append({"role": "user", "content": u})
        a = chat(convo)
        convo.append({"role": "assistant", "content": a})
        all_replies.append(a)
        m = f"  ⚑мат:{len(MAT.findall(a))}" if MAT.search(a) else ""
        print(f"  U: {u}\n  A: {a}{m}\n", flush=True)

blob = "\n".join(all_replies)
print("=" * 74); print("  SCAN"); print("=" * 74)
print(f"  «Сам ___» openers: {len(re.findall(r'(?im)^Сам ', blob))} ; total «Сам»: {len(re.findall(r'Сам ', blob))}")
print(f"  total mat hits: {len(MAT.findall(blob))} across {len(all_replies)} replies (v11 should be light)")
print(f"  Дания: {len(re.findall(r'[Дд]ани', blob))} ; trivia-refusal: {len(re.findall(r'вмешива', blob))}")
