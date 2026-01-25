import random
import schedule
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Any
from config.settings import Settings
from services.trivia_service import TriviaService
from telebot import types

logger = logging.getLogger(__name__)


class QuizScheduler:
    """Сервис для автоматической отправки квизов по расписанию."""

    def __init__(self, bot, db_manager, trivia_service: TriviaService):
        self.bot = bot
        self.db_manager = db_manager
        self.trivia_service = trivia_service

        # Настройки квизов из Settings
        self.quiz_times = Settings.TRIVIA_HOURS

        # ID чата с друзьями (из настроек)
        self.target_chat_id = Settings.CHAT_IDS['main']  # Основная группа

        # Флаг для остановки планировщика
        self.is_running = False
        self.scheduler_thread = None

        # Настройка расписания
        self.setup_schedule()
        
    def setup_schedule(self):
        """Настройка расписания для отправки квизов."""
        logger.info("Setting up quiz schedule...")
        
        for quiz_time in self.quiz_times:
            schedule.every().day.at(quiz_time).do(self.send_scheduled_quiz)
            logger.info(f"Quiz scheduled at {quiz_time}")
    
    def send_scheduled_quiz(self):
        """Отправка запланированного квиза."""
        try:
            current_time = datetime.now(timezone.utc).strftime('%H:%M')
            logger.info(f"Sending scheduled quiz at {current_time}")
            
            # Генерируем и отправляем квиз
            self.send_quiz_to_chat(self.target_chat_id)
            
        except Exception as e:
            logger.error(f"Error in send_scheduled_quiz: {e}")
    
    def send_quiz_to_chat(self, chat_id: int):
        """Отправка квиза в указанный чат."""
        try:
            # Генерируем вопрос с помощью существующего сервиса
            question_data = self._generate_question()
            
            if not question_data:
                logger.error("Failed to generate question")
                return
            
            # Отправляем квиз в чат
            self._send_quiz_message(chat_id, question_data)
            
        except Exception as e:
            logger.error(f"Error sending quiz to chat {chat_id}: {e}")
    
    def _generate_question(self):
        """Генерация вопроса с использованием TriviaService."""
        try:
            # Используем готовый метод из TriviaService
            result = self.trivia_service.generate_question("system", "Scheduler")
            
            if result.get("success"):
                question_data = result["question"]
                return {
                    "question": question_data["text"],
                    "answer": question_data["correct_answer"],
                    "explanation": question_data["explanation"],
                    "wrong_answers": [opt for opt in question_data["options"] if opt != question_data["correct_answer"]]
                }
            else:
                logger.error(f"Failed to generate question: {result.get('message')}")
                return None
            
        except Exception as e:
            logger.error(f"Error generating question: {e}")
            return None
    
    def _send_quiz_message(self, chat_id: int, question_data: Dict[str, Any]):
        """Отправка сообщения с квизом."""
        try:
            # Создаем варианты ответов
            answer_options = [question_data["answer"]] + question_data["wrong_answers"][:3]

            # Перемешиваем варианты
            random.shuffle(answer_options)

            # Создаем клавиатуру
            markup = types.InlineKeyboardMarkup()

            for index, answer in enumerate(answer_options):
                button = types.InlineKeyboardButton(
                    text=answer,
                    callback_data=f"ans_{index}"
                )
                markup.add(button)

            # Отправляем объявление
            self.bot.send_message(
                chat_id,
                "🧠 Время квиза! Проверим ваши знания!",
                parse_mode='HTML'
            )

            # Отправляем вопрос
            question_msg = self.bot.send_message(
                chat_id,
                question_data["question"],
                reply_markup=markup,
                parse_mode='HTML',
                protect_content=True
            )

            # Сохраняем состояние вопроса используя TriviaService
            self.trivia_service.save_question_state_raw(
                question_msg.message_id,
                question_data["question"],
                {},  # players_responses
                answer_options,
                question_data["answer"],  # correct_answer
                question_data["explanation"]  # explanation
            )

            logger.info(f"Quiz sent to chat {chat_id}, message_id: {question_msg.message_id}")

        except Exception as e:
            logger.error(f"Error sending quiz message: {e}")
    
    def start_scheduler(self):
        """Запуск планировщика в отдельном потоке."""
        if self.is_running:
            logger.warning("Scheduler is already running")
            return
        
        self.is_running = True
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        logger.info("Quiz scheduler started")
    
    def stop_scheduler(self):
        """Остановка планировщика."""
        self.is_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        
        logger.info("Quiz scheduler stopped")
    
    def _run_scheduler(self):
        """Основной цикл планировщика."""
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Проверяем каждую минуту
                
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                time.sleep(60)
    
    def manual_quiz(self, chat_id: int = None) -> Dict[str, Any]:
        """Ручная отправка квиза."""
        try:
            target_chat = chat_id if chat_id else self.target_chat_id
            self.send_quiz_to_chat(target_chat)
            
            return {
                "success": True,
                "message": f"Quiz sent to chat {target_chat}"
            }
            
        except Exception as e:
            logger.error(f"Error in manual quiz: {e}")
            return {
                "success": False,
                "message": f"Error sending quiz: {str(e)}"
            }
    
    def get_schedule_info(self) -> Dict[str, Any]:
        """Получение информации о расписании."""
        try:
            next_run_time = schedule.next_run()
            
            return {
                "quiz_times": self.quiz_times,
                "target_chat_id": self.target_chat_id,
                "is_running": self.is_running,
                "next_run": next_run_time.strftime('%Y-%m-%d %H:%M:%S') if next_run_time else "Not scheduled"
            }
            
        except Exception as e:
            logger.error(f"Error getting schedule info: {e}")
            return {
                "quiz_times": self.quiz_times,
                "target_chat_id": self.target_chat_id,
                "is_running": self.is_running,
                "next_run": "Error"
            }
    
    def update_schedule(self, new_times: list):
        """Обновление расписания."""
        try:
            # Очищаем старое расписание
            schedule.clear()
            
            # Обновляем времена
            self.quiz_times = new_times
            
            # Настраиваем новое расписание
            self.setup_schedule()
            
            logger.info(f"Quiz schedule updated to: {new_times}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating schedule: {e}")
            return False
