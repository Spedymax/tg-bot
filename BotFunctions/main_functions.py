import time
from datetime import datetime, timedelta, timezone
max_usage_per_day = 5
def kazik(message, pisunchik, bot):
    for i in range(0, 5):
        player_id = str(message.from_user.id)

        # Check if the user has exceeded the usage limit for today
        if player_id in pisunchik:
            last_usage_time = pisunchik[player_id].get('casino_last_used')
            current_time = datetime.now(timezone.utc)

            if last_usage_time is not None:
                # Calculate the time elapsed since the last usage
                time_elapsed = current_time - last_usage_time

                # If less than 24 hours have passed, and the usage limit is reached, deny access
                if time_elapsed < timedelta(hours=24) and pisunchik[player_id]['casino_usage_count'] >= max_usage_per_day:
                    bot.send_message(message.chat.id,
                                     f"Вы достигли лимита использования команды на сегодня.\n Времени осталось: {timedelta(days=1) - time_elapsed}")
                    return
                elif time_elapsed >= timedelta(hours=24):
                    # If 24 hours have passed since the last usage, reset the usage count
                    pisunchik[player_id]['casino_usage_count'] = 0
            else:
                # If last_usage_time is None, set it to current time
                pisunchik[player_id]['casino_last_used'] = current_time
                pisunchik[player_id]['casino_usage_count'] = 0

        # Update the last usage time and count for the user
        if player_id not in pisunchik:
            bot.send_message(message.chat.id, 'Вы не зарегистрированы как игрок')
            return
        else:
            pisunchik[player_id]['casino_last_used'] = datetime.now(timezone.utc)
            pisunchik[player_id]['casino_usage_count'] += 1

        result = bot.send_dice(message.chat.id, emoji='🎰')
        if result.dice.value in {1, 22, 43, 64}:
            time.sleep(4)
            bot.send_message(message.chat.id, "ДЕКПОТ! Вы получаете 300 BTC!")
            pisunchik[player_id]['coins'] += 300
