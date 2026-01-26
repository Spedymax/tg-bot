import random
import json
import logging
from telebot import types
from datetime import datetime, timezone, timedelta
from config.settings import Settings
from services.trivia_service import TriviaService
from services.pet_service import PetService
from utils.helpers import safe_split_callback, safe_int, escape_html

logger = logging.getLogger(__name__)

class TriviaHandlers:
    # Maximum number of questions to keep in memory
    MAX_CACHED_QUESTIONS = 100

    def __init__(self, bot, player_service, game_service, db_manager):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        self.db_manager = db_manager

        # Initialize TriviaService for AI question generation
        self.trivia_service = TriviaService(Settings.GEMINI_API_KEY, db_manager)

        # Initialize PetService for pet XP integration
        self.pet_service = PetService()

        # Store questions with timestamps: {message_id: {"data": ..., "created_at": datetime}}
        self.question_messages = {}

        # Load question states from database on startup (graceful recovery)
        self._load_states_on_startup()
    
    def setup_handlers(self):
        """Setup all trivia command handlers"""
        
        @self.bot.message_handler(commands=['trivia'])
        def trivia_command(message):
            """Handle /trivia command"""
            self.send_trivia_question(message.chat.id)
        
        @self.bot.message_handler(commands=['correct_answers'])
        def correct_answers_command(message):
            """Handle /correct_answers command"""
            self.get_correct_answers(message)
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('ans_'))
        def answer_callback(call):
            """Handle trivia answer callbacks"""
            self.handle_answer_callback(call)
    
    def _load_states_on_startup(self):
        """Load question states from database on startup."""
        try:
            loaded_states = self.trivia_service.load_question_states_from_db()
            # Sync question_messages with trivia_service.active_questions
            for message_id, state in loaded_states.items():
                self.question_messages[message_id] = {
                    "data": {
                        "text": state.question_text,
                        "players_responses": state.players_responses,
                        "options": state.answer_options
                    },
                    "created_at": datetime.now(timezone.utc)
                }
            logger.info(f"Loaded {len(loaded_states)} question states from database")
        except Exception as e:
            logger.error(f"Error loading question states on startup: {e}")

    def _cleanup_old_questions(self):
        """Remove oldest questions if cache exceeds limit."""
        if len(self.question_messages) <= self.MAX_CACHED_QUESTIONS:
            return

        # Sort by created_at and remove oldest
        sorted_messages = sorted(
            self.question_messages.items(),
            key=lambda x: x[1].get("created_at", datetime.min.replace(tzinfo=timezone.utc))
        )

        # Keep only the most recent MAX_CACHED_QUESTIONS
        to_remove = len(self.question_messages) - self.MAX_CACHED_QUESTIONS
        for message_id, _ in sorted_messages[:to_remove]:
            del self.question_messages[message_id]

        logger.info(f"Cleaned up {to_remove} old questions from memory cache")

    def _store_question(self, message_id: int, question_data: dict):
        """Store a question with timestamp and cleanup if needed."""
        self.question_messages[message_id] = {
            "data": question_data,
            "created_at": datetime.now(timezone.utc)
        }
        self._cleanup_old_questions()

    def _get_question(self, message_id: int) -> dict:
        """Get question data by message_id."""
        entry = self.question_messages.get(message_id)
        if entry:
            return entry.get("data")
        return None

    def get_question_from_gemini(self):
        """Generate a trivia question using TriviaService"""
        try:
            result = self.trivia_service.generate_question("system", "Handler")
            if result["success"]:
                return {
                    "question": result["question"]["text"],
                    "answer": result["question"]["correct_answer"],
                    "explanation": result["question"].get("explanation", ""),
                    "wrong_answers": [opt for opt in result["question"]["options"] if opt != result["question"]["correct_answer"]]
                }
            else:
                logger.error(f"Error generating question: {result['message']}")
                return None
        except Exception as e:
            logger.error(f"Error generating question: {e}")
            return None
    
    def send_trivia_question(self, chat_id):
        """Send a trivia question to the chat"""
        try:
            question_data = self.get_question_from_gemini()
            
            if question_data is None:
                self.bot.send_message(chat_id, "Извините, произошла ошибка при создании вопроса.")
                return
            
            question_text = question_data["question"]
            correct_answer = question_data["answer"]
            wrong_answers = question_data["wrong_answers"]
            
            # Create answer options
            answer_options = [correct_answer] + wrong_answers[:3]
            random.shuffle(answer_options)
            
            # Send question with inline keyboard
            self.send_question_with_options(chat_id, question_text, answer_options)
            
            # Save question to database using TriviaService
            # Question is already saved in the generate_question method
            
        except Exception as e:
            self.bot.send_message(chat_id, f'Ошибка при создании вопроса: {e}')
    
    def send_question_with_options(self, chat_id, question, answer_options):
        """Send question with answer options as inline keyboard"""
        markup = types.InlineKeyboardMarkup()
        
        # Use indices instead of full answer text in callback_data
        for index, answer in enumerate(answer_options):
            button = types.InlineKeyboardButton(text=answer, callback_data=f"ans_{index}")
            markup.add(button)
        
        self.bot.send_message(chat_id, "Внимание вопрос!", parse_mode='html')
        question_msg = self.bot.send_message(
            chat_id, 
            question, 
            reply_markup=markup, 
            parse_mode='html', 
            protect_content=True
        )
        
        # Store the original question, options and empty responses
        question_data = {
            "text": question,
            "players_responses": {},
            "options": answer_options
        }

        # Use the new store method with cleanup
        self._store_question(question_msg.message_id, question_data)
        # Save to database using TriviaService
        self.trivia_service.save_question_state_raw(
            question_msg.message_id, question, {}, answer_options
        )
    
    def handle_answer_callback(self, call):
        """Handle trivia answer selection"""
        try:
            message_id = call.message.message_id
            user_id = call.from_user.id

            # Safely parse callback data
            parts = safe_split_callback(call.data, "_", 2)
            if not parts:
                self.bot.answer_callback_query(call.id, "Неверный формат данных")
                return

            answer_index = safe_int(parts[1], -1)
            if answer_index < 0:
                self.bot.answer_callback_query(call.id, "Неверный формат ответа")
                return

            player_name = escape_html(call.from_user.first_name or "Игрок")
            
            # Try to get question from memory first, then from database
            question_data = self._get_question(message_id)
            if not question_data:
                # Load from database using TriviaService
                question_state = self.trivia_service.get_question_state(message_id)
                if question_state:
                    question_data = {
                        "text": question_state.question_text,
                        "players_responses": question_state.players_responses,
                        "options": question_state.answer_options
                    }
                    # Store in memory for future use
                    self._store_question(message_id, question_data)
            
            if not question_data:
                self.bot.answer_callback_query(call.id, "Вопрос не найден")
                return
            
            # Check if user already answered
            if user_id in question_data["players_responses"]:
                self.bot.answer_callback_query(call.id, "Вы уже ответили на этот вопрос")
                return
            
            # Safety check for answer_index
            if answer_index >= len(question_data["options"]) or answer_index < 0:
                self.bot.answer_callback_query(call.id, "Неверный выбор ответа")
                return
            
            # Get the selected answer
            selected_answer = question_data["options"][answer_index]
            
            # Check if answer is correct
            connection = self.db_manager.get_connection()
            is_correct = False
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT correct_answer FROM questions WHERE question = %s ORDER BY date_added DESC LIMIT 1",
                        (question_data["text"],)
                    )
                    result = cursor.fetchone()
                    if result:
                        is_correct = result[0] == selected_answer
            finally:
                self.db_manager.release_connection(connection)
            
            # Add player name with emoji to responses
            emoji = "✅" if is_correct else "❌"
            question_data["players_responses"][user_id] = f"{player_name} {emoji}"

            # Update memory cache with modified data
            self._store_question(message_id, question_data)

            self.bot.answer_callback_query(call.id, f"Вы выбрали: {selected_answer}")

            # Update the question message to show the response
            self.update_question_message(call.message, question_data)

            # Update question state in database using TriviaService
            self.trivia_service.save_question_state_raw(
                message_id,
                question_data["text"],
                question_data["players_responses"],
                question_data["options"]
            )
            
            # Update player score and pet system
            player = self.player_service.get_player(user_id)
            if player:
                chat_id = call.message.chat.id

                # Update quiz score if correct
                if is_correct:
                    current_score = player.get_quiz_score(chat_id)
                    player.update_quiz_score(chat_id, current_score + 1)

                # Update pet system (XP, streak, titles)
                pet_notifications = self._update_pet_on_trivia(player, is_correct, chat_id)
                self.player_service.save_player(player)

                # Send pet notifications
                if pet_notifications:
                    username = call.from_user.username
                    player_name = player.player_name or call.from_user.first_name
                    pet_name = escape_html(player.pet.get('name', 'Улюбленець')) if player.pet else 'Улюбленець'

                    if username:
                        mention = f"@{username}"
                    else:
                        mention = f'<a href="tg://user?id={call.from_user.id}">{escape_html(player_name)}</a>'

                    for notif_type, value in pet_notifications:
                        try:
                            if notif_type == 'title':
                                msg = f"{mention}, 🏷 Ти отримав титул \"{escape_html(value)}\"! Серія правильних відповідей!"
                            elif notif_type == 'level':
                                msg = f"{mention}, 🎉 {pet_name} досяг рівня {value}!"
                            elif notif_type == 'evolution':
                                stage_name = self.pet_service.get_stage_name(value)
                                msg = f"{mention}, ✨ {pet_name} еволюціонував у {stage_name}! Натисни /pet щоб налаштувати."
                            else:
                                continue
                            self.bot.send_message(chat_id, msg, parse_mode='HTML')
                        except Exception as e:
                            logger.error(f"Error sending pet notification: {e}")

        except Exception as e:
            logger.error(f"Error in answer callback: {e}")
            self.bot.answer_callback_query(call.id, "Произошла ошибка")

    def _update_pet_on_trivia(self, player, is_correct: bool, chat_id: int) -> list:
        """
        Update pet XP and streak after trivia answer.
        Returns list of notification tuples to send: ('title', name), ('level', level), ('evolution', stage)
        """
        notifications = []

        pet = getattr(player, 'pet', None)
        if not pet or not pet.get('is_alive') or not pet.get('is_locked'):
            return notifications

        # Update last trivia date
        player.last_trivia_date = datetime.now(timezone.utc)

        # Add XP: 1 for participation, +3 bonus for correct
        xp_gain = 1
        if is_correct:
            xp_gain += 3
            # Update streak
            player.trivia_streak = getattr(player, 'trivia_streak', 0) + 1

            # Check for title reward (every 3 streak)
            new_title = self.pet_service.check_streak_reward(
                player.trivia_streak,
                getattr(player, 'pet_titles', [])
            )
            if new_title:
                if not hasattr(player, 'pet_titles') or player.pet_titles is None:
                    player.pet_titles = []
                player.pet_titles.append(new_title)
                notifications.append(('title', new_title))
        else:
            # Reset streak on wrong answer
            player.trivia_streak = 0

        # Add XP and check for level up / evolution
        pet, leveled_up, evolved = self.pet_service.add_xp(pet, xp_gain)
        player.pet = pet

        if leveled_up and not evolved:
            notifications.append(('level', pet['level']))

        if evolved:
            notifications.append(('evolution', pet['stage']))

        return notifications

    def update_question_message(self, message, question_data):
        """Update the question message to show player responses"""
        try:
            # Build the updated message text
            updated_text = question_data["text"]
            
            # Add player responses
            if question_data["players_responses"]:
                updated_text += "\n\n"
                for user_id, response in question_data["players_responses"].items():
                    updated_text += f"{response}\n"
            
            # Keep the same keyboard
            markup = message.reply_markup
            
            # Edit the message
            self.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=message.message_id,
                text=updated_text,
                reply_markup=markup,
                parse_mode='html'
            )
        except Exception as e:
            logger.error(f"Error updating question message: {e}")

    def get_correct_answers(self, message):
        """Show today's questions with correct answers"""
        try:
            # Get today's questions using TriviaService
            today_questions = self.trivia_service.get_today_questions()

            if not today_questions:
                self.bot.reply_to(message, "📋 Сегодня вопросов еще не было!")
                return

            # Get player scores for this chat
            chat_id = message.chat.id
            scores_text = self.get_player_scores_for_chat(chat_id)

            # Build response message
            response_text = self._format_questions_for_display(today_questions)

            # Add player scores
            if scores_text:
                response_text += "\n🏆 <b>Очки игроков:</b>\n" + scores_text

            # Split message if too long and send
            self._send_long_message(message, response_text, today_questions)

        except Exception as e:
            logger.error(f"Error getting correct answers: {e}")
            self.bot.reply_to(message, "❌ Произошла ошибка при получении вопросов")

    def _format_questions_for_display(self, questions):
        """Format questions for display in message."""
        response_text = "📋 <b>Сегодняшние вопросы и ответы:</b>\n\n"

        for i, q in enumerate(questions, 1):
            # Escape HTML to prevent XSS
            question_text = escape_html(q['question'])
            answer_text = escape_html(q['correct_answer'])
            response_text += f"<b>{i}.</b> {question_text}\n"
            response_text += f"✅ <b>Ответ:</b> {answer_text}\n"
            if q.get('explanation'):
                explanation_text = escape_html(q['explanation'])
                response_text += f"💡 <i>{explanation_text}</i>\n"
            response_text += f"⏰ {q.get('date_added', 'N/A')}\n\n"

        return response_text

    def _send_long_message(self, message, response_text, questions):
        """Split and send long message if needed."""
        max_length = 4000

        if len(response_text) <= max_length:
            self.bot.reply_to(message, response_text, parse_mode='HTML')
            return

        # Split into parts
        parts = []
        current_part = "📋 <b>Сегодняшние вопросы и ответы:</b>\n\n"

        for i, q in enumerate(questions, 1):
            # Escape HTML to prevent XSS
            q_text = escape_html(q['question'])
            a_text = escape_html(q['correct_answer'])
            question_text = f"<b>{i}.</b> {q_text}\n"
            question_text += f"✅ <b>Ответ:</b> {a_text}\n"
            if q.get('explanation'):
                e_text = escape_html(q['explanation'])
                question_text += f"💡 <i>{e_text}</i>\n"
            question_text += f"⏰ {q.get('date_added', 'N/A')}\n\n"

            if len(current_part + question_text) > max_length:
                parts.append(current_part)
                current_part = question_text
            else:
                current_part += question_text

        if current_part:
            parts.append(current_part)

        # Send all parts
        for part in parts:
            self.bot.reply_to(message, part, parse_mode='HTML')
    
    def load_trivia_data(self):
        """Load trivia data from database"""
        connection = self.db_manager.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM questions ORDER BY date_added DESC")
                return [{
                    'question': row[0],
                    'correct_answer': row[1],
                    'date_added': row[3].strftime('%d-%m-%Y %H:%M') if row[3] else 'Unknown'
                } for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error loading trivia data: {e}")
            return []
        finally:
            self.db_manager.release_connection(connection)
    
    def get_player_scores_for_chat(self, chat_id):
        """Get player scores for specific chat"""
        try:
            connection = self.db_manager.get_connection()
            
            try:
                with connection.cursor() as cursor:
                    # Get all players from pisunchik_data table
                    cursor.execute("SELECT player_id, player_name, correct_answers FROM pisunchik_data")
                    players_data = cursor.fetchall()
                    
                    scores = []
                    chat_id_str = str(chat_id)
                    
                    for player_id, player_name, correct_answers in players_data:
                        if not correct_answers:
                            continue
                        
                        # Parse correct_answers array to find score for this chat
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
                    
                    # Sort by score descending
                    scores.sort(key=lambda x: x[1], reverse=True)
                    
                    if scores:
                        scores_text = ""
                        for i, (name, score) in enumerate(scores, 1):
                            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔸"
                            scores_text += f"{medal} {name}: {score} очков\n"
                        return scores_text
                    else:
                        return "Пока никто не набрал очков в этом чате."
                        
            finally:
                self.db_manager.release_connection(connection)
                
        except Exception as e:
            logger.error(f"Error getting player scores: {e}")
            return "Ошибка при получении очков."
    
