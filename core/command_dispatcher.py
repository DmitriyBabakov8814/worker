"""
core/command_dispatcher.py
Маршрутизатор команд.
"""

import sys
import os
import logging
from typing import Callable, Optional

# Гарантируем что корень проекта в sys.path
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger("jarvis.dispatcher")


class BaseCommand:
    TRIGGERS: list[str] = []

    def __init__(self, on_response: Optional[Callable[[str], None]] = None):
        self.on_response = on_response

    def matches(self, text: str) -> bool:
        return any(t in text for t in self.TRIGGERS)

    def execute(self, text: str) -> str:
        raise NotImplementedError

    def respond(self, message: str):
        logger.info(f"[RESPONSE] {message}")
        if self.on_response:
            self.on_response(message)


class CommandDispatcher:
    def __init__(self, on_response: Optional[Callable[[str], None]] = None):
        self.on_response = on_response
        self._commands: list[BaseCommand] = []
        self.register_all()

    def register_all(self):
        from commands.music     import MusicCommand
        from commands.claude_ai import ClaudeCommand
        from commands.volume    import (
            VolumeUpCommand, VolumeDownCommand,
            VolumeMaxCommand, VolumeMuteCommand,
        )
        from commands.shutdown_pc import ShutdownPcCommand
        from commands.unknown   import UnknownCommand

        for cls in [
            MusicCommand,
            ClaudeCommand,
            VolumeUpCommand,
            VolumeDownCommand,
            VolumeMaxCommand,
            VolumeMuteCommand,
            ShutdownPcCommand,
            UnknownCommand,      # ← всегда последний
        ]:
            self._commands.append(cls(on_response=self.on_response))

    def dispatch(self, text: str):
        text = text.lower().strip()
        logger.debug(f"Dispatch: '{text}'")
        for cmd in self._commands:
            if cmd.matches(text):
                try:
                    cmd.execute(text)
                except Exception as e:
                    logger.error(f"{cmd.__class__.__name__}: {e}")
                    if self.on_response:
                        self.on_response(f"Ошибка команды: {e}")
                return