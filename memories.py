import telebot
import psycopg2
from psycopg2.extras import RealDictCursor
import schedule
import time
import threading
import logging
from datetime import datetime, timedelta
import os
from typing import Optional, List, Dict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('memory_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Пароли пользователей и их состояния ввода пароля
user_passwords = {}
user_auth_states = {}

# Константы
BOT_TOKEN = os.getenv('MEMORY_BOT_TOKEN')  # Токен для memory бота
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'server-tg-pisunchik'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD')
}

bot = telebot.TeleBot(BOT_TOKEN)
global password_message
global write_your_memories

class MemoryBot:
    def __init__(self):
        self.init_database()
        self.current_memory_index = {}  # Для каждого пользователя храним текущий индекс просмотра
        self.custom_reminder_days = {}  # Хранение пользовательских дней напоминаний

    def init_database(self):
        """Создание таблиц для хранения воспоминаний и пользователей"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            # Таблица пользователей для напоминаний
            cursor.execute("""
                           CREATE TABLE IF NOT EXISTS memories_users
                           (
                               user_id
                               BIGINT
                               PRIMARY
                               KEY,
                               username
                               VARCHAR
                           (
                               255
                           ),
                               first_name VARCHAR
                           (
                               255
                           ),
                               last_name VARCHAR
                           (
                               255
                           ),
                               is_active BOOLEAN DEFAULT TRUE,
                               registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                               last_reminder TIMESTAMP,
                               password VARCHAR
                           (
                               255
                           ),
                               reminder_day VARCHAR
                           (
                               20
                           ) DEFAULT 'sunday'
                               );
                           """)

            # Таблица воспоминаний
            cursor.execute("""
                           CREATE TABLE IF NOT EXISTS memories
                           (
                               id
                               SERIAL
                               PRIMARY
                               KEY,
                               user_id
                               BIGINT
                               NOT
                               NULL,
                               content
                               TEXT
                               NOT
                               NULL,
                               memory_type
                               VARCHAR
                           (
                               20
                           ) NOT NULL CHECK
                           (
                               memory_type
                               IN
                           (
                               'weekly',
                               'extra'
                           )),
                               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                               week_number INTEGER,
                               week_start_date DATE,
                               FOREIGN KEY
                           (
                               user_id
                           ) REFERENCES memories_users
                           (
                               user_id
                           )
                               );
                           """)

            cursor.execute("""
                           CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);
                           """)
            cursor.execute("""
                           CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at);
                           """)
            cursor.execute("""
                           CREATE INDEX IF NOT EXISTS idx_users_active ON memories_users(is_active);
                           """)

            conn.commit()
            cursor.close()
            conn.close()
            logger.info("База данных инициализирована успешно")

        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")

    def register_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None,
                      password: str = None):
        """Регистрация пользователя"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            if password:
                cursor.execute("""
                               INSERT INTO memories_users (user_id, username, first_name, last_name, password)
                               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO
                               UPDATE SET
                                   username = EXCLUDED.username,
                                   first_name = EXCLUDED.first_name,
                                   last_name = EXCLUDED.last_name,
                                   password = EXCLUDED.password,
                                   is_active = TRUE
                               """, (user_id, username, first_name, last_name, password))
            else:
                cursor.execute("""
                               INSERT INTO memories_users (user_id, username, first_name, last_name)
                               VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO
                               UPDATE SET
                                   username = EXCLUDED.username,
                                   first_name = EXCLUDED.first_name,
                                   last_name = EXCLUDED.last_name,
                                   is_active = TRUE
                               """, (user_id, username, first_name, last_name))

            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"Пользователь {user_id} зарегистрирован")
            return True

        except Exception as e:
            logger.error(f"Ошибка регистрации пользователя: {e}")
            return False

    def get_user_password(self, user_id: int) -> Optional[str]:
        """Получение пароля пользователя из БД"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            cursor.execute("""
                           SELECT password
                           FROM memories_users
                           WHERE user_id = %s
                           """, (user_id,))

            result = cursor.fetchone()
            cursor.close()
            conn.close()

            return result[0] if result and result[0] else None

        except Exception as e:
            logger.error(f"Ошибка получения пароля пользователя: {e}")
            return None

    def set_reminder_day(self, user_id: int, day: str) -> bool:
        """Установка дня для еженедельного напоминания"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            cursor.execute("""
                           UPDATE memories_users
                           SET reminder_day = %s
                           WHERE user_id = %s
                           """, (day, user_id))

            conn.commit()
            cursor.close()
            conn.close()

            # Кэшируем день напоминания
            self.custom_reminder_days[user_id] = day

            logger.info(f"Установлен день напоминания {day} для пользователя {user_id}")
            return True

        except Exception as e:
            logger.error(f"Ошибка установки дня напоминания: {e}")
            return False

    def get_reminder_day(self, user_id: int) -> str:
        """Получение дня напоминания пользователя"""
        # Проверяем кэш
        if user_id in self.custom_reminder_days:
            return self.custom_reminder_days[user_id]

        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            cursor.execute("""
                           SELECT reminder_day
                           FROM memories_users
                           WHERE user_id = %s
                           """, (user_id,))

            result = cursor.fetchone()
            cursor.close()
            conn.close()

            day = result[0] if result and result[0] else 'sunday'
            self.custom_reminder_days[user_id] = day
            return day

        except Exception as e:
            logger.error(f"Ошибка получения дня напоминания: {e}")
            return 'sunday'

    def get_active_users(self) -> List[int]:
        """Получение списка активных пользователей для напоминаний"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            cursor.execute("""
                           SELECT user_id
                           FROM memories_users
                           WHERE is_active = TRUE
                           """)

            memories_users = [row[0] for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            return memories_users

        except Exception as e:
            logger.error(f"Ошибка получения активных пользователей: {e}")
            return []

    def save_memory(self, user_id: int, content: str, memory_type: str) -> bool:
        """Сохранение воспоминания в БД"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            now = datetime.now()
            week_number = None
            week_start_date = None

            if memory_type == 'weekly':
                week_number = now.isocalendar()[1]
                # Находим начало недели (понедельник)
                days_since_monday = now.weekday()
                week_start_date = (now - timedelta(days=days_since_monday)).date()

            cursor.execute("""
                           INSERT INTO memories (user_id, content, memory_type, week_number, week_start_date)
                           VALUES (%s, %s, %s, %s, %s)
                           """, (user_id, content, memory_type, week_number, week_start_date))

            conn.commit()
            cursor.close()
            conn.close()

            logger.info(f"Сохранено воспоминание пользователя {user_id}, тип: {memory_type}")
            return True

        except Exception as e:
            logger.error(f"Ошибка сохранения воспоминания: {e}")
            return False

    def get_memories(self, user_id: int) -> List[Dict]:
        """Получение всех воспоминаний пользователя"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute("""
                           SELECT *
                           FROM memories
                           WHERE user_id = %s
                           ORDER BY created_at ASC
                           """, (user_id,))

            memories = cursor.fetchall()
            cursor.close()
            conn.close()

            return [dict(memory) for memory in memories]

        except Exception as e:
            logger.error(f"Ошибка получения воспоминаний: {e}")
            return []

    def get_memory_stats(self, user_id: int) -> Dict:
        """Получение статистики воспоминаний"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()

            cursor.execute("""
                           SELECT COUNT(*)                                           as total,
                                  COUNT(CASE WHEN memory_type = 'weekly' THEN 1 END) as weekly,
                                  COUNT(CASE WHEN memory_type = 'extra' THEN 1 END)  as extra,
                                  MIN(created_at)                                    as first_memory,
                                  MAX(created_at)                                    as last_memory
                           FROM memories
                           WHERE user_id = %s
                           """, (user_id,))

            result = cursor.fetchone()
            cursor.close()
            conn.close()

            return {
                'total': result[0] or 0,
                'weekly': result[1] or 0,
                'extra': result[2] or 0,
                'first_memory': result[3],
                'last_memory': result[4]
            }

        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {'total': 0, 'weekly': 0, 'extra': 0}


memory_bot = MemoryBot()


def format_memory(memory: Dict, index: int, total: int) -> str:
    """Форматирование воспоминания для отображения"""
    created_at = memory['created_at']
    formatted_date = created_at.strftime("%d.%m.%Y в %H:%M")

    memory_type_text = ""
    memory_type_emoji = ""
    if memory['memory_type'] == 'weekly':
        memory_type_text = f"Неделя #{memory['week_number']}"
        memory_type_emoji = "📅"
        if memory['week_start_date']:
            week_start = memory['week_start_date'].strftime("%d.%m.%Y")
            memory_type_text += f" (с {week_start})"
    else:
        memory_type_text = "Экстра-мысль"
        memory_type_emoji = "💭"

    return f"""
╭────────────────────────╮
│  🧠 <b>ВОСПОМИНАНИЕ</b>  │
├────────────────────────┤
│  <b>{index + 1} из {total}</b>  │
╰────────────────────────╯

{memory_type_emoji} <b>{memory_type_text}</b>
📝 <b>Записано:</b> {formatted_date}

╭────────────────────────╮
<i>{memory['content']}</i>
╰────────────────────────╯
"""


def create_navigation_keyboard(current_index: int, total_memories: int):
    """Создание клавиатуры для навигации"""
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=3)

    buttons = []

    # Кнопка "Первое"
    if current_index > 0:
        buttons.append(telebot.types.InlineKeyboardButton("⏮ Первое", callback_data="nav_first"))

    # Кнопка "Предыдущее"
    if current_index > 0:
        buttons.append(telebot.types.InlineKeyboardButton("◀️ Пред.", callback_data="nav_prev"))

    # Кнопка "Следующее"
    if current_index < total_memories - 1:
        buttons.append(telebot.types.InlineKeyboardButton("След. ▶️", callback_data="nav_next"))

    # Кнопка "Последнее"
    if current_index < total_memories - 1:
        buttons.append(telebot.types.InlineKeyboardButton("Последнее ⏭", callback_data="nav_last"))

    if buttons:
        keyboard.row(*buttons)

    # Кнопка статистики и закрытия
    keyboard.row(
        telebot.types.InlineKeyboardButton("📊 Статистика", callback_data="show_stats"),
        telebot.types.InlineKeyboardButton("❌ Закрыть", callback_data="close_memories")
    )

    return keyboard


@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    user_id = message.from_user.id

    # Проверяем, есть ли у пользователя пароль
    password = memory_bot.get_user_password(user_id)

    if not password:
        # Если пароля нет, просим пользователя установить его
        bot.reply_to(message,
                     "👋 Добро пожаловать в Дневник воспоминаний!\n\n🔐 <b>Пожалуйста, установите пароль для защиты ваших записей:</b>",
                     parse_mode='HTML')
        user_auth_states[user_id] = 'setting_password'
        return

    # Уже зарегистрированный пользователь
    help_text = """
🧠 <b>Дневник воспоминаний</b>

Этот бот поможет вам сохранять мысли и воспоминания!

<b>Команды:</b>
/weekly - записать еженедельные мысли
/extra - записать экстра-мысль
/memories - просмотреть все воспоминания  
/review - просмотр воспоминаний в хронологическом порядке
/stats - статистика записей
/setreminder - установить день еженедельного напоминания

<b>Автоматические напоминания:</b>
Бот напомнит вам записать мысли за неделю в выбранный день.

Ваши записи защищены паролем и автоматически удаляются из чата! 🔒📝
"""
    bot.reply_to(message, help_text, parse_mode='HTML')


@bot.message_handler(func=lambda message: message.from_user.id in user_auth_states and user_auth_states[
    message.from_user.id] == 'setting_password')
def handle_set_password(message):
    user_id = message.from_user.id
    password = message.text.strip()

    # Удаляем сообщение с паролем
    bot.delete_message(message.chat.id, message.message_id)

    # Сохраняем пароль в БД и в кэш
    memory_bot.register_user(
        user_id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
        password
    )
    user_passwords[user_id] = password

    # Удаляем состояние ввода пароля
    user_auth_states.pop(user_id, None)

    help_text = """
🧠 <b>Дневник воспоминаний</b>

Этот бот поможет вам сохранять мысли и воспоминания!

<b>Команды:</b>
/weekly - записать еженедельные мысли
/extra - записать экстра-мысль
/memories - просмотреть все воспоминания  
/review - просмотр воспоминаний в хронологическом порядке
/stats - статистика записей
/setreminder - установить день еженедельного напоминания

<b>Автоматические напоминания:</b>
Бот напомнит вам записать мысли за неделю в выбранный день.

Ваши записи защищены паролем и автоматически удаляются из чата! 🔒📝
"""
    bot.send_message(message.chat.id, f"✅ <b>Пароль успешно установлен!</b>\n\n{help_text}", parse_mode='HTML')


@bot.message_handler(commands=['weekly'])
def handle_weekly_memory(message):
    global password_message
    user_id = message.from_user.id

    # Проверяем, есть ли у пользователя пароль
    stored_password = memory_bot.get_user_password(user_id)

    if not stored_password:
        bot.reply_to(message, "⚠️ Сначала необходимо установить пароль. Используйте команду /start")
        return

    # Запрашиваем пароль
    password_message = bot.send_message(message.chat.id, "🔐 <b>Введите ваш пароль для продолжения:</b>", parse_mode='HTML')
    user_auth_states[user_id] = 'weekly_password'
    bot.register_next_step_handler(message, check_password_for_weekly)
    bot.delete_message(message.chat.id, message.message_id)


def check_password_for_weekly(message):
    global password_message
    global write_your_memories
    user_id = message.from_user.id
    password = message.text.strip()

    # Удаляем сообщение с паролем
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, password_message.message_id)


    stored_password = memory_bot.get_user_password(user_id)

    if password != stored_password:
        msg = bot.send_message(message.chat.id, "❌ <b>Неверный пароль.</b> Попробуйте команду /weekly снова. Это сообщение будет удалено через 5 секунд", parse_mode='HTML')
        time.sleep(5)
        bot.delete_message(message.chat.id, msg.message_id)
        user_auth_states.pop(user_id, None)
        return

    # Пароль верный, продолжаем
    write_your_memories = bot.send_message(message.chat.id, "📝 Напишите ваши мысли за эту неделю:")
    user_auth_states[user_id] = 'writing_weekly'
    bot.register_next_step_handler(message, save_weekly_memory)


def save_weekly_memory(message):
    global write_your_memories
    user_id = message.from_user.id

    # Удаляем состояние
    user_auth_states.pop(user_id, None)

    if memory_bot.save_memory(user_id, message.text, 'weekly'):
        # Отправляем предупреждение о удалении сообщений
        notification = bot.reply_to(message,
                                    "✅ <b>Ваши еженедельные мысли сохранены!</b>\n\n⚠️ <i>Это сообщение будет удалено через 3 секунды...</i>",
                                    parse_mode='HTML')

        # Отсчет времени до удаления
        for i in range(2, -1, -1):
            time.sleep(1.1)
            bot.edit_message_text(
                f"✅ <b>Ваши еженедельные мысли сохранены!</b>\n\n⚠️ <i>Это сообщение будет удалено через {i} секунд{'ы' if i > 1 else 'у'}...</i>",
                message.chat.id,
                notification.message_id,
                parse_mode='HTML')

        # Удаляем все сообщения: команду пользователя, введенный текст и уведомление
        bot.delete_message(message.chat.id, message.message_id)
        bot.delete_message(message.chat.id, write_your_memories.message_id)
        bot.delete_message(message.chat.id, notification.message_id)

        logger.info(f"Пользователь {user_id} записал еженедельные мысли")
    else:
        error_msg = bot.reply_to(message, "❌ Произошла ошибка при сохранении. Попробуйте снова.")
        time.sleep(3)
        bot.delete_message(message.chat.id, error_msg.message_id)


@bot.message_handler(commands=['extra'])
def handle_extra_memory(message):
    global password_message
    user_id = message.from_user.id

    # Проверяем, есть ли у пользователя пароль
    stored_password = memory_bot.get_user_password(user_id)

    if not stored_password:
        bot.reply_to(message, "⚠️ Сначала необходимо установить пароль. Используйте команду /start")
        return

    # Запрашиваем пароль
    password_message = bot.send_message(message.chat.id, "🔐 <b>Введите ваш пароль для продолжения:</b>", parse_mode='HTML')
    user_auth_states[user_id] = 'extra_password'
    bot.register_next_step_handler(message, check_password_for_extra)
    bot.delete_message(message.chat.id, message.message_id)


def check_password_for_extra(message):
    global password_message
    global write_your_memories
    user_id = message.from_user.id
    password = message.text.strip()

    # Удаляем сообщение с паролем
    bot.delete_message(message.chat.id, message.message_id)
    bot.delete_message(message.chat.id, password_message.message_id)

    stored_password = memory_bot.get_user_password(user_id)

    if password != stored_password:
        msg = bot.send_message(message.chat.id,
                               "❌ <b>Неверный пароль.</b> Попробуйте команду /weekly снова. Это сообщение будет удалено через 5 секунд",
                               parse_mode='HTML')
        time.sleep(5)
        bot.delete_message(message.chat.id, msg.message_id)
        user_auth_states.pop(user_id, None)
        return

    # Пароль верный, продолжаем
    write_your_memories = bot.send_message(message.chat.id, "💭 Напишите вашу экстра-мысль:")
    user_auth_states[user_id] = 'writing_extra'
    bot.register_next_step_handler(message, save_extra_memory)


def save_extra_memory(message):
    global write_your_memories
    user_id = message.from_user.id

    # Удаляем состояние
    user_auth_states.pop(user_id, None)

    if memory_bot.save_memory(user_id, message.text, 'extra'):
        # Отправляем предупреждение о удалении сообщений
        notification = bot.reply_to(message,
                                    "✅ <b>Ваша экстра-мысль сохранена!</b>\n\n⚠️ <i>Это сообщение будет удалено через 3 секунды...</i>",
                                    parse_mode='HTML')

        # Отсчет времени до удаления
        for i in range(2, -1, -1):
            time.sleep(1.1)
            bot.edit_message_text(
                f"✅ <b>Ваша экстра-мысль сохранена!</b>\n\n⚠️ <i>Это сообщение будет удалено через {i} секунд{'ы' if i > 1 else 'у'}...</i>",
                message.chat.id,
                notification.message_id,
                parse_mode='HTML')

        # Удаляем все сообщения: команду пользователя, введенный текст и уведомление
        bot.delete_message(message.chat.id, message.message_id)
        bot.delete_message(message.chat.id, write_your_memories.message_id)
        bot.delete_message(message.chat.id, notification.message_id)

        logger.info(f"Пользователь {user_id} записал экстра-мысль")
    else:
        error_msg = bot.reply_to(message, "❌ Произошла ошибка при сохранении. Попробуйте снова.")
        time.sleep(3)
        bot.delete_message(message.chat.id, error_msg.message_id)


@bot.message_handler(commands=['memories'])
def handle_memories(message):
    """Простой просмотр всех воспоминаний"""
    memories = memory_bot.get_memories(message.from_user.id)

    if not memories:
        bot.reply_to(message,
                     "📭 У вас пока нет сохранённых воспоминаний.\n\nИспользуйте /weekly или /extra для создания первой записи!")
        return

    # Устанавливаем начальный индекс для пользователя
    memory_bot.current_memory_index[message.from_user.id] = 0

    # Показываем первое воспоминание
    show_memory_by_index(message.chat.id, message.from_user.id, 0, memories)


@bot.message_handler(commands=['review'])
def handle_review_memories(message):
    """Финальный красивый просмотр всех воспоминаний с обычными кнопками"""
    user_id = message.from_user.id
    memories = memory_bot.get_memories(user_id)

    if not memories:
        bot.reply_to(message,
                     "📭 У вас пока нет сохранённых воспоминаний для просмотра.\n\nИспользуйте /weekly или /extra для создания записей!")
        return

    stats = memory_bot.get_memory_stats(user_id)

    intro_text = f"""
✨ <b>Просмотр ваших воспоминаний</b> ✨

📊 <b>Всего воспоминаний:</b> {stats['total']}
📅 <b>Еженедельных записей:</b> {stats['weekly']}
💭 <b>Экстра-мыслей:</b> {stats['extra']}

Сейчас я покажу вам все ваши воспоминания в хронологическом порядке.
Для навигации используйте кнопки под сообщениями.
"""

    bot.reply_to(message, intro_text, parse_mode='HTML')

    # Устанавливаем начальный индекс для пользователя
    memory_bot.current_memory_index[user_id] = 0

    # Показываем первое воспоминание
    show_memory_by_index_regular(message.chat.id, user_id, 0, memories)


def show_memory_by_index_regular(chat_id: int, user_id: int, index: int, memories: List[Dict]):
    """Показать воспоминание по индексу с красивой клавиатурой навигации"""
    if not memories or index < 0 or index >= len(memories):
        return

    memory_text = format_memory(memories[index], index, len(memories))

    # Создаем красивую клавиатуру для навигации
    keyboard = telebot.types.ReplyKeyboardMarkup(row_width=3, resize_keyboard=True)
    
    # Первый ряд - основная навигация
    nav_buttons = []
    
    if index > 0:
        nav_buttons.append(telebot.types.KeyboardButton("⬅️ Предыдущее"))
    
    nav_buttons.append(telebot.types.KeyboardButton("❌ Закрыть"))
    
    if index < len(memories) - 1:
        nav_buttons.append(telebot.types.KeyboardButton("➡️ Следующее"))
    
    keyboard.row(*nav_buttons)
    
    # Второй ряд - дополнительная навигация
    second_row = []
    
    if index > 0:
        second_row.append(telebot.types.KeyboardButton("⏮️ Первое"))
    
    if index < len(memories) - 1:
        second_row.append(telebot.types.KeyboardButton("⏭️ Последнее"))
    
    if second_row:
        keyboard.row(*second_row)
    
    bot.send_message(chat_id, memory_text, parse_mode='HTML', reply_markup=keyboard)


@bot.message_handler(commands=['next'])
def handle_next_memory(message):
    user_id = message.from_user.id

    if user_id not in memory_bot.current_memory_index:
        bot.reply_to(message, "🔍 Сначала начните просмотр с помощью команды /review")
        return

    memories = memory_bot.get_memories(user_id)
    current_index = memory_bot.current_memory_index[user_id]

    if current_index >= len(memories) - 1:
        bot.reply_to(message, "⚠️ Вы уже просматриваете последнее воспоминание.")
        return

    # Переходим к следующему воспоминанию
    new_index = current_index + 1
    memory_bot.current_memory_index[user_id] = new_index

    show_memory_by_index_regular(message.chat.id, user_id, new_index, memories)


@bot.message_handler(commands=['prev'])
def handle_prev_memory(message):
    user_id = message.from_user.id

    if user_id not in memory_bot.current_memory_index:
        bot.reply_to(message, "🔍 Сначала начните просмотр с помощью команды /review")
        return

    memories = memory_bot.get_memories(user_id)
    current_index = memory_bot.current_memory_index[user_id]

    if current_index <= 0:
        bot.reply_to(message, "⚠️ Вы уже просматриваете первое воспоминание.")
        return

    # Переходим к предыдущему воспоминанию
    new_index = current_index - 1
    memory_bot.current_memory_index[user_id] = new_index

    show_memory_by_index_regular(message.chat.id, user_id, new_index, memories)


@bot.message_handler(commands=['first'])
def handle_first_memory(message):
    user_id = message.from_user.id

    if user_id not in memory_bot.current_memory_index:
        bot.reply_to(message, "🔍 Сначала начните просмотр с помощью команды /review")
        return

    memories = memory_bot.get_memories(user_id)
    memory_bot.current_memory_index[user_id] = 0

    show_memory_by_index_regular(message.chat.id, user_id, 0, memories)


@bot.message_handler(commands=['last'])
def handle_last_memory(message):
    user_id = message.from_user.id

    if user_id not in memory_bot.current_memory_index:
        bot.reply_to(message, "🔍 Сначала начните просмотр с помощью команды /review")
        return

    memories = memory_bot.get_memories(user_id)
    last_index = len(memories) - 1

    if last_index < 0:
        bot.reply_to(message, "📭 У вас нет сохраненных воспоминаний.")
        return

    memory_bot.current_memory_index[user_id] = last_index

    show_memory_by_index_regular(message.chat.id, user_id, last_index, memories)


@bot.message_handler(commands=['close'])
def handle_close_review(message):
    user_id = message.from_user.id

    if user_id not in memory_bot.current_memory_index:
        bot.reply_to(message, "🔍 Нет активного просмотра для закрытия.")
        return

    # Удаляем текущий индекс просмотра
    memory_bot.current_memory_index.pop(user_id, None)

    bot.reply_to(message, "✅ Просмотр воспоминаний завершен.")


def show_memory_by_index(chat_id: int, user_id: int, index: int, memories: List[Dict]):
    """Показать воспоминание по индексу"""
    if not memories or index < 0 or index >= len(memories):
        return

    memory_text = format_memory(memories[index], index, len(memories))
    keyboard = create_navigation_keyboard(index, len(memories))

    bot.send_message(chat_id, memory_text, parse_mode='HTML', reply_markup=keyboard)


@bot.message_handler(commands=['stats'])
def handle_stats(message):
    stats = memory_bot.get_memory_stats(message.from_user.id)

    if stats['total'] == 0:
        bot.reply_to(message, "📊 У вас пока нет записей для статистики.")
        return

    stats_text = f"""
📊 <b>Статистика ваших воспоминаний</b>

📝 <b>Всего записей:</b> {stats['total']}
📅 <b>Еженедельных:</b> {stats['weekly']}
💭 <b>Экстра-мыслей:</b> {stats['extra']}
"""

    if stats['first_memory']:
        first_date = stats['first_memory'].strftime("%d.%m.%Y")
        stats_text += f"\n🎯 <b>Первая запись:</b> {first_date}"

    if stats['last_memory']:
        last_date = stats['last_memory'].strftime("%d.%m.%Y")
        stats_text += f"\n🕐 <b>Последняя запись:</b> {last_date}"

    bot.reply_to(message, stats_text, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data.startswith('nav_'))
def handle_navigation(call):
    user_id = call.from_user.id
    memories = memory_bot.get_memories(user_id)

    if not memories:
        bot.answer_callback_query(call.id, "Воспоминания не найдены")
        return

    current_index = memory_bot.current_memory_index.get(user_id, 0)

    if call.data == 'nav_first':
        new_index = 0
    elif call.data == 'nav_prev':
        new_index = max(0, current_index - 1)
    elif call.data == 'nav_next':
        new_index = min(len(memories) - 1, current_index + 1)
    elif call.data == 'nav_last':
        new_index = len(memories) - 1
    else:
        bot.answer_callback_query(call.id, "Неизвестная команда")
        return

    memory_bot.current_memory_index[user_id] = new_index

    memory_text = format_memory(memories[new_index], new_index, len(memories))
    keyboard = create_navigation_keyboard(new_index, len(memories))

    bot.edit_message_text(
        memory_text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=keyboard
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == 'show_stats')
def handle_stats_callback(call):
    stats = memory_bot.get_memory_stats(call.from_user.id)

    stats_text = f"""
📊 Статистика воспоминаний

📝 Всего: {stats['total']}
📅 Еженедельных: {stats['weekly']}
💭 Экстра-мыслей: {stats['extra']}
"""

    bot.answer_callback_query(call.id, stats_text, show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data == 'close_memories')
def handle_close_memories(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id, "Воспоминания закрыты")


def send_weekly_reminder():
    """Отправка еженедельного напоминания всем активным пользователям с дефолтным днём (воскресенье)"""
    # Для обратной совместимости - вызываем функцию для воскресенья
    send_weekly_reminder_for_day("sunday")


@bot.message_handler(commands=['setreminder'])
def handle_set_reminder(message):
    """Установка дня для еженедельного напоминания"""
    keyboard = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=True)
    days = [
        "Понедельник", "Вторник", "Среда", "Четверг",
        "Пятница", "Суббота", "Воскресенье"
    ]
    keyboard.add(*[telebot.types.KeyboardButton(day) for day in days])

    bot.reply_to(message, "📅 Выберите день недели для еженедельного напоминания:", reply_markup=keyboard)
    bot.register_next_step_handler(message, process_reminder_day)


def process_reminder_day(message):
    user_id = message.from_user.id
    day_text = message.text.strip().lower()

    day_mapping = {
        "понедельник": "monday",
        "вторник": "tuesday",
        "среда": "wednesday",
        "четверг": "thursday",
        "пятница": "friday",
        "суббота": "saturday",
        "воскресенье": "sunday"
    }

    if day_text not in day_mapping:
        bot.reply_to(message, "❌ Пожалуйста, выберите день из списка.",
                     reply_markup=telebot.types.ReplyKeyboardRemove())
        return

    day_value = day_mapping[day_text]

    if memory_bot.set_reminder_day(user_id, day_value):
        bot.reply_to(message,
                     f"✅ Еженедельное напоминание установлено на <b>{message.text}</b> в 12:00.",
                     parse_mode='HTML',
                     reply_markup=telebot.types.ReplyKeyboardRemove())
    else:
        bot.reply_to(message,
                     "❌ Произошла ошибка при установке дня напоминания. Попробуйте позже.",
                     reply_markup=telebot.types.ReplyKeyboardRemove())


def schedule_reminders():
    """Настройка расписания напоминаний для всех дней недели"""
    # Настраиваем расписание для каждого дня недели
    schedule.every().monday.at("12:00").do(send_weekly_reminder_for_day, day="monday")
    schedule.every().tuesday.at("12:00").do(send_weekly_reminder_for_day, day="tuesday")
    schedule.every().wednesday.at("12:00").do(send_weekly_reminder_for_day, day="wednesday")
    schedule.every().thursday.at("12:00").do(send_weekly_reminder_for_day, day="thursday")
    schedule.every().friday.at("12:00").do(send_weekly_reminder_for_day, day="friday")
    schedule.every().saturday.at("12:00").do(send_weekly_reminder_for_day, day="saturday")
    schedule.every().sunday.at("12:00").do(send_weekly_reminder_for_day, day="sunday")

    logger.info("Расписание напоминаний настроено для всех дней недели в 12:00")


def send_weekly_reminder_for_day(day):
    """Отправка еженедельного напоминания пользователям с выбранным днем"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Получаем пользователей, которые выбрали этот день для напоминаний
        cursor.execute("""
                       SELECT user_id
                       FROM memories_users
                       WHERE is_active = TRUE
                         AND reminder_day = %s
                       """, (day,))

        users_for_day = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()

        message_text = """
🔔 <b>Время для еженедельных размышлений!</b>

Подошло время записать ваши мысли за прошедшую неделю.

Используйте команду /weekly и поделитесь тем, что происходило в вашей жизни, какие были важные моменты, открытия или просто настроение.

Это поможет вам лучше понять себя и сохранить важные воспоминания! 📝✨
"""

        sent_count = 0
        for user_id in users_for_day:
            try:
                bot.send_message(user_id, message_text, parse_mode='HTML')
                sent_count += 1
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания пользователю {user_id}: {e}")

        logger.info(f"Отправлено еженедельных напоминаний для дня {day}: {sent_count}")

    except Exception as e:
        logger.error(f"Ошибка отправки напоминаний для дня {day}: {e}")


def run_schedule():
    """Запуск планировщика в отдельном потоке"""
    while True:
        schedule.run_pending()
        time.sleep(60)  # Проверяем каждую минуту


def main():
    """Основная функция запуска бота"""
    logger.info("Запуск Memory Bot...")

    # Настраиваем расписание
    schedule_reminders()

    # Запускаем планировщик в отдельном потоке
    schedule_thread = threading.Thread(target=run_schedule, daemon=True)
    schedule_thread.start()

    logger.info("Memory Bot запущен и готов к работе!")

    # Запускаем бота
    bot.infinity_polling(none_stop=True)


# Обработчик для кнопок навигации с клавиатуры
@bot.message_handler(func=lambda message: message.text in ["⬅️ Предыдущее", "➡️ Следующее", "⏮️ Первое", "⏭️ Последнее", "❌ Закрыть"])
def handle_navigation_buttons(message):
    user_id = message.from_user.id
    
    if user_id not in memory_bot.current_memory_index:
        bot.reply_to(message, "🔍 Сначала начните просмотр с помощью команды /review")
        return
    
    memories = memory_bot.get_memories(user_id)
    current_index = memory_bot.current_memory_index[user_id]
    
    if message.text == "➡️ Следующее":
        if current_index >= len(memories) - 1:
            bot.reply_to(message, "⚠️ Вы уже просматриваете последнее воспоминание.")
            return
        new_index = current_index + 1
        
    elif message.text == "⬅️ Предыдущее":
        if current_index <= 0:
            bot.reply_to(message, "⚠️ Вы уже просматриваете первое воспоминание.")
            return
        new_index = current_index - 1
        
    elif message.text == "⏮️ Первое":
        new_index = 0
        
    elif message.text == "⏭️ Последнее":
        new_index = len(memories) - 1
        
    elif message.text == "❌ Закрыть":
        # Удаляем текущий индекс просмотра
        memory_bot.current_memory_index.pop(user_id, None)
        bot.reply_to(message, "✅ Просмотр воспоминаний завершен.", 
                    reply_markup=telebot.types.ReplyKeyboardRemove())
        return
    
    memory_bot.current_memory_index[user_id] = new_index
    show_memory_by_index_regular(message.chat.id, user_id, new_index, memories)


if __name__ == "__main__":
    main()