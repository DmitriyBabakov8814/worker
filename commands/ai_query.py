"""
commands/ai_query.py  –  AI-команда (интеграция с Ollama через AIEngine)

Перехватывает запросы, которые явно адресованы AI,
а также служит fallback когда ни одна другая команда не подошла.

Singleton AIEngine создаётся один раз при первом вызове,
чтобы не тратить память если AI не используется.
"""

import logging
from typing import Optional

from core.command_dispatcher import BaseCommand
from core.ai_config          import AI_PREFIXES

logger = logging.getLogger("worker.commands.ai_query")

# Singleton — один экземпляр на всё приложение
_engine: Optional["AIEngine"] = None  # type: ignore[name-defined]


def _get_engine():
    global _engine
    if _engine is None:
        from core.ai_engine import AIEngine
        _engine = AIEngine()
        logger.info("AIEngine (singleton) создан")
    return _engine


class AIQueryCommand(BaseCommand):
    """
    Команда-обёртка для AI.

    matches() → True если текст начинается с AI_PREFIXES.
    Используется как второй-последний в цепочке (перед UnknownCommand).
    """

    TRIGGERS = list(AI_PREFIXES)

    def matches(self, text: str) -> bool:
        return any(text.startswith(p) or p in text for p in AI_PREFIXES)

    def execute(self, text: str) -> str:
        engine = _get_engine()
        reply  = engine.ask(text)
        self.respond(reply)
        return reply


class AIFallbackCommand(BaseCommand):
    """
    Fallback: если ни одна команда не сработала — отправить в AI.

    Заменяет UnknownCommand: вместо «не знаю команду» — умный ответ.
    Всегда последний в цепочке (matches() всегда True).
    """

    TRIGGERS = [""]

    def matches(self, text: str) -> bool:
        return True

    def execute(self, text: str) -> str:
        engine = _get_engine()
        reply  = engine.ask(text)
        self.respond(reply)
        return reply


class AIClearHistoryCommand(BaseCommand):
    """Очищает историю диалога с AI."""

    TRIGGERS = [
        "очисти историю",
        "сбрось историю",
        "новый диалог",
        "забудь всё",
        "очисти диалог",
    ]

    def execute(self, text: str) -> str:
        engine = _get_engine()
        msg    = engine.clear_history()
        self.respond(msg)
        return msg