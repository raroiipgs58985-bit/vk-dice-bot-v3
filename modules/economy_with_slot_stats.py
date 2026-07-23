from __future__ import annotations

from typing import Any

from .economy import (
    EVENT_LOSS_JACKPOT_PERCENT,
    JACKPOT_START,
    SLOT_JACKPOT_CHANCE,
    TRANSFER_FEE_PERCENT,
    EconomyManager as BaseEconomyManager,
)


SLOT_SPINS_STATE_KEY = "slot_spins_total"


class EconomyManager(BaseEconomyManager):
    """Экономика со счётчиком вращений слотов, хранящимся в общей БД."""

    def _get_slot_spins(self) -> int:
        raw_value = self.db.get_state(SLOT_SPINS_STATE_KEY, 0)
        try:
            return max(0, int(raw_value))
        except (TypeError, ValueError):
            return 0

    def _record_slot_spin(self) -> int:
        total = self._get_slot_spins() + 1
        self.db.set_state(SLOT_SPINS_STATE_KEY, total)
        return total

    def _jackpot_statistics(self) -> str:
        spins = self._get_slot_spins()
        jackpot_wins = sum(player.jackpot_wins for player in self.players.values())
        chance_percent = 100 / SLOT_JACKPOT_CHANCE

        return (
            f"💰 Общий джекпот\n\n"
            f"Размер: {self.jackpot} тронов\n"
            f"Комбинация: 👑 | 👑 | 👑\n"
            f"Шанс: 1 из {SLOT_JACKPOT_CHANCE:,} ({chance_percent:.3f}%)\n"
            f"Вращений слотов: {spins}\n"
            f"Выиграно джекпотов: {jackpot_wins}\n\n"
            f"Пополняется:\n"
            f"• комиссией {TRANSFER_FEE_PERCENT}% с переводов\n"
            f"• чистыми проигрышами казино\n"
            f"• {EVENT_LOSS_JACKPOT_PERCENT}% проигранных ставок\n\n"
            f"Счётчик вращений ведётся с версии, в которой он был добавлен."
        ).replace(f"{SLOT_JACKPOT_CHANCE:,}", f"{SLOT_JACKPOT_CHANCE:,}".replace(",", " "))

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

        response = super().handle(
            text=text,
            user_id=user_id,
            user_name=user_name,
            message=message,
            vk=vk,
        )

        if lower.startswith("[слоты ") and response:
            successful_spin = response.startswith("🎰 Слоты") or response.startswith("👑💎 ДЖЕКПОТ")
            if successful_spin:
                self._record_slot_spin()

        return response
