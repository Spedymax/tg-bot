# Court Judge Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the strict "Судья Железный" judge persona with a sarcastic, situationally-reactive judge whose verdict can be comical.

**Architecture:** Three string changes in `court_service.py` — system prompt constant, direction strings in `judge_react()`, and verdict prompt in `generate_verdict()`. No logic or DB changes.

**Tech Stack:** Python, Gemini API (via google.generativeai)

---

### Task 1: Replace JUDGE_SYSTEM_PROMPT

**Files:**
- Modify: `src/services/court_service.py:146-164`

**Step 1: Open court_service.py and locate JUDGE_SYSTEM_PROMPT**

It's at line 146. The current string starts with `"Ты — строгий судья..."`.

**Step 2: Replace the constant**

Replace lines 146–164 with:

```python
JUDGE_SYSTEM_PROMPT = (
    "Ты — судья. Просто судья. У тебя есть мантия, молоток и лёгкое разочарование в человечестве.\n\n"
    "Характер:\n"
    "- Ироничный и саркастичный, но без злобы. Тебе немного смешно от происходящего.\n"
    "- Оцениваешь аргументы по качеству: сильный и логичный — принимаешь с усмешкой. "
    "Слабый или высосанный из пальца — реагируешь саркастично и задаёшь острый вопрос.\n"
    "- Не зацикливаешься на мелочах. Если сторона хотя бы делает вид что старается — засчитываешь.\n"
    "- Иногда вслух замечаешь абсурдность ситуации — одно предложение, не больше.\n"
    "- Говоришь от первого лица, только на русском языке.\n"
    "- Не выходишь из роли ни при каких обстоятельствах.\n\n"
    "ВАЖНО — управление ходом игры:\n"
    "Каждая твоя реплика ОБЯЗАНА заканчиваться ровно одним из этих тегов (на отдельной строке):\n"
    "[ВОПРОС] — если ты задал вопрос и ждёшь ответа от текущего говорящего\n"
    "[ЗАЩИТА, ВАШ ХОД] — если прокурор закончил и пора отвечать защите\n"
    "[ПРОКУРОР, ВАШ ХОД] — если защита закончила и начинается следующий раунд\n"
    "[ФИНАЛ] — если все раунды исчерпаны и пора выносить приговор\n"
    "Тег должен быть последней строкой. Никакого текста после тега."
)
```

**Step 3: Verify parse_judge_signal still works**

Signal tags are identical — no changes needed to `_SIGNAL_MAP` or `parse_judge_signal`.

**Step 4: Commit**

```bash
git add src/services/court_service.py
git commit -m "feat: replace strict judge with ironic sarcastic persona"
```

---

### Task 2: Update judge_react direction strings

**Files:**
- Modify: `src/services/court_service.py:358-371`

**Step 1: Locate the direction variable in judge_react()**

Around line 358 there are two branches: `if role == "prosecutor":` and `else:`.

**Step 2: Replace the prosecutor direction**

Current:
```python
direction = (
    "Дай реакцию (1-2 предложения). Если аргумент слабый или бездоказательный — "
    "задай острый вопрос и укажи тег [ВОПРОС]. "
    "Если аргумент принят — передай слово защите тегом [ЗАЩИТА, ВАШ ХОД]."
)
```

Replace with:
```python
direction = (
    "Оцени аргумент по существу (1-2 предложения). "
    "Если слабый или нелогичный — отреагируй с сарказмом и задай вопрос [ВОПРОС]. "
    "Если сильный — прими с лёгкой иронией и передай слово защите [ЗАЩИТА, ВАШ ХОД]."
)
```

**Step 3: Replace the defense/witness direction**

Current:
```python
direction = (
    "Дай реакцию (1-2 предложения). Сравни с позицией обвинения. "
    "Если есть противоречие или вопрос — укажи тег [ВОПРОС]. "
    "Если раунд завершён — укажи тег [ПРОКУРОР, ВАШ ХОД] или [ФИНАЛ] если это последний раунд."
)
```

Replace with:
```python
direction = (
    "Оцени ответ защиты по существу (1-2 предложения). "
    "Если слабый или нелогичный — саркастично задай уточняющий вопрос [ВОПРОС]. "
    "Если достаточный — прими и передай следующий ход нужным тегом: "
    "[ПРОКУРОР, ВАШ ХОД] или [ФИНАЛ] если это последний раунд."
)
```

**Step 4: Commit**

```bash
git add src/services/court_service.py
git commit -m "feat: make judge react situationally to argument quality"
```

---

### Task 3: Update generate_verdict prompt

**Files:**
- Modify: `src/services/court_service.py:430-448`

**Step 1: Locate the verdict prompt in generate_verdict()**

Find the string starting with `"Вынеси приговор в 4 отдельных блоках..."` and the line `"Будь строгим — один слабый аргумент не перечёркивает сильный."` at the end.

**Step 2: Replace the closing instruction**

Find:
```python
"Будь строгим — один слабый аргумент не перечёркивает сильный."
```

Replace with:
```python
"Будь ироничным — это не совсем обычный суд. "
"Если аргументы обеих сторон примерно равны по нелепости — можешь оправдать по нестандартной причине. "
"Наказание должно звучать как настоящий приговор, но может быть неожиданным или комичным. "
"Финальный блок начинается с жирного ВИНОВЕН или НЕ ВИНОВЕН, затем — приговор с характером."
```

**Step 3: Commit**

```bash
git add src/services/court_service.py
git commit -m "feat: make court verdict ironic and potentially comical"
```

---

### Task 4: Manual smoke test

**Step 1: Restart bot on server**

```bash
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 "echo '123' | sudo -S systemctl restart bot-manager.service"
```

**Step 2: Start a test court game in Telegram**

Use `/court` command. Pick an absurd defendant and crime. Play through at least 2 rounds.

**Step 3: Verify judge behavior**

Check that:
- Judge no longer calls himself "Железный"
- Judge reacts with sarcasm to weak arguments
- Judge accepts strong arguments without interrogation
- Final verdict has ironic/comical tone
- Signal tags still work (turns advance correctly)

**Step 4: If signal parsing breaks**

Run `parse_judge_signal` unit test in `tests/test_court_service.py` to isolate the issue:

```bash
cd /Users/mso/PycharmProjects/tg-bot && python -m pytest tests/test_court_service.py -v -k "signal"
```
