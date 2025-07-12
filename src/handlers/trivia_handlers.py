import random
import json
import html
from telebot import types
from datetime import datetime, timezone, timedelta
import google.generativeai as genai
from config.settings import Settings
from services.trivia_service import TriviaService

class TriviaHandlers:
    def __init__(self, bot, player_service, game_service, db_manager):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        self.db_manager = db_manager
        
        # Initialize TriviaService for AI question generation
        self.trivia_service = TriviaService(Settings.GEMINI_API_KEY, db_manager)
        
        self.question_messages = {}
        self.original_questions = {}
        
        # Player IDs for scoring
        self.PLAYER_IDS = {
            'YURA': 742272644,
            'MAX': 741542965,
            'BODYA': 855951767
        }
    
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
                player = self.player_service.get_player(user_id)
                if player:
                    chat_id = call.message.chat.id
                    current_score = player.get_quiz_score(chat_id)
                    player.update_quiz_score(chat_id, current_score + 1)
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
        connection = self.db_manager.get_connection()
        try:
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
            self.db_manager.release_connection(connection)
    
    def load_question_state_from_db(self, message_id):
        """Load question state from database"""
        connection = self.db_manager.get_connection()
        try:
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
            self.db_manager.release_connection(connection)
    
    def get_correct_answers(self, message):
        """Show today's questions with correct answers"""
        try:
            connection = self.db_manager.get_connection()
            
            try:
                with connection.cursor() as cursor:
                    # Get today's questions
                    cursor.execute(
                        "SELECT question, correct_answer, explanation, date_added "
                        "FROM questions "
                        "WHERE DATE(date_added) = CURRENT_DATE "
                        "ORDER BY date_added DESC"
                    )
                    
                    today_questions = cursor.fetchall()
                    
                    if not today_questions:
                        self.bot.reply_to(message, "📋 Сегодня вопросов еще не было!")
                        return
                    
                    # Get player scores for this chat
                    chat_id = message.chat.id
                    scores_text = self.get_player_scores_for_chat(chat_id)
                    
                    # Build response message
                    response_text = "📋 <b>Сегодняшние вопросы и ответы:</b>\n\n"
                    
                    for i, (question, correct_answer, explanation, date_added) in enumerate(today_questions, 1):
                        time_str = date_added.strftime('%H:%M') if date_added else 'N/A'
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
                        
                        for i, (question, correct_answer, explanation, date_added) in enumerate(today_questions, 1):
                            time_str = date_added.strftime('%H:%M') if date_added else 'N/A'
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
                        
            finally:
                self.db_manager.release_connection(connection)
                
        except Exception as e:
            print(f"Error getting correct answers: {e}")
            self.bot.reply_to(message, "❌ Произошла ошибка при получении вопросов")
    
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
            print(f"Error loading trivia data: {e}")
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
            print(f"Error getting player scores: {e}")
            return "Ошибка при получении очков."
    
