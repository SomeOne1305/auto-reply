import time
import aiosqlite
from typing import Optional, Dict, Any, List
from config import DATABASE_PATH

async def get_db_connection():
    return await aiosqlite.connect(DATABASE_PATH)

async def init_db():
    """Initializes tables for users, auto-reply configurations, and cooldown tracking."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                api_id INTEGER NOT NULL,
                api_hash TEXT NOT NULL,
                phone TEXT NOT NULL,
                session_string TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reply_configs (
                user_id INTEGER PRIMARY KEY,
                media_type TEXT,
                media_path TEXT,
                reply_text TEXT,
                is_enabled INTEGER DEFAULT 1,
                cooldown_seconds INTEGER DEFAULT 1800,
                updated_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reply_cooldowns (
                user_id INTEGER NOT NULL,
                peer_id INTEGER NOT NULL,
                last_replied_at REAL NOT NULL,
                PRIMARY KEY (user_id, peer_id)
            )
        """)
        await db.commit()

async def save_user(user_id: int, api_id: int, api_hash: str, phone: str, session_string: str) -> None:
    now = time.time()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, api_id, api_hash, phone, session_string, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                api_id=excluded.api_id,
                api_hash=excluded.api_hash,
                phone=excluded.phone,
                session_string=excluded.session_string,
                is_active=1,
                updated_at=excluded.updated_at
        """, (user_id, api_id, api_hash, phone, session_string, now, now))
        await db.commit()

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_all_active_users() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE is_active = 1") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def delete_user(user_id: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM reply_configs WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM reply_cooldowns WHERE user_id = ?", (user_id,))
        await db.commit()

async def save_reply_config(
    user_id: int,
    media_type: Optional[str],
    media_path: Optional[str],
    reply_text: Optional[str],
    is_enabled: int = 1,
    cooldown_seconds: int = 1800
) -> None:
    now = time.time()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO reply_configs (user_id, media_type, media_path, reply_text, is_enabled, cooldown_seconds, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                media_type=excluded.media_type,
                media_path=excluded.media_path,
                reply_text=excluded.reply_text,
                is_enabled=excluded.is_enabled,
                cooldown_seconds=excluded.cooldown_seconds,
                updated_at=excluded.updated_at
        """, (user_id, media_type, media_path, reply_text, is_enabled, cooldown_seconds, now))
        await db.commit()

async def get_reply_config(user_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM reply_configs WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def toggle_reply(user_id: int, is_enabled: int) -> None:
    now = time.time()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            UPDATE reply_configs 
            SET is_enabled = ?, updated_at = ?
            WHERE user_id = ?
        """, (is_enabled, now, user_id))
        await db.commit()

async def check_and_update_cooldown(user_id: int, peer_id: int, cooldown_seconds: int) -> bool:
    """
    Checks if a reply is eligible based on the cooldown window for a specific peer.
    If eligible, updates the timestamp and returns True.
    Otherwise returns False.
    """
    now = time.time()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT last_replied_at FROM reply_cooldowns WHERE user_id = ? AND peer_id = ?",
            (user_id, peer_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                last_replied = row["last_replied_at"]
                if now - last_replied < cooldown_seconds:
                    return False

        await db.execute("""
            INSERT INTO reply_cooldowns (user_id, peer_id, last_replied_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, peer_id) DO UPDATE SET last_replied_at = excluded.last_replied_at
        """, (user_id, peer_id, now))
        await db.commit()
        return True
