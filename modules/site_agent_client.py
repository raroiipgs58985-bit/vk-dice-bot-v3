from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

import requests


@dataclass(frozen=True)
class AgentRequest:
    question: str
    deep: bool


class SiteAgentClient:
    """HTTP client for the separate Render site-research service."""

    def __init__(
        self,
        *,
        base_url: str,
        secret: str,
        connect_timeout_seconds: int = 90,
        read_timeout_seconds: int = 600,
        max_parallel_requests: int = 2,
    ) -> None:
        self.base_url = self._normalize_base_url(base_url)
        self.secret = secret.strip()
        self.connect_timeout_seconds = max(10, int(connect_timeout_seconds))
        self.read_timeout_seconds = max(60, int(read_timeout_seconds))
        self._slots = threading.BoundedSemaphore(max(1, int(max_parallel_requests)))

    @classmethod
    def from_env(cls) -> "SiteAgentClient":
        return cls(
            base_url=os.environ.get("SITE_AGENT_URL", ""),
            secret=os.environ.get("SITE_AGENT_SECRET", ""),
            connect_timeout_seconds=_env_int("SITE_AGENT_CONNECT_TIMEOUT", 90, 10, 180),
            read_timeout_seconds=_env_int("SITE_AGENT_READ_TIMEOUT", 600, 60, 900),
            max_parallel_requests=_env_int("SITE_AGENT_PARALLEL_REQUESTS", 2, 1, 5),
        )

    @property
    def configured(self) -> bool:
        parsed = urlsplit(self.base_url)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
            and len(self.secret) >= 16
        )

    def status_text(self) -> str:
        if not self.configured:
            return (
                "🤖 АГЕНТ САЙТА НЕ НАСТРОЕН\n"
                "На Render основного бота добавьте SITE_AGENT_URL и "
                "SITE_AGENT_SECRET."
            )
        return (
            "🤖 АГЕНТ САЙТА НАСТРОЕН\n"
            f"Сервис: {self.base_url}\n"
            "Обычный поиск: [найди ваш вопрос\n"
            "Глубокий поиск: [глубокий поиск ваш вопрос"
        )

    def handle(
        self,
        *,
        text: str,
        on_result: Callable[[str], None],
    ) -> str | None:
        parsed = self.parse_command(text)
        if parsed is None:
            return None
        if parsed.question == "__status__":
            return self.status_text()
        if not parsed.question:
            return (
                "Использование:\n"
                "[найди ваш вопрос\n"
                "[глубокий поиск ваш вопрос"
            )
        if len(parsed.question) > 1200:
            return "Вопрос слишком длинный. Сократите его до 1200 символов."
        if not self.configured:
            return self.status_text()
        if not self._slots.acquire(blocking=False):
            return "⏳ Уже выполняется слишком много запросов к агенту. Повторите позже."

        worker = threading.Thread(
            target=self._worker,
            kwargs={
                "request": parsed,
                "on_result": on_result,
            },
            daemon=True,
            name="site-agent-request",
        )
        worker.start()
        mode = "глубокий поиск" if parsed.deep else "поиск"
        return (
            f"🔎 Запускаю {mode} по сайту.\n"
            "Если отдельный Render спит, его пробуждение может занять около минуты. "
            "Кубики и остальные команды продолжат работать."
        )

    @staticmethod
    def parse_command(text: str) -> AgentRequest | None:
        stripped = text.strip().rstrip("]").strip()
        lowered = stripped.casefold()
        if lowered in {"[агент статус", "[статус агента", "[сайт"}:
            return AgentRequest(question="__status__", deep=False)

        prefixes: tuple[tuple[str, bool], ...] = (
            ("[глубокий поиск", True),
            ("[глубокий", True),
            ("[найди", False),
            ("[агент", False),
        )
        for prefix, deep in prefixes:
            if lowered == prefix:
                return AgentRequest(question="", deep=deep)
            if lowered.startswith(prefix + " "):
                question = stripped[len(prefix):].strip()
                return AgentRequest(question=question, deep=deep)
        return None

    def _worker(self, *, request: AgentRequest, on_result: Callable[[str], None]) -> None:
        try:
            payload = self._ask(request)
            for part in self._format_response(payload):
                on_result(part)
        except Exception as exc:
            on_result(self._format_error(exc))
        finally:
            self._slots.release()

    def _ask(self, request: AgentRequest) -> dict:
        url = self.base_url.rstrip("/") + "/ask"
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.secret}",
                        "Content-Type": "application/json",
                        "User-Agent": "KubyatnyaVKBot/4.1",
                    },
                    json={"question": request.question, "deep": request.deep},
                    timeout=(self.connect_timeout_seconds, self.read_timeout_seconds),
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(8 + attempt * 7)
                    continue
                raise RuntimeError(f"сервис агента недоступен: {exc}") from exc

            if response.status_code in {502, 503, 504} and attempt < 2:
                time.sleep(10 + attempt * 10)
                continue
            if response.status_code == 401:
                raise RuntimeError("SITE_AGENT_SECRET не совпадает на двух Render-сервисах")
            if response.status_code == 429:
                detail = self._extract_error(response)
                raise RuntimeError(detail or "агент занят или достигнут лимит запросов")
            if response.status_code >= 400:
                detail = self._extract_error(response)
                raise RuntimeError(
                    detail or f"сервис агента вернул HTTP {response.status_code}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError("сервис агента вернул не JSON") from exc
            if not isinstance(payload, dict) or not payload.get("ok"):
                raise RuntimeError(str(payload.get("details") or payload.get("error") or "неизвестная ошибка агента"))
            return payload

        if last_error:
            raise RuntimeError(str(last_error))
        raise RuntimeError("не удалось получить ответ от агента")

    @staticmethod
    def _extract_error(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:400].strip()
        if not isinstance(payload, dict):
            return ""
        details = payload.get("details")
        if isinstance(details, list):
            return "; ".join(str(item) for item in details)[:500]
        return str(details or payload.get("error") or "")[:500]

    @staticmethod
    def _format_response(payload: dict) -> list[str]:
        answer = str(payload.get("answer", "")).strip()
        confidence = {
            "high": "высокая",
            "medium": "средняя",
            "low": "низкая",
        }.get(str(payload.get("confidence", "low")).casefold(), "низкая")

        lines = [
            "🤖 РЕЗУЛЬТАТ ПОИСКА",
            "━━━━━━━━━━━━━━━",
            answer or "Агент не вернул текст ответа.",
        ]
        sources = payload.get("sources", [])
        if isinstance(sources, list) and sources:
            lines.extend(["", "Источники:"])
            for number, source in enumerate(sources[:8], start=1):
                if not isinstance(source, dict):
                    continue
                title = str(source.get("title", "Источник")).strip()
                url = str(source.get("url", "")).strip()
                lines.append(f"{number}. {title}\n{url}")

        pages = int(payload.get("pages_scanned", 0) or 0)
        discovered = int(payload.get("urls_discovered", 0) or 0)
        elapsed = float(payload.get("elapsed_seconds", 0.0) or 0.0)
        lines.extend(
            [
                "",
                f"Уверенность: {confidence}.",
                f"Прочитано страниц: {pages}; обнаружено адресов: {discovered}.",
                f"Время работы агента: {elapsed:.1f} сек.",
            ]
        )
        return _split_vk_message("\n".join(lines), max_length=3500)

    @staticmethod
    def _format_error(error: Exception) -> str:
        text = str(error).strip() or type(error).__name__
        return (
            "❌ Агент не смог завершить поиск.\n"
            f"Причина: {text[:700]}"
        )

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        try:
            parsed = urlsplit(value)
        except ValueError:
            return value
        path = parsed.path.rstrip("/")
        return urlunsplit((parsed.scheme.casefold(), parsed.netloc, path, "", ""))


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _split_vk_message(text: str, *, max_length: int) -> list[str]:
    if len(text) <= max_length:
        return [text]
    parts: list[str] = []
    remaining = text
    while len(remaining) > max_length:
        split_at = remaining.rfind("\n\n", 0, max_length)
        if split_at < max_length // 2:
            split_at = remaining.rfind("\n", 0, max_length)
        if split_at < max_length // 2:
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at <= 0:
            split_at = max_length
        parts.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts
