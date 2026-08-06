"""Shared .env loader. app.main, app.database and bot.config all call this.

Kept dependency-free (no python-dotenv) and idempotent: values already present
in os.environ always win, so launchd EnvironmentVariables override .env.
"""
import os
from pathlib import Path

_ENV_PATH = Path(__file__).parent.parent / ".env"


def load_dot_env() -> None:
    if not _ENV_PATH.is_file():
        return
    with open(_ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value
