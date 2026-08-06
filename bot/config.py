"""Bot configuration: loads TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_IDS from env/.env.

Uses the shared app.env.load_dot_env() loader. Importing app.env is safe —
it imports nothing from app.main, so no FastAPI middleware is initialized
in the bot process.
"""
import os

from app.env import load_dot_env

load_dot_env()

BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# ---------------------------------------------------------------------------
# Ollama / extractor configuration
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "hermes3:8b")
VLM_MODEL: str = os.environ.get("VLM_MODEL", "qwen3-vl:4b")
# Which extractor to use: stub | hermes | vlm  — default hermes
EXTRACTOR: str = os.environ.get("EXTRACTOR", "hermes")


def parse_allowed_ids(raw: str) -> list[int]:
    """Parse a comma-separated string of Telegram user IDs into a list of ints.

    Examples:
        parse_allowed_ids("111, 222")  -> [111, 222]
        parse_allowed_ids("")          -> []
        parse_allowed_ids("111,")      -> [111]
    """
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


ALLOWED_IDS: list[int] = parse_allowed_ids(os.environ.get("TELEGRAM_ALLOWED_IDS", ""))
