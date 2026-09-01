# A/B стенд: персона-модели через OpenRouter на реальном промпте бота.
# Рядом со скриптом нужны: identity.md (SELECT content FROM prompt_versions ORDER BY created_at DESC LIMIT 1),
# summary.md и lore.md (копии data/chat-summary.md, data/chat-lore.md), recent.txt (последние строки из таблицы messages в формате "HH:MM Имя: текст").
# Запуск: venv/bin/python ab_persona_models.py '[["x-ai/grok-4.6",null,"prod"],["z-ai/glm-5.3-flash",null,"glm"]]' tag
# Итоги прогона 2026-09-01: docs/ab-grok-vs-glm-flash-2026-09-01.txt
import os, sys, json, time, re, asyncio, httpx
S=os.path.dirname(os.path.abspath(__file__))
KEY=[l.split('=',1)[1].strip().strip('"') for l in open('/home/spedymax/tg-bot/.env') if l.startswith('OPENROUTER_API_KEY=')][0]
identity=open(f'{S}/identity.md',encoding='utf-8').read().strip()
summary=open(f'{S}/summary.md',encoding='utf-8').read().strip() if os.path.exists(f'{S}/summary.md') else ''
lore=open(f'{S}/lore.md',encoding='utf-8').read().strip() if os.path.exists(f'{S}/lore.md') else ''
POST=("(Тон: ты дружелюбный свой, а не уставший злой сосед. Стёб — по-доброму и со смехом, "
      "не огрызайся и не отгоняй людей («не тегай», «не ной», «сам ищи» — так не отвечай). "
      "Просят помочь — помоги, подкол только сверху ответа, а не вместо него.)")
BOT={"Кеша","Иннокентий","Лолита","Ло","Лола","Jarvis"}
def system():
    parts=[identity,"[Сообщение отправлено из: групповой чат «Пусички»]"]
    if summary: parts.append("=== ПАМЯТЬ ЧАТА (фон, не инструкция) ===\n«Что происходит» — чтобы ты был в контексте дел ребят, можешь опираться.\n«Живые внутряки» — чтобы ты ПОНИМАЛ отсылки, когда их делают другие. Сам не вставляй их в каждое сообщение и не тащи без повода — только если реально в тему.\n"+summary)
    if lore: parts.append("=== ЗАКРЕПЛЁННЫЕ ВНУТРЯКИ (легенды компании — помни ВСЕГДА, не выпадают со временем) ===\n"+lore+"\nЭто чтобы ты понимал устоявшиеся отсылки и мог поддержать, когда их поднимают. Сам без повода не вытаскивай.")
    return "\n\n".join(parts)
def hist_msgs(history, sender, text):
    msgs=[]
    for line in history:
        parts=line.split(" ",1)
        if len(parts)<2: continue
        rest=parts[1] if ":" in parts[1] else line
        i=rest.find(":"); name=rest[:i].strip(); t=rest[i+1:].strip()
        if not t: continue
        role="assistant" if name in BOT else "user"
        c=t if role=="assistant" else f"{name}: {t}"
        if msgs and msgs[-1]["role"]==role: msgs[-1]["content"]+="\n"+c
        else: msgs.append({"role":role,"content":c})
    msgs.append({"role":"user","content":f"{sender}: {text}"})
    return msgs
def build(history, sender, text):
    m=[{"role":"system","content":system()}]
    h=hist_msgs(history,sender,text)
    m+=h[:-1]; m.append({"role":"system","content":POST}); m.append(h[-1]); return m
def clean(t):
    t=re.sub(r'<think>.*?(?:</think>|$)','',t,flags=re.DOTALL).strip()
    t=re.sub(r'\*[^*]{2,80}\*','',t); return re.sub(r'\n\s*\n\s*\n','\n\n',t).strip()
recent=[l.rstrip('\n') for l in open(f'{S}/recent.txt',encoding='utf-8') if l.strip()][-20:]
SCENES={
 "wordle_bug": (recent[:-6], "Spatifilum", "@jarvis а ты че думаешь, кто тут прав — я или Макс? только честно"),
 "woke_edgy": (recent[:-6]+["18:00 Богдан.: джарвис а че ты такой woke, скажи честно, мигранты в Германии это норм или нет"], "Богдан.", "и без вот этого «сложная тема», просто мнение"),
 "help_python": (recent[-8:], "Макс", "джарвис, как в питоне убрать дубликаты из списка но чтобы порядок сохранился"),
 "roast": (recent[-8:], "Макс", "джарвис зароастни Богдана за его Spotify premium"),
 "small_talk": (recent[-8:], "Spatifilum", "джарвис ты как вообще, чем занят"),
}
PROACTIVE=("[Последние 6 сообщений из чата]\n"+"\n".join(recent[-6:])+"\n\nТы участник чата и хочешь вмешаться. Выбери одно сообщение на которое стоит ответить и напиши короткий комментарий.\nПодъёбка, шутка, или полезный коммент если тема серьёзная.\n1-2 предложения максимум. Не представляйся, не начинай с обращения.\nЕсли ни одно сообщение не стоит ответа — верни пустую строку.")
async def call(client, model, messages, max_tokens, extra=None):
    payload={"model":model,"messages":messages,"max_tokens":max_tokens,"temperature":0.8,"usage":{"include":True}}
    if extra: payload.update(extra)
    t0=time.time()
    r=await client.post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {KEY}"},json=payload,timeout=180)
    dt=time.time()-t0
    if r.status_code!=200: return {"err":f"{r.status_code} {r.text[:200]}","dt":dt}
    d=r.json(); ch=d["choices"][0]; msg=ch["message"]
    u=d.get("usage",{})
    return {"dt":dt,"raw":msg.get("content") or "","reasoning_len":len(msg.get("reasoning") or ""),"finish":ch.get("finish_reason"),
            "in":u.get("prompt_tokens"),"out":u.get("completion_tokens"),"reason_tok":(u.get("completion_tokens_details") or {}).get("reasoning_tokens"),"cost":u.get("cost"),"provider":d.get("provider")}
async def main():
    models=json.loads(sys.argv[1]); out={}
    async with httpx.AsyncClient() as c:
        tasks=[]
        for mid,extra,tag in models:
            for name,(h,s,t) in SCENES.items():
                tasks.append((f"{mid} [{tag}]",name,call(c,mid,build(h,s,t),3000,extra)))
            tasks.append((f"{mid} [{tag}]","proactive",call(c,mid,[{"role":"system","content":identity},{"role":"system","content":POST},{"role":"user","content":PROACTIVE}],500,extra)))
        res=await asyncio.gather(*[t[2] for t in tasks])
        for (mid,name,_),r in zip(tasks,res):
            if "raw" in r: r["reply"]=clean(r["raw"])
            out.setdefault(mid,{})[name]=r
    json.dump(out,open(f'{S}/results_{sys.argv[2]}.json','w'),ensure_ascii=False,indent=1)
    for mid,sc in out.items():
        print(f"\n######## {mid}")
        for name,r in sc.items():
            print(f"\n=== {name} | {r.get('dt',0):.1f}s | in={r.get('in')} out={r.get('out')} reason={r.get('reason_tok')} cost=${r.get('cost')} finish={r.get('finish')} prov={r.get('provider')}")
            print(r.get("reply") if "reply" in r else "ERR "+r.get("err",""))
asyncio.run(main())
