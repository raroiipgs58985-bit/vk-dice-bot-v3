import random
import re
from dataclasses import dataclass
from typing import Optional

from config import MAX_DICE_COUNT, MAX_DICE_SIDES


DICE_PATTERN = re.compile(
    r"(\d*)к(\d+)([+-]\d+)?(?:\s*\((\d+)\))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DiceResult:
    rolls: list[int]
    total: int
    modifier: int
    dice: str
    comment: str
    threshold: Optional[int] = None
    outcome: Optional[str] = None
    degrees: Optional[int] = None


def _calculate_degrees(roll_value: int, threshold: int) -> tuple[str, int]:
    if roll_value <= threshold:
        degrees = ((threshold - roll_value) // 10) + 1
        return "success", degrees

    degrees = ((roll_value - threshold) // 10) + 1
    return "failure", degrees


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
        if sides != 100:
            return "⛔ Порог в скобках поддерживается только для броска к100."

        if count != 1:
            return "⛔ Проверка порога поддерживается только для одного кубика к100."

        if modifier != 0:
            return "⛔ Для проверки порога модификатор +/− пока не используется."

        if threshold < 1 or threshold > 100:
            return "⛔ Порог должен быть от 1 до 100."

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier

    dice_name = f"{count}к{sides}"
    if modifier > 0:
        dice_name += f"+{modifier}"
    elif modifier < 0:
        dice_name += str(modifier)

    outcome = None
    degrees = None

    if threshold is not None:
        dice_name += f" ({threshold})"
        outcome, degrees = _calculate_degrees(rolls[0], threshold)

    return DiceResult(
        rolls=rolls,
        total=total,
        modifier=modifier,
        dice=dice_name,
        comment=comment,
        threshold=threshold,
        outcome=outcome,
        degrees=degrees,
    )


def _outcome_text(result: DiceResult) -> Optional[str]:
    if result.threshold is None or result.outcome is None or result.degrees is None:
        return None

    if result.outcome == "success":
        return f"✅ Успехов: {result.degrees}"

    return f"❌ Провалов: {result.degrees}"


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
        outcome_text = _outcome_text(result)
        if outcome_text:
            lines.append(outcome_text)

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
            outcome_text = _outcome_text(result) or ""
            lines.append(
                f"{number}. {result.dice}: {rolls_text} — {outcome_text}{comment_text}"
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
