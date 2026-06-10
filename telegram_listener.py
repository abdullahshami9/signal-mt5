import asyncio
import os
import json
import sys
from telethon import TelegramClient, events
from utils.db import init_db, get_settings, add_signal, add_log, save_settings
from parser import parse_signal

# Ensure database is initialized
init_db()

async def main():
    add_log("INFO", "listener", "Starting Telegram listener...")
    
    settings = get_settings()
    api_id_str = settings.get("api_id", "")
    api_hash = settings.get("api_hash", "")
    
    if not api_id_str or not api_hash:
        add_log("WARNING", "listener", "Telegram API credentials not set. Listener idle.")
        save_settings({"telegram_status": "disconnected"})
        # Keep process alive so it doesn't crash loop
        while True:
            await asyncio.sleep(60)
            
    try:
        api_id = int(api_id_str)
    except ValueError:
        add_log("ERROR", "listener", "Invalid API ID in settings. Must be an integer.")
        save_settings({"telegram_status": "disconnected"})
        while True:
            await asyncio.sleep(60)
            
    # Resolve the session file path (in the project folder)
    session_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "telegram"))
    
    client = TelegramClient(session_path, api_id, api_hash)
    
    try:
        await client.connect()
    except Exception as e:
        add_log("ERROR", "listener", f"Failed to connect to Telegram: {e}")
        save_settings({"telegram_status": "disconnected"})
        sys.exit(1)
        
    authorized = await client.is_user_authorized()
    if not authorized:
        add_log("WARNING", "listener", "Telegram session unauthorized. Waiting for dashboard login.")
        save_settings({"telegram_status": "auth_required"})
        while True:
            await asyncio.sleep(60)
            
    add_log("INFO", "listener", "Telegram listener connected and authorized.")
    save_settings({"telegram_status": "connected"})
    
    # Load monitored channels
    try:
        monitored_channels = json.loads(settings.get("monitored_channels", "[]"))
    except Exception:
        monitored_channels = []
        
    add_log("INFO", "listener", f"Monitoring channels: {monitored_channels}")
    
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
                
            add_log("DEBUG", "listener", f"Received message from chat {chat_id}: {text[:100]}")
            
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
                    tp3=parsed.get("tp3")
                )
        except Exception as e:
            add_log("ERROR", "listener", f"Error in message handler: {e}")
            
    # Run client until disconnected
    try:
        await client.run_until_disconnected()
    except Exception as e:
        add_log("ERROR", "listener", f"Telegram listener disconnected: {e}")
        save_settings({"telegram_status": "disconnected"})
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Telegram listener stopped by user.")
