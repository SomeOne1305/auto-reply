import os
import re
import logging
from typing import Dict, Optional
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ContentType

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

import database
from config import MEDIA_DIR, AUTO_REPLY_COOLDOWN
from userbot_manager import UserbotManager

logger = logging.getLogger("BotController")

class LoginStates(StatesGroup):
    waiting_for_api_id = State()
    waiting_for_api_hash = State()
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()

class MessageStates(StatesGroup):
    waiting_for_content = State()

def create_bot_router(bot: Bot, userbot_manager: UserbotManager) -> Router:
    router = Router()
    
    # Store temporary telethon clients for users currently in the login flow
    # user_id -> dict with 'client', 'phone_code_hash', etc.
    temp_login_sessions: Dict[int, Dict] = {}

    async def cleanup_temp_client(user_id: int):
        sess = temp_login_sessions.pop(user_id, None)
        if sess and "client" in sess:
            client: TelegramClient = sess["client"]
            if client.is_connected():
                try:
                    await client.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting temporary client for user {user_id}: {e}")

    # ------------------ /start & /help ------------------
    @router.message(Command("start"))
    async def cmd_start(message: Message, state: FSMContext):
        user_id = message.from_user.id
        await state.clear()
        await cleanup_temp_client(user_id)

        existing = await database.get_user(user_id)
        if existing:
            await message.answer(
                "👋 <b>Welcome back!</b>\n\n"
                f"Your account (<code>{existing['phone']}</code>) is active.\n\n"
                "<b>Commands:</b>\n"
                "• /message - Set your auto-reply template (sticker/image, text, /ends)\n"
                "• /status - View current status and active template\n"
                "• /toggle - Enable/pause auto-replies\n"
                "• /logout - Disconnect and delete credentials",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                "👋 <b>Welcome to AutoReply Bot!</b>\n\n"
                "This bot enables automated replies for your personal Telegram account (1-on-1 direct chats only).\n\n"
                "<b>Quick Start:</b>\n"
                "1️⃣ Send /login to connect your Telegram account.\n"
                "2️⃣ Send /message to record your auto-reply sticker/image and text.\n"
                "3️⃣ Send /ends to activate it!",
                parse_mode="HTML"
            )

    @router.message(Command("cancel"))
    async def cmd_cancel(message: Message, state: FSMContext):
        user_id = message.from_user.id
        current_state = await state.get_state()
        if not current_state:
            await message.answer("No active operation to cancel.")
            return

        await state.clear()
        await cleanup_temp_client(user_id)
        await message.answer("❌ Current operation cancelled. You are back in idle mode.")

    # ------------------ /status & /toggle & /logout ------------------
    @router.message(Command("status"))
    async def cmd_status(message: Message):
        user_id = message.from_user.id
        user = await database.get_user(user_id)
        if not user:
            await message.answer("❌ You are not logged in. Use /login to get started.")
            return

        config = await database.get_reply_config(user_id)
        is_running = userbot_manager.is_running(user_id)
        is_enabled = config.get("is_enabled", 1) if config else 0
        has_media = bool(config and config.get("media_path") and os.path.exists(config["media_path"]))
        media_type = config.get("media_type") if has_media else "None"
        text_preview = config.get("reply_text") if config and config.get("reply_text") else "<i>(None)</i>"

        await message.answer(
            "📊 <b>Auto-Reply Status</b>\n\n"
            f"• <b>Account:</b> <code>{user['phone']}</code>\n"
            f"• <b>Worker:</b> {'🟢 Online' if is_running else '🔴 Offline'}\n"
            f"• <b>Auto-Reply:</b> {'✅ Enabled' if is_enabled else '⏸️ Paused'}\n"
            f"• <b>Attached Media:</b> <code>{media_type}</code>\n"
            f"• <b>Text Template:</b>\n\"{text_preview}\"\n\n"
            "<b>Controls:</b>\n"
            "• /message - Update auto-reply template\n"
            "• /toggle - Enable/Pause auto-replies\n"
            "• /logout - Log out and delete credentials",
            parse_mode="HTML"
        )

    @router.message(Command("toggle"))
    async def cmd_toggle(message: Message):
        user_id = message.from_user.id
        user = await database.get_user(user_id)
        if not user:
            await message.answer("❌ Please login first with /login.")
            return

        config = await database.get_reply_config(user_id)
        new_state = 0 if (config and config.get("is_enabled", 1)) else 1
        await database.toggle_reply(user_id, new_state)
        await userbot_manager.reload_config(user_id)

        status_text = "✅ <b>Enabled</b>" if new_state else "⏸️ <b>Paused</b>"
        await message.answer(f"Auto-reply has been {status_text}.", parse_mode="HTML")

    @router.message(Command("logout"))
    async def cmd_logout(message: Message, state: FSMContext):
        user_id = message.from_user.id
        user = await database.get_user(user_id)
        if not user:
            await message.answer("You are not logged in.")
            return

        await userbot_manager.stop_userbot(user_id)
        await database.delete_user(user_id)
        await state.clear()
        await cleanup_temp_client(user_id)
        await message.answer("🚪 You have been successfully logged out and your credentials removed.")

    # ------------------ /login FLOW ------------------
    @router.message(Command("login"))
    async def cmd_login(message: Message, state: FSMContext):
        user_id = message.from_user.id
        user = await database.get_user(user_id)
        if user:
            await message.answer(
                f"⚠️ You are already logged in with phone <code>{user['phone']}</code>.\n"
                "Use /status to check settings or /logout to switch accounts.",
                parse_mode="HTML"
            )
            return

        await state.clear()
        await cleanup_temp_client(user_id)
        await state.set_state(LoginStates.waiting_for_api_id)
        await message.answer(
            "🔑 <b>Step 1/4: Telegram API ID</b>\n\n"
            "Please enter your numeric <b><code>api_id</code></b>.\n"
            "<i>(Get it from https://my.telegram.org under 'API development tools')</i>\n\n"
            "Type /cancel at any time to abort.",
            parse_mode="HTML"
        )

    @router.message(LoginStates.waiting_for_api_id)
    async def process_api_id(message: Message, state: FSMContext):
        text = message.text.strip() if message.text else ""
        if not text.isdigit():
            await message.answer("❌ Invalid API ID. It must be numeric (e.g. <code>12345678</code>). Please try again:", parse_mode="HTML")
            return

        await state.update_data(api_id=int(text))
        await state.set_state(LoginStates.waiting_for_api_hash)
        await message.answer(
            "🔑 <b>Step 2/4: Telegram API Hash</b>\n\n"
            "Please enter your <b><code>api_hash</code></b> (32-character hexadecimal string):",
            parse_mode="HTML"
        )

    @router.message(LoginStates.waiting_for_api_hash)
    async def process_api_hash(message: Message, state: FSMContext):
        api_hash = message.text.strip() if message.text else ""
        if len(api_hash) < 16:
            await message.answer("❌ Invalid API Hash. Please enter a valid <code>api_hash</code>:", parse_mode="HTML")
            return

        await state.update_data(api_hash=api_hash)
        await state.set_state(LoginStates.waiting_for_phone)
        await message.answer(
            "📱 <b>Step 3/4: Phone Number</b>\n\n"
            "Please enter your phone number with country code (e.g. <code>+1234567890</code>):",
            parse_mode="HTML"
        )

    @router.message(LoginStates.waiting_for_phone)
    async def process_phone(message: Message, state: FSMContext):
        user_id = message.from_user.id
        phone = message.text.strip().replace(" ", "") if message.text else ""
        if not re.match(r"^\+?[0-9]{7,16}$", phone):
            await message.answer("❌ Invalid format. Please enter your phone in international format (e.g. <code>+1234567890</code>):", parse_mode="HTML")
            return

        data = await state.get_data()
        api_id = data["api_id"]
        api_hash = data["api_hash"]

        wait_msg = await message.answer("⏳ Connecting to Telegram and requesting verification code...")

        temp_client = TelegramClient(
            StringSession(),
            api_id,
            api_hash,
            device_model="AutoReply Assistant",
            system_version="Linux",
            app_version="1.0"
        )
        await temp_client.connect()

        try:
            sent_code = await temp_client.send_code_request(phone)
            temp_login_sessions[user_id] = {
                "client": temp_client,
                "phone_code_hash": sent_code.phone_code_hash,
                "phone": phone,
                "api_id": api_id,
                "api_hash": api_hash
            }
            await state.set_state(LoginStates.waiting_for_code)
            await wait_msg.edit_text(
                "📩 <b>Step 4/4: Verification Code</b>\n\n"
                f"Telegram sent an OTP code to <code>{phone}</code> (check your Telegram app).\n\n"
                "Please enter the code here (e.g. <code>12345</code> or <code>1 2 3 4 5</code>):",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error requesting code for {phone}: {e}")
            await temp_client.disconnect()
            await state.clear()
            await wait_msg.edit_text(f"❌ Failed to request code: {e}\n\nUse /login to try again.")

    @router.message(LoginStates.waiting_for_code)
    async def process_code(message: Message, state: FSMContext):
        user_id = message.from_user.id
        sess = temp_login_sessions.get(user_id)
        if not sess or "client" not in sess:
            await state.clear()
            await message.answer("Session expired. Please restart with /login.")
            return

        code_raw = message.text.strip().replace(" ", "").replace("-", "") if message.text else ""
        temp_client: TelegramClient = sess["client"]
        phone = sess["phone"]
        phone_code_hash = sess["phone_code_hash"]
        api_id = sess["api_id"]
        api_hash = sess["api_hash"]

        try:
            await temp_client.sign_in(phone=phone, code=code_raw, phone_code_hash=phone_code_hash)
            session_str = temp_client.session.save()
            
            # Save user credentials and session
            await database.save_user(user_id, api_id, api_hash, phone, session_str)
            
            # Start background userbot client
            await userbot_manager.start_userbot(user_id, api_id, api_hash, session_str)
            
            await state.clear()
            await cleanup_temp_client(user_id)

            await message.answer(
                "🎉 <b>Login Successful!</b>\n\n"
                "Your Telegram account is now connected.\n\n"
                "Now set your auto-reply by sending /message !",
                parse_mode="HTML"
            )
        except errors.SessionPasswordNeededError:
            await state.set_state(LoginStates.waiting_for_2fa)
            await message.answer(
                "🔐 <b>Two-Step Verification (2FA) is enabled!</b>\n\n"
                "Please enter your Telegram Cloud Password:",
                parse_mode="HTML"
            )
        except errors.PhoneCodeInvalidError:
            await message.answer("❌ Invalid code. Please enter the code again:")
        except errors.PhoneCodeExpiredError:
            await message.answer("❌ Code expired. Please use /login to request a new code.")
            await state.clear()
            await cleanup_temp_client(user_id)
        except Exception as e:
            logger.error(f"Error signing in: {e}")
            await message.answer(f"❌ Login failed: {e}\n\nUse /login to restart.")
            await state.clear()
            await cleanup_temp_client(user_id)

    @router.message(LoginStates.waiting_for_2fa)
    async def process_2fa(message: Message, state: FSMContext):
        user_id = message.from_user.id
        sess = temp_login_sessions.get(user_id)
        if not sess or "client" not in sess:
            await state.clear()
            await message.answer("Session expired. Please restart with /login.")
            return

        password = message.text.strip() if message.text else ""
        temp_client: TelegramClient = sess["client"]
        phone = sess["phone"]
        api_id = sess["api_id"]
        api_hash = sess["api_hash"]

        try:
            await temp_client.sign_in(password=password)
            session_str = temp_client.session.save()

            await database.save_user(user_id, api_id, api_hash, phone, session_str)
            await userbot_manager.start_userbot(user_id, api_id, api_hash, session_str)

            await state.clear()
            await cleanup_temp_client(user_id)

            await message.answer(
                "🎉 <b>2FA Verified & Login Successful!</b>\n\n"
                "Your Telegram account is linked.\n\n"
                "Now set your auto-reply by sending /message !",
                parse_mode="HTML"
            )
        except errors.PasswordHashInvalidError:
            await message.answer("❌ Incorrect password. Please try entering your 2FA password again:")
        except Exception as e:
            logger.error(f"2FA error: {e}")
            await message.answer(f"❌ 2FA login failed: {e}\n\nUse /login to restart.")
            await state.clear()
            await cleanup_temp_client(user_id)

    # ------------------ /message & TEMPLATE SETUP FLOW ------------------
    @router.message(Command("message"))
    async def cmd_message(message: Message, state: FSMContext):
        user_id = message.from_user.id
        user = await database.get_user(user_id)
        if not user:
            await message.answer("❌ Please connect your Telegram account first using /login.")
            return

        await state.set_state(MessageStates.waiting_for_content)
        await state.set_data({
            "draft_media_path": None,
            "draft_media_type": None,
            "draft_text": None
        })

        await message.answer(
            "📝 <b>Auto-Reply Setup Started</b>\n\n"
            "1️⃣ <b>Sticker / Image</b> (optional): Send your sticker or image first.\n"
            "2️⃣ <b>Text Message</b>: Send your auto-reply text.\n"
            "3️⃣ Send /ends to save and activate auto-reply for personal chats!\n\n"
            "<i>(Send /cancel to discard)</i>",
            parse_mode="HTML"
        )

    @router.message(MessageStates.waiting_for_content, Command("ends"))
    async def cmd_ends(message: Message, state: FSMContext):
        user_id = message.from_user.id
        data = await state.get_data()

        draft_media_path = data.get("draft_media_path")
        draft_media_type = data.get("draft_media_type")
        draft_text = data.get("draft_text")

        if not draft_media_path and not draft_text:
            await message.answer(
                "⚠️ You haven't sent any sticker, image, or text yet!\n"
                "Please send your sticker/image or text message first, then send /ends.\n"
                "Or send /cancel to abort."
            )
            return

        # Commit to database
        await database.save_reply_config(
            user_id=user_id,
            media_type=draft_media_type,
            media_path=draft_media_path,
            reply_text=draft_text,
            is_enabled=1,
            cooldown_seconds=AUTO_REPLY_COOLDOWN
        )

        # Reload configuration in running userbot
        await userbot_manager.reload_config(user_id)
        await state.clear()

        summary = []
        if draft_media_type:
            summary.append(f"• Media: <code>{draft_media_type.capitalize()}</code>")
        if draft_text:
            summary.append(f"• Text: \"{draft_text}\"")

        await message.answer(
            "🎉 <b>Auto-Reply Template Saved & Activated!</b>\n\n"
            "<b>Configuration:</b>\n" + "\n".join(summary) + "\n\n"
            "Auto-reply is now active for all incoming <b>personal direct chats</b>.\n"
            "Use /status to review or /toggle to pause anytime.",
            parse_mode="HTML"
        )

    @router.message(MessageStates.waiting_for_content, F.sticker)
    async def handle_draft_sticker(message: Message, state: FSMContext):
        user_id = message.from_user.id
        dest_path = MEDIA_DIR / f"reply_{user_id}_sticker.webp"
        
        file_info = await bot.get_file(message.sticker.file_id)
        await bot.download_file(file_info.file_path, destination=dest_path)

        await state.update_data(draft_media_path=str(dest_path), draft_media_type="sticker")
        await message.answer(
            "🖼️ <b>Sticker received!</b>\n\n"
            "• Next, send your <b>Text message</b> (if any).\n"
            "• When ready, send /ends to finalize and activate.",
            parse_mode="HTML"
        )

    @router.message(MessageStates.waiting_for_content, F.photo)
    async def handle_draft_photo(message: Message, state: FSMContext):
        user_id = message.from_user.id
        dest_path = MEDIA_DIR / f"reply_{user_id}_photo.jpg"
        
        # Get highest resolution photo
        highest_photo = message.photo[-1]
        file_info = await bot.get_file(highest_photo.file_id)
        await bot.download_file(file_info.file_path, destination=dest_path)

        await state.update_data(draft_media_path=str(dest_path), draft_media_type="photo")
        await message.answer(
            "📷 <b>Image received!</b>\n\n"
            "• Next, send your <b>Text message</b> (if any).\n"
            "• When ready, send /ends to finalize and activate.",
            parse_mode="HTML"
        )

    @router.message(MessageStates.waiting_for_content, F.text)
    async def handle_draft_text(message: Message, state: FSMContext):
        text = message.text.strip()
        await state.update_data(draft_text=text)
        await message.answer(
            f"📝 <b>Text message recorded!</b>\n\n"
            f"Preview:\n\"{text}\"\n\n"
            "Send /ends to finalize and activate, or send another text to update it.",
            parse_mode="HTML"
        )

    return router
