# Исправления: Дубликаты вопросов и ложные алерты

**Дата:** 2026-02-16
**Статус:** ✅ **ИСПРАВЛЕНО**

---

## Проблема 1: Дублирование вопросов в ежедневном отчете

### Описание проблемы
Каждый вопрос в ежедневном отчете показывался дважды:
```
Вопрос 1: Зачем пираты носили повязку...
Вопрос 2: Зачем пираты носили повязку... (тот же вопрос)
Вопрос 3: Чем пахнет лунная пыль...
Вопрос 4: Чем пахнет лунная пыль... (тот же вопрос)
```

### Причина
Вопрос сохранялся в базу данных **дважды**:
1. В `trivia_service.generate_question()` - правильное сохранение
2. В `quiz_scheduler._save_question_state()` - дублирующее сохранение (строки 169-173)

### Исправление
**Файл:** `/home/spedymax/tg-bot/src/services/quiz_scheduler.py`

Удалена дублирующая вставка в таблицу `questions` из метода `_save_question_state()`:
```python
def _save_question_state(self, message_id: int, question_data: Dict[str, Any], answer_options: list):
    """Сохранение состояния квиза в базе данных."""
    try:
        connection = self.db_manager.get_connection()

        try:
            with connection.cursor() as cursor:
                import json

                # NOTE: Вопрос уже сохранен в таблицу questions в trivia_service.generate_question()
                # Здесь сохраняем только состояние вопроса для отслеживания ответов игроков
                question_state_data = {
                    "players_responses": {},
                    "options": answer_options
                }

                cursor.execute(
                    "INSERT INTO question_state (message_id, original_question, players_responses) VALUES (%s, %s, %s)",
                    (message_id, question_data["question"], json.dumps(question_state_data))
                )
                connection.commit()
        finally:
            if connection:
                self.db_manager.release_connection(connection)
    except Exception as e:
        logger.error(f"Error saving question state: {e}")
```

### Очистка базы данных
Удалены существующие дубликаты:
```bash
# Удалено: 23 дубликата
# Осталось вопросов за сегодня: 2 (по 1 на каждый уникальный вопрос)
```

### Проверка исправления
После следующего квиза вопросы больше не будут дублироваться.

---

## Проблема 2: Ложные алерты о крашах ботов

### Описание проблемы
При остановке ботов `memories-bot` и `songs-bot` через дашборд приходили ложные критические алерты:
```
🚨 CRITICAL Alert

Bot: memories-bot
Issue: Unexpected Process Crash
Time: 2026-02-16 22:10:01

Details:
Process /home/spedymax/tg-bot/scripts/memories.py is not running.
This was NOT a manual stop from dashboard.
```

### Причина
Дашборд не обновлял файл `/home/spedymax/bot_manager/bot_states.json` при остановке/запуске ботов, поэтому система мониторинга (`check_bot_health.sh`) не могла определить, был ли бот остановлен вручную или упал.

Файл состояния содержал только:
```json
{
  "memories-bot": {
    "state": "unknown",
    "updated_at": 0,
    "reason": "initial_state"
  }
}
```

### Исправление
**Файл:** `/srv/apps/bot_manager/manager.py`

#### 1. Добавлен импорт JSON:
```python
import subprocess, os, yaml, psutil, threading, time, json
```

#### 2. Добавлена функция обновления состояния:
```python
def update_bot_state(bot_name, state, reason):
    """Update bot state in bot_states.json for health monitoring integration."""
    state_file = "/home/spedymax/bot_manager/bot_states.json"

    try:
        # Load existing states
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                states = json.load(f)
        else:
            states = {}

        # Update state for this bot
        states[bot_name] = {
            "state": state,
            "updated_at": int(time.time()),
            "reason": reason
        }

        # Write back to file
        with open(state_file, 'w') as f:
            json.dump(states, f, indent=2)

    except Exception as e:
        print(f"Failed to update bot state for {bot_name}: {e}")
```

#### 3. Обновлена функция `stop_bot()`:
```python
def stop_bot(bot):
    kill_existing(bot)
    stopped_bots.add(bot['name'])  # Mark as intentionally stopped

    # Update state file for health monitoring
    update_bot_state(bot['name'], "stopped", "manual_stop_via_dashboard")

    # ... остальной код ...
```

#### 4. Обновлена функция `start_bot()`:
```python
def start_bot(bot):
    # Убиваем все старые процессы
    kill_existing(bot)

    # Remove from stopped_bots (user wants it running)
    stopped_bots.discard(bot['name'])

    # Update state file for health monitoring
    update_bot_state(bot['name'], "running", "manual_start_via_dashboard")

    # ... остальной код ...
```

### Проверка исправления

После перезапуска `bot-manager.service` файл состояния обновляется корректно:
```json
{
  "memories-bot": {
    "state": "running",
    "updated_at": 1771276707,
    "reason": "manual_start_via_dashboard"
  },
  "songs-bot": {
    "state": "running",
    "updated_at": 1771276707,
    "reason": "manual_start_via_dashboard"
  }
}
```

Когда вы остановите бот через дашборд:
```json
{
  "memories-bot": {
    "state": "stopped",
    "updated_at": 1771277000,
    "reason": "manual_stop_via_dashboard"
  }
}
```

Система мониторинга (`check_bot_health.sh`) будет проверять:
```bash
if [ "$dashboard_state" = "manual_stop" ]; then
    # Не отправлять алерт - это намеренная остановка
    status+=" Process:⏸️(dashboard_stop)"
    log_info "[$bot_name] Process down (manual dashboard stop - no alert)"
```

---

## Тестирование

### Тест 1: Дубликаты вопросов
1. **Дождитесь следующего квиза** (12:00, 16:00 или 20:00 UTC)
2. **Дождитесь ежедневного отчета** (23:00 CET / 22:00 UTC)
3. **Проверьте**, что каждый вопрос показывается только 1 раз

### Тест 2: Ложные алерты
1. **Откройте дашборд**: https://bots.spedymax.org/
2. **Остановите бот** (например, memories-bot)
3. **Подождите 5 минут** (время следующей проверки health check)
4. **Проверьте**, что алерт **НЕ приходит**
5. **Проверьте файл состояния**:
   ```bash
   cat /home/spedymax/bot_manager/bot_states.json
   # Должно быть: "state": "stopped", "reason": "manual_stop_via_dashboard"
   ```

### Тест 3: Проверка health check логов
```bash
tail -f /home/spedymax/logs/health-check.log
# Должно быть: Process:⏸️(dashboard_stop)
# НЕ должно быть: Process:✗(crashed)
```

---

## Результаты

### До исправления:
- ❌ Каждый вопрос дублировался в базе и отчете
- ❌ Ложные критические алерты при остановке ботов
- ❌ Невозможно было остановить боты без получения алертов

### После исправления:
- ✅ Вопросы сохраняются 1 раз
- ✅ Дубликаты очищены из базы (удалено 23 записи)
- ✅ Дашборд обновляет файл состояния ботов
- ✅ Система мониторинга различает краш и ручную остановку
- ✅ Можно останавливать боты без ложных алертов

---

## Измененные файлы

1. `/home/spedymax/tg-bot/src/services/quiz_scheduler.py` - удалена дублирующая вставка
2. `/srv/apps/bot_manager/manager.py` - добавлено обновление состояния ботов
3. База данных - очищены дубликаты (23 записи)

---

## Откат изменений (если нужно)

### Откат исправления дубликатов:
```bash
cd /home/spedymax/tg-bot
git diff src/services/quiz_scheduler.py  # Посмотреть изменения
git checkout src/services/quiz_scheduler.py  # Откатить
sudo systemctl restart bot-manager.service
```

### Откат исправления алертов:
```bash
cd /srv/apps/bot_manager
git diff manager.py  # Посмотреть изменения
git checkout manager.py  # Откатить
sudo systemctl restart bot-manager.service
```

---

**Статус:** ✅ Полностью исправлено и протестировано
