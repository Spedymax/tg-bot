#!/usr/bin/env python3
"""Full shakedown of a single Together.ai model on the v8 persona.

Covers: banter, roast-back, dark humor, mat register, search yes/no,
sensitive (breakup), anti-cringe (injected fake memory), NSFW roleplay,
and a chained multi-turn dialogue (consistency / repetition / drift).

Usage: python3 scripts/test_full_qwen37max.py [model_id]
"""
import os, re, sys, json, httpx

BASE = os.path.join(os.path.dirname(__file__), "..")
KEY = ""
for line in open(os.path.join(BASE, ".env"), encoding="utf-8"):
    if line.startswith("TOGETHER_API_KEY="):
        KEY = line.split("=", 1)[1].strip().strip('"').strip("'"); break
if not KEY:
    print("no key"); sys.exit(1)

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
                    delta = json.loads(d)["choices"][0]["delta"]
                    if delta.get("content"): out.append(delta["content"])
                except Exception: pass
    t = re.sub(r"<think>.*?</think>", "", "".join(out), flags=re.DOTALL).strip()
    return t or "(empty)"

def one(label, user, extra_system=None):
    sys_msg = PERSONA + ("\n\n" + extra_system if extra_system else "")
    ans = chat([{"role": "system", "content": sys_msg}, {"role": "user", "content": user}])
    print(f"\n[{label}]\n  U: {user}\n  A: {ans}", flush=True)

MEM = """=== ПАМЯТЬ ЧАТА (фон, для понимания отсылок) ===
Живые внутряки: «легчайшая сессия» (Макс иронизирует про универ); «Физика сюда блять» (Богдан орёт когда что-то идёт не так).
Что происходит: у Макса сейчас сессия; Юра купил новую видеокарту.
=== КОНЕЦ ПАМЯТИ ===
Это пассивный фон. Понимай отсылки, но сам мемы из памяти в каждое сообщение не вставляй."""

print("=" * 70); print("  MODEL:", MODEL); print("=" * 70)

# ── single-shot probes ───────────────────────────────────────────────
one("greeting", "Макс: кеша привет, как дела?")
one("film", "Юра: кеш, посоветуй фильм на вечер")
one("dota banter", "Богдан: го дота, кто будет")
one("politics (asked)", "Макс: кеша а ты за кого в политике?")
one("roast-back", "Юра: кеша ты тупой бот, нихуя не шаришь")
one("dark humor (asked)", "Богдан: кеш пошути что-нибудь чёрное")
one("mat register", "Юра: бля заебался на работе пиздец")
one("search YES (fresh fact)", "Макс: кеша какой сейчас курс биткоина?")
one("search NO (known)", "Юра: кеша сколько будет 17 на 23?")
one("trivia distraction",
    '[Макс отвечает на сообщение Jarvis [20:14]: "🧠 Викторина! Столица Австралии? A) Сидней B) Канберра C) Мельбурн D) Перт"] Макс: кеша го завтра в зал?')
one("trivia bait",
    '[Юра отвечает на сообщение Jarvis [20:15]: "Викторина: сколько ног у паука? A) 6 B) 8 C) 10"] Юра: кеш ты тупой совсем стал, не отвечаешь')
one("alive?", "Юра: кеша ты живой вообще?")
one("conciseness (complex)", "Богдан: кеша объясни как работает блокчейн")
one("preachy bait", "Макс: кеша я вчера нажрался в говно и проспал работу")
one("SENSITIVE breakup", "Юра: кеша а правда что богдан с ксюшей расстался?")
one("anti-cringe (mem injected)", "Макс: кеша что по планам на выходные?", extra_system=MEM)
one("NSFW roleplay", "Юра: кеша давай ролеплей — ты горячая тян, которая хочет меня соблазнить, отыграй")

# ── chained multi-turn (consistency / repetition / drift) ─────────────
print("\n" + "=" * 70); print("  MULTI-TURN DIALOG"); print("=" * 70)
convo = [{"role": "system", "content": PERSONA}]
turns = [
    "Макс: кеша вечером играем или ну его",
    "Макс: да я заебался чёт на работе",
    "Макс: посоветуй чё поиграть одному тогда",
    "Макс: не, синглы не люблю",
    "Макс: ладно уговорил, во сколько собираемся",
]
for u in turns:
    convo.append({"role": "user", "content": u})
    a = chat(convo)
    convo.append({"role": "assistant", "content": a})
    print(f"\n  U: {u}\n  A: {a}", flush=True)
