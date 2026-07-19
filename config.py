import os
from pathlib import Path

VERSION = "4.0.0"
BASE_DIR = Path(__file__).resolve().parent

# Render: задайте VK_TOKEN и VK_GROUP_ID в Environment.
TOKEN = os.environ.get("VK_TOKEN", "")
GROUP_ID = int(os.environ.get("VK_GROUP_ID", 0))

# VK ID администраторов экономики через запятую:
# VK_ADMIN_IDS=123456789,987654321
VK_ADMIN_IDS = {
    int(value.strip())
    for value in os.environ.get("VK_ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}

STARTING_BALANCE = int(os.environ.get("STARTING_BALANCE", 100))
SALARY_MIN = int(os.environ.get("SALARY_MIN", 10))
SALARY_MAX = int(os.environ.get("SALARY_MAX", 20))
SALARY_COOLDOWN_SECONDS = int(
    os.environ.get("SALARY_COOLDOWN_SECONDS", 24 * 60 * 60)
)

MAX_DICE_COUNT = 100
MAX_DICE_SIDES = 1_000_000
MAX_TALENT_SUGGESTIONS = 10

QUOTES_FILE = BASE_DIR / "data" / "quotes.txt"
REPLIES_FILE = BASE_DIR / "data" / "replies.json"
ATTACHMENT_CACHE_FILE = BASE_DIR / "data" / "attachments.json"
TALENTS_FILE = BASE_DIR / "data" / "talents.json"
