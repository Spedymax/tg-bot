import json
import uuid
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import google.generativeai as genai

logger = logging.getLogger(__name__)


@dataclass
class Question:
    """Data class representing a trivia question."""
    question: str
    correct_answer: str
    wrong_answers: List[str]
    explanation: str = ""
    answer_options: List[str] = None
    
    def __post_init__(self):
        if self.answer_options is None:
            self.answer_options = [self.correct_answer] + self.wrong_answers[:3]
            random.shuffle(self.answer_options)


@dataclass
class QuestionState:
    """Data class representing the state of an active question."""
    message_id: int
    question_text: str
    players_responses: Dict[str, str]
    answer_options: List[str]
    correct_answer: str
    explanation: str = ""


class TriviaService:
    """Service for managing trivia game logic and question generation."""
    
    def __init__(self, gemini_api_key: str, db_manager):
        self.db_manager = db_manager
        
        # Configure Gemini AI
        genai.configure(api_key=gemini_api_key)
        self.ai_client = genai.GenerativeModel('gemini-2.5-flash')
        
        self.difficulty = 'medium'
        self.active_questions: Dict[int, QuestionState] = {}
        
        # Player IDs for compatibility
        self.player_ids = {
            'YURA': 742272644,
            'MAX': 741542965,
            'BODYA': 855951767
        }
    
    def generate_question_with_ai(self) -> Optional[Question]:
        """Generate a trivia question using AI client."""
        if not self.ai_client:
            logger.error("AI client not available for question generation")
            return None
            
        try:
            prompt = self._build_question_prompt()
            
            response = self.ai_client.generate_content(prompt)
            response_text = response.text
            return self._parse_ai_response(response_text)
            
        except Exception as e:
            logger.error(f"Error generating question with AI: {str(e)}")
            return None
    
    def _build_question_prompt(self) -> str:
        """Build the prompt for AI question generation."""
        return """Ты - эксперт по созданию вопросов для викторины. Создай интересный вопрос на интересную тему.

Структура вопроса:
1. Формат:
   - Вопрос должен быть кратким (не более 2 строк)
   - Используй разговорный стиль, но без упрощения содержания
   - Избегай сложных терминов без необходимости
   - Вопрос должен быть однозначным и не допускать двойных толкований

2. Сложность:
   - Средний уровень (не очевидный, но и не экспертный)
   - Должен заставлять задуматься
   - Может содержать элементы юмора или неожиданные факты
   - Должен быть актуальным и основанным на реальных фактах

3. Ответы:
   - Правильный ответ должен быть однозначным и логически связан с вопросом
   - Неправильные ответы должны быть правдоподобными
   - Все ответы должны быть на одном языке
   - Каждый ответ не более 50 байт
   - Начинай каждый ответ с большой буквы
   - Без подсказок в формулировках

4. Проверка качества:
   - Вопрос и ответ должны соответствовать историческим/фактическим данным
   - Нет противоречий между условием и ответом
   - Все ответы логически связаны с темой вопроса
   - Вопрос должен быть интересным и познавательным

Обязательный формат ответа, придерживайся только его, не используй никакую другую формулировку:
ВОПРОС: [сам вопрос]
ПРАВИЛЬНЫЙ ОТВЕТ: [правильный ответ]
ОБЪЯСНЕНИЕ: [1-2 интересных факта, объясняющих правильный ответ]
НЕПРАВИЛЬНЫЕ ОТВЕТЫ: [ответ1], [ответ2], [ответ3]

Помни:
- Это дружеская викторина, но с образовательным элементом
- Вопросы должны быть интересными и запоминающимися
- Избегай тривиальных или слишком сложных вопросов
- Проверь финальный результат на логичность и соответствие фактам"""
    
    def _parse_ai_response(self, response_text: str) -> Optional[Question]:
        """Parse AI response into a Question object."""
        try:
            question = response_text.split('ВОПРОС: ')[1].split('ПРАВИЛЬНЫЙ ОТВЕТ:')[0].strip()
            correct_answer = response_text.split('ПРАВИЛЬНЫЙ ОТВЕТ: ')[1].split('ОБЪЯСНЕНИЕ:')[0].strip()
            explanation = response_text.split('ОБЪЯСНЕНИЕ: ')[1].split('НЕПРАВИЛЬНЫЕ ОТВЕТЫ:')[0].strip()
            wrong_answers_str = response_text.split('НЕПРАВИЛЬНЫЕ ОТВЕТЫ: ')[1].strip()
            wrong_answers = [ans.strip() for ans in wrong_answers_str.split(',')]
            
            return Question(
                question=question,
                correct_answer=correct_answer,
                wrong_answers=wrong_answers,
                explanation=explanation
            )
        except Exception as e:
            logger.error(f"Error parsing AI response: {str(e)}")
            return None
    
    def is_duplicate_question(self, question_text: str, correct_answer: str) -> bool:
        """Check if similar question already exists based on answer and keywords."""
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            # Check by exact answer match
            cursor.execute("SELECT question FROM questions WHERE LOWER(correct_answer) = LOWER(%s)", (correct_answer,))
            existing_questions = cursor.fetchall()
            
            if existing_questions:
                # Check if the question is about the same topic using keywords
                question_keywords = self._extract_keywords(question_text)
                
                for (existing_question,) in existing_questions:
                    existing_keywords = self._extract_keywords(existing_question)
                    
                    # Multiple checks for duplicates
                    similarity = self._calculate_similarity(question_keywords, existing_keywords)
                    
                    # Check 1: High keyword similarity (30% threshold since answers already match)
                    if similarity > 0.5:
                        logger.info(f"Duplicate detected by keyword similarity ({similarity:.2f}): '{question_text}' similar to '{existing_question}'")
                        cursor.close()
                        conn.close()
                        return True
                    
                    # Check 2: Look for key shared concepts
                    shared_important_words = question_keywords.intersection(existing_keywords)
                    if len(shared_important_words) >= 2:  # At least 2 important words match
                        logger.info(f"Duplicate detected by shared concepts ({shared_important_words}): '{question_text}' similar to '{existing_question}'")
                        cursor.close()
                        conn.close()
                        return True
            
            # Check for exact question match (just in case)
            cursor.execute("SELECT 1 FROM questions WHERE LOWER(question) = LOWER(%s)", (question_text,))
            if cursor.fetchone():
                logger.info(f"Exact duplicate question found: '{question_text}'")
                cursor.close()
                conn.close()
                return True
            
            cursor.close()
            conn.close()
            return False
        except Exception as e:
            logger.error(f"Error checking for duplicate question: {str(e)}")
            return False
    
    def _extract_keywords(self, text: str) -> set:
        """Extract meaningful keywords from question text."""
        # Remove common words and extract meaningful terms
        stop_words = {
            'какой', 'какая', 'какие', 'кто', 'что', 'где', 'когда', 'почему', 'как',
            'является', 'был', 'была', 'были', 'будет', 'это', 'этот', 'эта', 'эти',
            'в', 'на', 'из', 'по', 'для', 'с', 'от', 'до', 'при', 'над', 'под',
            'и', 'или', 'но', 'а', 'же', 'ли', 'не', 'ни', 'да', 'нет',
            'году', 'года', 'лет', 'веке', 'столетии', 'время', 'период'
        }
        
        words = text.lower().replace('?', '').replace('.', '').replace(',', '').split()
        keywords = {word for word in words if len(word) > 2 and word not in stop_words}
        
        return keywords
    
    def _calculate_similarity(self, keywords1: set, keywords2: set) -> float:
        """Calculate similarity between two sets of keywords."""
        if not keywords1 or not keywords2:
            return 0.0
        
        intersection = keywords1.intersection(keywords2)
        union = keywords1.union(keywords2)
        
        return len(intersection) / len(union) if union else 0.0
    
    def save_question_to_database(self, question: Question) -> bool:
        """Save question to database."""
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            answer_options_str = json.dumps(question.answer_options)
            current_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute(
                "INSERT INTO questions (question, correct_answer, answer_options, date_added, explanation) VALUES (%s, %s, %s, %s, %s)",
                (question.question, question.correct_answer, answer_options_str, current_date, question.explanation)
            )
            conn.commit()
            
            cursor.close()
            conn.close()
            logger.info("Question saved to database successfully")
            return True
        except Exception as e:
            logger.error(f"Error saving question to database: {str(e)}")
            return False
    
    def create_question_state(self, message_id: int, question: Question) -> QuestionState:
        """Create and store question state."""
        question_state = QuestionState(
            message_id=message_id,
            question_text=question.question,
            players_responses={},
            answer_options=question.answer_options,
            correct_answer=question.correct_answer,
            explanation=question.explanation
        )
        
        self.active_questions[message_id] = question_state
        self._save_question_state_to_db(question_state)
        return question_state
    
    def _save_question_state_to_db(self, question_state: QuestionState) -> bool:
        """Save question state to database."""
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            data_to_save = {
                "players_responses": question_state.players_responses,
                "options": question_state.answer_options,
                "correct_answer": question_state.correct_answer,
                "explanation": question_state.explanation
            }
            
            cursor.execute("""
                INSERT INTO question_state (message_id, original_question, players_responses)
                VALUES (%s, %s, %s) ON CONFLICT (message_id) DO
                UPDATE SET players_responses = EXCLUDED.players_responses
            """, (question_state.message_id, question_state.question_text, json.dumps(data_to_save)))
            
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error saving question state to database: {str(e)}")
            return False
    
    def load_question_states_from_db(self) -> Dict[int, QuestionState]:
        """Load all question states from database."""
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT message_id, original_question, players_responses FROM question_state")
            question_states = cursor.fetchall()
            
            loaded_states = {}
            for row in question_states:
                message_id, original_question = row[0], row[1]
                
                try:
                    data = json.loads(row[2]) if isinstance(row[2], str) else {}
                    
                    if isinstance(data, dict) and "players_responses" in data:
                        # New format
                        loaded_states[message_id] = QuestionState(
                            message_id=message_id,
                            question_text=original_question,
                            players_responses=data.get("players_responses", {}),
                            answer_options=data.get("options", []),
                            correct_answer=data.get("correct_answer", ""),
                            explanation=data.get("explanation", "")
                        )
                    else:
                        # Old format compatibility
                        loaded_states[message_id] = QuestionState(
                            message_id=message_id,
                            question_text=original_question,
                            players_responses=data if isinstance(data, dict) else {},
                            answer_options=[],
                            correct_answer="",
                            explanation=""
                        )
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Failed to parse question state for message {message_id}")
                    continue
            
            cursor.close()
            conn.close()
            self.active_questions = loaded_states
            return loaded_states
        except Exception as e:
            logger.error(f"Error loading question states from database: {str(e)}")
            return {}
    
    def process_answer(self, message_id: int, user_id: str, player_name: str, 
                      answer_index: int, chat_id: int) -> tuple[bool, str, bool]:
        """
        Process a user's answer to a question.
        Returns: (is_correct, response_message, should_show_explanation)
        """
        if message_id not in self.active_questions:
            return False, "Question not found", False
        
        question_state = self.active_questions[message_id]
        
        # Check if user already answered
        if self.has_answered_question(user_id, question_state.question_text):
            return False, "Ты уже ответил.", False
        
        # Validate answer index
        if answer_index >= len(question_state.answer_options):
            return False, "Answer option not found", False
        
        # Get the actual answer
        selected_answer = question_state.answer_options[answer_index]
        is_correct = selected_answer == question_state.correct_answer
        
        # Update responses
        emoji = "✅" if is_correct else "❌"
        question_state.players_responses[player_name] = emoji
        
        # Save to database
        self._save_question_state_to_db(question_state)
        self._record_user_answer(user_id, question_state.question_text)
        
        # Check if we should show explanation
        should_show_explanation = self._should_show_explanation(chat_id, question_state)
        
        return is_correct, "Vote counted!", should_show_explanation
    
    def has_answered_question(self, user_id: str, question: str) -> bool:
        """Check if user has already answered this question today."""
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            cursor.execute(
                "SELECT 1 FROM answered_questions WHERE user_id = %s AND question = %s AND date_added = %s",
                (user_id, question, current_date)
            )
            result = cursor.fetchone() is not None
            
            cursor.close()
            conn.close()
            return result
        except Exception as e:
            logger.error(f"Error checking if user answered question: {str(e)}")
            return False
    
    def _record_user_answer(self, user_id: str, question: str) -> bool:
        """Record that user has answered this question."""
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            cursor.execute(
                "INSERT INTO answered_questions (user_id, question, date_added) VALUES (%s, %s, %s)",
                (user_id, question, current_date)
            )
            conn.commit()
            
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error recording user answer: {str(e)}")
            return False
    
    def _should_show_explanation(self, chat_id: int, question_state: QuestionState) -> bool:
        """Determine if explanation should be shown."""
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            # Get active users count for this chat
            cursor.execute(
                "SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE chat_id = %s", 
                (chat_id,)
            )
            active_users_count = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            # Show explanation if all active users have answered
            return len(question_state.players_responses) >= active_users_count
        except Exception as e:
            logger.error(f"Error checking if should show explanation: {str(e)}")
            return False
    
    def get_question_display_text(self, message_id: int) -> str:
        """Get the formatted display text for a question."""
        if message_id not in self.active_questions:
            return "Question not found"
        
        question_state = self.active_questions[message_id]
        text = question_state.question_text
        
        if question_state.players_responses:
            text += "\n\n" + "\n".join([
                f"{player} {response}" 
                for player, response in question_state.players_responses.items()
            ])
        
        return text
    
    def get_trivia_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get trivia question history."""
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT question, correct_answer, date_added, explanation FROM questions ORDER BY date_added DESC LIMIT %s",
                (limit,)
            )
            
            history = []
            for row in cursor.fetchall():
                history.append({
                    'question': row[0],
                    'correct_answer': row[1],
                    'date_added': row[2].strftime('%d-%m-%Y %H:%M'),
                    'explanation': row[3] or ""
                })
            
            cursor.close()
            conn.close()
            return history
        except Exception as e:
            logger.error(f"Error getting trivia history: {str(e)}")
            return []
    
    def get_today_questions(self) -> List[Dict[str, Any]]:
        """Get today's trivia questions with answers."""
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT question, correct_answer, explanation, date_added "
                "FROM questions "
                "WHERE DATE(date_added) = CURRENT_DATE "
                "ORDER BY date_added DESC"
            )
            
            today_questions = []
            for row in cursor.fetchall():
                today_questions.append({
                    'question': row[0],
                    'correct_answer': row[1],
                    'explanation': row[2] or "",
                    'date_added': row[3].strftime('%H:%M') if row[3] else 'N/A'
                })
            
            cursor.close()
            conn.close()
            return today_questions
        except Exception as e:
            logger.error(f"Error getting today's questions: {str(e)}")
            return []
    
    def clear_trivia_data(self) -> bool:
        """Clear all trivia data."""
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM answered_questions")
            conn.commit()
            
            cursor.close()
            conn.close()
            
            self.active_questions.clear()
            logger.info("Trivia data cleared successfully")
            return True
        except Exception as e:
            logger.error(f"Error clearing trivia data: {str(e)}")
            return False
    
    def update_player_score(self, user_id: str, chat_id: int, is_correct: bool, 
                          player_stats: Dict[str, Any]) -> bool:
        """Update player score for correct answer."""
        if not is_correct or user_id not in player_stats:
            return False
        
        try:
            # Find current score for this chat
            current_score = 0
            for score_entry in player_stats[user_id]["correct_answers"]:
                if f"{chat_id}:" in score_entry:
                    current_score = int(score_entry.split(":")[1])
                    break
            
            # Update score
            new_score = current_score + 1
            new_score_entry = f"{chat_id}:{new_score}"
            
            # Remove old score and add new one
            player_stats[user_id]["correct_answers"] = [
                entry for entry in player_stats[user_id]["correct_answers"]
                if not entry.startswith(f"{chat_id}:")
            ]
            player_stats[user_id]["correct_answers"].append(new_score_entry)
            
            return True
        except Exception as e:
            logger.error(f"Error updating player score: {str(e)}")
            return False
    
    def generate_question(self, user_id: str, player_name: str) -> Dict[str, Any]:
        """Generate a new trivia question for a user."""
        try:
            # Generate question using AI
            question = self.generate_question_with_ai()
            if not question:
                return {
                    "success": False,
                    "message": "Не удалось сгенерировать вопрос. Попробуйте позже."
                }
            
            # Check if question is a duplicate
            if self.is_duplicate_question(question.question, question.correct_answer):
                return {
                    "success": False,
                    "message": "Этот вопрос уже был задан ранее. Попробуйте еще раз."
                }
            
            # Save question to database
            if not self.save_question_to_database(question):
                logger.warning("Failed to save question to database")
            
            # Create question ID
            question_id = str(uuid.uuid4())[:8]
            
            return {
                "success": True,
                "question": {
                    "id": question_id,
                    "text": question.question,
                    "options": question.answer_options,
                    "correct_answer": question.correct_answer,
                    "explanation": question.explanation
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating question: {str(e)}")
            return {
                "success": False,
                "message": "Произошла ошибка при создании вопроса."
            }
    
    def submit_answer(self, question_id: str, answer_idx: int, user_id: str, player_name: str) -> Dict[str, Any]:
        """Submit an answer to a trivia question."""
        try:
            # For now, we'll simulate a correct/incorrect response
            # In a real implementation, you'd track the question state
            is_correct = random.choice([True, False])  # Simplified for demo
            
            score_change = 10 if is_correct else 0
            emoji = "✅" if is_correct else "❌"
            
            callback_message = "Правильно!" if is_correct else "Неправильно!"
            
            message = f"{player_name} {emoji}\n\n"
            if is_correct:
                message += "🎉 Отличный ответ! +10 очков"
            else:
                message += "😔 Не угадали, но не расстраивайтесь!"
            
            return {
                "success": True,
                "message": message,
                "callback_message": callback_message,
                "score_change": score_change,
                "is_correct": is_correct
            }
            
        except Exception as e:
            logger.error(f"Error submitting answer: {str(e)}")
            return {
                "success": False,
                "message": "Произошла ошибка при обработке ответа.",
                "callback_message": "Ошибка",
                "score_change": 0,
                "is_correct": False
            }
