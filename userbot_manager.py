import os
import asyncio
import logging
from typing import Dict, Any, Optional
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession
import database

logger = logging.getLogger("UserbotManager")

class UserbotManager:
    """
    Manages active MTProto TelegramClient instances for authenticated users.
    Dispatches automated replies for private chats based on user configurations.
    """
    def __init__(self):
        self.clients: Dict[int, TelegramClient] = {}
        self.configs: Dict[int, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def start_userbot(self, user_id: int, api_id: int, api_hash: str, session_string: str) -> bool:
        async with self._lock:
            # Stop existing client if any
            if user_id in self.clients:
                await self._disconnect_client(user_id)

            logger.info(f"Starting userbot client for user {user_id}...")
            client = TelegramClient(
                StringSession(session_string),
                api_id,
                api_hash,
                device_model="AutoReply Assistant",
                system_version="Linux",
                app_version="1.0"
            )

            try:
                await client.connect()
                if not await client.is_user_authorized():
                    logger.warning(f"Session for user {user_id} is no longer authorized.")
                    await client.disconnect()
                    return False

                # Load reply configuration from database
                config = await database.get_reply_config(user_id)
                self.configs[user_id] = config or {}

                # Register private chat auto-reply listener
                @client.on(events.NewMessage(incoming=True))
                async def handle_incoming_message(event):
                    await self._process_incoming_message(user_id, client, event)

                self.clients[user_id] = client
                logger.info(f"Userbot successfully active for user {user_id}")
                return True

            except Exception as e:
                logger.error(f"Failed to start userbot for user {user_id}: {e}", exc_info=True)
                if client.is_connected():
                    await client.disconnect()
                return False

    async def _process_incoming_message(self, user_id: int, client: TelegramClient, event: events.NewMessage.Event):
        try:
            # 1. Filter: Must be personal/direct private chat
            if not event.is_private:
                return

            # 2. Filter: Never reply to outgoing messages sent by the user themselves
            if event.out:
                return

            # 3. Filter: Ignore Telegram system service notifications
            if event.chat_id in (777000, 42777):
                return

            # 4. Filter: Ignore bots
            sender = await event.get_sender()
            if sender and getattr(sender, "bot", False):
                return

            # 5. Check if user auto-reply is enabled and configured
            config = self.configs.get(user_id)
            if not config or not config.get("is_enabled", 1):
                return

            reply_text = config.get("reply_text")
            media_path = config.get("media_path")

            # Must have at least text or media to reply with
            if not reply_text and not media_path:
                return

            # 6. Check cooldown to prevent flooding consecutive messages
            cooldown_seconds = config.get("cooldown_seconds", 1800)
            eligible = await database.check_and_update_cooldown(user_id, event.chat_id, cooldown_seconds)
            if not eligible:
                logger.debug(f"User {user_id}: Skipping reply to peer {event.chat_id} due to cooldown.")
                return

            logger.info(f"User {user_id}: Auto-replying to peer {event.chat_id}")

            # 7. Step 1: Send sticker or image first if configured
            if media_path and os.path.exists(media_path):
                try:
                    await client.send_file(event.chat_id, media_path)
                    # Small delay between media and text for realistic delivery
                    await asyncio.sleep(0.8)
                except Exception as media_err:
                    logger.error(f"User {user_id}: Error sending media auto-reply: {media_err}")

            # 8. Step 2: Send text message if configured
            if reply_text:
                try:
                    await client.send_message(event.chat_id, reply_text)
                except Exception as text_err:
                    logger.error(f"User {user_id}: Error sending text auto-reply: {text_err}")

        except errors.FloodWaitError as fwe:
            logger.warning(f"User {user_id} hit FloodWait: sleeping {fwe.seconds}s required.")
        except Exception as e:
            logger.error(f"User {user_id}: Unexpected error in message handler: {e}", exc_info=True)

    async def reload_config(self, user_id: int):
        """Reloads the reply configuration from SQLite into memory for a running userbot."""
        config = await database.get_reply_config(user_id)
        self.configs[user_id] = config or {}
        logger.info(f"Reloaded auto-reply config for user {user_id}")

    async def stop_userbot(self, user_id: int):
        async with self._lock:
            await self._disconnect_client(user_id)

    async def _disconnect_client(self, user_id: int):
        client = self.clients.pop(user_id, None)
        self.configs.pop(user_id, None)
        if client and client.is_connected():
            try:
                await client.disconnect()
                logger.info(f"Disconnected userbot for user {user_id}")
            except Exception as e:
                logger.warning(f"Error disconnecting client {user_id}: {e}")

    async def stop_all(self):
        async with self._lock:
            for user_id in list(self.clients.keys()):
                await self._disconnect_client(user_id)

    def is_running(self, user_id: int) -> bool:
        client = self.clients.get(user_id)
        return bool(client and client.is_connected())
