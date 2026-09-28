"""Environment variable loading. No web server, no secrets in code."""
import os

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


INSTA_USERNAME = _get("INSTA_USERNAME")
INSTA_PASSWORD = _get("INSTA_PASSWORD")
BOT_USERNAME = _get("BOT_USERNAME", INSTA_USERNAME).lstrip("@")
OWNER_USERNAME = _get("OWNER_USERNAME").lstrip("@")
OWNER_USER_ID = _get("OWNER_USER_ID", "0")
GROQ_API_KEY = _get("GROQ_API_KEY")
NEWS_API_KEY = _get("NEWS_API_KEY", "NONE")

TARGET_THREADS = _get("TARGET_THREADS", "ALL").upper()

try:
    POLL_INTERVAL_SEC = int(_get("POLL_INTERVAL_SEC", "10"))
except ValueError:
    POLL_INTERVAL_SEC = 10

# Discloud persists files in the working directory between restarts,
# so keep session.json in CWD (NOT /tmp).
SESSION_PATH = _get("SESSION_PATH", os.path.join(os.getcwd(), "session.json"))

# IMAGE_ON=yes at boot, toggleable at runtime via Instagram DM !imagegenon|off
IMAGE_ENABLED_DEFAULT = _get("IMAGE_ON", "yes").lower() in ("1", "true", "yes", "on")
NEWS_ENABLED = _get("NEWS_ON", "no").lower() in ("1", "true", "yes", "on")

SYSTEM_PROMPT = (
    "You are a ruthless, sarcastic, and unhinged member of a chaotic group chat. "
    "You roast everyone mercilessly, swear constantly, use all lowercase, and never give a straight answer. "
    "Keep replies short, punchy, and under 15 words. Never be nice. Never break character."
)

GROQ_MODEL = _get("GROQ_MODEL", "llama-3.3-70b-versatile")


def missing_required() -> list:
    missing = []
    if not INSTA_USERNAME:
        missing.append("INSTA_USERNAME")
    if not INSTA_PASSWORD:
        missing.append("INSTA_PASSWORD")
    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")
    if not BOT_USERNAME:
        missing.append("BOT_USERNAME")
    if not OWNER_USERNAME:
        missing.append("OWNER_USERNAME")
    return missing
