from __future__ import annotations

import json
import math
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .database import EconomyDatabase

MENTION_RE = re.compile(r"\[id(\d+)\|[^\]]+\]", re.IGNORECASE)
ID_RE = re.compile(r"\bid(\d+)\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"\b(\d+)\b")
TX_RE = re.compile(r"\b([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\b", re.I)

JACKPOT_START = 500
TRANSFER_FEE_PERCENT = 5
EVENT_LOSS_JACKPOT_PERCENT = 5
SLOT_JACKPOT_CHANCE = 50_000


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
    casino_games: int = 0
    casino_wins: int = 0
    casino_losses: int = 0
    casino_wagered: int = 0
    casino_profit: int = 0
    biggest_win: int = 0
    jackpot_wins: int = 0
    biggest_jackpot: int = 0


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
        return sum(b.amount for b in self.bets.values())


class EconomyManager:
    def __init__(self, *, starting_balance: int = 100, salary_min: int = 10, salary_max: int = 20,
                 salary_cooldown_seconds: int = 86400, admin_ids: set[int] | None = None,
                 history_limit: int = 20, casino_min_bet: int = 5, casino_max_bet: int = 1000,
                 casino_cooldown_seconds: int = 3) -> None:
        self.starting_balance = max(0, int(starting_balance))
        self.salary_min = max(0, int(salary_min))
        self.salary_max = max(self.salary_min, int(salary_max))
        self.salary_cooldown_seconds = max(1, int(salary_cooldown_seconds))
        self.admin_ids = set(admin_ids or set())
        self.history_limit = max(1, int(history_limit))
        self.casino_min_bet = max(1, int(casino_min_bet))
        self.casino_max_bet = max(self.casino_min_bet, int(casino_max_bet))
        self.casino_cooldown_seconds = max(1, int(casino_cooldown_seconds))
        self._casino_cooldowns: dict[int, float] = {}
        self.db = EconomyDatabase(history_retention_days=90)
        self.players: dict[int, Player] = {}
        self.event: BettingEvent | None = None
        self.jackpot = JACKPOT_START
        self._load_from_database()

    def _load_from_database(self) -> None:
        for row in self.db.load_players():
            p = Player(
                vk_id=int(row["vk_id"]), name=str(row["name"]), balance=int(row["balance"]),
                last_salary_at=float(row["last_salary_at"]), history=list(row.get("history", [])),
                bets_count=int(row["bets_count"]), wins=int(row["wins"]), losses=int(row["losses"]),
                total_bet=int(row["total_bet"]), total_won=int(row["total_won"]), total_lost=int(row["total_lost"]),
                casino_games=int(row.get("casino_games", 0)), casino_wins=int(row.get("casino_wins", 0)),
                casino_losses=int(row.get("casino_losses", 0)), casino_wagered=int(row.get("casino_wagered", 0)),
                casino_profit=int(row.get("casino_profit", 0)), biggest_win=int(row.get("biggest_win", 0)),
                jackpot_wins=int(row.get("jackpot_wins", 0)), biggest_jackpot=int(row.get("biggest_jackpot", 0)),
            )
            self.players[p.vk_id] = p
        raw_jackpot = self.db.get_state("jackpot", JACKPOT_START)
        try:
            self.jackpot = max(JACKPOT_START, int(raw_jackpot))
        except (TypeError, ValueError):
            self.jackpot = JACKPOT_START
        payload = self.db.load_event()
        if payload:
            event = BettingEvent(str(payload.get("title", "Событие")), [str(x) for x in payload.get("outcomes", [])], bool(payload.get("bets_open", True)))
            for item in payload.get("bets", []):
                bet = Bet(int(item["user_id"]), str(item["outcome"]), int(item["amount"]))
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
            self.db.add_transaction(kind="start", amount=self.starting_balance, reason="Стартовый капитал", target_vk_id=user_id)
        elif player.name != name:
            player.name = name
            self.db.save_player(player)
        return player

    def _save(self, *players: Player) -> None:
        for player in players:
            self.db.save_player(player)

    def _log(self, player: Player, text: str) -> None:
        entry = f"{time.strftime('%d.%m %H:%M')} — {text}"
        player.history.append(entry)
        if len(player.history) > self.history_limit:
            del player.history[:-self.history_limit]
        self.db.add_history(player.vk_id, entry)

    def _add_jackpot(self, amount: int, reason: str, *, actor_vk_id: int | None = None,
                     source_vk_id: int | None = None, metadata: dict[str, Any] | None = None) -> int:
        amount = max(0, int(amount))
        if not amount:
            return 0
        self.jackpot += amount
        self.db.set_state("jackpot", self.jackpot)
        self.db.add_transaction(kind="jackpot_fund", amount=amount, reason=reason, actor_vk_id=actor_vk_id,
                                source_vk_id=source_vk_id, metadata=metadata)
        return amount

    @staticmethod
    def _clean(text: str) -> str:
        return text.strip().rstrip("]").strip()

    @staticmethod
    def _format_duration(seconds: int) -> str:
        hours, remainder = divmod(max(0, seconds), 3600)
        minutes = remainder // 60
        return f"{hours} ч. {minutes} мин." if hours else f"{minutes} мин."

    def _resolve_target_id(self, tail: str, message: dict[str, Any]) -> int | None:
        match = MENTION_RE.search(tail) or ID_RE.search(tail)
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
        if value.isdigit() and 0 <= int(value) - 1 < len(event.outcomes):
            return event.outcomes[int(value) - 1]
        exact = [x for x in event.outcomes if x.casefold() == value.casefold()]
        if exact:
            return exact[0]
        partial = [x for x in event.outcomes if value.casefold() in x.casefold()]
        return partial[0] if len(partial) == 1 else None

    def _admin_required(self, user_id: int) -> str | None:
        return None if self.is_admin(user_id) else "⛔ Эта команда доступна только администраторам."

    def _profile(self, player: Player) -> str:
        event_games = player.wins + player.losses
        event_wr = round(player.wins * 100 / event_games) if event_games else 0
        casino_wr = round(player.casino_wins * 100 / player.casino_games) if player.casino_games else 0
        ranked = sorted(self.players.values(), key=lambda x: (-x.balance, x.name.casefold()))
        place = next((i for i, item in enumerate(ranked, 1) if item.vk_id == player.vk_id), 0)
        return (
            f"👤 {player.name}\n\n💰 Баланс: {player.balance} тронов\n🏅 Место в рейтинге: {place}\n"
            f"🎲 Ставок на события: {player.bets_count}\n🏆 Побед: {player.wins}\n💀 Поражений: {player.losses}\n"
            f"📈 WinRate событий: {event_wr}%\n💵 Поставлено: {player.total_bet}\n"
            f"🎰 Игр в казино: {player.casino_games}\n🎯 Побед в казино: {player.casino_wins}\n"
            f"📊 WinRate казино: {casino_wr}%\n💸 Оборот казино: {player.casino_wagered}\n"
            f"📉 Прибыль казино: {player.casino_profit:+d}\n🔥 Крупнейший выигрыш: {player.biggest_win}\n"
            f"👑 Выиграно джекпотов: {player.jackpot_wins}\n💎 Крупнейший джекпот: {player.biggest_jackpot}"
        )

    def _casino_ready(self, user_id: int) -> str | None:
        left = self.casino_cooldown_seconds - (time.time() - self._casino_cooldowns.get(user_id, 0))
        if left > 0:
            return f"⏳ Подождите ещё {max(1, int(left))} сек."
        self._casino_cooldowns[user_id] = time.time()
        return None

    def _casino_result(self, player: Player, stake: int, payout: int, game: str, details: str) -> str:
        player.balance -= stake
        player.balance += payout
        profit = payout - stake
        player.casino_games += 1
        player.casino_wagered += stake
        player.casino_profit += profit
        jackpot_add = 0
        if profit > 0:
            player.casino_wins += 1
            player.biggest_win = max(player.biggest_win, payout)
        else:
            player.casino_losses += 1
            if profit < 0:
                jackpot_add = self._add_jackpot(-profit, f"Проигрыш в казино: {game}", source_vk_id=player.vk_id,
                                                metadata={"stake": stake, "payout": payout})
        self._save(player)
        self._log(player, f"{profit:+d} — казино: {game}")
        tx = self.db.add_transaction(kind="casino", amount=abs(profit), reason=game,
                                     source_vk_id=player.vk_id if profit < 0 else None,
                                     target_vk_id=player.vk_id if profit > 0 else None,
                                     metadata={"stake": stake, "payout": payout, "details": details, "jackpot": jackpot_add})
        outcome = f"Выигрыш: {payout} тронов" if payout else "Ставка проиграна"
        extra = f"\nВ джекпот: +{jackpot_add}" if jackpot_add else ""
        return f"🎰 {game}\n{details}\n{outcome}{extra}\nБаланс: {player.balance}\nОперация: {tx[:8]}"

    def _win_jackpot(self, player: Player, stake: int) -> str:
        prize = self.jackpot
        player.balance -= stake
        player.balance += prize
        player.casino_games += 1
        player.casino_wins += 1
        player.casino_wagered += stake
        player.casino_profit += prize - stake
        player.biggest_win = max(player.biggest_win, prize)
        player.jackpot_wins += 1
        player.biggest_jackpot = max(player.biggest_jackpot, prize)
        self.jackpot = JACKPOT_START
        self.db.set_state("jackpot", self.jackpot)
        self._save(player)
        self._log(player, f"+{prize - stake} — ДЖЕКПОТ")
        tx = self.db.add_transaction(kind="jackpot_win", amount=prize, reason="Джекпот слотов",
                                     target_vk_id=player.vk_id, metadata={"stake": stake, "reset_to": JACKPOT_START})
        return (f"👑💎 ДЖЕКПОТ! 💎👑\n👑 | 👑 | 👑\n{player.name} получает {prize} тронов!\n"
                f"Баланс: {player.balance}\nНовый джекпот: {self.jackpot}\nОперация: {tx[:8]}")

    def handle(self, *, text: str, user_id: int, user_name: str, message: dict[str, Any], vk: Any) -> str | None:
        self.db.cleanup()
        lower = self._clean(text).casefold()
        player = self.get_or_create_player(user_id, user_name)

        if lower == "[баланс":
            return f"💰 {player.name}\nБаланс: {player.balance} тронов."
        if lower.startswith("[профиль"):
            target_id = self._resolve_target_id(self._clean(text[len("[профиль"):]), message)
            target = player if target_id is None else self.get_or_create_player(target_id, self._get_vk_name(vk, target_id))
            return self._profile(target)
        if lower == "[история":
            return f"📜 История операций {player.name}\n\n" + ("\n".join(player.history[-10:]) or "История пока пуста.")
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
            tx = self.db.add_transaction(kind="salary", amount=amount, reason="Жалование", target_vk_id=user_id)
            return f"💰 Получено жалование: {amount} тронов.\nБаланс: {player.balance}\nОперация: {tx[:8]}"
        if lower in ("[топ", "[богатые", "[балансы"):
            ranked = sorted(self.players.values(), key=lambda x: (-x.balance, x.name.casefold()))
            limit = 50 if lower == "[балансы" else 10
            return "🏆 Богачи Империума\n\n" + "\n".join(f"{i}. {x.name} — {x.balance}" for i, x in enumerate(ranked[:limit], 1))
        if lower == "[топ выигрышей":
            ranked = sorted(self.players.values(), key=lambda x: (-max(x.biggest_win, x.biggest_jackpot), x.name.casefold()))
            ranked = [x for x in ranked if max(x.biggest_win, x.biggest_jackpot) > 0]
            return "🏆 Крупнейшие выигрыши\n\n" + ("\n".join(f"{i}. {x.name} — {max(x.biggest_win, x.biggest_jackpot)}" for i, x in enumerate(ranked[:10], 1)) or "Выигрышей пока нет.")
        if lower == "[статистика":
            total = sum(p.balance for p in self.players.values())
            games = sum(p.casino_games for p in self.players.values())
            wagered = sum(p.casino_wagered for p in self.players.values())
            return (f"📊 Экономика Кубятни\n\nИгроков: {len(self.players)}\nТронов на руках: {total}\n"
                    f"Игр в казино: {games}\nОборот казино: {wagered}\nДжекпот: {self.jackpot}\n"
                    f"Активное событие: {'да' if self.event else 'нет'}")
        if lower == "[джекпот":
            return (f"💰 Общий джекпот\n\nРазмер: {self.jackpot} тронов\n\nПополняется:\n"
                    f"• комиссией {TRANSFER_FEE_PERCENT}% с переводов\n• чистыми проигрышами казино\n"
                    f"• {EVENT_LOSS_JACKPOT_PERCENT}% проигранных ставок\n\nВыигрывается редкой комбинацией в слотах.")

        if lower.startswith("[перевести "):
            tail = self._clean(text[len("[перевести"):])
            target_id = self._resolve_target_id(tail, message)
            amount = self._extract_last_amount(tail)
            if target_id is None or amount is None:
                return "Формат: [перевести @игрок 100"
            if target_id == user_id:
                return "Нельзя переводить троны самому себе."
            if amount <= 0 or amount > player.balance:
                return f"Недостаточно тронов. Ваш баланс: {player.balance}"
            fee = max(1, math.ceil(amount * TRANSFER_FEE_PERCENT / 100))
            received = amount - fee
            if received <= 0:
                return f"Минимальная сумма перевода — {math.ceil(100 / TRANSFER_FEE_PERCENT)} тронов."
            target = self.get_or_create_player(target_id, self._get_vk_name(vk, target_id))
            player.balance -= amount
            target.balance += received
            self._save(player, target)
            self._log(player, f"-{amount} — перевод {target.name}; комиссия {fee}")
            self._log(target, f"+{received} — перевод от {player.name}")
            self._add_jackpot(fee, "Комиссия перевода", actor_vk_id=user_id, source_vk_id=user_id,
                              metadata={"target_vk_id": target_id, "gross": amount})
            tx = self.db.add_transaction(kind="transfer", amount=amount, reason="Перевод игроку", actor_vk_id=user_id,
                                         source_vk_id=user_id, target_vk_id=target_id,
                                         metadata={"fee": fee, "received": received})
            return (f"✅ Перевод выполнен.\nПолучатель: {target.name}\nСписано: {amount}\n"
                    f"Комиссия в джекпот: {fee}\nПолучено: {received}\nВаш баланс: {player.balance}\nОперация: {tx[:8]}")

        for prefix, game in (("[монетка ", "Монетка"), ("[кости ", "Кости"), ("[слоты ", "Слоты")):
            if lower.startswith(prefix):
                cooldown = self._casino_ready(user_id)
                if cooldown:
                    return cooldown
                stake = self._extract_last_amount(lower)
                if stake is None:
                    return f"Формат: {prefix}{self.casino_min_bet}"
                if stake < self.casino_min_bet or stake > self.casino_max_bet:
                    return f"Ставка должна быть от {self.casino_min_bet} до {self.casino_max_bet}."
                if stake > player.balance:
                    return f"Недостаточно тронов. Ваш баланс: {player.balance}"
                if game == "Монетка":
                    win = random.random() < 0.48
                    side = random.choice(("орёл", "решка"))
                    return self._casino_result(player, stake, stake * 2 if win else 0, game, f"Выпало: {side}")
                if game == "Кости":
                    user_roll, bot_roll = random.randint(1, 6), random.randint(1, 6)
                    payout = stake * 2 if user_roll > bot_roll else stake if user_roll == bot_roll else 0
                    return self._casino_result(player, stake, payout, game, f"Вы: {user_roll} | Бот: {bot_roll}")
                if random.randint(1, SLOT_JACKPOT_CHANCE) == 1:
                    return self._win_jackpot(player, stake)
                symbols = ["🍒", "🍋", "🔔", "💀", "⚙"]
                reels = [random.choice(symbols) for _ in range(3)]
                payout = stake * 5 if len(set(reels)) == 1 else stake * 2 if len(set(reels)) == 2 else 0
                return self._casino_result(player, stake, payout, game, " | ".join(reels))

        if lower in ("[банк", "[ставки"):
            if self.event is None:
                return "📭 Активного события нет."
            lines = []
            for i, outcome in enumerate(self.event.outcomes, 1):
                bets = [b for b in self.event.bets.values() if b.outcome == outcome]
                lines.append(f"{i}. {outcome} — {len(bets)} ставок, {sum(b.amount for b in bets)} тронов")
            return f"🎲 {self.event.title}\nСтавки: {'открыты' if self.event.bets_open else 'закрыты'}\nБанк: {self.event.bank}\n\n" + "\n".join(lines)
        if lower.startswith("[ставка "):
            if self.event is None:
                return "📭 Активного события нет."
            if not self.event.bets_open:
                return "🔒 Приём ставок закрыт."
            if user_id in self.event.bets:
                return "⚠ Вы уже сделали ставку."
            tail = self._clean(text[len("[ставка"):])
            parts = tail.split(maxsplit=1)
            if len(parts) != 2 or not parts[0].isdigit():
                return "Формат: [ставка 25 Победа"
            amount = int(parts[0])
            outcome = self._find_outcome(self.event, parts[1])
            if amount <= 0 or amount > player.balance:
                return f"Недостаточно тронов. Ваш баланс: {player.balance}"
            if outcome is None:
                return "Не удалось определить исход."
            player.balance -= amount
            player.bets_count += 1
            player.total_bet += amount
            self.event.bets[user_id] = Bet(user_id, outcome, amount)
            self._save(player)
            self._log(player, f"-{amount} — ставка: {outcome}")
            self.db.save_event(self.event)
            self.db.add_transaction(kind="event_bet", amount=amount, reason=outcome, source_vk_id=user_id,
                                    metadata={"event": self.event.title})
            return f"✅ Ставка принята.\nИсход: {outcome}\nСумма: {amount}\nОстаток: {player.balance}"
        if lower.startswith("[событие "):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            if self.event:
                return "⚠ Сначала завершите или отмените текущее событие."
            chunks = [x.strip() for x in self._clean(text[len("[событие"):]).split("|") if x.strip()]
            if len(chunks) < 3:
                return "Формат: [событие Название | Победа | Поражение"
            outcomes = list(dict.fromkeys(chunks[1:]))
            self.event = BettingEvent(chunks[0], outcomes)
            self.db.save_event(self.event)
            return f"📢 Создано событие:\n{chunks[0]}\n\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(outcomes, 1))
        if lower == "[закрыть ставки":
            denied = self._admin_required(user_id)
            if denied:
                return denied
            if not self.event:
                return "Активного события нет."
            self.event.bets_open = False
            self.db.save_event(self.event)
            return f"🔒 Ставки закрыты. Банк: {self.event.bank}"
        if lower.startswith("[итог "):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            if not self.event:
                return "Активного события нет."
            winning = self._find_outcome(self.event, self._clean(text[len("[итог"):]))
            if winning is None:
                return "Не удалось определить победивший исход."
            event = self.event
            winners = [b for b in event.bets.values() if b.outcome == winning]
            losers = [b for b in event.bets.values() if b.outcome != winning]
            losing_total = sum(b.amount for b in losers)
            jackpot_cut = math.ceil(losing_total * EVENT_LOSS_JACKPOT_PERCENT / 100) if losing_total else 0
            payout_bank = max(0, event.bank - jackpot_cut)
            payouts: dict[int, int] = {}
            if winners:
                total_winning_stake = sum(b.amount for b in winners)
                payouts = {b.user_id: payout_bank * b.amount // total_winning_stake for b in winners}
                remainder = payout_bank - sum(payouts.values())
                for bet in sorted(winners, key=lambda x: (-x.amount, x.user_id)):
                    if remainder <= 0:
                        break
                    payouts[bet.user_id] += 1
                    remainder -= 1
            else:
                jackpot_cut = event.bank
                payout_bank = 0
            if jackpot_cut:
                self._add_jackpot(jackpot_cut, f"Проигранные ставки: {event.title}",
                                  metadata={"winning": winning, "event_bank": event.bank})
            lines = []
            for bet in event.bets.values():
                current = self.players.get(bet.user_id)
                if not current:
                    continue
                if bet.user_id in payouts:
                    pay = payouts[bet.user_id]
                    current.balance += pay
                    current.wins += 1
                    current.total_won += pay
                    current.biggest_win = max(current.biggest_win, pay)
                    self._log(current, f"+{pay} — выигрыш: {winning}")
                    lines.append(f"{current.name} — +{pay}")
                else:
                    current.losses += 1
                    current.total_lost += bet.amount
                self._save(current)
            self.event = None
            self.db.save_event(None)
            return (f"🏁 Итог: {winning}\nБанк: {event.bank}\nВ джекпот: {jackpot_cut}\n\n" +
                    ("\n".join(lines) if lines else "Победителей нет. Весь банк ушёл в джекпот."))
        if lower in ("[отмена события", "[сброс ставок"):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            if not self.event:
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
            return f"↩ Событие «{title}» отменено. Возвращено: {refunded}"

        if lower.startswith("[джекпот +"):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            amount = self._extract_last_amount(lower)
            if not amount:
                return "Формат: [джекпот +1000"
            self._add_jackpot(amount, "Административное пополнение", actor_vk_id=user_id)
            return f"✅ Джекпот пополнен на {amount}. Текущий размер: {self.jackpot}"

        for command, mode in (("[выдать ", "give"), ("[забрать ", "take"), ("[установить ", "set")):
            if lower.startswith(command):
                denied = self._admin_required(user_id)
                if denied:
                    return denied
                tail = self._clean(text[len(command.rstrip()):])
                target_id = self._resolve_target_id(tail, message)
                amount = self._extract_last_amount(tail)
                if target_id is None or amount is None:
                    return "Укажите игрока и сумму."
                target = self.get_or_create_player(target_id, self._get_vk_name(vk, target_id))
                old = target.balance
                target.balance = old + amount if mode == "give" else max(0, old - amount) if mode == "take" else max(0, amount)
                delta = target.balance - old
                self._save(target)
                self._log(target, f"{delta:+d} — изменение администратором")
                tx = self.db.add_transaction(kind=f"admin_{mode}", amount=abs(delta), reason="Административное изменение",
                                             actor_vk_id=user_id, source_vk_id=target_id if delta < 0 else None,
                                             target_vk_id=target_id if delta > 0 else None,
                                             metadata={"old": old, "new": target.balance})
                return f"✅ Баланс {target.name}: {target.balance}. Операция: {tx[:8]}"
        if lower.startswith("[операции") or lower.startswith("[история игрока"):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            target_id = self._resolve_target_id(text, message) if lower.startswith("[история игрока") else None
            rows = self.db.get_transactions(target_id, 20)
            if not rows:
                return "Операций не найдено."
            lines = [f"{str(row['id'])[:8]} | {row['kind']} | {row['amount']} | {row['reason']}" for row in rows]
            return "📜 Журнал операций\n\n" + "\n".join(lines)
        if lower.startswith("[операция "):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            match = TX_RE.search(text)
            if not match:
                return "Укажите полный ID операции."
            row = self.db.get_transaction(match.group(1))
            return "Операция не найдена." if not row else json.dumps(dict(row), ensure_ascii=False, default=str, indent=2)
        if lower.startswith("[откатить "):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            match = TX_RE.search(text)
            if not match:
                return "Укажите полный ID операции."
            row = self.db.get_transaction(match.group(1))
            if not row:
                return "Операция не найдена."
            if row.get("reversed_by"):
                return "Эта операция уже отменена."
            amount = int(row["amount"])
            source = row.get("source_vk_id")
            target = row.get("target_vk_id")
            source_p = self.players.get(int(source)) if source else None
            target_p = self.players.get(int(target)) if target else None
            if target_p and target_p.balance < amount:
                return "Откат невозможен: у получателя недостаточно тронов."
            if source_p:
                source_p.balance += amount
            if target_p:
                target_p.balance -= amount
            self._save(*(p for p in (source_p, target_p) if p))
            reverse = self.db.add_transaction(kind="reversal", amount=amount, reason=f"Откат {row['id']}",
                                              actor_vk_id=user_id, source_vk_id=target, target_vk_id=source)
            self.db.mark_reversed(str(row["id"]), reverse)
            return f"↩ Операция отменена. Новый ID: {reverse}"
        if lower == "[экспорт экономики":
            denied = self._admin_required(user_id)
            if denied:
                return denied
            snapshot = self.db.export_snapshot()
            data = json.dumps(snapshot, ensure_ascii=False, default=str)
            return f"💾 Экспорт готов. Игроков: {len(snapshot.get('players', []))}, операций: {len(snapshot.get('transactions', []))}, размер: {len(data)} байт."
        if lower in ("[экономика", "[диагностика базы"):
            denied = self._admin_required(user_id)
            if denied:
                return denied
            total = sum(p.balance for p in self.players.values())
            event = "нет" if not self.event else f"{self.event.title}, банк {self.event.bank}"
            return (f"⚙ Экономика Кубятни\nИгроков: {len(self.players)}\nТронов: {total}\nДжекпот: {self.jackpot}\n"
                    f"БД: {'подключена' if self.db.enabled else 'не подключена'}\nСхема: {self.db.schema_version}\nСобытие: {event}")
        if lower == "[очистить базу":
            denied = self._admin_required(user_id)
            if denied:
                return denied
            return f"🧹 Удалено старых записей: {self.db.cleanup(force=True)}."
        if lower == "[сброс тронов":
            denied = self._admin_required(user_id)
            if denied:
                return denied
            self.players.clear()
            self.event = None
            self.jackpot = JACKPOT_START
            self.db.reset_all()
            return "♻ Экономика полностью сброшена. Джекпот установлен на 500."
        return None

    @staticmethod
    def _get_vk_name(vk: Any, user_id: int) -> str:
        try:
            user = vk.users.get(user_ids=user_id)[0]
            return f"[id{user_id}|{user['first_name']}]"
        except Exception:
            return f"[id{user_id}|Игрок]"
