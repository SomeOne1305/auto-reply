import asyncio
import os
from pathlib import Path

# Override DB path for testing
os.environ["DATABASE_PATH"] = "data/test_autoreply.db"
os.environ["BOT_TOKEN"] = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"

import database
from userbot_manager import UserbotManager
from bot import create_bot_router, LoginStates, MessageStates

async def test_database():
    print("Testing Database...")
    await database.init_db()

    test_user_id = 999999
    await database.save_user(
        user_id=test_user_id,
        api_id=123456,
        api_hash="abcdef1234567890abcdef1234567890",
        phone="+1234567890",
        session_string="1BVtsOMQBu..."
    )
    user = await database.get_user(test_user_id)
    assert user is not None
    assert user["phone"] == "+1234567890"

    await database.save_reply_config(
        user_id=test_user_id,
        media_type="photo",
        media_path="/path/to/image.jpg",
        reply_text="Hello, thanks for reaching out!",
        is_enabled=1,
        cooldown_seconds=60
    )
    config = await database.get_reply_config(test_user_id)
    assert config is not None
    assert config["reply_text"] == "Hello, thanks for reaching out!"
    assert config["media_type"] == "photo"

    # Cooldown verification
    peer_id = 111222
    assert await database.check_and_update_cooldown(test_user_id, peer_id, 10) is True
    assert await database.check_and_update_cooldown(test_user_id, peer_id, 10) is False

    await database.delete_user(test_user_id)
    assert await database.get_user(test_user_id) is None

    test_db = Path("data/test_autoreply.db")
    if test_db.exists():
        test_db.unlink()
    print("✅ Database tests passed!")

async def test_userbot_manager():
    print("Testing UserbotManager...")
    manager = UserbotManager()
    assert manager.is_running(999999) is False
    print("✅ UserbotManager test passed!")

async def main():
    await test_database()
    await test_userbot_manager()
    print("🎉 All smoke tests passed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
