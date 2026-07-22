import random
import re
from dataclasses import dataclass
from typing import Optional

from config import MAX_DICE_COUNT, MAX_DICE_SIDES


DICE_PATTERN = re.compile(
    r"(\d*)к(\d+)([+-]\d+)?(?:\s*\((\d+)\))?",
    re.IGNORECASE,
)
MAX_THRESHOLD = 200


@dataclass(frozen=True)
class DiceResult:
    rolls: list[int]
    total: int
    modifier: int
    dice: str
    sides: int
    comment: str
    threshold: Optional[int] = None
    outcome: Optional[str] = None
    degrees: Optional[int] = None
    roll_outcomes: tuple[str, ...] = ()
    roll_degrees: tuple[int, ...] = ()
    critical_successes: int = 0
    critical_failures: int = 0

    @property
    def successes(self) -> int:
        return sum(1 for value in self.roll_outcomes if value == "success")

    @property
    def failures(self) -> int:
        return sum(1 for value in self.roll_outcomes if value == "failure")


def _evaluate_roll(roll_value: int, threshold: int, sides: int) -> tuple[str, int, str | None]:
    critical = None

    # Критические результаты существуют только на к100.
    if sides == 100 and 1 <= roll_value <= 5:
        outcome = "success"
        critical = "critical_success"
    elif sides == 100 and 96 <= roll_value <= 100:
        outcome = "failure"
        critical = "critical_failure"
    else:
        outcome = "success" if roll_value <= threshold else "failure"

    if outcome == "success":
        degrees = max(1, ((threshold - roll_value) // 10) + 1)
    else:
        degrees = max(1, ((roll_value - threshold) // 10) + 1)

    return outcome, degrees, critical


def roll(command: str) -> Optional[DiceResult | str]:
    command = command.strip()

    if not command.startswith("["):
        return None

    command = command[1:].strip().lower().replace("k", "к")
    comment = ""

    if "#" in command:
        command, comment = command.split("#", 1)
        command = command.strip()
        comment = comment.strip()

    match = DICE_PATTERN.fullmatch(command)
    if not match:
        return None

    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    modifier = int(match.group(3) or 0)
    threshold = int(match.group(4)) if match.group(4) else None

    if count < 1:
        return "⛔ Количество кубиков должно быть не меньше 1."

    if count > MAX_DICE_COUNT:
        return f"⛔ Слишком много кубиков. Максимум: {MAX_DICE_COUNT}."

    if sides < 2:
        return "⛔ У кубика должно быть минимум 2 грани."

    if sides > MAX_DICE_SIDES:
        return f"⛔ Слишком много граней. Максимум: {MAX_DICE_SIDES}."

    if threshold is not None:
        if modifier != 0:
            return "⛔ Для проверки порога модификатор +/− пока не используется."
        if threshold < 1 or threshold > MAX_THRESHOLD:
            return f"⛔ Порог должен быть от 1 до {MAX_THRESHOLD}."

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier

    dice_name = f"{count}к{sides}"
    if modifier > 0:
        dice_name += f"+{modifier}"
    elif modifier < 0:
        dice_name += str(modifier)

    outcome = None
    degrees = None
    roll_outcomes: list[str] = []
    roll_degrees: list[int] = []
    critical_successes = 0
    critical_failures = 0

    if threshold is not None:
        dice_name += f" ({threshold})"
        for value in rolls:
            roll_outcome, roll_degree, critical = _evaluate_roll(value, threshold, sides)
            roll_outcomes.append(roll_outcome)
            roll_degrees.append(roll_degree)
            if critical == "critical_success":
                critical_successes += 1
            elif critical == "critical_failure":
                critical_failures += 1

        if count == 1:
            outcome = roll_outcomes[0]
            degrees = roll_degrees[0]

    return DiceResult(
        rolls=rolls,
        total=total,
        modifier=modifier,
        dice=dice_name,
        sides=sides,
        comment=comment,
        threshold=threshold,
        outcome=outcome,
        degrees=degrees,
        roll_outcomes=tuple(roll_outcomes),
        roll_degrees=tuple(roll_degrees),
        critical_successes=critical_successes,
        critical_failures=critical_failures,
    )


def _single_outcome_text(result: DiceResult) -> list[str]:
    if result.threshold is None or result.outcome is None or result.degrees is None:
        return []

    lines: list[str] = []
    value = result.rolls[0]

    if result.sides == 100 and 1 <= value <= 5:
        lines.append("💥 Критический успех!")
    elif result.sides == 100 and 96 <= value <= 100:
        lines.append("☠ Критический промах!")

    if result.outcome == "success":
        lines.append(f"✅ Успехов: {result.degrees}")
    else:
        lines.append(f"❌ Провалов: {result.degrees}")

    return lines


def _roll_marker(result: DiceResult, index: int) -> str:
    value = result.rolls[index]
    outcome = result.roll_outcomes[index]

    if result.sides == 100 and 1 <= value <= 5:
        return "💥"
    if result.sides == 100 and 96 <= value <= 100:
        return "☠"
    return "✅" if outcome == "success" else "❌"


def format_single_roll(player: str, result: DiceResult, quote: str) -> str:
    lines = [
        "🎲 КУБЯТНЯ 🎲",
        "━━━━━━━━━━━━━━━",
        "",
        f"👤 Игрок: {player}",
        f"🎲 Бросок: {result.dice}",
    ]

    if result.comment:
        lines.append(f"💬 {result.comment}")

    lines.extend([
        "",
        f"🎯 Выпало: {', '.join(map(str, result.rolls))}",
    ])

    if result.modifier > 0:
        lines.append(f"➕ Бонус: +{result.modifier}")
    elif result.modifier < 0:
        lines.append(f"➖ Штраф: {result.modifier}")

    if result.threshold is None:
        lines.append(f"🏆 Итог: {result.total}")
    else:
        lines.append(f"🎚 Порог: {result.threshold}")
        if len(result.rolls) == 1:
            lines.extend(_single_outcome_text(result))
        else:
            lines.append("")
            for index, value in enumerate(result.rolls):
                lines.append(f"{index + 1}) {value} {_roll_marker(result, index)}")
            lines.extend([
                "━━━━━━━━━━━━━━━",
                f"✅ Успешных бросков: {result.successes}",
                f"❌ Провальных бросков: {result.failures}",
            ])
            if result.sides == 100:
                lines.append(f"💥 Критических успехов: {result.critical_successes}")
                lines.append(f"☠ Критических промахов: {result.critical_failures}")

    lines.extend([
        "",
        "📜 Цитата дня:",
        f"«{quote}»",
    ])

    return "\n".join(lines)


def format_multiple_rolls(
    player: str,
    results: list[DiceResult | str],
    quote: str,
) -> str:
    lines = [
        "🎲 КУБЯТНЯ 🎲",
        "━━━━━━━━━━━━━━━",
        f"👤 Игрок: {player}",
        "",
    ]

    for number, result in enumerate(results, start=1):
        if isinstance(result, str):
            lines.append(f"{number}. {result}")
            continue

        rolls_text = ", ".join(map(str, result.rolls))
        comment_text = f" — {result.comment}" if result.comment else ""

        if result.threshold is not None:
            if len(result.rolls) == 1:
                outcome_text = " | ".join(_single_outcome_text(result))
                lines.append(
                    f"{number}. {result.dice}: {rolls_text} — {outcome_text}{comment_text}"
                )
            else:
                critical_text = ""
                if result.sides == 100:
                    critical_text = (
                        f", крит. успехов: {result.critical_successes}, "
                        f"крит. промахов: {result.critical_failures}"
                    )
                lines.append(
                    f"{number}. {result.dice}: {rolls_text} — "
                    f"успехов: {result.successes}, провалов: {result.failures}"
                    f"{critical_text}{comment_text}"
                )
        else:
            lines.append(
                f"{number}. {result.dice}: {rolls_text} → {result.total}{comment_text}"
            )

    lines.extend([
        "",
        "📜 Цитата дня:",
        f"«{quote}»",
    ])

    return "\n".join(lines)
