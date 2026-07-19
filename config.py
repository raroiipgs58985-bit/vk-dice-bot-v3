from pathlib import Path

VERSION = "4.0.1"
BASE_DIR = Path(__file__).resolve().parent

# Все основные настройки хранятся прямо в этом файле.
# Вставьте НОВЫЙ токен сообщества VK между кавычками.
TOKEN = "vk1.a.ceenGlcLhhVpKFGc4HAJfNdEZiBEwu4qoN25_7vnElyV7S7GF4PQGoYVCqD_eAFaUqnSe-MjCuttecLlxuyxqI6dsi93ACm7Wrdg6NDar7x5F5GVl1IFrPnGbPzgKn1W3sIAlAsPAYcWjOF9Ab-olAIcpby-Y4LAOYUSgbDP5iRGPvdRIO0eM4dJJVKf_sU7IHjhTZI3nx6M3fAIJTFHbQ"

# Числовой ID сообщества без минуса.
GROUP_ID = 239351715

# Числовые VK ID администраторов экономики.
# Для одного администратора:
# VK_ADMIN_IDS = {123456789}
#
# Для нескольких:
# VK_ADMIN_IDS = {123456789, 987654321}
VK_ADMIN_IDS = {
    165893050, 546836544, 483392903
}

STARTING_BALANCE = 200
SALARY_MIN = 15
SALARY_MAX = 25
SALARY_COOLDOWN_SECONDS = 24 * 60 * 60

MAX_DICE_COUNT = 100
MAX_DICE_SIDES = 1_000_000
MAX_TALENT_SUGGESTIONS = 10

QUOTES_FILE = BASE_DIR / "data" / "quotes.txt"
REPLIES_FILE = BASE_DIR / "data" / "replies.json"
ATTACHMENT_CACHE_FILE = BASE_DIR / "data" / "attachments.json"
TALENTS_FILE = BASE_DIR / "data" / "talents.json"
