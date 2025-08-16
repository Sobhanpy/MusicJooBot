import os
import logging
from dotenv import load_dotenv

def setup_logging():
    """Configure basic logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    return logging.getLogger("musicjoo")

def load_env():
    """Load environment variables from .env if present."""
    load_dotenv()

def get_env(name: str, default: str = "") -> str:
    """Fetch environment variable with a default."""
    return os.getenv(name, default)

def human_exc(e: Exception) -> str:
    """Short, user-friendly exception text."""
    return f"{type(e).name}: {str(e)[:300]}"