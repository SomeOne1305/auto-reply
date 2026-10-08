import sys
import asyncio
import signal
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import (
    BOT_TOKEN,
    WEBHOOK_URL,
    WEBHOOK_PATH,
    WEBHOOK_SECRET,
    HOST,
    PORT
)
import database
from userbot_manager import UserbotManager
from bot import create_bot_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("AutoReplyDaemon")

async def on_startup(bot: Bot, userbot_manager: UserbotManager):
    logger.info("Initializing database...")
    await database.init_db()

    # Restore active user sessions
    active_users = await database.get_all_active_users()
    logger.info(f"Found {len(active_users)} active user session(s) in database.")
    for user in active_users:
        u_id = user["user_id"]
        logger.info(f"Restoring background userbot for user {u_id} ({user['phone']})...")
        asyncio.create_task(
            userbot_manager.start_userbot(
                user_id=u_id,
                api_id=user["api_id"],
                api_hash=user["api_hash"],
                session_string=user["session_string"]
            )
        )

    # If running in Webhook mode, register webhook with Telegram
    if WEBHOOK_URL:
        webhook_endpoint = f"{WEBHOOK_URL.rstrip('/')}{WEBHOOK_PATH}"
        logger.info(f"Configuring Telegram Webhook: {webhook_endpoint}")
        await bot.set_webhook(
            url=webhook_endpoint,
            secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None,
            drop_pending_updates=True
        )
        logger.info("✅ Telegram Webhook registered successfully.")

async def on_shutdown(bot: Bot, userbot_manager: UserbotManager):
    logger.info("Shutting down...")
    if WEBHOOK_URL:
        logger.info("Removing Telegram Webhook...")
        await bot.delete_webhook()
    
    logger.info("Stopping all active userbot clients...")
    await userbot_manager.stop_all()
    await bot.session.close()
    logger.info("Shutdown cleanly completed.")

async def main():
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        logger.error("BOT_TOKEN is missing! Please configure BOT_TOKEN in .env.")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    userbot_manager = UserbotManager()

    # Setup routes
    router = create_bot_router(bot, userbot_manager)
    dp.include_router(router)

    try:
        bot_info = await bot.get_me()
        logger.info(f"Bot connected: @{bot_info.username} (ID: {bot_info.id})")
    except Exception as e:
        logger.error(f"Failed to authenticate BOT_TOKEN: {e}")
        sys.exit(1)

    # ----------------- WEBHOOK MODE -----------------
    if WEBHOOK_URL:
        logger.info(f"Starting in WEBHOOK mode on {HOST}:{PORT}{WEBHOOK_PATH}")
        await on_startup(bot, userbot_manager)

        app = web.Application()
        
        # Simple health check endpoint for monitoring/hosting platforms
        async def health_check(request):
            return web.Response(text="OK", status=200)
        app.router.add_get("/", health_check)
        app.router.add_get("/health", health_check)

        webhook_requests_handler = SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
            secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None,
        )
        webhook_requests_handler.register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, HOST, PORT)
        await site.start()
        logger.info(f"🚀 Webhook HTTP server listening on {HOST}:{PORT}")

        # Keep alive until signal
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

        await stop_event.wait()
        await on_shutdown(bot, userbot_manager)
        await runner.cleanup()

    # ----------------- POLLING MODE -----------------
    else:
        logger.info("Starting in POLLING mode (set WEBHOOK_URL in .env to enable webhooks)...")
        await on_startup(bot, userbot_manager)

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

        polling_task = asyncio.create_task(dp.start_polling(bot))
        stop_task = asyncio.create_task(stop_event.wait())

        try:
            done, pending = await asyncio.wait(
                [polling_task, stop_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
        finally:
            await dp.stop_polling()
            await on_shutdown(bot, userbot_manager)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
