import asyncio
import os
import json
import sys
from telethon import TelegramClient, events
from utils.db import init_db, get_settings, add_signal, add_log, save_settings
from parser import parse_signal

import argparse

# Ensure database is initialized
init_db()

def parse_args():
    parser = argparse.ArgumentParser(description="Telegram Listener Worker")
    parser.add_argument("--user-id", type=int, required=True, help="Database User (Vendor) ID")
    return parser.parse_args()

async def main():
    args = parse_args()
    user_id = args.user_id
    
    add_log("INFO", "listener", f"Starting Telegram listener for user {user_id}...", user_id=user_id)
    
    settings = get_settings(user_id=user_id)
    api_id_str = settings.get("api_id", "")
    api_hash = settings.get("api_hash", "")
    
    if not api_id_str or not api_hash:
        add_log("WARNING", "listener", f"Telegram API credentials not set for user {user_id}. Listener idle.", user_id=user_id)
        save_settings({"telegram_status": "disconnected"}, user_id=user_id)
        # Keep process alive so it doesn't crash loop
        while True:
            await asyncio.sleep(60)
            
    try:
        api_id = int(api_id_str)
    except ValueError:
        add_log("ERROR", "listener", f"Invalid API ID in settings for user {user_id}. Must be an integer.", user_id=user_id)
        save_settings({"telegram_status": "disconnected"}, user_id=user_id)
        while True:
            await asyncio.sleep(60)
            
    # Resolve the session file path (in the project folder)
    session_path = os.path.abspath(os.path.join(os.path.dirname(__file__), f"telegram_user_{user_id}"))
    
    client = TelegramClient(session_path, api_id, api_hash)
    
    try:
        await client.connect()
    except Exception as e:
        add_log("ERROR", "listener", f"Failed to connect to Telegram for user {user_id}: {e}", user_id=user_id)
        save_settings({"telegram_status": "disconnected"}, user_id=user_id)
        sys.exit(1)
        
    authorized = await client.is_user_authorized()
    if not authorized:
        add_log("WARNING", "listener", f"Telegram session unauthorized for user {user_id}. Waiting for dashboard login.", user_id=user_id)
        save_settings({"telegram_status": "auth_required"}, user_id=user_id)
        while True:
            await asyncio.sleep(60)
            
    add_log("INFO", "listener", f"Telegram listener for user {user_id} connected and authorized.", user_id=user_id)
    save_settings({"telegram_status": "connected"}, user_id=user_id)
    
    # Load monitored channels
    try:
        monitored_channels = json.loads(settings.get("monitored_channels", "[]"))
    except Exception:
        monitored_channels = []
        
    add_log("INFO", "listener", f"Monitoring channels for user {user_id}: {monitored_channels}", user_id=user_id)
    
    # Handle incoming messages
    @client.on(events.NewMessage)
    async def handler(event):
        try:
            chat = await event.get_chat()
            chat_id = event.chat_id
            
            # Check if chat is in monitored list (by ID or username)
            is_monitored = False
            chat_username = getattr(chat, 'username', '')
            
            # If monitored_channels is empty, we monitor ALL channels/chats the user is in (good for testing)
            if not monitored_channels:
                is_monitored = True
            else:
                for item in monitored_channels:
                    item_str = str(item).strip().upper()
                    if item_str == str(chat_id) or (chat_username and item_str == chat_username.upper()):
                        is_monitored = True
                        break
                        
            if not is_monitored:
                return
                
            text = event.raw_text
            if not text:
                return
                
            add_log("DEBUG", "listener", f"Received message from chat {chat_id}: {text[:100]}", user_id=user_id)
            
            parsed = parse_signal(text)
            if parsed:
                add_signal(
                    telegram_msg_id=event.id,
                    channel_id=chat_id,
                    raw_text=text,
                    action=parsed["action"],
                    symbol=parsed["symbol"],
                    sl=parsed.get("sl"),
                    tp1=parsed.get("tp1"),
                    tp2=parsed.get("tp2"),
                    tp3=parsed.get("tp3"),
                    entry_min=parsed.get("entry_min"),
                    entry_max=parsed.get("entry_max"),
                    user_id=user_id
                )
        except Exception as e:
            add_log("ERROR", "listener", f"Error in message handler: {e}", user_id=user_id)
            
    # Run client until disconnected
    try:
        await client.run_until_disconnected()
    except Exception as e:
        add_log("ERROR", "listener", f"Telegram listener for user {user_id} disconnected: {e}", user_id=user_id)
        save_settings({"telegram_status": "disconnected"}, user_id=user_id)
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Telegram listener stopped by user.")
