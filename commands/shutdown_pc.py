"""
commands/shutdown_pc.py  –  выключение компьютера (Windows)

Команды:
  «мой комп» / «выключи компьютер» / «заверши работу»  →  завершение работы ОС

Отмена (если сказали по ошибке): shutdown /a  в командной строке.
"""

import logging
import subprocess
import sys
import threading
import time

from core.command_dispatcher import BaseCommand

logger = logging.getLogger("worker.commands.shutdown_pc")

SHUTDOWN_DELAY_SEC = 5   # пауза после голосового ответа
SHUTDOWN_TIMER_SEC = 3   # таймер Windows shutdown /t


def _shutdown_windows():
    if sys.platform != "win32":
        logger.error("Выключение поддерживается только на Windows")
        return False
    try:
        subprocess.run(
            ["shutdown", "/s", "/t", str(SHUTDOWN_TIMER_SEC)],
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
        logger.info("Запущено выключение Windows")
        return True
    except Exception as e:
        logger.error(f"Не удалось выключить ПК: {e}")
        return False


def _schedule_shutdown():
    time.sleep(SHUTDOWN_DELAY_SEC)
    _shutdown_windows()


class ShutdownPcCommand(BaseCommand):
    TRIGGERS = [
        "мой комп",
        "мой камп",
        "мой компьютер",
        "выключи компьютер",
        "выключи комп",
        "выключи пк",
        "выключи компьютер",
        "выключить компьютер",
        "заверши работу",
        "завершить работу",
        "отключи компьютер",
    ]

    def execute(self, text: str) -> str:
        if sys.platform != "win32":
            msg = "Выключение компьютера доступно только на Windows."
            self.respond(msg)
            return msg

        msg = "Выключаю компьютер. До отключения несколько секунд."
        self.respond(msg)
        threading.Thread(target=_schedule_shutdown, daemon=True).start()
        return msg
