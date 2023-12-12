from telethon import TelegramClient, events
import re
import time
api_id = 26306414  # Replace with your API ID
api_hash = 'b0e8fce181aa6035ba65349fb465939e'  # Replace with your API hash
usernames = ['@vichyyyyy', '@lofiSnitch']  # Replace with the usernames of the users

client = TelegramClient('session', api_id, api_hash)


async def main():
    # Getting information about yourself
    me = await client.get_me()

    await client.start()
    while True:
        time.sleep(1 * 60)

        # Dictionary to keep track of user status
        user_status = {username: False for username in usernames}

        for username in usernames:
            user = await client.get_entity(username)
            match = re.search(r'UserStatus(Offline|Online)', user.status.stringify())
            user_status[username] = match.group()

        # Check if both users are online
        if all(status == 'UserStatusOnline' for status in user_status.values()):
            await client.send_message('me', 'Надо наругать девушку!')
            time.sleep(4*60)


with client:
    client.loop.run_until_complete(main())
