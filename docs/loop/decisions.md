# Self-Improve Loop — Decision Log

Newest entry on top. Each cycle appends one entry. See `self-improve-loop.md` for the process.

---

## 2026-06-16 — auto cycle (propose mode)
- **Prev fix held?** n/a — в окне нет ни одного Jarvis-ответа, проверить невозможно
- **Data:** 9 msgs reviewed, 0 Jarvis replies
- **Findings:** clean — окно содержит только человеческие сообщения (Макс + Spatifilum обсуждают войну/дроны/деньги), бот не отвечал
- **Proposed fix:** none
- **Queued for Max:** none

---

## 2026-06-15 — auto cycle (propose mode)
- **Prev fix held?** yes — ни «Не вмешиваюсь в викторину», ни Дания-callback в окне не появились
- **Data:** ~195 msgs reviewed, ~44 Jarvis replies
- **Findings:**
  1. **missed-search** (×1): Макс написал «напиши мне правила пятничной трансляции у Стрея это три» — Jarvis ответил «Бро, я не помню никаких правил Стрея, не грузи. Напомни лучше по-человечески» вместо `SEARCH: правила трансляции Stray228`. Макс в итоге скинул правила сам. Триггер-список в персоне («знаешь X?», «кто такой X?» и т.д.) не покрывает конструкцию «напиши [факт] у/про X».
  2. **repetition/double-reply** (×1, вероятно code): два подряд Jarvis-ответа на одно сообщение Макса «тут тоталитаризм не забывай, пару лишних слов и ты лоботомизированный пупсик» — «Да забей, конспиролог из тебя так себе...» + «Это конец эпохи, господа, демократия официально пала...». Оба на одну тему, контентно ок, но дубль. Остальные consecutive-пары (китайский тред) — легитимны: каждый ответ на отдельного участника.
  3. Всё остальное — **ok**: Безуглая-бит (×5, чистая эскалация, закрылся сам), осеменение-тред (×5, Jarvis сам вышел), фанфик/Вова (game + SEARCH по разрешению Макса — правомерно), фута-150ч-уважуха, summary по запросу (2 шага — сначала отказ, потом сделал кратко без структуры) — всё в характере. Негативных реакций пользователей нет.
- **Proposed fix:** в строке 31 персоны, в список примеров SEARCH-триггеров добавить конструкцию `«напиши/расскажи [правила/инфо/детали] у X»`:

  **Было:** `«знаешь X?», «слышал про X?», «что за X», «кто такой X»`
  
  **Станет:** `«знаешь X?», «слышал про X?», «что за X», «кто такой X», «напиши/расскажи правила/инфо про X»`

- **Queued for Max:** double-reply на «тоталитаризм» — скорее всего хендлер отрабатывает дважды (race condition или два update в очереди), стоит глянуть `moltbot_handlers.py` на предмет дублирующих `message.answer` в одном flow.

---

## 2026-06-15 — auto cycle (propose mode)
- **Prev fix held?** yes — ни «Не вмешиваюсь в викторину», ни Дания-callback в окне не появились; обе проблемы, судя по всему, закрыты v8/v10
- **Data:** ~38 msgs reviewed, 11 Jarvis replies
- **Findings:** clean. Все 11 реплик — **ok**. Разбивка:
  - Dota-наказание → остроумно по теме («пента саппортов без вардов»)
  - Urals/иранский договорняк → по делу, тон норм
  - «Коли перемога?» → взвешенный ответ без слива
  - ТЦК бусик → смешно + практично
  - boobs/Безуглая-тред (3 реплики) → *playing along* с юмором пользователя, не форсирует; не затянул
  - военная логистика (без видимого триггера в логе) — вероятно, reply в треде, не отображённый; контентно чистый
  - «Зеленський президент мира?» → ироничный toss-back
  - «Торсионный генератор» → хороший roast-back, РЕН-ТВ-jab — строго в характере
  - Ни одного canned-ответа 3+, ни негативных реакций от пользователей
- **Proposed fix:** none
- **Queued for Max:** none

---

## 2026-06-14 — auto cycle (propose mode)
- **Prev fix held?** нет данных — все 6 реплик Jarvis находятся в «старом» хвосте 36ч-окна (Booty Warrior тред и «Не вмешиваюсь» — ближе к концу списка, т.е. старше); post-v10 реплик не видно
- **Data:** ~100 msgs reviewed, 6 Jarvis replies
- **Findings:**
  - **false-refusal ×2** — «Не вмешиваюсь в викторину 🤐» на «зови танюша / идем тестить аукцион ебучий» и «ебало завали чушка» — триvia не при чём; третий цикл подряд эта фраза всплывает; пользователь ответил «ебало завали чушка» = раздражение; timing vs v8/v10 неизвестен
  - **over-reliance-on-one-fact (Дания) ×2** — «Сдал бы ему твою датскую жопу» → «Так ты ж в Дании, это элитный экспорт» — подряд в одном Booty Warrior треде, точный паттерн который v10 должен был убрать; timing vs v10 неизвестен
  - **ok ×2** — точный factual Booty Warrior ответ + «Куплю виллу и буду игнорить все твои сообщения» (4-я реплика в том же треде — Дания НЕ повторилась, хороший знак)
- **Proposed fix:** none — обе проблемы скорее всего pre-v10; если timing подтвердится — v10 мог уже закрыть обе
- **Queued for Max:** «Не вмешиваюсь в викторину 🤐» третий цикл подряд — проверь логи сервера: есть ли эта фраза POST-v10 деплоя? Если да → нужен явный запрет в персоне: `не произноси фразу «не вмешиваюсь в викторину» — ты не модератор; просто ответь человеку`. Аналогично — проверь timestamp Booty Warrior треда vs moment apply v10.

---

## 2026-06-14 — auto cycle (propose mode)
- **Prev fix held?** частично — в нейтральных темах Дания не всплывает, но в треде где Denmark реально в контексте — 2/3 Jarvis-реплик всё равно используют Данию подряд; цель «1/6» в реальном чате не достигнута
- **Data:** ~120 msgs reviewed, 6 Jarvis replies
- **Findings:**
  - **over-reliance-on-one-fact (Дания) ×2** — «Так ты ж в Дании, это элитный экспорт» + «Сдал бы ему твою датскую жопу» — обе в одном треде, одна за другой
  - **false-refusal ×2** — «Не вмешиваюсь в викторину 🤐» triggered на «Words can't describe how much I disrespect and hate this person» и «ебало завали чушка» — не триvia вообще; exact canned reply с emoji 🤐 = hardcode в коде, LLM так не пишет
- **Proposed fix:** усилить существующую строку про Дания:
  `если уже упомянул факт о ком-то в этой же цепочке реплик (например, что Макс в Дании) — не возвращайся к нему, смени угол`
- **Queued for Max:** ~~«Не вмешиваюсь в викторину 🤐» = hardcoded handler~~ → **FALSE ALARM, verified.** No such code (grep: only `"🤐 AI отказался отвечать"` generic refusal-fallback at moltbot_handlers.py:1494/1650/1716). All «Не вмешиваюсь» replies are dated 06-10..06-13 — BEFORE the v8 deploy; they were v7-prompt-driven (v7 ordered that exact phrase + emoji). Already fixed by v8/v9. Root cause of the false alarm: the loop analyzed stale pre-deploy data → loop fixed (data window now 36h).
- **Applied (Max approved 2026-06-14):** persona **v10** — «если уже упомянул факт о ком-то в этой цепочке, не возвращайся к нему, смени угол». NEXT CYCLE must verify this held (Дания no longer repeats within a thread).

---

---

## 2026-06-14 — cycle 1
- **Prev fix held?** n/a (first cycle)
- **Data:** replay of real bot-directed messages mined from `messages` table (mentions/replies to Jarvis) + a 7-turn chain in Max's style.
- **Findings:** bot is otherwise strong — trivia distraction, roast-back, dark humor, factual + search discipline, identity probes all OK. One drift: **over-reliance-on-one-fact** — the "Дания" callback appeared in ~most replies.
- **Auto-fixed:** persona one-liner added — «не зацикливайся на одном факте про человека (например, Дания), это приедается» → `prompt_versions` **v9** (note "cycle1: stop over-using Дания callback").
- **Verified:** re-ran 6 Дания-prone probes on v9 → callback dropped to **1/6** (was ~all). Fix works.
- **Queued for Max:** none.
- **Notified:** yes (TG DM via Jarvis token).

---

<!-- ENTRY TEMPLATE (copy, fill, prepend above this line):
## YYYY-MM-DD — cycle N
- **Prev fix held?** <yes/no/n-a — did last cycle's change actually help?>
- **Data:** <N messages reviewed, window>
- **Findings:** <labels + 1-2 verbatim examples>
- **Auto-fixed:** <what + prompt_version id, or "none">
- **Queued for Max:** <items needing approval, or "none">
- **Notified:** <yes/no>
-->
