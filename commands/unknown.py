"""
commands/unknown.py  –  фолбек (всегда последний в списке)
"""
from core.command_dispatcher import BaseCommand


class UnknownCommand(BaseCommand):
    TRIGGERS = [""]

    def matches(self, text: str) -> bool:
        return True

    def execute(self, text: str) -> str:
        msg = f"Не знаю как выполнить: «{text}»"
        self.respond(msg)
        return msg