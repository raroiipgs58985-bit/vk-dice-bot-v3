import json
from pathlib import Path
from typing import Optional


class ReplyManager:
    def __init__(self, path):
        self.path = Path(path)
        self.replies = self._load()
        self._ordered_triggers = sorted(
            self.replies,
            key=len,
            reverse=True,
        )

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"Файл автоответов не найден: {self.path}", flush=True)
            return {}
        except json.JSONDecodeError as error:
            print(f"Ошибка JSON в {self.path}: {error}", flush=True)
            return {}

        if not isinstance(data, dict):
            print("Файл автоответов должен содержать JSON-объект.", flush=True)
            return {}

        result = {}
        for trigger, payload in data.items():
            if not isinstance(trigger, str) or not trigger.strip():
                continue
            if not isinstance(payload, dict):
                continue

            result[trigger.strip()] = {
                "text": str(payload.get("text", "")),
                "image": payload.get("image"),
                "attachment": payload.get("attachment"),
            }

        return result

    def find(self, text: str) -> Optional[tuple[str, dict]]:
        lower_text = text.casefold()

        for trigger in self._ordered_triggers:
            if trigger.casefold() in lower_text:
                return trigger, self.replies[trigger]

        return None

    def __len__(self) -> int:
        return len(self.replies)
