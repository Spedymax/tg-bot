import random
import time
import os
from telebot import types
from datetime import datetime, timezone, timedelta
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json

class EntertainmentHandlers:
    def __init__(self, bot, player_service, game_service):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        
        # Bot response commands
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
        
        # Load configuration
        self.config = self.load_config()
        self.image_urls = self.config.get('furry_image_urls', [])
        
        # Dad jokes list (you'd load these from a file or database)
        self.dad_jokes_list = [
            "Почему программисты не любят природу? Потому что в ней слишком много багов!",
            "Как называется программист, который не пьёт кофе? Спящий режим!",
            "Почему у программистов плохая память? Потому что они всё в переменных хранят!",
            # Add more jokes here
        ]
    
    def load_config(self):
        """Load configuration from furry_images.json"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'furry_images.json')
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            # Return default config if file doesn't exist
            return {
                'furry_image_urls': [
                    'https://cdn.pixabay.com/photo/2016/12/13/05/15/puppy-1903313_960_720.jpg',
                    'https://cdn.pixabay.com/photo/2014/11/30/14/11/cat-551554_960_720.jpg',
                    'https://cdn.pixabay.com/photo/2016/07/15/15/55/dachshund-1519374_960_720.jpg'
                ]
            }
    
    def setup_handlers(self):
        """Setup all entertainment command handlers"""
        
        @self.bot.message_handler(commands=['furrypics'])
        def furry_pics_command(message):
            """Handle /furrypics command"""
            self.send_furry_pics(message.chat.id)
        
        @self.bot.message_handler(commands=['piratik'])
        def pirate_song_command(message):
            """Handle /piratik command"""
            self.send_pirate_song(message)
        
        @self.bot.message_handler(commands=['anekdot', 'joke'])
        def dad_joke_command(message):
            """Handle joke commands"""
            self.send_dad_joke(message)
        
        @self.bot.message_handler(commands=['otsos'])
        def otsos_command(message):
            """Handle /otsos command"""
            self.handle_otsos(message)
        
        @self.bot.message_handler(commands=['peremoga'])
        def peremoga_command(message):
            """Handle /peremoga command"""
            for i in range(5):
                self.bot.send_message(message.chat.id, 'ПЕРЕМОГА БУДЕ ЛЮЮЮЮЮЮЮДИИИИИИИИ!!!!!')
        
        @self.bot.message_handler(commands=['zrada'])
        def zrada_command(message):
            """Handle /zrada command"""
            for i in range(5):
                self.bot.send_message(message.chat.id, 'ЗРАДАААА😭😭😭😭')
        
        @self.bot.message_handler(commands=['prosipaisya'])
        def prosipaisya_command(message):
            """Handle /prosipaisya command"""
            BODYA_ID = 855951767
            for i in range(1, 5):
                self.bot.send_message(message.chat.id,
                                    f"<a href='tg://user?id={BODYA_ID}'>@lofiSnitch</a>",
                                    parse_mode='html')
        
        # Bot conversation handler
        @self.bot.message_handler(func=lambda message: message.text and message.text.startswith("Бот,"))
        def bot_conversation(message):
            """Handle bot conversation commands"""
            self.handle_bot_answer(message)
        
        # Callback handlers
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('otsos'))
        def otsos_callback(call):
            """Handle otsos callback"""
            self.handle_otsos_callback(call)
    
    def handle_bot_answer(self, message):
        """Handle bot conversation commands"""
        try:
            # Extract text after bot mention
            prompt = message.text.split("Бот,", 1)[1].strip()
            
            # Check if it's a command list request
            if prompt in ["расскажи что ты можешь", "что ты можешь?"]:
                command_list = "\\n".join(self.commands.keys())
                self.bot.send_message(message.chat.id, "Вот мои команды:\\n" + command_list)
                return
            
            # Handle specific commands
            if prompt in self.commands:
                if prompt == "расскажи анекдот":
                    self.send_dad_joke(message)
                elif prompt == "накажи Богдана":
                    self.bot.send_message(message.chat.id, "Отсылаю 9999 каринок фурри в личку Богдану :)")
                    for i in range(1, 15):
                        self.send_furry_pics(855951767)  # Bogdan's ID
                        print(f'Отправлено: {i}')
                elif prompt == "давай ещё разок":
                    self.bot.send_message(message.chat.id, "Отсылаю ещё 9999 каринок фурри в личку Богдану :)")
                    for i in range(1, 15):
                        self.send_furry_pics(855951767)
                        print(f'Отправлено: {i}')
                elif prompt == "расскажи анекдот про маму Юры":
                    self.bot.send_message(message.chat.id, "Ну ладно")
                    try:
                        with open('assets/images/bezobidno.jpg', 'rb') as photo:
                            time.sleep(1)
                            self.bot.send_photo(message.chat.id, photo)
                    except FileNotFoundError:
                        self.bot.send_message(message.chat.id, "Файл изображения не найден")
                elif prompt == "что-то жарко стало":
                    self.bot.send_message(message.chat.id, "Понял, включаю вентилятор 卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐...")
                    time.sleep(5)
                    self.bot.send_message(message.chat.id, "Чёт вентилятор сломался 卐卐卐卐卐卐, из-за грозы наверное ᛋᛋ")
                    time.sleep(5)
                    self.bot.send_message(message.chat.id, "Достаём инструменты ☭☭☭☭☭, всё починил, можно и поспать ZzzZZzZzZZZ")
                elif prompt in ["расскажи анекдот про маму Максима", "расскажи анекдот про маму Макса"]:
                    self.bot.send_message(message.chat.id, "С радостью :)")
                    time.sleep(3)
                    self.bot.send_message(message.chat.id,
                                        "Мама Максима попросила его друга Юру помочь с ремонтом ванной. Юра согласился и начал "
                                        "разбираться с трубами.\\nВ какой-то момент он спрашивает: — Мама Максима, а у вас есть "
                                        "гаечный ключ?\\nНа что мама отвечает:— Нет, Юра, иди нахуй")
                elif prompt == "как правильно ухаживать за ребёнком?":
                    # This is a very dark joke - you might want to remove or modify this
                    self.bot.send_message(message.chat.id, "Это очень тёмный юмор, который я не буду повторять...")
                else:
                    self.bot.send_message(message.chat.id, self.commands[prompt])
            else:
                self.bot.send_message(message.chat.id, "?")
                
        except Exception as e:
            print(f"Error in bot conversation: {e}")
            self.bot.send_message(message.chat.id, "Произошла ошибка при обработке команды.")

    def parse_furry_images(self, source, source_type='url'):
        """
        Parse furry images and extract URLs

        Args:
            source: URL string, HTML content, or file path
            source_type: 'url', 'html', or 'file'

        Returns:
            list: List of image URLs
        """
        image_urls = []

        try:
            # Get HTML content based on source type
            if source_type == 'url':
                response = requests.get(source, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }, timeout=10)
                response.raise_for_status()
                html_content = response.text
                base_url = source
            elif source_type == 'html':
                html_content = source
                base_url = ''
            elif source_type == 'file':
                with open(source, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                base_url = ''

            # Parse HTML
            soup = BeautifulSoup(html_content, 'html.parser')

            # Find all image tags
            img_tags = soup.find_all('img')

            # Common furry art file extensions
            furry_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']

            # Extract URLs from img tags
            for img in img_tags:
                src = img.get('src') or img.get('data-src') or img.get('data-original') or img.get('data-lazy-src')
                if src:
                    # Convert relative URLs to absolute
                    if base_url and not src.startswith(('http://', 'https://')):
                        src = urljoin(base_url, src)

                    # Check if it's an image file
                    if any(ext in src.lower() for ext in furry_extensions):
                        image_urls.append(src)

            # Also check for links to images
            links = soup.find_all('a', href=True)
            for link in links:
                href = link['href']
                if base_url and not href.startswith(('http://', 'https://')):
                    href = urljoin(base_url, href)

                if any(ext in href.lower() for ext in furry_extensions):
                    image_urls.append(href)

            # Remove duplicates while preserving order
            image_urls = list(dict.fromkeys(image_urls))

            # Filter out common non-furry images (icons, UI elements, etc.)
            filtered_urls = []
            skip_patterns = ['icon', 'logo', 'button', 'arrow', 'banner', 'ad', 'avatar', 'thumb']

            for url in image_urls:
                if not any(pattern in url.lower() for pattern in skip_patterns):
                    # Validate URL format
                    parsed = urlparse(url)
                    if parsed.scheme in ['http', 'https'] and parsed.netloc:
                        filtered_urls.append(url)

            return filtered_urls

        except Exception as e:
            print(f"Error parsing images: {e}")
            return []

    def get_furry_images_from_multiple_sources(self):
        """Get furry images from multiple reliable sources"""
        image_urls = []
        
        # Try multiple sources
        sources = [
            'https://e621.net/posts.json'  # E621 API (SFW only)
        ]

        
        for source in sources:
            try:
                response = requests.get(source, timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; FurryBot/1.0)'
                })
                if response.status_code == 200:
                    data = response.json()
                    # Extract image URLs from API response
                    if 'posts' in data:  # E621 format
                        for post in data['posts']:
                            if 'file' in post and 'url' in post['file']:
                                image_urls.append(post['file']['url'])
                    elif 'submissions' in data:  # FurAffinity format
                        for submission in data['submissions']:
                            if 'thumbnail' in submission:
                                image_urls.append(submission['thumbnail'])
            except:
                continue
        
        # If no images found from APIs, use fallback
        if not image_urls:
            image_urls = fallback_urls
            
        return image_urls

    def send_furry_pics(self, chat_id):
        """Send furry pictures"""
        # Try to get images from APIs first
        image_urls = self.get_furry_images_from_multiple_sources()
        
        # If no images from APIs, try parsing a simple gallery site
        if not image_urls:
            try:
                # Use a more reliable source
                filtered = self.parse_furry_images('https://www.furaffinity.net/browse/', 'url')
                if filtered:
                    image_urls = filtered
            except:
                pass
        
        # Final fallback: use pre-configured URLs from config
        if not image_urls:
            image_urls = self.image_urls
        
        if not image_urls:
            self.bot.send_message(chat_id, "Изображения временно недоступны")
            return
            
        # Select random images
        num_to_send = min(5, len(image_urls))
        random_selection = random.sample(image_urls, num_to_send)
        
        for url in random_selection:
            try:
                # Validate URL before sending
                if self.is_valid_image_url(url):
                    if url.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        self.bot.send_photo(chat_id, photo=url)
                    elif url.lower().endswith(('.gif', '.gifv')):
                        self.bot.send_animation(chat_id, animation=url)
                    time.sleep(0.5)  # Small delay between sends
            except Exception as e:
                print(f"Error sending image {url}: {e}")
                continue
    
    def is_valid_image_url(self, url):
        """Validate if URL is a valid image URL"""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False
            
            # Check if it's a valid image extension
            valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']
            return any(url.lower().endswith(ext) for ext in valid_extensions)
        except:
            return False
    
    def send_pirate_song(self, message):
        """Send random pirate song"""
        songs_folder = 'assets/audio/pirat-songs'
        try:
            if not os.path.exists(songs_folder):
                self.bot.send_message(message.chat.id, "Папка с песнями не найдена")
                return
                
            song_files = [f for f in os.listdir(songs_folder) if f.endswith('.mp3')]
            
            if not song_files:
                self.bot.send_message(message.chat.id, "No MP3 songs found in the folder.")
                return
            
            # Select a random song from the list
            random_song = random.choice(song_files)
            
            # Send the selected song to the user
            with open(os.path.join(songs_folder, random_song), 'rb') as audio_file:
                self.bot.send_audio(message.chat.id, audio_file)
                
        except Exception as e:
            print(f"Error sending pirate song: {e}")
            self.bot.send_message(message.chat.id, "Ошибка при отправке песни")
    
    def send_dad_joke(self, message):
        """Send a random dad joke"""
        if self.dad_jokes_list:
            joke = random.choice(self.dad_jokes_list)
            self.bot.send_message(message.chat.id, joke)
        else:
            self.bot.send_message(message.chat.id, "Анекдоты не загружены :(")
    
    def handle_otsos(self, message):
        """Handle /otsos command"""
        player_id = message.from_user.id
        player = self.player_service.get_player(player_id)
        
        if not player:
            self.bot.reply_to(message, "Вы не зарегистрированы как игрок")
            return
        
        # Create inline keyboard for target selection
        markup = types.InlineKeyboardMarkup()
        
        # Add buttons for different targets (customize based on your player IDs)
        targets = [
            ("Юра", "otsos_742272644"),
            ("Макс", "otsos_741542965"), 
            ("Богдан", "otsos_855951767")
        ]
        
        for name, callback_data in targets:
            button = types.InlineKeyboardButton(name, callback_data=callback_data)
            markup.add(button)
        
        self.bot.send_message(
            message.chat.id,
            f"<a href='tg://user?id={player_id}'>@{message.from_user.username}</a>, у кого отсасываем?",
            reply_markup=markup,
            parse_mode='html'
        )
    
    def handle_otsos_callback(self, call):
        """Handle otsos target selection"""
        try:
            target_id = int(call.data.split('_')[1])
            
            # Remove the keyboard
            self.bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
            
            # Get players
            player = self.player_service.get_player(call.from_user.id)
            target = self.player_service.get_player(target_id)
            
            if not player or not target:
                self.bot.send_message(call.message.chat.id, "Игрок не найден")
                return
            
            # Apply otsos effect (reduce target's size, increase player's size)
            stolen_amount = random.randint(1, 5)
            target.pisunchik_size -= stolen_amount
            player.pisunchik_size += stolen_amount
            
            # Save changes
            self.player_service.save_player(player)
            self.player_service.save_player(target)
            
            self.bot.send_message(
                call.message.chat.id, 
                f"Вы отсосали {stolen_amount} см у {target.player_name}!"
            )
            
        except Exception as e:
            print(f"Error in otsos callback: {e}")
            self.bot.send_message(call.message.chat.id, "Произошла ошибка")
