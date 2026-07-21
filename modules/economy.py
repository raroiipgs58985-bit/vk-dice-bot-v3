from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .database import EconomyDatabase


MENTION_RE = re.compile(r"\[id(\d+)\|[^\]]+\]", re.IGNORECASE)
ID_RE = re.compile(r"\bid(\d+)\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"\b(\d+)\b")


@dataclass
class Player:
    vk_id: int
    name: str
    balance: int
    last_salary_at: float = 0.0
    history: list[str] = field(default_factory=list)
    bets_count: int = 0
    wins: int = 0
    losses: int = 0
    total_bet: int = 0
    total_won: int = 0
    total_lost: int = 0


@dataclass
class Bet:
    user_id: int
    outcome: str
    amount: int


@dataclass
class BettingEvent:
    title: str
    outcomes: list[str]
    bets_open: bool = True
    bets: dict[int, Bet] = field(default_factory=dict)

    @property
    def bank(self) -> int:
        return sum(bet.amount for bet in self.bets.values())


class EconomyManager:
    def __init__(
        self,
        *,
        starting_balance: int = 100,
        salary_min: int = 10,
        salary_max: int = 20,
        salary_cooldown_seconds: int = 24 * 60 * 60,
        admin_ids: set[int] | None = None,
        history_limit: int = 20,
    ) -> None:
        self.starting_balance = max(0, int(starting_balance))
        self.salary_min = max(0, int(salary_min))
        self.salary_max = max(self.salary_min, int(salary_max))
        self.salary_cooldown_seconds = max(1, int(salary_cooldown_seconds))
        self.admin_ids = set(admin_ids or set())
        self.history_limit = max(1, int(history_limit))
        self.db = EconomyDatabase(history_retention_days=90)
        self.players: dict[int, Player] = {}
        self.event: BettingEvent | None = None
        self._load_from_database()

    def _load_from_database(self) -> None:
        for row in self.db.load_players():
            player = Player(
                vk_id=int(row["vk_id"]),
                name=str(row["name"]),
                balance=int(row["balance"]),
                last_salary_at=float(row["last_salary_at"]),
                history=list(row.get("history", [])),
                bets_count=int(row["bets_count"]),
                wins=int(row["wins"]),
                losses=int(row["losses"]),
                total_bet=int(row["total_bet"]),
                total_won=int(row["total_won"]),
                total_lost=int(row["total_lost"]),
            )
            self.players[player.vk_id] = player

        payload = self.db.load_event()
        if payload:
            event = BettingEvent(
                title=str(payload.get("title", "Событие")),
                outcomes=[str(x) for x in payload.get("outcomes", [])],
                bets_open=bool(payload.get("bets_open", True)),
            )
            for item in payload.get("bets", []):
                bet = Bet(
                    user_id=int(item["user_id"]),
                    outcome=str(item["outcome"]),
                    amount=int(item["amount"]),
                )
                event.bets[bet.user_id] = bet
            if len(event.outcomes) >= 2:
                self.event = event

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    def get_or_create_player(self, user_id: int, name: str) -> Player:
        player = self.players.get(user_id)
        if player is None:
            player = Player(user_id, name, self.starting_balance)
            self.players[user_id] = player
            self.db.save_player(player)
            self._log(player, f"+{self.starting_balance} — стартовый капитал")
        elif player.name != name:
            player.name = name
            self.db.save_player(player)
        return player

    def _save(self, *players: Player) -> None:
        for player in players:
            self.db.save_player(player)

    def _log(self, player: Player, text: str) -> None:
        timestamp = time.strftime("%d.%m %H:%M", time.localtime())
        entry = f"{timestamp} — {text}"
        player.history.append(entry)
        if len(player.history) > self.history_limit:
            del player.history[:-self.history_limit]
        self.db.add_history(player.vk_id, entry)

    @staticmethod
    def _clean(text: str) -> str:
        return text.strip().rstrip("]").strip()

    @staticmethod
    def _format_duration(seconds: int) -> str:
        hours, remainder = divmod(max(0, seconds), 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{hours} ч. {minutes} мин." if hours else f"{minutes} мин."

    def _resolve_target_id(self, tail: str, message: dict[str, Any]) -> int | None:
        mention = MENTION_RE.search(tail)
        if mention:
            return int(mention.group(1))
        match = ID_RE.search(tail)
        if match:
            return int(match.group(1))
        reply = message.get("reply_message")
        if isinstance(reply, dict) and isinstance(reply.get("from_id"), int):
            return int(reply["from_id"])
        for part in tail.split():
            if part.isdigit() and len(part) >= 5:
                return int(part)
        return None

    @staticmethod
    def _extract_last_amount(text: str) -> int | None:
        values = NUMBER_RE.findall(text)
        return int(values[-1]) if values else None

    @staticmethod
    def _find_outcome(event: BettingEvent, value: str) -> str | None:
        value = value.strip()
        if value.isdigit():
            index = int(value) - 1
            if 0 <= index < len(event.outcomes):
                return event.outcomes[index]
        folded = value.casefold()
        exact = [x for x in event.outcomes if x.casefold() == folded]
        if exact:
            return exact[0]
        partial = [x for x in event.outcomes if folded in x.casefold()]
        return partial[0] if len(partial) == 1 else None

    def _admin_required(self, user_id: int) -> str | None:
        if self.is_admin(user_id):
            return None
        return "⛔ Эта команда доступна только администраторам."

    def handle(self, *, text: str, user_id: int, user_name: str, message: dict[str, Any], vk: Any) -> str | None:
        self.db.cleanup()
        lower = self._clean(text).casefold()
        player = self.get_or_create_player(user_id, user_name)

        if lower == "[баланс":
            return f"💰 {player.name}\nБаланс: {player.balance} тронов."

        if lower == "[история":
            history = "\n".join(player.history[-10:]) or "История пока пуста."
            return f"📜 История операций {player.name}\n\n{history}"

        if lower == "[жалование":
            now = time.time()
            elapsed = now - player.last_salary_at
            if player.last_salary_at and elapsed < self.salary_cooldown_seconds:
                return "⏳ Жалование уже получено.\nСледующее начисление через " + self._format_duration(int(self.salary_cooldown_seconds - elapsed))
            amount = random.randint(self.salary_min, self.salary_max)
            player.balance += amount
            player.last_salary_at = now
            self._save(player)
            self._log(player, f"+{amount} — жалование")
            return f"💰 Получено жалование: {amount} тронов.\nБаланс: {player.balance} тронов."

        if lower in ("[топ", "[балансы"):
            ranked = sorted(self.players.values(), key=lambda x: (-x.balance, x.name.casefold()))
            if not ranked:
                return "Игроков пока нет."
            limit = 10 if lower == "[топ" else 50
            title = "🏆 Богачи Империума" if lower == "[топ" else "💰 Балансы игроков"
            lines = [f"{i}. {x.name} — {x.balance}" if lower == "[топ" else f"{x.name} — {x.balance}" for i, x in enumerate(ranked[:limit], 1)]
            return title + "\n\n" + "\n".join(lines)

        if lower in ("[банк", "[ставки"):
            if self.event is None:
                return "📭 Активного события нет."
            lines = []
            for i, outcome in enumerate(self.event.outcomes, 1):
                bets = [x for x in self.event.bets.values() if x.outcome == outcome]
                lines.append(f"{i}. {outcome} — {len(bets)} ставок, {sum(x.amount for x in bets)} тронов")
            status = "открыты" if self.event.bets_open else "закрыты"
            return f"🎲 {self.event.title}\nСтавки: {status}\nБанк: {self.event.bank} тронов\n\n" + "\n".join(lines)

        if lower.startswith("[ставка "):
            if self.event is None:
                return "📭 Активного события нет."
            if not self.event.bets_open:
                return "🔒 Приём ставок закрыт."
            if user_id in self.event.bets:
                return "⚠ Вы уже сделали ставку на это событие."
            tail = self._clean(text[len("[ставка"):])
            parts = tail.split(maxsplit=1)
            if len(parts) != 2 or not parts[0].isdigit():
                return "Формат: [ставка 25 Победа"
            amount = int(parts[0])
            if amount <= 0 or amount > player.balance:
                return f"Недостаточно тронов.\nВаш баланс: {player.balance}"
            outcome = self._find_outcome(self.event, parts[1])
            if outcome is None:
                return "Не удалось определить исход."
            player.balance -= amount
            player.bets_count += 1
            player.total_bet += amount
            self.event.bets[user_id] = Bet(user_id, outcome, amount)
            self._save(player)
            self._log(player, f"-{amount} — ставка: {outcome}")
            self.db.save_event(self.event)
            return f"✅ Ставка принята.\n\nИсход: {outcome}\nСумма: {amount} тронов\nОстаток: {player.balance} тронов"

        if lower.startswith("[событие "):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            if self.event is not None:
                return "⚠ Сначала завершите или отмените текущее событие."
            chunks = [x.strip() for x in self._clean(text[len("[событие"):]).split("|") if x.strip()]
            if len(chunks) < 3:
                return "Формат: [событие Название | Победа | Поражение"
            title, raw_outcomes = chunks[0], chunks[1:]
            outcomes = []
            seen = set()
            for outcome in raw_outcomes:
                key = outcome.casefold()
                if key not in seen:
                    seen.add(key)
                    outcomes.append(outcome)
            if len(outcomes) < 2:
                return "Нужно указать минимум два разных исхода."
            self.event = BettingEvent(title, outcomes)
            self.db.save_event(self.event)
            return f"📢 Создано событие:\n{title}\n\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(outcomes, 1))

        if lower == "[закрыть ставки":
            denied = self._admin_required(user_id)
            if denied:
                return denied
            if self.event is None:
                return "Активного события нет."
            self.event.bets_open = False
            self.db.save_event(self.event)
            return f"🔒 Ставки закрыты.\nСобытие: {self.event.title}\nБанк: {self.event.bank} тронов."

        if lower.startswith("[итог "):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            if self.event is None:
                return "Активного события нет."
            winning = self._find_outcome(self.event, self._clean(text[len("[итог"):]))
            if winning is None:
                return "Не удалось определить победивший исход."
            event = self.event
            bank = event.bank
            winners = [x for x in event.bets.values() if x.outcome == winning]
            payouts: dict[int, int] = {}
            if winners:
                winner_stake = sum(x.amount for x in winners)
                distributed = 0
                for bet in winners:
                    payouts[bet.user_id] = bank * bet.amount // winner_stake
                    distributed += payouts[bet.user_id]
                remainder = bank - distributed
                for bet in sorted(winners, key=lambda x: (-x.amount, x.user_id)):
                    if remainder <= 0:
                        break
                    payouts[bet.user_id] += 1
                    remainder -= 1
            lines = []
            winner_ids = {x.user_id for x in winners}
            for bet in event.bets.values():
                current = self.players.get(bet.user_id)
                if not current:
                    continue
                if bet.user_id in winner_ids:
                    payout = payouts[bet.user_id]
                    current.balance += payout
                    current.wins += 1
                    current.total_won += payout
                    self._log(current, f"+{payout} — выигрыш: {winning}")
                    lines.append(f"{current.name} — +{payout}")
                else:
                    current.losses += 1
                    current.total_lost += bet.amount
                self._save(current)
            self.event = None
            self.db.save_event(None)
            if not winners:
                return f"🏁 Итог: {winning}\nПобедителей нет. Банк в {bank} тронов сгорает."
            return f"🏁 Итог: {winning}\nБанк: {bank} тронов\n\n" + "\n".join(lines)

        if lower in ("[отмена события", "[сброс ставок"):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            if self.event is None:
                return "Активного события нет."
            refunded = 0
            for bet in self.event.bets.values():
                current = self.players.get(bet.user_id)
                if current:
                    current.balance += bet.amount
                    refunded += bet.amount
                    self._save(current)
                    self._log(current, f"+{bet.amount} — возврат ставки")
            title = self.event.title
            self.event = None
            self.db.save_event(None)
            return f"↩ Событие «{title}» отменено.\nВозвращено: {refunded} тронов."

        for command, mode in (("[выдать ", "give"), ("[забрать ", "take"), ("[установить ", "set")):
            if lower.startswith(command):
                denied = self._admin_required(user_id)
                if denied:
                    return denied
                tail = self._clean(text[len(command.rstrip()):])
                target_id = self._resolve_target_id(tail, message)
                amount = self._extract_last_amount(tail)
                if target_id is None or amount is None:
                    return "Укажите игрока и сумму — упоминанием или ответом на сообщение."
                target = self.get_or_create_player(target_id, self._get_vk_name(vk, target_id))
                if mode == "give":
                    target.balance += amount
                    log = f"+{amount} — выдано администратором"
                elif mode == "take":
                    amount = min(amount, target.balance)
                    target.balance -= amount
                    log = f"-{amount} — изъято администратором"
                else:
                    old = target.balance
                    target.balance = max(0, amount)
                    delta = target.balance - old
                    log = f"{'+' if delta >= 0 else ''}{delta} — баланс установлен администратором"
                self._save(target)
                self._log(target, log)
                return f"✅ Баланс {target.name}: {target.balance} тронов."

        if lower == "[сброс тронов":
            denied = self._admin_required(user_id)
            if denied:
                return denied
            self.players.clear()
            self.event = None
            self.db.reset_all()
            return f"♻ Экономика полностью сброшена.\nНовые игроки получат по {self.starting_balance} тронов."

        if lower == "[экономика":
            denied = self._admin_required(user_id)
            if denied:
                return denied
            total = sum(x.balance for x in self.players.values())
            event_text = "нет" if not self.event else f"{self.event.title}; банк: {self.event.bank}; ставки {'открыты' if self.event.bets_open else 'закрыты'}"
            db_status = "подключена" if self.db.enabled else "не подключена"
            return f"⚙ Экономика Кубятни\n\nИгроков: {len(self.players)}\nСтартовый баланс: {self.starting_balance}\nТронов на руках: {total}\nБаза данных: {db_status}\nАктивное событие: {event_text}"

        if lower == "[очистить базу":
            denied = self._admin_required(user_id)
            if denied:
                return denied
            deleted = self.db.cleanup(force=True)
            return f"🧹 Очистка завершена. Удалено старых записей истории: {deleted}. Балансы и статистика сохранены."

        return None

    @staticmethod
    def _get_vk_name(vk: Any, user_id: int) -> str:
        try:
            user = vk.users.get(user_ids=user_id)[0]
            return f"[id{user_id}|{user['first_name']}]"
        except Exception:
            return f"[id{user_id}|Игрок]"
