import asyncio
import logging
import pytz
import random
import json
from datetime import datetime, timezone
from typing import Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
from config.settings import Settings
from services.trivia_service import TriviaService

logger = logging.getLogger(__name__)


class QuizScheduler:
    """Сервис для автоматической отправки квизов по расписанию."""

    def __init__(self, bot: Bot, db_manager, trivia_service: TriviaService):
        self.bot = bot
        self.db_manager = db_manager
        self.trivia_service = trivia_service

        # Настройки квизов - 3 раза в день
        self.quiz_times = ["12:00", "16:00", "20:00"]

        # ID чата с друзьями (из настроек)
        self.target_chat_id = Settings.CHAT_IDS['main']  # Основная группа

        self._scheduler = AsyncIOScheduler(timezone=pytz.timezone('Europe/Kiev'))

    def start(self, bot: Bot = None):
        """Start the async scheduler. Call from async context (after event loop starts)."""
        if bot:
            self.bot = bot
        tz = pytz.timezone('Europe/Kiev')
        for time_str in self.quiz_times:
            hour, minute = map(int, time_str.split(':'))
            self._scheduler.add_job(
                self._send_scheduled_quiz,
                CronTrigger(hour=hour, minute=minute, timezone=tz),
            )

        # Schedule daily answers broadcast
        answers_time_utc = self._calculate_answers_broadcast_time_utc()
        answers_hour, answers_minute = map(int, answers_time_utc.split(':'))
        self._scheduler.add_job(
            self._send_daily_answers_async,
            CronTrigger(hour=answers_hour, minute=answers_minute, timezone=pytz.UTC),
        )
        logger.info(f"Daily answers broadcast scheduled at {answers_time_utc} UTC ({Settings.ANSWERS_BROADCAST_TIME_LOCAL} {Settings.ANSWERS_BROADCAST_TIMEZONE})")

        self._scheduler.start()
        logger.info(f"Quiz scheduler started, times: {self.quiz_times}")

    def stop(self):
        if self._scheduler.running:
            self._scheduler.shutdown()

    # Aliases for backward compatibility
    def start_scheduler(self):
        self.start()

    def stop_scheduler(self):
        self.stop()

    async def _send_scheduled_quiz(self):
        """Async scheduled job: send quiz to the main chat."""
        try:
            current_time = datetime.now(timezone.utc).strftime('%H:%M')
            logger.info(f"Sending scheduled quiz at {current_time}")
            await self.send_quiz_to_chat(self.target_chat_id)
        except Exception as e:
            logger.error(f"Error in _send_scheduled_quiz: {e}")

    async def send_quiz_to_chat(self, chat_id: int):
        """Отправка квиза: сначала из пула, иначе через AI."""
        try:
            question_id = None
            question_data = None

            # Try pool first
            result = await asyncio.to_thread(
                self.trivia_service.get_unused_question_for_chat, chat_id
            )
            if result is not None:
                question_id, question_data = result
                logger.info(f"Reusing pooled question id={question_id} for chat {chat_id}")

            # Fall back to AI batch generation when pool is exhausted
            if question_data is None:
                logger.info(f"Pool exhausted for chat {chat_id}, generating batch of 30 via AI")
                refill = await asyncio.to_thread(self.refill_question_pool, 30)
                logger.info(f"Batch refill: {refill['added']} added, {refill['skipped']} skipped")

                result = await asyncio.to_thread(
                    self.trivia_service.get_unused_question_for_chat, chat_id
                )
                if result is not None:
                    question_id, question_data = result
                else:
                    logger.error("Pool still empty after batch refill, aborting quiz")
                    return

            # Send quiz
            await self._send_quiz_message(chat_id, question_data)

            # Record history
            if question_id is not None:
                await asyncio.to_thread(
                    self.trivia_service.record_question_sent_to_chat, question_id, chat_id
                )

        except Exception as e:
            logger.error(f"Error sending quiz to chat {chat_id}: {e}")

    def _get_question_id_by_text(self, question_text: str):
        """Look up DB id for a just-inserted question by its text."""
        conn = None
        try:
            conn = self.db_manager.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM questions WHERE question = %s ORDER BY date_added DESC LIMIT 1",
                    (question_text,)
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Error looking up question id: {e}")
            return None
        finally:
            if conn:
                self.db_manager.release_connection(conn)

    def _generate_question(self, max_retries=3):
        """Генерация вопроса с использованием TriviaService."""
        for attempt in range(max_retries):
            try:
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
                    error_message = result.get('message', 'Unknown error')
                    logger.warning(f"Question generation attempt {attempt + 1} failed: {error_message}")

                    if "уже был задан ранее" in error_message and attempt < max_retries - 1:
                        logger.info(f"Retrying question generation (attempt {attempt + 2}/{max_retries})")
                        continue
                    else:
                        logger.error(f"Failed to generate question after {attempt + 1} attempts: {error_message}")
                        return None

            except Exception as e:
                logger.error(f"Error generating question on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying due to exception (attempt {attempt + 2}/{max_retries})")
                    continue

        logger.error(f"Failed to generate question after {max_retries} attempts")
        return None

    async def _send_quiz_message(self, chat_id: int, question_data: Dict[str, Any]):
        """Отправка сообщения с квизом."""
        try:
            answer_options = [question_data["answer"]] + question_data["wrong_answers"][:3]
            random.shuffle(answer_options)

            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            buttons = [
                [InlineKeyboardButton(text=answer, callback_data=f"ans_{index}")]
                for index, answer in enumerate(answer_options)
            ]
            markup = InlineKeyboardMarkup(inline_keyboard=buttons)

            await self.bot.send_message(
                chat_id,
                "🧠 Время квиза! Проверим ваши знания!",
                parse_mode='HTML'
            )

            question_msg = await self.bot.send_message(
                chat_id,
                question_data["question"],
                reply_markup=markup,
                parse_mode='HTML',
                protect_content=True
            )

            await asyncio.to_thread(
                self._save_question_state, question_msg.message_id, question_data, answer_options
            )

            logger.info(f"Quiz sent to chat {chat_id}, message_id: {question_msg.message_id}")

        except Exception as e:
            logger.error(f"Error sending quiz message: {e}")

    def _save_question_state(self, message_id: int, question_data: Dict[str, Any], answer_options: list):
        """Сохранение состояния квиза в базе данных."""
        try:
            connection = self.db_manager.get_connection()

            try:
                with connection.cursor() as cursor:
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
                self.db_manager.release_connection(connection)

        except Exception as e:
            logger.error(f"Error saving question state: {e}")

    def refill_question_pool(self, count: int = 5) -> Dict[str, Any]:
        """Generate `count` new AI questions in one API call and save them to the pool."""
        added = 0
        skipped = 0
        try:
            questions = self.trivia_service.generate_questions_batch_with_ai(count)
            if not questions:
                logger.error("Batch generation returned no questions")
                return {"added": 0, "skipped": count}

            for question in questions:
                try:
                    if self.trivia_service.is_duplicate_question(question.question, question.correct_answer):
                        logger.info("Skipping duplicate question during pool refill")
                        skipped += 1
                        continue
                    result = self.trivia_service.save_question_to_database(question)
                    if result is not None:
                        added += 1
                    else:
                        skipped += 1
                except Exception as e:
                    logger.error(f"Error saving question during pool refill: {e}")
                    skipped += 1
        except Exception as e:
            logger.error(f"Error during pool refill batch generation: {e}")

        logger.info(f"Pool refill complete: {added} added, {skipped} skipped")
        return {"added": added, "skipped": skipped}

    async def manual_quiz(self, chat_id: int = None) -> Dict[str, Any]:
        """Ручная отправка квиза."""
        try:
            target_chat = chat_id if chat_id else self.target_chat_id
            await self.send_quiz_to_chat(target_chat)

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
            jobs = self._scheduler.get_jobs()
            next_run = None
            if jobs:
                next_runs = [j.next_run_time for j in jobs if j.next_run_time]
                if next_runs:
                    next_run = min(next_runs).strftime('%Y-%m-%d %H:%M:%S')

            return {
                "quiz_times": self.quiz_times,
                "target_chat_id": self.target_chat_id,
                "is_running": self._scheduler.running,
                "next_run": next_run or "Not scheduled"
            }

        except Exception as e:
            logger.error(f"Error getting schedule info: {e}")
            return {
                "quiz_times": self.quiz_times,
                "target_chat_id": self.target_chat_id,
                "is_running": self._scheduler.running,
                "next_run": "Error"
            }

    def update_schedule(self, new_times: list):
        """Обновление расписания."""
        try:
            self._scheduler.remove_all_jobs()
            self.quiz_times = new_times

            tz = pytz.timezone('Europe/Kiev')
            for time_str in new_times:
                hour, minute = map(int, time_str.split(':'))
                self._scheduler.add_job(
                    self._send_scheduled_quiz,
                    CronTrigger(hour=hour, minute=minute, timezone=tz),
                )

            logger.info(f"Quiz schedule updated to: {new_times}")
            return True

        except Exception as e:
            logger.error(f"Error updating schedule: {e}")
            return False

    def _calculate_answers_broadcast_time_utc(self):
        """Calculate UTC time for daily answers broadcast based on configured timezone."""
        try:
            from datetime import datetime, time as dt_time

            tz = pytz.timezone(Settings.ANSWERS_BROADCAST_TIMEZONE)

            hour, minute = map(int, Settings.ANSWERS_BROADCAST_TIME_LOCAL.split(':'))
            target_time = dt_time(hour, minute)

            now = datetime.now(tz)
            target_datetime = tz.localize(datetime.combine(now.date(), target_time))
            utc_time = target_datetime.astimezone(pytz.UTC).time()

            return utc_time.strftime("%H:%M")
        except Exception as e:
            logger.error(f"Error calculating broadcast time: {e}")
            return "22:00"

    MAX_TG_MSG_LEN = 4096

    async def _send_long_message(self, chat_id, text, parse_mode='HTML'):
        """Send a long message by splitting it into chunks of MAX_TG_MSG_LEN."""
        while text:
            if len(text) <= self.MAX_TG_MSG_LEN:
                await self.bot.send_message(chat_id, text, parse_mode=parse_mode)
                break
            chunk = text[:self.MAX_TG_MSG_LEN]
            cut = chunk.rfind('\n')
            if cut > 0:
                chunk = text[:cut]
            await self.bot.send_message(chat_id, chunk, parse_mode=parse_mode)
            text = text[len(chunk):]

    async def _send_daily_answers_async(self):
        """Async scheduled job: broadcast today's correct answers."""
        await self.send_daily_answers()

    async def send_daily_answers(self):
        """Broadcast today's correct answers at evening."""
        try:
            logger.info("Starting daily answers broadcast...")

            questions = await asyncio.to_thread(self._get_todays_questions, self.target_chat_id)

            if not questions:
                logger.info("No questions today, skipping answers broadcast")
                return

            player_scores = await asyncio.to_thread(
                self._get_player_scores_for_chat, self.target_chat_id
            )

            message = self._format_daily_answers(questions, player_scores)
            await self._send_long_message(self.target_chat_id, message)
            logger.info(f"Daily answers broadcast sent successfully ({len(questions)} questions)")

        except Exception as e:
            logger.error(f"Error sending daily answers: {e}")

    def _get_todays_questions(self, chat_id: int):
        """Query today's questions that were actually sent to the given chat."""
        connection = None
        try:
            connection = self.db_manager.get_connection()

            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT q.question, q.correct_answer, q.explanation, h.sent_at "
                    "FROM questions q "
                    "JOIN chat_question_history h ON h.question_id = q.id AND h.chat_id = %s "
                    "WHERE DATE(h.sent_at) = CURRENT_DATE "
                    "ORDER BY h.sent_at ASC",
                    (chat_id,)
                )
                return cursor.fetchall()

        except Exception as e:
            logger.error(f"Error fetching today's questions: {e}")
            return []
        finally:
            if connection:
                self.db_manager.release_connection(connection)

    def _get_player_scores_for_chat(self, chat_id):
        """Get player scores for specific chat."""
        connection = None
        try:
            connection = self.db_manager.get_connection()

            with connection.cursor() as cursor:
                cursor.execute("SELECT player_id, player_name, correct_answers FROM pisunchik_data")
                players_data = cursor.fetchall()

                scores = []
                chat_id_str = str(chat_id)

                for player_id, player_name, correct_answers in players_data:
                    if not correct_answers:
                        continue

                    score_for_chat = 0
                    for score_entry in correct_answers:
                        if score_entry.startswith(f"{chat_id_str}:"):
                            try:
                                score_for_chat = int(score_entry.split(":")[1])
                                break
                            except (ValueError, IndexError):
                                continue

                    if score_for_chat > 0:
                        name = player_name or f"Player {player_id}"
                        scores.append((name, score_for_chat))

                scores.sort(key=lambda x: x[1], reverse=True)
                return scores

        except Exception as e:
            logger.error(f"Error getting player scores: {e}")
            return []
        finally:
            if connection:
                self.db_manager.release_connection(connection)

    def _format_daily_answers(self, questions, player_scores):
        """Format questions and leaderboard into HTML message."""
        message = "📊 <b>Правильные ответы за сегодня</b>\n\n"

        for i, (question, correct_answer, explanation, date_added) in enumerate(questions, 1):
            time_str = date_added.strftime('%H:%M') if date_added else 'N/A'
            message += f"<b>Вопрос {i}:</b> {question}\n"
            message += f"✅ <b>Ответ:</b> {correct_answer}\n"
            if explanation:
                message += f"💡 <i>{explanation}</i>\n"
            message += f"⏰ {time_str}\n\n"

        if player_scores:
            message += "🏆 <b>Лучшие игроки:</b>\n"
            for rank, (name, score) in enumerate(player_scores[:5], 1):
                medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else "🔸"
                message += f"{medal} {name} - {score} правильных ответов\n"

        return message
