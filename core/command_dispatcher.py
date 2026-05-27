"""
core/command_dispatcher.py  –  маршрутизатор команд W.O.R.K.E.R

Цепочка обработки:
  1. Конкретные команды (музыка, громкость, выключение, …)
  2. AIQueryCommand  — явные AI-запросы (фразы из AI_PREFIXES)
  3. AIClearHistoryCommand — управление историей диалога
  4. AIFallbackCommand — всё остальное уходит в Ollama
"""

import sys
import os
import logging
from typing import Callable, Optional

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger("worker.dispatcher")


class BaseCommand:
    TRIGGERS: list[str] = []

    def __init__(self, on_response: Optional[Callable[[str], None]] = None):
        self.on_response = on_response

    def matches(self, text: str) -> bool:
        return any(t and t in text for t in self.TRIGGERS)

    def execute(self, text: str) -> str:
        raise NotImplementedError

    def respond(self, message: str) -> None:
        logger.info(f"[RESPONSE] {message}")
        if self.on_response:
            self.on_response(message)


class CommandDispatcher:
    def __init__(self, on_response: Optional[Callable[[str], None]] = None):
        self.on_response = on_response
        self._commands: list[BaseCommand] = []
        self._register_all()

    def _register_all(self) -> None:
        from commands.music              import MusicCommand
        from commands.claude_ai          import ClaudeCommand
        from commands.volume             import (
            VolumeUpCommand, VolumeDownCommand,
            VolumeMaxCommand, VolumeMuteCommand,
        )
        from commands.shutdown_pc        import ShutdownPcCommand
        from commands.ai_query           import (
            AIClearHistoryCommand,
            AIQueryCommand,
            AIFallbackCommand,   # ← заменяет UnknownCommand
        )

        for cls in [
            # ── Конкретные команды ───────────────────────────────────────────
            MusicCommand,
            ClaudeCommand,
            VolumeUpCommand,
            VolumeDownCommand,
            VolumeMaxCommand,
            VolumeMuteCommand,
            ShutdownPcCommand,
            # ── AI-слой ──────────────────────────────────────────────────────
            AIClearHistoryCommand,   # сначала — чтобы не улетело в AI как запрос
            AIQueryCommand,          # явные AI-фразы
            AIFallbackCommand,       # ← всегда последний, matches() == True
        ]:
            self._commands.append(cls(on_response=self.on_response))

        logger.info(f"Зарегистрировано команд: {len(self._commands)}")

    def dispatch(self, text: str) -> None:
        text = text.lower().strip()
        if not text:
            return
        logger.debug(f"Dispatch: '{text}'")
        for cmd in self._commands:
            if cmd.matches(text):
                try:
                    cmd.execute(text)
                except Exception as e:
                    logger.error(f"{cmd.__class__.__name__}: {e}", exc_info=True)
                    if self.on_response:
                        self.on_response(f"Ошибка команды: {e}")
                return