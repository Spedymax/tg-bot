from telethon import TelegramClient, events
import datetime
import time
from telethon.tl.types import UserStatusRecently, UserStatusEmpty, UserStatusOnline, UserStatusOffline, PeerUser, PeerChat, PeerChannel
api_id = 26306414  # Replace with your API ID
api_hash = 'b0e8fce181aa6035ba65349fb465939e'  # Replace with your API hash
username = '@spedymax'  # Replace with the usernames of the users
client = TelegramClient('session', api_id, api_hash)

@client.on(events.UserUpdate)
async def user_update_event_handler(event):
    if event.online:
        try:
            user_details = await client.get_entity(event.user_id)
            print(f" {user_details.first_name}, came online at : {datetime.now()}")
        except:
            print(event)
async def main():
    # Getting information about yourself
    await client.start()
    while True:
        user = await client.get_entity(username)
        # Check if both users are online
        if isinstance(user.status, UserStatusOnline):
            await client.send_message('me', 'Надо наругать девушку!')
            time.sleep(4*60)
        time.sleep(1 * 60)
with client:
    client.loop.run_until_complete(main())