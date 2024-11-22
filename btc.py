import telebot
import requests
import time
import json
from threading import Thread, Event

# Initialize bot
bot = telebot.TeleBot('7460498911:AAGbjXFhXOOnXIr46dooSq_apvH-OM4HMP4')

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


# Load user states from file at startup
user_states = load_user_states()


def get_btc_price():
    """Fetch the current Bitcoin price in USD."""
    try:
        response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd',
                                timeout=10)
        return response.json().get('bitcoin', {}).get('usd')
    except Exception as e:
        print(f"Error fetching BTC price: {e}")
        return None


@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Welcome! Use /set_check_btc_price to set a price alert.")


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

        # Start monitoring in a separate thread
        Thread(target=monitor_target_price, args=(message.chat.id, target_price), daemon=True).start()
    except ValueError:
        bot.reply_to(message, "Please enter a valid number.")


def monitor_target_price(chat_id, target_price):
    """Monitor BTC price and alert when it nears the target."""
    try:
        while not stop_event.is_set():
            current_price = get_btc_price()
            if current_price is None:
                time.sleep(60)
                continue

            if abs(current_price - target_price) <= 100:
                bot.send_message(chat_id, f"Target price reached! Current price: ${current_price:,.2f} USD")
                break

            time.sleep(60)
    except Exception as e:
        print(f"Error in monitor_target_price: {e}")


def monitor_price_changes(chat_id, threshold=1000):
    """Monitor BTC price changes and notify of significant shifts."""
    try:
        last_price = get_btc_price()
        last_notification_price = last_price

        while not stop_event.is_set():
            current_price = get_btc_price()
            if current_price is None:
                time.sleep(60)
                continue

            price_change = abs(current_price - last_notification_price)

            if price_change >= threshold:
                direction = "up to" if current_price > last_notification_price else "down to"
                bot.send_message(chat_id, f"Price went {direction} ${current_price:,.2f} USD")
                last_notification_price = current_price

            last_price = current_price
            time.sleep(60)
    except Exception as e:
        print(f"Error in monitor_price_changes: {e}")


if __name__ == "__main__":
    try:
        # Start monitoring significant price changes in a background thread
        Thread(target=monitor_price_changes, args=(741542965,), daemon=True).start()

        print("Bot is running. Press Ctrl+C to stop.")
        bot.polling()  # Start the bot
    except KeyboardInterrupt:
        print("\nShutting down bot gracefully...")
        stop_event.set()
        save_user_states(user_states)
        print("Bot stopped.")
