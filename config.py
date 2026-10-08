import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Telegram Bot Token from @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Webhook Configuration (if WEBHOOK_URL is set, bot runs in Webhook mode, otherwise Polling)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
HOST = os.getenv("HOST", "0.0.0.0").strip()
PORT = int(os.getenv("PORT", "8080"))

# Base directories
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", str(DATA_DIR / "media")))
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "autoreply.db")))

# Auto reply defaults
# Default cooldown in seconds (30 minutes)
AUTO_REPLY_COOLDOWN = int(os.getenv("AUTO_REPLY_COOLDOWN", "1800"))

# Ensure storage directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
