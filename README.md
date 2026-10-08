# Telegram Auto-Reply System

An asynchronous Telegram automation daemon combining an **aiogram-powered Telegram Bot interface** (for interactive user authentication and configuration) with background **Telethon MTProto userbot workers** to automatically reply to incoming direct personal chats.

---

## 🚀 Key Advantages

- **Zero API ID/Hash needed on server**: Your server configuration **only requires `BOT_TOKEN`** from [@BotFather](https://t.me/BotFather).
- **Users Provide Their Own Credentials**: When users run `/login`, they provide their own `api_id`, `api_hash`, phone number, and OTP. The server spins up their personal `Telethon` MTProto userbot on demand.
- **Strict Personal Chat Filtering**: Auto-replies **only to 1-on-1 private direct chats**. Ignores groups, channels, service notifications (`777000`), bots, and outgoing messages.
- **Anti-Spam Debounce**: Built-in per-contact cooldown (default: 30 minutes) prevents spamming when someone sends multiple messages in a row.
- **Persistent Across Restarts**: Active user sessions and templates are stored in SQLite and automatically restored on boot.

---

## 🏛 System Architecture & Workflow

```
       +--------------------------------------------------------+
       |                  User's Telegram App                   |
       +--------------------------------------------------------+
                |                                      ^
        1. /start, /login                              |
        2. Enter API ID, Hash, Phone, OTP              | 6. Incoming Direct Messages
        3. /message -> Sticker/Image -> Text -> /ends  |    (Strictly 1-on-1 chats)
                v                                      v
       +----------------------+              +----------------------+
       | Telegram Bot Client  |              | MTProto Userbot Pool |
       | (aiogram HTTP Bot)   |              | (Telethon MTProto)   |
       |     [bot.py]         |              | [userbot_manager.py] |
       +----------------------+              +----------------------+
                |                                      ^
         Updates DB & Config                           | Reads Config & Session
                v                                      v
       +--------------------------------------------------------+
       |             SQLite Database (data/autoreply.db)        |
       |  - users (credentials & StringSession)                 |
       |  - reply_configs (media paths & text message)          |
       |  - reply_cooldowns (anti-spam debounce per contact)    |
       +--------------------------------------------------------+
```

---

## 🛠 Setup & Deployment

### 1. Requirements
- Python 3.10+
- Bot Token from [@BotFather](https://t.me/BotFather)

### 2. Install Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure `.env`
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Your `.env` file only needs:
```ini
# Telegram Bot Token from @BotFather
BOT_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ

# Storage Configuration
DATABASE_PATH=data/autoreply.db
MEDIA_DIR=data/media

# Auto-reply cooldown in seconds (1800 = 30 minutes before replying to the same contact again)
AUTO_REPLY_COOLDOWN=1800
```

### 4. Run Smoke Tests
```bash
./venv/bin/python3 test_system.py
```

### 5. Start the Server Daemon
```bash
./venv/bin/python3 main.py
```

---

## 📱 User Interaction Walkthrough

### 1. Connecting Telegram Account
1. Open your bot in Telegram and send `/start`.
2. Send `/login`.
3. Enter your `api_id` and `api_hash` (from https://my.telegram.org).
4. Enter your phone number with country code (e.g., `+1234567890`).
5. Enter the OTP verification code sent by Telegram.
6. If Two-Step Verification (2FA) is enabled, enter your Cloud Password.
7. The bot confirms login and starts your background userbot worker.

### 2. Setting Auto-Reply Template
1. Send `/message`.
2. *(Optional)* Send a **Sticker** or **Image/Photo**. The bot saves it.
3. Send your **Text message**.
4. Send `/ends` to save and activate!
5. Any personal contact who messages you directly will receive your sticker/image followed by your text message.

### 3. Management Commands
- `/status` — View your account phone, worker status, template preview, and active toggle.
- `/toggle` — Temporarily pause or re-enable auto-replies without logging out.
- `/logout` — Disconnect userbot worker and delete credentials from the database.
- `/cancel` — Cancel any active login or configuration wizard.
