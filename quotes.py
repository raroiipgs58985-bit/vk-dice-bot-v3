import random
from pathlib import Path


class QuoteManager:
    def __init__(self, path: str):
        self.path = Path(path)
        self.quotes: list[str] = []
        self.pool: list[str] = []
        self.reload()

    def reload(self) -> None:
        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"Файл цитат не найден: {self.path}", flush=True)
            self.quotes = ["За Императора!"]
            self.pool = []
            return

        quotes = self._parse_quotes(raw_text)
        quotes = list(dict.fromkeys(quotes))

        self.quotes = quotes or ["За Императора!"]
        self.pool = []

    @staticmethod
    def _parse_quotes(raw_text: str) -> list[str]:
        # Старый формат: одна цитата на строку.
        # Новый формат: многострочные цитаты можно разделять строкой ===.
        if any(line.strip() == "===" for line in raw_text.splitlines()):
            blocks = raw_text.split("\n===\n")
            return [
                block.strip()
                for block in blocks
                if block.strip()
            ]

        return [
            line.strip()
            for line in raw_text.splitlines()
            if line.strip()
        ]

    def get_random(self) -> str:
        if not self.pool:
            self.pool = self.quotes.copy()
            random.shuffle(self.pool)

        return self.pool.pop()

    def __len__(self) -> int:
        return len(self.quotes)
