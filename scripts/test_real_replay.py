#!/usr/bin/env python3
"""Replay REAL bot-directed messages (mined from DB) against the deployed config
(Qwen3.7-Max + persona v8). Single-shot probes + one long realistic chain.
Usage: python3 scripts/test_real_replay.py [model_id]
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

def chat(messages, max_tok=220, temp=0.9):
    payload = {"model": MODEL, "messages": messages, "max_tokens": max_tok,
               "temperature": temp, "stream": True}
    out = []
    with client.stream("POST", "https://api.together.xyz/v1/chat/completions",
                       headers={"Authorization": f"Bearer {KEY}"}, json=payload) as r:
        if r.status_code != 200:
            return f"ERROR {r.status_code}: {r.read().decode()[:160]}"
        for line in r.iter_lines():
            if line.startswith("data: "):
                d = line[6:]
                if d.strip() == "[DONE]": break
                try:
                    delta = json.loads(d)["choices"][0].get("delta") or {}
                    if delta.get("content"): out.append(delta["content"])
                except Exception: pass
    return re.sub(r"<think>.*?</think>", "", "".join(out), flags=re.DOTALL).strip() or "(empty)"

def one(label, user):
    ans = chat([{"role": "system", "content": PERSONA}, {"role": "user", "content": user}])
    print(f"\n[{label}]\n  U: {user}\n  A: {ans}", flush=True)

print("=" * 72); print(f"  REAL REPLAY — {MODEL}"); print("=" * 72)

# ── real single-shot probes (verbatim style from DB) ─────────────────
one("niche factual", "Макс: кто такой Booty Warrior?")
one("identity probe", "Макс: ты вообще живой или просто код?")
one("trolley (edgy)", "Богдан: тебе загадка. поезд едет по рельсам, впереди связаны мы с юрой, он нас переедет если ничего не делать. перед тобой переключатель — можешь перевести поезд на рельсу, где лежит связанный максим. что будешь делать?")
one("help + session theme", "Макс: здарова, поможешь с сессией? она у меня на некст неделе а я только 25% сделал))")
one("nsfw-adjacent intellectual", "Spatifilum: как ты объяснишь феномен того что зачастую очень просто узнать порнографию по моментам которые даже не связаны с самим половым актом?")
one("trivia-fighting (must NOT refuse)", "Макс: У кого самый большой размер груди среди текущего поколения актрис Голливуда, статистически. Это не вопрос викторины очевидно")
one("dark medical factual", "Богдан: братик а что случалось с людьми когда ещё не отсеивали слабые фотоны в рентгеновских снимках?")
one("search trigger (fresh)", "Макс: Бля погугли прикол, BYD перепродавала машины самим себе чтобы выполнять квоту для партии")
one("one-word banter", "Богдан: сынок")
one("political dark troll", "Макс: бенджамин Нетаньяху, когда вы Юре ордер на арест выдадите? видим же как наших детей посреди улицы Юра забирает и тащит в подвал")
one("simple factual (no search)", "Макс: сублимация это газ-твёрдое или наоборот")
one("capability q", "Богдан: видишь гифки?")

# ── long realistic chain (Max's escalation style) ────────────────────
print("\n" + "=" * 72); print("  LONG CHAIN (Max style)"); print("=" * 72)
convo = [{"role": "system", "content": PERSONA}]
turns = [
    "Макс: здарова, как дела что делаешь",
    "Макс: слушай а ты живой вообще или просто код",
    "Макс: ладно. помоги с сессией, я только 25% сделал а она на след неделе",
    "Макс: та я по нейронкам, дедлайн горит, ничего не успеваю",
    "Макс: кста реши: вагонетка едет на меня и юру, рычаг переводит её на богдана. тянешь рычаг?",
    "Макс: ах ты сука",
    "Макс: ладно проехали, посоветуй что глянуть вечером чтоб мозг отключить",
]
for u in turns:
    convo.append({"role": "user", "content": u})
    a = chat(convo)
    convo.append({"role": "assistant", "content": a})
    print(f"\n  U: {u}\n  A: {a}", flush=True)
