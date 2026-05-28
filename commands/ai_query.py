"""
commands/ai_query.py  –  AI-команда (интеграция с Ollama через AIEngine)

Перехватывает запросы, которые явно адресованы AI,
а также служит fallback когда ни одна другая команда не подошла.

Singleton AIEngine создаётся один раз при первом вызове.
Добавлены команды управления памятью о пользователе.
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


class MemoryRecallCommand(BaseCommand):
    """Рассказывает что Jarvis знает о пользователе."""

    TRIGGERS = [
        "что ты знаешь обо мне",
        "что знаешь обо мне",
        "расскажи что знаешь обо мне",
        "что ты помнишь обо мне",
        "что ты обо мне знаешь",
    ]

    def execute(self, text: str) -> str:
        from core.user_memory import get_memory
        msg = get_memory().recall_text()
        self.respond(msg)
        return msg


class MemoryForgetCommand(BaseCommand):
    """Стирает всю память о пользователе."""

    TRIGGERS = [
        "забудь всё что знаешь обо мне",
        "забудь всё обо мне",
        "удали мои данные",
        "очисти память о себе",
        "сотри память обо мне",
        "очисти память",
    ]

    def execute(self, text: str) -> str:
        from core.user_memory import get_memory
        msg = get_memory().forget_all()
        self.respond(msg)
        return msg