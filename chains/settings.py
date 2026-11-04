"""Read private settings (API keys) from environment variables or the .env file."""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def get_setting(name):
    """Return a setting's value, or None. An environment variable wins over .env."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        # utf-8-sig also accepts the invisible BOM that some Windows editors add.
        lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return None
    for line in lines:
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip("'\"") or None
    return None
