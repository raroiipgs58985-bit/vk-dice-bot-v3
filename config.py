from pathlib import Path

VERSION = "4.0.1"
BASE_DIR = Path(__file__).resolve().parent

# Все основные настройки хранятся прямо в этом файле.
# Вставьте НОВЫЙ токен сообщества VK между кавычками.
TOKEN = "ВСТАВЬТЕ_НОВЫЙ_ТОКЕН_СООБЩЕСТВА"

# Числовой ID сообщества без минуса.
GROUP_ID = 239351715

# Числовые VK ID администраторов экономики.
# Для одного администратора:
# VK_ADMIN_IDS = {123456789}
#
# Для нескольких:
# VK_ADMIN_IDS = {123456789, 987654321}
VK_ADMIN_IDS = {
    123456789,
}

STARTING_BALANCE = 100
SALARY_MIN = 10
SALARY_MAX = 20
SALARY_COOLDOWN_SECONDS = 24 * 60 * 60

MAX_DICE_COUNT = 100
MAX_DICE_SIDES = 1_000_000
MAX_TALENT_SUGGESTIONS = 10

QUOTES_FILE = BASE_DIR / "data" / "quotes.txt"
REPLIES_FILE = BASE_DIR / "data" / "replies.json"
ATTACHMENT_CACHE_FILE = BASE_DIR / "data" / "attachments.json"
TALENTS_FILE = BASE_DIR / "data" / "talents.json"
