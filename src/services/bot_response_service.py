import random
import time
import logging
from typing import Dict, List, Optional, Callable
import telebot

logger = logging.getLogger(__name__)


class BotResponseService:
    """Service for handling bot command responses and entertainment features."""
    
    def __init__(self):
        self.commands = {
            "отшлёпай Юру": "Юра отшлёпан :)",
            "отшлёпай Машу": "Маша отшлёпана :)",
            "расскажи что ты можешь": "Отправляет список команд",
            "отшлёпай Макса": "Нельзя шлёпать Макса :(",
            "что-то жарко стало": "Включает вентилятор",
            "расскажи анекдот": "Рассказывает анекдот",
            "расскажи анекдот про маму Юры": "Рассказывает анекдот про маму Юры",
            "расскажи анекдот про маму Богдана": "Нет.",
            "расскажи анекдот про маму Максима": "Шутка",
            "накажи Богдана": "Наказание",
            "давай ещё разок": "Наказание2",
            "как правильно ухаживать за ребёнком?": "Уход за ребёнком",
        }
        
        # Special user IDs
        self.bogdan_id = 855951767
        
    def get_command_list(self) -> str:
        """Get formatted list of available commands."""
        return "Вот мои команды:\n" + "\n".join(self.commands.keys())
    
    def process_bot_command(self, message: telebot.types.Message, bot: telebot.TeleBot, 
                          dad_jokes_func: Optional[Callable] = None, 
                          image_urls: Optional[List[str]] = None) -> bool:
        """
        Process bot command from message.
        Returns True if command was processed, False otherwise.
        """
        if not message.text or "Бот," not in message.text:
            return False
        
        try:
            # Extract text after bot mention
            prompt = message.text.split("Бот,", 1)[1].strip()
            
            return self._handle_command(prompt, message, bot, dad_jokes_func, image_urls)
        except Exception as e:
            logger.error(f"Error processing bot command: {str(e)}")
            bot.send_message(message.chat.id, "?")
            return True
    
    def _handle_command(self, prompt: str, message: telebot.types.Message, 
                       bot: telebot.TeleBot, dad_jokes_func: Optional[Callable] = None,
                       image_urls: Optional[List[str]] = None) -> bool:
        """Handle specific command logic."""
        
        # Command list request
        if prompt in ["расскажи что ты можешь", "что ты можешь?"]:
            bot.send_message(message.chat.id, self.get_command_list())
            return True
        
        # Check if command exists
        if prompt not in self.commands:
            bot.send_message(message.chat.id, "?")
            return True
        
        # Handle specific commands
        if prompt == "расскажи анекдот":
            if dad_jokes_func:
                dad_jokes_func(message)
            else:
                bot.send_message(message.chat.id, "Функция анекдотов недоступна")
                
        elif prompt == "накажи Богдана":
            self._punish_bogdan(bot, message.chat.id, image_urls)
            
        elif prompt == "давай ещё разок":
            self._punish_bogdan_again(bot, message.chat.id, image_urls)
            
        elif prompt == "как правильно ухаживать за ребёнком?":
            self._send_controversial_content(bot, message.chat.id)
            
        elif prompt == "расскажи анекдот про маму Юры":
            self._send_yura_mom_joke(bot, message.chat.id)
            
        elif prompt == "что-то жарко стало":
            self._handle_fan_request(bot, message.chat.id)
            
        elif prompt in ["расскажи анекдот про маму Максима", "расскажи анекдот про маму Макса", 
                       "расскажи анекдот про маму максима", "расскажи анекдот про маму макса"]:
            self._send_max_mom_joke(bot, message.chat.id)
            
        else:
            # Default command response
            bot.send_message(message.chat.id, self.commands[prompt])
        
        return True
    
    def _punish_bogdan(self, bot: telebot.TeleBot, chat_id: int, image_urls: Optional[List[str]]):
        """Send punishment to Bogdan."""
        bot.send_message(chat_id, "Отсылаю 9999 каринок фурри в личку Богдану :)")
        
        if image_urls:
            for i in range(1, 15):
                self._send_furry_pics(bot, image_urls, self.bogdan_id)
                logger.info(f'Punishment image sent: {i}')
    
    def _punish_bogdan_again(self, bot: telebot.TeleBot, chat_id: int, image_urls: Optional[List[str]]):
        """Send additional punishment to Bogdan."""
        bot.send_message(chat_id, "Отсылаю ещё 9999 каринок фурри в личку Богдану :)")
        
        if image_urls:
            for i in range(1, 15):
                self._send_furry_pics(bot, image_urls, self.bogdan_id)
                logger.info(f'Additional punishment image sent: {i}')
    
    def _send_controversial_content(self, bot: telebot.TeleBot, chat_id: int):
        """Send controversial content (warning: dark humor)."""
        controversial_text = (
            "1.Спускаем кровь \\n Чтобы мясо не испортилось, спускают кровь. Делают это "
            "следующим образом: кладут ребёнка на правый бок так, чтобы голова оказалась ниже "
            "тела. Левую ногу нужно прижать к груди, затем острым охотничьим ножом протыкают "
            "артерии и вены. У детей нож вводить нужно в сердце и делать разрез по направлению "
            "к хребту. Для того, чтобы облегчить доступ к сердцу ребёнка, нужно левую ногу "
            "отвести в строну. Кровь выпускается до тех пор, пока она не перестанет вытекать. "
            "Если обескровить ребёнка не полностью, то мясо может плохо храниться или потерять "
            "вкусовые свойства. \\n 2. Потрошение тушки \\n Потрошение детей происходит по "
            "одинаковому алгоритму. Ребёнка кладут на спину и закрепляют в таком положении с "
            "помощью веревок и растяжек. Под бока следует подложить камни или поленья, "
            "чтобы тело не перекатилась на бок. Первое действие – разрезать кожу, проводя ножом "
            "от шеи через грудину и живот до анального отверстия. Далее нужно аккуратно снять "
            "шкуру с ребёнка, постепенно ее подрезая ножом. Внутренности начинают извлекать из "
            "шейной части: пищевод отделяют от трахеи и завязывают узлом, чтобы избежать "
            "загрязнения мяса. Далее Вам нужно высвободить пальцами пищевод и отрезать его у "
            "переднего конца. Пищевод из-за этих процедур достаточно плотно закрывается, "
            "после чего его нужно запихнуть подальше в грудную клетку. Чтобы избавить язык от "
            "связок, делают глубокие разрезы по обеим сторонам челюсти. Далее нужно обработать "
            "брюшную полость: делается разрез по средней линии живота до грудной кости. Для "
            "потрошения существуют специальные ножи, которые позволяют сделать вскрытие одним "
            "движением. Если тело большое, то после последнего ребра делают разрез до "
            "позвоночника. Еще один разрез делают по направлению к выходу прямой кишки. Когда "
            "будете вскрывать брюшную полость, действуйте предельно осторожно, "
            "чтобы не разрезать кишки и другие внутренние органы. В противном случае, "
            "можно загрязнить мясо. Помните, что диафрагма быстро портиться. Поэтому ее "
            "рекомендуют убрать от ребер сразу же при потрошении. Удаляя пищевод, прямую кишку, "
            "следите, чтобы содержимое не вылилось наружу. Почки, печень, селезенка, сердце, "
            "легкие, язык и желудок могут употребляться в пищу. Сердце нужно надрезать и "
            "выпустить кровь. Не забудьте обескровить тело до конца, для этого нужно сделать "
            "разрез на внутренней части бедра. Для того, чтобы кровь максимально стеклась, "
            "тело подвешивают за переднюю часть. При потрошении нужно обращать внимание на "
            "форму и цвет всех внутренних органов. Если заметите что-то подозрительное, "
            "то лучше не употреблять такое мясо в пищу. Не забудьте сдать мясо на проверку, "
            "вдруг ментам понравиться :)"
        )
        bot.send_message(chat_id, controversial_text)
    
    def _send_yura_mom_joke(self, bot: telebot.TeleBot, chat_id: int):
        """Send Yura's mom joke with image."""
        bot.send_message(chat_id, "Ну ладно")
        try:
            with open('/home/spedymax/tg-bot/assets/images/bezobidno.jpg', 'rb') as photo:
                time.sleep(1)
                bot.send_photo(chat_id, photo)
        except FileNotFoundError:
            bot.send_message(chat_id, "Image not found")
    
    def _handle_fan_request(self, bot: telebot.TeleBot, chat_id: int):
        """Handle fan request with animated response."""
        bot.send_message(chat_id, "Понял, включаю вентилятор 卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐...")
        time.sleep(5)
        bot.send_message(chat_id, "Чёт вентилятор сломался 卐卐卐卐卐卐, из-за грозы наверное ᛋᛋ")
        time.sleep(5)
        bot.send_message(chat_id, "Достаём инструменты ☭☭☭☭☭, всё починил, можно и поспать ZzzZZzZzZZZ")
    
    def _send_max_mom_joke(self, bot: telebot.TeleBot, chat_id: int):
        """Send Max's mom joke."""
        bot.send_message(chat_id, "С радостью :)")
        time.sleep(3)
        joke_text = (
            "Мама Максима попросила его друга Юру помочь с ремонтом ванной. Юра согласился и начал "
            "разбираться с трубами.\\nВ какой-то момент он спрашивает: — Мама Максима, а у вас есть "
            "гаечный ключ?\\nНа что мама отвечает:— Нет, Юра, иди нахуй"
        )
        bot.send_message(chat_id, joke_text)
    
    def _send_furry_pics(self, bot: telebot.TeleBot, image_urls: List[str], chat_id: int):
        """Send random furry pictures."""
        try:
            random_selection = random.sample(image_urls, min(5, len(image_urls)))
            for url in random_selection:
                try:
                    if url.endswith(('.jpg', '.jpeg', '.png')):
                        bot.send_photo(chat_id, photo=url)
                    elif url.endswith(('.gif', '.gifv')):
                        bot.send_animation(chat_id, animation=url)
                except Exception as e:
                    logger.error(f"Error sending furry pic: {str(e)}")
        except Exception as e:
            logger.error(f"Error in send_furry_pics: {str(e)}")
    
    def add_custom_command(self, command: str, description: str):
        """Add a custom command to the bot."""
        self.commands[command] = description
    
    def remove_command(self, command: str) -> bool:
        """Remove a command from the bot."""
        if command in self.commands:
            del self.commands[command]
            return True
        return False
    
    def get_command_description(self, command: str) -> Optional[str]:
        """Get description for a specific command."""
        return self.commands.get(command)
    
    def get_help_text(self) -> str:
        """Get help text with available commands."""
        return (
            "🤖 **Доступные команды:**\n\n"
            "**Основные команды:**\n"
            "/start - начать работу с ботом\n"
            "/help - показать это сообщение\n"
            "/stats, /profile - показать профиль игрока\n\n"
            "**Игры и викторины:**\n"
            "/trivia, /quiz - викторина с вопросами\n"
            "/kazik, /casino <ставка> - казино\n"
            "кубик - бросить кубик\n"
            "монетка - подбросить монету\n\n"
            "**Турнир:**\n"
            "/tournament start - начать новый раунд\n"
            "/tournament leaderboard - таблица лидеров\n\n"
            "**NoNutNovember (только в ноябре):**\n"
            "/nnn motivation - мотивация\n"
            "/nnn leaderboard - таблица лидеров\n"
            "/nnn status - ваш статус\n\n"
            "**Развлечения:**\n"
            "/joke - случайная шутка\n"
            "/rofl - рандомное изображение\n"
            "/punishment - наказание\n\n"
            "**Простые команды:**\n"
            "привет - поздороваться\n"
            "пока - попрощаться\n"
            "спасибо - поблагодарить"
        )
    
    def process_command(self, command: str) -> Optional[Dict[str, str]]:
        """Process simple text commands and return response."""
        command = command.lower().strip()
        
        # Simple responses
        simple_responses = {
            "привет": "Привет! 👋",
            "пока": "Пока! До встречи! 👋",
            "спасибо": "Пожалуйста! 😊",
            "кубик": f"🎲 Выпало: {random.randint(1, 6)}",
            "монетка": f"🪙 Выпало: {'Орёл' if random.choice([True, False]) else 'Решка'}"
        }
        
        if command in simple_responses:
            return {"content": simple_responses[command], "type": "text"}
        
        return None
