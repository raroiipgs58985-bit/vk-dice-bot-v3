import os
from pathlib import Path

VERSION = "3.0.0"
BASE_DIR = Path(__file__).resolve().parent

# Render: рекомендуемый вариант — задать VK_TOKEN и VK_GROUP_ID в Environment.
# Старые значения сохранены как запасной вариант, чтобы текущий деплой не сломался.
TOKEN = os.environ.get("VK_TOKEN", "vk1.a.ceenGlcLhhVpKFGc4HAJfNdEZiBEwu4qoN25_7vnElyV7S7GF4PQGoYVCqD_eAFaUqnSe-MjCuttecLlxuyxqI6dsi93ACm7Wrdg6NDar7x5F5GVl1IFrPnGbPzgKn1W3sIAlAsPAYcWjOF9Ab-olAIcpby-Y4LAOYUSgbDP5iRGPvdRIO0eM4dJJVKf_sU7IHjhTZI3nx6M3fAIJTFHbQ")
GROUP_ID = int(os.environ.get("VK_GROUP_ID", 239351715))

MAX_DICE_COUNT = 100
MAX_DICE_SIDES = 1_000_000
MAX_TALENT_SUGGESTIONS = 10

QUOTES_FILE = BASE_DIR / "data" / "quotes.txt"
REPLIES_FILE = BASE_DIR / "data" / "replies.json"
ATTACHMENT_CACHE_FILE = BASE_DIR / "data" / "attachments.json"
TALENTS_FILE = BASE_DIR / "data" / "talents.json"
