"""
commands/music.py  –  открывает музыку в браузере
"""
import webbrowser
import logging
from core.command_dispatcher import BaseCommand

logger = logging.getLogger("jarvis.commands.music")

MUSIC_URLS = [
    "https://music.yandex.ru/playlists/lk.ea3e7d37-e738-41f5-aed8-3d2c3dc03ff3",
    "https://soundcloud.com/you/likes",
]


class MusicCommand(BaseCommand):
    TRIGGERS = [
        "включи музыку", "включить музыку", "запусти музыку",
        "поставь музыку", "открой музыку", "музыку",
    ]

    def execute(self, text: str) -> str:
        for url in MUSIC_URLS:
            webbrowser.open_new_tab(url)
        msg = "Открываю музыку в браузере."
        self.respond(msg)
        return msg