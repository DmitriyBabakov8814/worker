"""
commands/claude_ai.py  –  открывает Claude в системном браузере по умолчанию
"""
import webbrowser
import logging
from core.command_dispatcher import BaseCommand

logger = logging.getLogger("worker.commands.claude_ai")

CLAUDE_URL = "https://claude.ai"


class ClaudeCommand(BaseCommand):
    TRIGGERS = [
        "открой клауд",
        "открыть клауд",
        "запусти клауд",
        "клауд",
        "открой claude",
        "запусти claude",
        "открой club",
        "открой шныря",
        "включи шныря",
        "шныря",
        "шнырь",
        "нейросеть",
        "открой ии"
    ]

    def execute(self, text: str) -> str:
        logger.info(f"Открываю Claude: {CLAUDE_URL}")
        webbrowser.open(CLAUDE_URL)
        msg = "Открываю Claude в браузере."
        self.respond(msg)
        return msg