from __future__ import annotations

import random
from typing import Any

from .economy import (
    EVENT_LOSS_JACKPOT_PERCENT,
    JACKPOT_START,
    SLOT_JACKPOT_CHANCE,
    TRANSFER_FEE_PERCENT,
    EconomyManager as BaseEconomyManager,
)


SLOT_SPINS_STATE_KEY = "slot_spins_total"
SLOT_LOSSES_STATE_KEY = "slot_losses_since_jackpot"
BASE_JACKPOT_CHANCE_PERCENT = 100 / SLOT_JACKPOT_CHANCE
JACKPOT_CHANCE_GAIN_PER_LOSS_PERCENT = 0.0001


class EconomyManager(BaseEconomyManager):
    """Экономика со статистикой слотов и растущим шансом джекпота."""

    def _get_state_counter(self, key: str) -> int:
        raw_value = self.db.get_state(key, 0)
        try:
            return max(0, int(raw_value))
        except (TypeError, ValueError):
            return 0

    def _get_slot_spins(self) -> int:
        return self._get_state_counter(SLOT_SPINS_STATE_KEY)

    def _get_slot_losses(self) -> int:
        return self._get_state_counter(SLOT_LOSSES_STATE_KEY)

    def _record_slot_spin(self) -> int:
        total = self._get_slot_spins() + 1
        self.db.set_state(SLOT_SPINS_STATE_KEY, total)
        return total

    def _record_slot_loss(self) -> int:
        losses = self._get_slot_losses() + 1
        self.db.set_state(SLOT_LOSSES_STATE_KEY, losses)
        return losses

    def _reset_slot_losses(self) -> None:
        self.db.set_state(SLOT_LOSSES_STATE_KEY, 0)

    def _current_jackpot_chance_percent(self) -> float:
        chance = BASE_JACKPOT_CHANCE_PERCENT + (
            self._get_slot_losses() * JACKPOT_CHANCE_GAIN_PER_LOSS_PERCENT
        )
        return min(100.0, chance)

    def _jackpot_statistics(self) -> str:
        spins = self._get_slot_spins()
        losses = self._get_slot_losses()
        jackpot_wins = sum(player.jackpot_wins for player in self.players.values())
        chance_percent = self._current_jackpot_chance_percent()
        chance_one_in = max(1, round(100 / chance_percent))
        bonus_percent = losses * JACKPOT_CHANCE_GAIN_PER_LOSS_PERCENT

        return (
            f"💰 Общий джекпот\n\n"
            f"Размер: {self.jackpot} тронов\n"
            f"Комбинация: 👑 | 👑 | 👑\n"
            f"Текущий шанс: {chance_percent:.4f}% (примерно 1 из {chance_one_in:,})\n"
            f"Базовый шанс: {BASE_JACKPOT_CHANCE_PERCENT:.3f}% (1 из {SLOT_JACKPOT_CHANCE:,})\n"
            f"Бонус за проигрыши: +{bonus_percent:.4f}%\n"
            f"Проигрышей с последнего джекпота: {losses}\n"
            f"Всего вращений слотов: {spins}\n"
            f"Выиграно джекпотов: {jackpot_wins}\n\n"
            f"Каждый проигрыш в слотах повышает шанс на "
            f"{JACKPOT_CHANCE_GAIN_PER_LOSS_PERCENT:.4f}%. После джекпота бонус сбрасывается.\n\n"
            f"Пополняется:\n"
            f"• комиссией {TRANSFER_FEE_PERCENT}% с переводов\n"
            f"• чистыми проигрышами казино\n"
            f"• {EVENT_LOSS_JACKPOT_PERCENT}% проигранных ставок"
        ).replace(",", " ")

    def _win_jackpot(self, player, stake: int) -> str:
        self._reset_slot_losses()
        return super()._win_jackpot(player, stake)

    def _handle_slots(self, *, lower: str, user_id: int, user_name: str) -> str:
        self.db.cleanup()
        player = self.get_or_create_player(user_id, user_name)

        cooldown = self._casino_ready(user_id)
        if cooldown:
            return cooldown

        stake = self._extract_last_amount(lower)
        if stake is None:
            return f"Формат: [слоты {self.casino_min_bet}"
        if stake < self.casino_min_bet or stake > self.casino_max_bet:
            return f"Ставка должна быть от {self.casino_min_bet} до {self.casino_max_bet}."
        if stake > player.balance:
            return f"Недостаточно тронов. Ваш баланс: {player.balance}"

        self._record_slot_spin()
        chance_percent = self._current_jackpot_chance_percent()
        if random.random() < chance_percent / 100:
            return self._win_jackpot(player, stake)

        symbols = ["🍒", "🍋", "🔔", "💀", "⚙"]
        reels = [random.choice(symbols) for _ in range(3)]
        payout = stake * 5 if len(set(reels)) == 1 else stake * 2 if len(set(reels)) == 2 else 0

        if payout == 0:
            self._record_slot_loss()

        return self._casino_result(player, stake, payout, "Слоты", " | ".join(reels))

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

        if lower == "[джекпот":
            self.db.cleanup()
            self.get_or_create_player(user_id, user_name)
            return self._jackpot_statistics()

        if lower.startswith("[слоты "):
            return self._handle_slots(lower=lower, user_id=user_id, user_name=user_name)

        return super().handle(
            text=text,
            user_id=user_id,
            user_name=user_name,
            message=message,
            vk=vk,
        )
