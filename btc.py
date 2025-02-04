import telebot
import requests
import time
import json
from threading import Thread, Event, Lock
from collections import deque
import random

# Initialize bot
bot = telebot.TeleBot('7460498911:AAGbjXFhXOOnXIr46dooSq_apvH-OM4HMP4')

# API Configuration
API_KEYS = [
    '86baf32f-7a2e-4bfc-88af-1941b444c8c9',
    'bd2c05dc-481e-4770-a3a3-396aa6623c15',
    '04182d40-7c7c-45ef-8ccb-b017585d70a2',
    'b169dbb1-cc25-40b7-ab28-d0cbde161bec',
    '788ea4bd-f0b2-4996-aebd-733e42741c96',
    '3eefc680-b2ed-407f-b233-490911c798e6',
    'bf0aa70b-92f6-417d-abd1-e0451fb34715'
]
CMC_API_URL = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest'


class APIKeyManager:
    def __init__(self, api_keys):
        self.api_keys = api_keys
        self.current_key_index = 0
        self.request_counts = {key: deque(maxlen=2592000) for key in api_keys}  # 30 days in seconds
        self.lock = Lock()

    def get_next_api_key(self):
        with self.lock:
            current_time = time.time()

            # Clean up old requests
            for key in self.api_keys:
                while self.request_counts[key] and current_time - self.request_counts[key][0] > 2592000:
                    self.request_counts[key].popleft()

            # Find key with least usage
            min_requests = float('inf')
            selected_key = None

            for key in self.api_keys:
                requests = len(self.request_counts[key])
                if requests < min_requests:
                    min_requests = requests
                    selected_key = key

            if selected_key and min_requests < 10000:
                self.request_counts[selected_key].append(current_time)
                return selected_key

            return None


class PriceCache:
    def __init__(self, cache_duration=60):  # Cache duration in seconds
        self.price = None
        self.last_update = None
        self.cache_duration = cache_duration
        self.lock = Lock()

    def update(self, price):
        with self.lock:
            self.price = price
            self.last_update = time.time()

    def get(self):
        with self.lock:
            if self.last_update is None:
                return None
            if time.time() - self.last_update > self.cache_duration:
                return None
            return self.price

# Persistent storage for user data
USER_STATES_FILE = "user_states.json"
stop_event = Event()


def load_user_states():
    try:
        with open(USER_STATES_FILE, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}


def save_user_states(states):
    with open(USER_STATES_FILE, "w") as file:
        json.dump(states, file)


@bot.message_handler(commands=['list_alerts'])
def list_alerts(message):
    """List all active price alerts for the user."""
    chat_id = message.chat.id
    user_state = user_states.get(chat_id, {})

    if 'target_price' in user_state:
        target_price = user_state['target_price']
        bot.reply_to(message, f"Your active price alert:\n${target_price:,.2f} USD")
    else:
        bot.reply_to(message, "You have no active price alerts.")


@bot.message_handler(commands=['delete_alert'])
def delete_alert(message):
    """Delete the user's price alert."""
    chat_id = message.chat.id
    if chat_id in user_states and 'target_price' in user_states[chat_id]:
        target_price = user_states[chat_id]['target_price']
        del user_states[chat_id]['target_price']
        save_user_states(user_states)
        bot.reply_to(message, f"Price alert for ${target_price:,.2f} USD has been deleted.")
    else:
        bot.reply_to(message, "You have no active price alerts to delete.")


# Load user states from file at startup
user_states = load_user_states()
# Global instances
api_manager = APIKeyManager(API_KEYS)
price_cache = PriceCache()

def get_btc_price():
    """Fetch the current Bitcoin price with caching and API key rotation."""
    cached_price = price_cache.get()
    if cached_price is not None:
        return cached_price

    api_key = api_manager.get_next_api_key()
    if api_key is None:
        return None  # All API keys exceeded limits

    try:
        headers = {
            'X-CMC_PRO_API_KEY': api_key,
            'Accept': 'application/json'
        }
        params = {
            'symbol': 'BTC',
            'convert': 'USD'
        }
        response = requests.get(CMC_API_URL, headers=headers, params=params, timeout=10)
        data = response.json()
        price = data['data']['BTC']['quote']['USD']['price']
        price_cache.update(price)
        return price
    except Exception as e:
        print(f"Error fetching BTC price: {e}")
        return None


@bot.message_handler(commands=['price'])
def show_live_price(message):
    """Show current BTC price and update it every minute."""
    try:
        current_price = get_btc_price()
        if current_price is None:
            bot.reply_to(message, "Error fetching BTC price. Please try again later.")
            return

        sent_message = bot.reply_to(
            message,
            f"Current BTC Price: ${current_price:,.2f} USD\n\nUpdating every minute..."
        )

        Thread(
            target=update_price_message,
            args=(message.chat.id, sent_message.message_id),
            daemon=True
        ).start()

    except Exception as e:
        print(f"Error in show_live_price: {e}")
        bot.reply_to(message, "An error occurred. Please try again later.")


def update_price_message(chat_id, message_id):
    """Update price message with reduced frequency."""
    update_interval = random.randint(55, 65)  # Randomize interval to prevent synchronized requests

    while not stop_event.is_set():
        current_price = get_btc_price()
        if current_price is None:
            time.sleep(update_interval)
            continue

        try:
            bot.edit_message_text(
                f"Current BTC Price: ${current_price:,.2f} USD\n\nLast update: {time.strftime('%H:%M:%S')}",
                chat_id=chat_id,
                message_id=message_id
            )
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" not in str(e).lower():
                raise e

        time.sleep(update_interval)


@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message,
                 "Welcome! Available commands:\n"
                 "/set_check_btc_price - Set a price alert\n"
                 "/price - Show live BTC price updates\n"
                 "/list_alerts - Show your active price alerts\n"
                 "/delete_alert - Delete a price alert"
                 )


@bot.message_handler(commands=['set_check_btc_price'])
def set_price_command(message):
    user_states[message.chat.id] = {'waiting_for_price': True}
    save_user_states(user_states)
    bot.reply_to(message, "Please enter the target price in USD (e.g., 85000):")


@bot.message_handler(
    func=lambda message: message.chat.id in user_states and user_states[message.chat.id].get('waiting_for_price'))
def handle_target_price(message):
    try:
        target_price = float(message.text)
        user_states[message.chat.id] = {'waiting_for_price': False, 'target_price': target_price}
        save_user_states(user_states)

        bot.reply_to(message, f"Alert set for ${target_price:,.2f} USD")

        Thread(target=monitor_target_price, args=(message.chat.id, target_price), daemon=True).start()
    except ValueError:
        bot.reply_to(message, "Please enter a valid number.")


def monitor_target_price(chat_id, target_price):
    """Monitor target price with optimized checking."""
    check_interval = random.randint(55, 65)

    while not stop_event.is_set():
        current_price = get_btc_price()
        if current_price is None:
            time.sleep(check_interval)
            continue

        if abs(current_price - target_price) <= 100:
            bot.send_message(chat_id, f"Target price reached! Current price: ${current_price:,.2f} USD")
            break

        time.sleep(check_interval)


def monitor_price_changes(chat_id):
    """Monitor price changes and notify when crossing $500 thresholds."""
    check_interval = random.randint(55, 65)
    last_price = None  # Track the price from the previous check

    while not stop_event.is_set():
        current_price = get_btc_price()
        if current_price is None:
            time.sleep(check_interval)
            continue
        direction = None
        if last_price is not None:
            thresholds = []
            if current_price > last_price:
                # Price increased: check upwards thresholds
                step = 500
                first_threshold = ((last_price // step) + 1) * step
                current_threshold = first_threshold
                while current_threshold <= current_price:
                    thresholds.append(current_threshold)
                    current_threshold += step
                direction = 'up'
            elif current_price < last_price:
                # Price decreased: check downwards thresholds
                step = 500
                first_threshold = (last_price // step) * step
                # If last_price was exactly on a threshold, start from the next lower one
                if last_price == first_threshold:
                    first_threshold -= step
                current_threshold = first_threshold
                while current_threshold >= current_price:
                    thresholds.append(current_threshold)
                    current_threshold -= step
                direction = 'down'
            else:
                # No price change
                thresholds = []

            # Send notifications for each threshold crossed
            for threshold in thresholds:
                if direction == 'up':
                    message = f"🚀 Price reached ${threshold:,.0f} USD (Current: ${current_price:,.2f})"
                else:
                    message = f"🔻 Price fell below ${threshold:,.0f} USD (Current: ${current_price:,.2f})"
                try:
                    bot.send_message(chat_id, message)
                except Exception as e:
                    print(f"Error sending message: {e}")

        # Update last_price for the next iteration
        last_price = current_price
        time.sleep(check_interval)

if __name__ == "__main__":
    try:
        # Start monitoring price changes for the specified chat ID
        Thread(target=monitor_price_changes, args=(741542965,), daemon=True).start()
        print("Bot is running. Press Ctrl+C to stop.")
        bot.polling()
    except KeyboardInterrupt:
        print("\nShutting down bot gracefully...")
        stop_event.set()
        save_user_states(user_states)
        print("Bot stopped.")