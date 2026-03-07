import random
import os
import logging
from datetime import datetime, timezone, timedelta
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
import asyncio

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from utils.helpers import safe_split_callback, safe_int, escape_html, safe_username

logger = logging.getLogger(__name__)

class EntertainmentHandlers:
    def __init__(self, bot, player_service, game_service):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        self.router = Router()

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
        self.whats_new_path = os.path.join(os.path.dirname(__file__), '..', '..', 'assets', 'data', 'whats_new.json')

        # Dad jokes list (you'd load these from a file or database)
        self.dad_jokes_list = [
            "Почему программисты не любят природу? Потому что в ней слишком много багов!",
            "Как называется программист, который не пьёт кофе? Спящий режим!",
            "Почему у программистов плохая память? Потому что они всё в переменных хранят!",
            # Add more jokes here
        ]

        self._register()

    def load_config(self):
        """Load configuration from furry_images.json"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'furry_images.json')
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading config: {e}")
            # Return default config if file doesn't exist
            return {
                'furry_image_urls': [
                    'https://cdn.pixabay.com/photo/2016/12/13/05/15/puppy-1903313_960_720.jpg',
                    'https://cdn.pixabay.com/photo/2014/11/30/14/11/cat-551554_960_720.jpg',
                    'https://cdn.pixabay.com/photo/2016/07/15/15/55/dachshund-1519374_960_720.jpg'
                ]
            }

    def _register(self):
        """Setup all entertainment command handlers"""

        @self.router.message(Command('new'))
        async def whats_new_command(message: Message):
            """Handle /new command - show latest feature announcement"""
            await self.send_whats_new(message.chat.id)

        @self.router.message(Command('furrypics'))
        async def furry_pics_command(message: Message):
            """Handle /furrypics command"""
            await self.send_furry_pics(message.chat.id)

        @self.router.message(Command('piratik'))
        async def pirate_song_command(message: Message):
            """Handle /piratik command"""
            await self.send_pirate_song(message)

        @self.router.message(Command('anekdot', 'joke'))
        async def dad_joke_command(message: Message):
            """Handle joke commands"""
            await self.send_dad_joke(message)

        @self.router.message(Command('otsos'))
        async def otsos_command(message: Message):
            """Handle /otsos command"""
            await self.handle_otsos(message)

        @self.router.message(Command('peremoga'))
        async def peremoga_command(message: Message):
            """Handle /peremoga command"""
            for i in range(5):
                await self.bot.send_message(message.chat.id, 'ПЕРЕМОГА БУДЕ ЛЮЮЮЮЮЮЮДИИИИИИИИ!!!!!')

        @self.router.message(Command('zrada'))
        async def zrada_command(message: Message):
            """Handle /zrada command"""
            for i in range(5):
                await self.bot.send_message(message.chat.id, 'ЗРАДАААА😭😭😭😭')

        @self.router.message(Command('prosipaisya'))
        async def prosipaisya_command(message: Message):
            """Handle /prosipaisya command"""
            BODYA_ID = 855951767
            for i in range(1, 5):
                await self.bot.send_message(
                    message.chat.id,
                    f"<a href='tg://user?id={BODYA_ID}'>@lofiSnitch</a>",
                    parse_mode='html'
                )

        # Bot conversation handler
        @self.router.message(F.text.startswith("Бот,"))
        async def bot_conversation(message: Message):
            """Handle bot conversation commands"""
            await self.handle_bot_answer(message)

        # Callback handlers
        @self.router.callback_query(F.data.startswith('otsos'))
        async def otsos_callback(call: CallbackQuery):
            """Handle otsos callback"""
            await self.handle_otsos_callback(call)

    async def handle_bot_answer(self, message: Message):
        """Handle bot conversation commands"""
        try:
            # Extract text after bot mention
            prompt = message.text.split("Бот,", 1)[1].strip()

            # Check if it's a command list request
            if prompt in ["расскажи что ты можешь", "что ты можешь?"]:
                command_list = "\n".join(self.commands.keys())
                await self.bot.send_message(message.chat.id, "Вот мои команды:\n" + command_list)
                return

            # Handle specific commands
            if prompt in self.commands:
                if prompt == "расскажи анекдот":
                    await self.send_dad_joke(message)
                elif prompt == "накажи Богдана":
                    await self.bot.send_message(message.chat.id, "Отсылаю 9999 каринок фурри в личку Богдану :)")
                    for i in range(1, 15):
                        await self.send_furry_pics(855951767)  # Bogdan's ID
                        logger.debug(f'Отправлено: {i}')
                elif prompt == "давай ещё разок":
                    await self.bot.send_message(message.chat.id, "Отсылаю ещё 9999 каринок фурри в личку Богдану :)")
                    for i in range(1, 15):
                        await self.send_furry_pics(855951767)
                        logger.debug(f'Отправлено: {i}')
                elif prompt == "расскажи анекдот про маму Юры":
                    await self.bot.send_message(message.chat.id, "Ну ладно")
                    try:
                        with open('/home/spedymax/tg-bot/assets/images/bezobidno.jpg', 'rb') as photo:
                            await asyncio.sleep(1)
                            await self.bot.send_photo(message.chat.id, photo)
                    except FileNotFoundError:
                        await self.bot.send_message(message.chat.id, "Файл изображения не найден")
                elif prompt == "что-то жарко стало":
                    await self.bot.send_message(message.chat.id, "Понял, включаю вентилятор 卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐...")
                    await asyncio.sleep(5)
                    await self.bot.send_message(message.chat.id, "Чёт вентилятор сломался 卐卐卐卐卐卐, из-за грозы наверное ᛋᛋ")
                    await asyncio.sleep(5)
                    await self.bot.send_message(message.chat.id, "Достаём инструменты ☭☭☭☭☭, всё починил, можно и поспать ZzzZZzZzZZZ")
                elif prompt in ["расскажи анекдот про маму Максима", "расскажи анекдот про маму Макса"]:
                    await self.bot.send_message(message.chat.id, "С радостью :)")
                    await asyncio.sleep(3)
                    await self.bot.send_message(
                        message.chat.id,
                        "Мама Максима попросила его друга Юру помочь с ремонтом ванной. Юра согласился и начал "
                        "разбираться с трубами.\nВ какой-то момент он спрашивает: — Мама Максима, а у вас есть "
                        "гаечный ключ?\nНа что мама отвечает:— Нет, Юра, иди нахуй"
                    )
                elif prompt == "как правильно ухаживать за ребёнком?":
                    # This is a very dark joke - you might want to remove or modify this
                    await self.bot.send_message(message.chat.id, "Это очень тёмный юмор, который я не буду повторять...")
                else:
                    await self.bot.send_message(message.chat.id, self.commands[prompt])
            else:
                await self.bot.send_message(message.chat.id, "?")

        except Exception as e:
            logger.error(f"Error in bot conversation: {e}")
            await self.bot.send_message(message.chat.id, "Произошла ошибка при обработке команды.")

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
                # Validate file path to prevent path traversal
                safe_base = os.path.abspath('assets')
                abs_source = os.path.abspath(source)
                if not abs_source.startswith(safe_base):
                    logger.warning(f"Attempted path traversal: {source}")
                    return image_urls
                if not os.path.isfile(abs_source):
                    logger.warning(f"File not found: {source}")
                    return image_urls
                with open(abs_source, 'r', encoding='utf-8') as f:
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
            logger.error(f"Error parsing images: {e}")
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
            except Exception as e:
                logger.debug(f"Failed to fetch from {source}: {e}")
                continue

        # If no images found from APIs, use fallback from config
        if not image_urls:
            image_urls = self.image_urls

        return image_urls

    async def send_furry_pics(self, chat_id):
        """Send furry pictures"""
        # Try to get images from APIs first
        image_urls = await asyncio.to_thread(self.get_furry_images_from_multiple_sources)

        # If no images from APIs, try parsing a simple gallery site
        if not image_urls:
            try:
                # Use a more reliable source
                filtered = await asyncio.to_thread(self.parse_furry_images, 'https://www.furaffinity.net/browse/', 'url')
                if filtered:
                    image_urls = filtered
            except Exception as e:
                logger.debug(f"Failed to parse furaffinity: {e}")

        # Final fallback: use pre-configured URLs from config
        if not image_urls:
            image_urls = self.image_urls

        if not image_urls:
            await self.bot.send_message(chat_id, "Изображения временно недоступны")
            return

        # Select random images
        num_to_send = min(5, len(image_urls))
        random_selection = random.sample(image_urls, num_to_send)

        for url in random_selection:
            try:
                # Validate URL before sending
                if self.is_valid_image_url(url):
                    if url.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        await self.bot.send_photo(chat_id, photo=url)
                    elif url.lower().endswith(('.gif', '.gifv')):
                        await self.bot.send_animation(chat_id, animation=url)
                    await asyncio.sleep(0.5)  # Small delay between sends
            except Exception as e:
                logger.debug(f"Error sending image {url}: {e}")
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
        except (ValueError, TypeError):
            return False

    async def send_pirate_song(self, message: Message):
        """Send random pirate song"""
        songs_folder = '/home/spedymax/tg-bot/assets/audio/pirat-songs'
        try:
            if not os.path.exists(songs_folder):
                await self.bot.send_message(message.chat.id, "Папка с песнями не найдена")
                return

            song_files = [f for f in os.listdir(songs_folder) if f.endswith('.mp3')]

            if not song_files:
                await self.bot.send_message(message.chat.id, "No MP3 songs found in the folder.")
                return

            # Select a random song from the list
            random_song = random.choice(song_files)

            # Send the selected song to the user
            with open(os.path.join(songs_folder, random_song), 'rb') as audio_file:
                await self.bot.send_audio(message.chat.id, audio_file)

        except Exception as e:
            logger.error(f"Error sending pirate song: {e}")
            await self.bot.send_message(message.chat.id, "Ошибка при отправке песни")

    async def send_dad_joke(self, message: Message):
        """Send a random dad joke"""
        if self.dad_jokes_list:
            joke = random.choice(self.dad_jokes_list)
            await self.bot.send_message(message.chat.id, joke)
        else:
            await self.bot.send_message(message.chat.id, "Анекдоты не загружены :(")

    async def handle_otsos(self, message: Message):
        """Handle /otsos command"""
        player_id = message.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, player_id)

        if not player:
            await message.reply("Вы не зарегистрированы как игрок")
            return

        # Create inline keyboard for target selection
        from config.settings import Settings
        targets = [
            ("Юра", f"otsos_{Settings.PLAYER_IDS['YURA']}"),
            ("Макс", f"otsos_{Settings.PLAYER_IDS['MAX']}"),
            ("Богдан", f"otsos_{Settings.PLAYER_IDS['BODYA']}")
        ]

        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=name, callback_data=callback_data)]
                for name, callback_data in targets
            ]
        )

        # Escape username to prevent XSS
        username = safe_username(message.from_user.username, player_id)
        await self.bot.send_message(
            message.chat.id,
            f"<a href='tg://user?id={player_id}'>@{username}</a>, у кого отсасываем?",
            reply_markup=markup,
            parse_mode='html'
        )

    async def handle_otsos_callback(self, call: CallbackQuery):
        """Handle otsos target selection"""
        try:
            parts = safe_split_callback(call.data, "_", 2)
            if not parts:
                await self.bot.send_message(call.message.chat.id, "Неверный формат данных")
                return

            target_id = safe_int(parts[1], 0)
            if target_id == 0:
                await self.bot.send_message(call.message.chat.id, "Неверный ID игрока")
                return

            # Remove the keyboard
            await self.bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )

            # Get players
            player = await asyncio.to_thread(self.player_service.get_player, call.from_user.id)
            target = await asyncio.to_thread(self.player_service.get_player, target_id)

            if not player or not target:
                await self.bot.send_message(call.message.chat.id, "Игрок не найден")
                return

            # Apply otsos effect (reduce target's size, increase player's size)
            stolen_amount = random.randint(1, 5)
            target.pisunchik_size -= stolen_amount
            player.pisunchik_size += stolen_amount

            # Save changes
            await asyncio.to_thread(self.player_service.save_player, player)
            await asyncio.to_thread(self.player_service.save_player, target)

            # Escape player name to prevent XSS
            target_name = escape_html(target.player_name or "игрока")
            await self.bot.send_message(
                call.message.chat.id,
                f"Вы отсосали {stolen_amount} см у {target_name}!"
            )

        except Exception as e:
            logger.error(f"Error in otsos callback: {e}")
            await self.bot.send_message(call.message.chat.id, "Произошла ошибка")

    async def send_whats_new(self, chat_id: int):
        """Send the latest feature announcement Apple-style."""
        try:
            with open(self.whats_new_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            updates = data.get('updates', [])
            if not updates:
                await self.bot.send_message(chat_id, "No updates yet.")
                return
            await self.bot.send_message(chat_id, updates[0]['message'], parse_mode='HTML')
        except FileNotFoundError:
            logger.error("whats_new.json not found")
            await self.bot.send_message(chat_id, "No updates available.")
        except Exception as e:
            logger.error(f"Error sending whats new: {e}")
            await self.bot.send_message(chat_id, "Could not load update info.")
