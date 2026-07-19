from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from typing import Any


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

        self.players: dict[int, Player] = {}
        self.event: BettingEvent | None = None

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    def get_or_create_player(self, user_id: int, name: str) -> Player:
        player = self.players.get(user_id)
        if player is None:
            player = Player(
                vk_id=user_id,
                name=name,
                balance=self.starting_balance,
            )
            self.players[user_id] = player
            self._log(player, f"+{self.starting_balance} — стартовый капитал")
        else:
            player.name = name
        return player

    def _log(self, player: Player, text: str) -> None:
        timestamp = time.strftime("%d.%m %H:%M", time.localtime())
        player.history.append(f"{timestamp} — {text}")
        if len(player.history) > self.history_limit:
            del player.history[:-self.history_limit]

    @staticmethod
    def _clean(text: str) -> str:
        return text.strip().rstrip("]").strip()

    @staticmethod
    def _format_duration(seconds: int) -> str:
        seconds = max(0, seconds)
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours:
            return f"{hours} ч. {minutes} мин."
        return f"{minutes} мин."

    def _resolve_target_id(self, command_tail: str, message: dict[str, Any]) -> int | None:
        mention = MENTION_RE.search(command_tail)
        if mention:
            return int(mention.group(1))

        id_match = ID_RE.search(command_tail)
        if id_match:
            return int(id_match.group(1))

        reply_message = message.get("reply_message")
        if isinstance(reply_message, dict):
            reply_user_id = reply_message.get("from_id")
            if isinstance(reply_user_id, int) and reply_user_id > 0:
                return reply_user_id

        parts = command_tail.split()
        for part in parts:
            if part.isdigit() and len(part) >= 5:
                return int(part)

        return None

    @staticmethod
    def _extract_last_amount(text: str) -> int | None:
        numbers = NUMBER_RE.findall(text)
        if not numbers:
            return None
        return int(numbers[-1])

    @staticmethod
    def _find_outcome(event: BettingEvent, value: str) -> str | None:
        value = value.strip()
        if value.isdigit():
            index = int(value) - 1
            if 0 <= index < len(event.outcomes):
                return event.outcomes[index]

        folded = value.casefold()
        exact = [outcome for outcome in event.outcomes if outcome.casefold() == folded]
        if exact:
            return exact[0]

        partial = [outcome for outcome in event.outcomes if folded in outcome.casefold()]
        if len(partial) == 1:
            return partial[0]

        return None

    def _admin_required(self, user_id: int) -> str | None:
        if self.is_admin(user_id):
            return None
        if not self.admin_ids:
            return (
                "⛔ Администраторы экономики не настроены.\n"
                "Добавьте VK_ADMIN_IDS в переменные окружения Render."
            )
        return "⛔ Эта команда доступна только администраторам."

    def handle(
        self,
        *,
        text: str,
        user_id: int,
        user_name: str,
        message: dict[str, Any],
        vk: Any,
    ) -> str | None:
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
                wait = int(self.salary_cooldown_seconds - elapsed)
                return (
                    "⏳ Жалование уже получено.\n"
                    f"Следующее начисление через {self._format_duration(wait)}"
                )

            amount = random.randint(self.salary_min, self.salary_max)
            player.balance += amount
            player.last_salary_at = now
            self._log(player, f"+{amount} — жалование")
            return (
                f"💰 Получено жалование: {amount} тронов.\n"
                f"Баланс: {player.balance} тронов."
            )

        if lower == "[топ":
            if not self.players:
                return "Игроков пока нет."
            ranked = sorted(
                self.players.values(),
                key=lambda item: (-item.balance, item.name.casefold()),
            )[:10]
            lines = [
                f"{index}. {item.name} — {item.balance}"
                for index, item in enumerate(ranked, start=1)
            ]
            return "🏆 Богачи Империума\n\n" + "\n".join(lines)

        if lower == "[балансы":
            if not self.players:
                return "Игроков пока нет."
            ranked = sorted(
                self.players.values(),
                key=lambda item: (-item.balance, item.name.casefold()),
            )
            lines = [f"{item.name} — {item.balance}" for item in ranked[:50]]
            suffix = ""
            if len(ranked) > 50:
                suffix = f"\n\nПоказано 50 из {len(ranked)} игроков."
            return "💰 Балансы игроков\n\n" + "\n".join(lines) + suffix

        if lower == "[банк" or lower == "[ставки":
            if self.event is None:
                return "📭 Активного события нет."

            counts = {
                outcome: sum(
                    1 for bet in self.event.bets.values()
                    if bet.outcome == outcome
                )
                for outcome in self.event.outcomes
            }
            sums = {
                outcome: sum(
                    bet.amount for bet in self.event.bets.values()
                    if bet.outcome == outcome
                )
                for outcome in self.event.outcomes
            }
            lines = [
                f"{index}. {outcome} — {counts[outcome]} ставок, {sums[outcome]} тронов"
                for index, outcome in enumerate(self.event.outcomes, start=1)
            ]
            status = "открыты" if self.event.bets_open else "закрыты"
            return (
                f"🎲 {self.event.title}\n"
                f"Ставки: {status}\n"
                f"Банк: {self.event.bank} тронов\n\n"
                + "\n".join(lines)
            )

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
            if amount <= 0:
                return "Сумма ставки должна быть больше нуля."
            if amount > player.balance:
                return (
                    f"Недостаточно тронов.\n"
                    f"Ваш баланс: {player.balance}"
                )

            outcome = self._find_outcome(self.event, parts[1])
            if outcome is None:
                options = "\n".join(
                    f"{index}. {item}"
                    for index, item in enumerate(self.event.outcomes, start=1)
                )
                return "Не удалось определить исход.\n\n" + options

            player.balance -= amount
            player.bets_count += 1
            player.total_bet += amount
            self.event.bets[user_id] = Bet(
                user_id=user_id,
                outcome=outcome,
                amount=amount,
            )
            self._log(player, f"-{amount} — ставка: {outcome}")
            return (
                "✅ Ставка принята.\n\n"
                f"Исход: {outcome}\n"
                f"Сумма: {amount} тронов\n"
                f"Остаток: {player.balance} тронов"
            )

        if lower.startswith("[событие "):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            if self.event is not None:
                return "⚠ Сначала завершите или отмените текущее событие."

            raw = self._clean(text[len("[событие"):])
            chunks = [chunk.strip() for chunk in raw.split("|") if chunk.strip()]
            if len(chunks) < 3:
                return "Формат: [событие Название | Победа | Поражение"

            title, outcomes = chunks[0], chunks[1:]
            unique: list[str] = []
            seen: set[str] = set()
            for outcome in outcomes:
                key = outcome.casefold()
                if key not in seen:
                    seen.add(key)
                    unique.append(outcome)

            if len(unique) < 2:
                return "Нужно указать минимум два разных исхода."

            self.event = BettingEvent(title=title, outcomes=unique)
            options = "\n".join(
                f"{index}. {outcome}"
                for index, outcome in enumerate(unique, start=1)
            )
            return f"📢 Создано событие:\n{title}\n\n{options}"

        if lower == "[закрыть ставки":
            denied = self._admin_required(user_id)
            if denied:
                return denied
            if self.event is None:
                return "Активного события нет."
            if not self.event.bets_open:
                return "Ставки уже закрыты."
            self.event.bets_open = False
            return (
                f"🔒 Ставки закрыты.\n"
                f"Событие: {self.event.title}\n"
                f"Банк: {self.event.bank} тронов."
            )

        if lower.startswith("[итог "):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            if self.event is None:
                return "Активного события нет."

            raw_outcome = self._clean(text[len("[итог"):])
            winning_outcome = self._find_outcome(self.event, raw_outcome)
            if winning_outcome is None:
                return "Не удалось определить победивший исход."

            event = self.event
            bank = event.bank
            winners = [
                bet for bet in event.bets.values()
                if bet.outcome == winning_outcome
            ]

            if not winners:
                for bet in event.bets.values():
                    loser = self.players.get(bet.user_id)
                    if loser:
                        loser.losses += 1
                        loser.total_lost += bet.amount
                self.event = None
                return (
                    f"🏁 Итог: {winning_outcome}\n"
                    f"Победителей нет. Банк в {bank} тронов сгорает."
                )

            winner_stake = sum(bet.amount for bet in winners)
            payouts: dict[int, int] = {}
            distributed = 0

            for bet in winners:
                payout = bank * bet.amount // winner_stake
                payouts[bet.user_id] = payout
                distributed += payout

            remainder = bank - distributed
            for bet in sorted(winners, key=lambda item: (-item.amount, item.user_id)):
                if remainder <= 0:
                    break
                payouts[bet.user_id] += 1
                remainder -= 1

            result_lines: list[str] = []
            winner_ids = {bet.user_id for bet in winners}

            for bet in event.bets.values():
                current = self.players.get(bet.user_id)
                if current is None:
                    continue

                if bet.user_id in winner_ids:
                    payout = payouts[bet.user_id]
                    current.balance += payout
                    current.wins += 1
                    current.total_won += payout
                    self._log(
                        current,
                        f"+{payout} — выигрыш: {winning_outcome}",
                    )
                    result_lines.append(f"{current.name} — +{payout}")
                else:
                    current.losses += 1
                    current.total_lost += bet.amount

            self.event = None
            return (
                f"🏁 Итог: {winning_outcome}\n"
                f"Банк: {bank} тронов\n\n"
                + "\n".join(result_lines)
            )

        if lower == "[отмена события" or lower == "[сброс ставок":
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
                    self._log(current, f"+{bet.amount} — возврат ставки")

            title = self.event.title
            self.event = None
            return (
                f"↩ Событие «{title}» отменено.\n"
                f"Возвращено: {refunded} тронов."
            )

        if lower.startswith("[выдать "):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            tail = self._clean(text[len("[выдать"):])
            target_id = self._resolve_target_id(tail, message)
            amount = self._extract_last_amount(tail)
            if target_id is None or amount is None:
                return "Формат: [выдать @игрок 50 — или ответом на сообщение."
            if amount <= 0:
                return "Сумма должна быть больше нуля."

            target_name = self._get_vk_name(vk, target_id)
            target = self.get_or_create_player(target_id, target_name)
            target.balance += amount
            self._log(target, f"+{amount} — выдано администратором")
            return f"✅ {target.name} получил {amount} тронов.\nБаланс: {target.balance}"

        if lower.startswith("[забрать "):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            tail = self._clean(text[len("[забрать"):])
            target_id = self._resolve_target_id(tail, message)
            amount = self._extract_last_amount(tail)
            if target_id is None or amount is None:
                return "Формат: [забрать @игрок 25 — или ответом на сообщение."
            if amount <= 0:
                return "Сумма должна быть больше нуля."

            target_name = self._get_vk_name(vk, target_id)
            target = self.get_or_create_player(target_id, target_name)
            taken = min(amount, target.balance)
            target.balance -= taken
            self._log(target, f"-{taken} — изъято администратором")
            return f"✅ У {target.name} изъято {taken} тронов.\nБаланс: {target.balance}"

        if lower.startswith("[установить "):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            tail = self._clean(text[len("[установить"):])
            target_id = self._resolve_target_id(tail, message)
            amount = self._extract_last_amount(tail)
            if target_id is None or amount is None:
                return "Формат: [установить @игрок 100 — или ответом на сообщение."

            target_name = self._get_vk_name(vk, target_id)
            target = self.get_or_create_player(target_id, target_name)
            old_balance = target.balance
            target.balance = max(0, amount)
            delta = target.balance - old_balance
            sign = "+" if delta >= 0 else ""
            self._log(target, f"{sign}{delta} — баланс установлен администратором")
            return f"✅ Баланс {target.name}: {target.balance} тронов."

        if lower == "[сброс тронов":
            denied = self._admin_required(user_id)
            if denied:
                return denied
            self.players.clear()
            self.event = None
            return (
                "♻ Экономика полностью сброшена.\n"
                f"Новые игроки получат по {self.starting_balance} тронов."
            )

        if lower == "[экономика":
            denied = self._admin_required(user_id)
            if denied:
                return denied
            total = sum(item.balance for item in self.players.values())
            event_text = "нет"
            if self.event:
                event_text = (
                    f"{self.event.title}; банк: {self.event.bank}; "
                    f"ставки {'открыты' if self.event.bets_open else 'закрыты'}"
                )
            return (
                "⚙ Экономика Кубятни\n\n"
                f"Игроков: {len(self.players)}\n"
                f"Стартовый баланс: {self.starting_balance}\n"
                f"Тронов на руках: {total}\n"
                f"Активное событие: {event_text}"
            )

        return None

    @staticmethod
    def _get_vk_name(vk: Any, user_id: int) -> str:
        try:
            user = vk.users.get(user_ids=user_id)[0]
            return f"[id{user_id}|{user['first_name']}]"
        except Exception:
            return f"[id{user_id}|Игрок]"
