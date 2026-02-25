import random
import json
import html
import logging
from telebot import types
from datetime import datetime, timezone, timedelta
import google.generativeai as genai
from config.settings import Settings
from services.trivia_service import TriviaService
from services.pet_service import PetService

logger = logging.getLogger(__name__)

class TriviaHandlers:
    def __init__(self, bot, player_service, game_service, db_manager):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        self.db_manager = db_manager
        
        # Initialize TriviaService for AI question generation
        self.trivia_service = TriviaService(Settings.GEMINI_API_KEY, db_manager)
        self.pet_service = PetService()
        
        self.quiz_scheduler = None  # Set later via set_quiz_scheduler()
        self.question_messages = {}
        self.original_questions = {}
        
        # Player IDs for scoring
        self.PLAYER_IDS = {
            'YURA': 742272644,
            'MAX': 741542965,
            'BODYA': 855951767
        }
    
    def set_quiz_scheduler(self, quiz_scheduler):
        """Set the quiz scheduler instance (used for pool refill)."""
        self.quiz_scheduler = quiz_scheduler

    def _get_pet_badge(self, player) -> str:
        """Get pet stage badge for appending to game result messages."""
        if not player.pet or not player.pet.get('is_alive') or not player.pet.get('is_locked'):
            return ''
        emojis = {'egg': '🥚', 'baby': '🐣', 'adult': '🐤', 'legendary': '🦅'}
        badge = emojis.get(player.pet.get('stage', ''), '')
        if not badge:
            return ''
        if self.pet_service.is_ulta_available(player):
            badge += '⚡'
        return f' {badge}'

    def setup_handlers(self):
        """Setup all trivia command handlers"""

        @self.bot.message_handler(commands=['regen_questions'])
        def regen_questions_command(message):
            """Handle /regen_questions [count] — admin-only pool refill."""
            from config.settings import Settings
            if message.from_user.id not in Settings.ADMIN_IDS:
                self.bot.reply_to(message, "У вас нет доступа к этой команде.")
                return

            # Parse optional count argument
            parts = message.text.split()
            count = 5
            if len(parts) > 1:
                try:
                    count = max(1, min(int(parts[1]), 20))
                except ValueError:
                    self.bot.reply_to(message, "Неверный формат. Используйте: /regen_questions [1-20]")
                    return

            status_msg = self.bot.reply_to(message, f"🔄 Генерирую {count} вопросов для пула...")
            if self.quiz_scheduler is None:
                self.bot.edit_message_text(
                    "❌ Планировщик квизов не инициализирован.",
                    status_msg.chat.id, status_msg.message_id
                )
                return

            result = self.quiz_scheduler.refill_question_pool(count)
            self.bot.edit_message_text(
                f"✅ Готово!\n\n"
                f"Добавлено в пул: {result['added']}\n"
                f"Пропущено (дубли/ошибки): {result['skipped']}",
                status_msg.chat.id, status_msg.message_id
            )

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
    
    def _announce_evolution(self, chat_id: int, player, old_stage: str):
        """Announce pet evolution to the group chat."""
        from utils.helpers import escape_html
        stage_names = {'egg': 'Яйцо', 'baby': 'Малыш', 'adult': 'Взрослый', 'legendary': 'Легендарный'}
        stage_emojis = {'egg': '🥚', 'baby': '🐣', 'adult': '🐤', 'legendary': '🦅'}
        new_stage = player.pet.get('stage', '')
        pet_name = escape_html(player.pet.get('name', 'питомец'))
        mention = f'<a href="tg://user?id={player.player_id}">{escape_html(player.player_name)}</a>'
        text = (
            f"🎉 Питомец «{pet_name}» игрока {mention} эволюционировал!\n"
            f"{stage_emojis.get(old_stage, '')} {stage_names.get(old_stage, old_stage)} → "
            f"{stage_emojis.get(new_stage, '')} {stage_names.get(new_stage, new_stage)}"
        )
        try:
            self.bot.send_message(chat_id, text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Failed to send evolution announcement: {e}")

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
                print(f"Error: {result['message']}")
                return None
        except Exception as e:
            print(f"Error generating question: {e}")
            return None
    
    def send_trivia_question(self, chat_id):
        """Send a trivia question to the chat"""
        try:
            # Send "thinking" message
            thinking_msg = self.bot.send_message(chat_id, "🤔 Генерирую вопрос...")

            # Try pool first, fall back to AI
            question_id = None
            question_data = None
            result = self.trivia_service.get_unused_question_for_chat(chat_id)
            if result is not None:
                question_id, question_data = result
                logger.info(f"Reusing pooled question id={question_id} for /trivia in chat {chat_id}")
            else:
                logger.info(f"Pool exhausted for chat {chat_id}, generating batch of 30 via AI for /trivia")
                if self.quiz_scheduler:
                    refill = self.quiz_scheduler.refill_question_pool(30)
                    logger.info(f"Batch refill: {refill['added']} added, {refill['skipped']} skipped")
                    result = self.trivia_service.get_unused_question_for_chat(chat_id)
                    if result is not None:
                        question_id, question_data = result

            # Delete the "thinking" message
            try:
                self.bot.delete_message(chat_id, thinking_msg.message_id)
            except:
                pass  # If deletion fails, just continue

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

            # Record in history so this question won't be repeated for this chat
            if question_id is None:
                # AI-generated: look up the id by text
                question_id = self.quiz_scheduler._get_question_id_by_text(question_text) if self.quiz_scheduler else None
            if question_id is not None:
                self.trivia_service.record_question_sent_to_chat(question_id, chat_id)
            
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
        
        self.question_messages[question_msg.message_id] = question_data
        self.save_question_state(question_msg.message_id, question, {}, answer_options)
    
    def handle_answer_callback(self, call):
        """Handle trivia answer selection"""
        try:
            message_id = call.message.message_id
            user_id = call.from_user.id
            answer_index = int(call.data.split('_')[1])
            player_name = call.from_user.first_name or "Игрок"
            
            # Try to get question from memory first, then from database
            question_data = None
            if message_id in self.question_messages:
                question_data = self.question_messages[message_id]
            else:
                # Load from database
                question_data = self.load_question_state_from_db(message_id)
                if question_data:
                    # Store in memory for future use
                    self.question_messages[message_id] = question_data
            
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
            connection = None
            is_correct = False
            try:
                connection = self.db_manager.get_connection()
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT correct_answer FROM questions WHERE question = %s ORDER BY date_added DESC LIMIT 1",
                        (question_data["text"],)
                    )
                    result = cursor.fetchone()
                    if result:
                        is_correct = result[0] == selected_answer
            finally:
                if connection:
                    self.db_manager.release_connection(connection)

            # Халява ulta override: force correct BEFORE emoji and response are recorded
            player = self.player_service.get_player(user_id)
            if player and getattr(player, 'pet_ulta_trivia_pending', False):
                player.pet_ulta_trivia_pending = False
                is_correct = True

            # Add player name with emoji to responses
            emoji = "✅" if is_correct else "❌"
            if is_correct:
                _pet_badge = self._get_pet_badge(player) if player else ''
            else:
                _pet_badge = ''
            question_data["players_responses"][user_id] = f"{player_name}{_pet_badge} {emoji}"
            
            self.bot.answer_callback_query(call.id, f"Вы выбрали: {selected_answer}")
            
            # Update the question message to show the response
            self.update_question_message(call.message, question_data)
            
            # Update question state in database
            self.save_question_state(
                message_id, 
                question_data["text"], 
                question_data["players_responses"], 
                question_data["options"]
            )
            
            # Update player score if correct
            if is_correct:
                if not player:
                    player = self.player_service.get_player(user_id)
                if player:
                    chat_id = call.message.chat.id
                    current_score = player.get_quiz_score(chat_id)
                    player.update_quiz_score(chat_id, current_score + 1)

                    # Update streak and add XP to pet
                    player.trivia_streak = getattr(player, 'trivia_streak', 0) + 1
                    if player.pet and player.pet.get('is_alive') and player.pet.get('is_locked'):
                        now = datetime.now(timezone.utc)
                        self.pet_service.apply_hunger_decay(player, now)
                        self.pet_service.record_game_activity(player, 'trivia', now)
                        multiplier = self.pet_service.get_xp_multiplier(player)
                        xp_gain = int(10 * multiplier)
                        if xp_gain > 0:
                            old_stage = player.pet.get('stage')
                            player.pet, _, evolved = self.pet_service.add_xp(player.pet, xp_gain)
                            if evolved:
                                self._announce_evolution(chat_id, player, old_stage)
                        new_title = self.pet_service.check_streak_reward(
                            player.trivia_streak, getattr(player, 'pet_titles', [])
                        )
                        if new_title and new_title not in player.pet_titles:
                            player.pet_titles.append(new_title)

                    # Food drop (25% chance on correct answer)
                    import random as _rand
                    if player.pet and player.pet.get('is_alive') and _rand.random() < 0.25:
                        player.add_item('pet_food_basic')

                    self.player_service.save_player(player)
            else:
                # Reset streak on wrong answer
                if not player:
                    player = self.player_service.get_player(user_id)
                if player and getattr(player, 'trivia_streak', 0) > 0:
                    player.trivia_streak = 0
                    self.player_service.save_player(player)
                
        except Exception as e:
            print(f"Error in answer callback: {e}")
            self.bot.answer_callback_query(call.id, "Произошла ошибка")
    
    
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
            print(f"Error updating question message: {e}")
    
    def save_question_state(self, message_id, question, players_responses, answer_options=None):
        """Save question state to database"""
        connection = None
        try:
            connection = self.db_manager.get_connection()
            with connection.cursor() as cursor:
                data_to_save = {
                    "players_responses": players_responses
                }
                
                if answer_options:
                    data_to_save["options"] = answer_options
                
                # Check if record exists
                cursor.execute(
                    "SELECT 1 FROM question_state WHERE message_id = %s",
                    (message_id,)
                )
                
                if cursor.fetchone():
                    # Update existing record
                    cursor.execute(
                        "UPDATE question_state SET original_question = %s, players_responses = %s WHERE message_id = %s",
                        (question, json.dumps(data_to_save), message_id)
                    )
                else:
                    # Insert new record
                    cursor.execute(
                        "INSERT INTO question_state (message_id, original_question, players_responses) VALUES (%s, %s, %s)",
                        (message_id, question, json.dumps(data_to_save))
                    )
                
                connection.commit()
        except Exception as e:
            print(f"Error saving question state: {e}")
        finally:
            if connection:
                self.db_manager.release_connection(connection)
    
    def load_question_state_from_db(self, message_id):
        """Load question state from database"""
        connection = None
        try:
            connection = self.db_manager.get_connection()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT original_question, players_responses FROM question_state WHERE message_id = %s",
                    (message_id,)
                )
                result = cursor.fetchone()
                
                if result:
                    question_text, players_responses_json = result
                    
                    # Handle None or empty JSON
                    if not players_responses_json:
                        return {
                            "text": question_text,
                            "players_responses": {},
                            "options": []
                        }
                    
                    # Parse the JSON data
                    try:
                        if isinstance(players_responses_json, str):
                            data = json.loads(players_responses_json)
                        else:
                            data = players_responses_json  # Already a dict
                        
                        # Handle different data formats
                        if isinstance(data, dict):
                            return {
                                "text": question_text,
                                "players_responses": data.get("players_responses", {}),
                                "options": data.get("options", [])
                            }
                        else:
                            # Legacy format - data is directly players_responses
                            return {
                                "text": question_text,
                                "players_responses": data if isinstance(data, dict) else {},
                                "options": []
                            }
                    except (json.JSONDecodeError, TypeError) as e:
                        print(f"Error parsing question state JSON: {e}")
                        # Return empty structure instead of None
                        return {
                            "text": question_text,
                            "players_responses": {},
                            "options": []
                        }
                
                return None
        except Exception as e:
            print(f"Error loading question state: {e}")
            return None
        finally:
            if connection:
                self.db_manager.release_connection(connection)
    
    def get_correct_answers(self, message):
        """Show today's questions with correct answers"""
        connection = None
        try:
            connection = self.db_manager.get_connection()
            chat_id = message.chat.id

            with connection.cursor() as cursor:
                # Get today's questions that were actually sent to this chat
                cursor.execute(
                    "SELECT q.question, q.correct_answer, q.explanation, h.sent_at "
                    "FROM questions q "
                    "JOIN chat_question_history h ON h.question_id = q.id AND h.chat_id = %s "
                    "WHERE DATE(h.sent_at) = CURRENT_DATE "
                    "ORDER BY h.sent_at ASC",
                    (chat_id,)
                )

                today_questions = cursor.fetchall()

                if not today_questions:
                    self.bot.reply_to(message, "📋 Сегодня вопросов еще не было!")
                    return

                # Get player scores for this chat
                scores_text = self.get_player_scores_for_chat(chat_id)

                # Build response message
                response_text = "📋 <b>Сегодняшние вопросы и ответы:</b>\n\n"

                for i, (question, correct_answer, explanation, sent_at) in enumerate(today_questions, 1):
                    time_str = sent_at.strftime('%H:%M') if sent_at else 'N/A'
                    response_text += f"<b>{i}.</b> {question}\n"
                    response_text += f"✅ <b>Ответ:</b> {correct_answer}\n"
                    if explanation:
                        response_text += f"💡 <i>{explanation}</i>\n"
                    response_text += f"⏰ {time_str}\n\n"

                # Add player scores
                if scores_text:
                    response_text += "\n🏆 <b>Очки игроков:</b>\n" + scores_text

                # Split message if too long
                max_length = 4000
                if len(response_text) > max_length:
                    parts = []
                    current_part = "📋 <b>Сегодняшние вопросы и ответы:</b>\n\n"

                    for i, (question, correct_answer, explanation, sent_at) in enumerate(today_questions, 1):
                        time_str = sent_at.strftime('%H:%M') if sent_at else 'N/A'
                        question_text = f"<b>{i}.</b> {question}\n"
                        question_text += f"✅ <b>Ответ:</b> {correct_answer}\n"
                        if explanation:
                            question_text += f"💡 <i>{explanation}</i>\n"
                        question_text += f"⏰ {time_str}\n\n"

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
                else:
                    self.bot.reply_to(message, response_text, parse_mode='HTML')

        except Exception as e:
            print(f"Error getting correct answers: {e}")
            self.bot.reply_to(message, "❌ Произошла ошибка при получении вопросов")
        finally:
            if connection:
                self.db_manager.release_connection(connection)
    
    def load_trivia_data(self):
        """Load trivia data from database"""
        connection = None
        try:
            connection = self.db_manager.get_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM questions ORDER BY date_added DESC")
                return [{
                    'question': row[0],
                    'correct_answer': row[1],
                    'date_added': row[3].strftime('%d-%m-%Y %H:%M') if row[3] else 'Unknown'
                } for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error loading trivia data: {e}")
            return []
        finally:
            if connection:
                self.db_manager.release_connection(connection)
    
    def get_player_scores_for_chat(self, chat_id):
        """Get player scores for specific chat"""
        connection = None
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
                if connection:
                    self.db_manager.release_connection(connection)
                
        except Exception as e:
            print(f"Error getting player scores: {e}")
            return "Ошибка при получении очков."
        finally:
            if connection:
                self.db_manager.release_connection(connection)
    
