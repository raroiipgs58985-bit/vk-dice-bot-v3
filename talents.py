import json
import re
from pathlib import Path
from typing import Optional


def normalize_talent_name(value: str) -> str:
    value = value.casefold().replace("ё", "е")
    value = value.replace("†", "")
    value = re.sub(r"[«»\"'`]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


class TalentManager:
    def __init__(self, path):
        self.path = Path(path)
        self.talents = self._load()
        self.index = {
            normalize_talent_name(name): (name, description)
            for name, description in self.talents.items()
        }

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"Файл талантов не найден: {self.path}", flush=True)
            return {}
        except json.JSONDecodeError as error:
            print(f"Ошибка JSON в {self.path}: {error}", flush=True)
            return {}

        if not isinstance(data, dict):
            return {}

        return {
            str(name).strip(): str(description).strip()
            for name, description in data.items()
            if str(name).strip() and str(description).strip()
        }

    def find_exact(self, command: str) -> Optional[tuple[str, str]]:
        command = command.strip()
        if not command.startswith("["):
            return None

        query = command[1:].strip()
        if query.endswith("]"):
            query = query[:-1].strip()

        return self.index.get(normalize_talent_name(query))

    def search(self, query: str, limit: int = 10) -> list[str]:
        normalized = normalize_talent_name(query)
        if not normalized:
            return []

        starts = []
        contains = []

        for name in self.talents:
            candidate = normalize_talent_name(name)
            if candidate.startswith(normalized):
                starts.append(name)
            elif normalized in candidate:
                contains.append(name)

        return (sorted(starts) + sorted(contains))[:limit]

    @staticmethod
    def format_talent(name: str, description: str) -> str:
        return (
            "📖 ТАЛАНТ\n"
            "━━━━━━━━━━━━━━━\n"
            f"⚜ {name}\n\n"
            f"{description}"
        )

    @staticmethod
    def format_search(query: str, matches: list[str]) -> str:
        if not matches:
            return f"🔎 По запросу «{query}» таланты не найдены."

        lines = [
            f"🔎 ТАЛАНТЫ: «{query}»",
            "━━━━━━━━━━━━━━━",
        ]
        lines.extend(f"• {name}" for name in matches)
        lines.append("")
        lines.append("Для описания отправь точное название через символ [.")
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self.talents)
