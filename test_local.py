from dice import _calculate_degrees
from talents import TalentManager
from replies import ReplyManager
from config import TALENTS_FILE, REPLIES_FILE


assert _calculate_degrees(24, 50) == ("success", 3)
assert _calculate_degrees(44, 50) == ("success", 1)
assert _calculate_degrees(50, 50) == ("success", 1)
assert _calculate_degrees(51, 50) == ("failure", 1)
assert _calculate_degrees(60, 50) == ("failure", 2)
assert _calculate_degrees(79, 50) == ("failure", 3)

talents = TalentManager(TALENTS_FILE)
assert talents.find_exact("[мгновенная реакция")
assert talents.find_exact("[МГНОВЕННАЯ РЕАКЦИЯ]")
assert "Мгновенная реакция" in talents.search("мгновенная")

replies = ReplyManager(REPLIES_FILE)
assert len(replies) > 0

print("Все локальные тесты пройдены.")
