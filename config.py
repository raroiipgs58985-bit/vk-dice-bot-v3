from __future__ import annotations

import os
from pathlib import Path


VERSION = "4.1.0"
BASE_DIR = Path(__file__).resolve().parent


# Токен сообщества VK хранится только в Environment Variables на Render.
TOKEN = os.environ.get("VK_TOKEN", "").strip()

# ID сообщества без минуса.
GROUP_ID = int(os.environ.get("VK_GROUP_ID", "239351715"))

# Администраторы экономики.
# Можно переопределить через VK_ADMIN_IDS=123456789,987654321
_default_admins = "165893050,546836544,483392903"
VK_ADMIN_IDS = {
    int(value.strip())
    for value in os.environ.get("VK_ADMIN_IDS", _default_admins).split(",")
    if value.strip().isdigit()
}

STARTING_BALANCE = int(os.environ.get("STARTING_BALANCE", "200"))
SALARY_MIN = int(os.environ.get("SALARY_MIN", "15"))
SALARY_MAX = int(os.environ.get("SALARY_MAX", "25"))
SALARY_COOLDOWN_SECONDS = int(
    os.environ.get("SALARY_COOLDOWN_SECONDS", str(24 * 60 * 60))
)

MAX_DICE_COUNT = 100
MAX_DICE_SIDES = 1_000_000
MAX_TALENT_SUGGESTIONS = 10

QUOTES_FILE = BASE_DIR / "data" / "quotes.txt"
REPLIES_FILE = BASE_DIR / "data" / "replies.json"
ATTACHMENT_CACHE_FILE = BASE_DIR / "data" / "attachments.json"
TALENTS_FILE = BASE_DIR / "data" / "talents.json"
