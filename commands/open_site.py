"""
commands/open_site.py  –  открытие сайтов по названию

Примеры:
  «открой вконтакте»           → https://vk.com
  «открой инстаграм»           → https://instagram.com
  «открой сайт авито»          → https://avito.ru
  «зайди на пикабу»            → https://pikabu.ru
  «открой wildberries»         → https://wildberries.ru
  «открой сайт моего банка»    → поиск в Google
  «открой сайт apple.com»      → https://apple.com  (прямой URL)
  «открой сайт example.ru»     → https://example.ru (прямой URL)
"""

import re
import webbrowser
import logging
import urllib.parse

from core.command_dispatcher import BaseCommand

logger = logging.getLogger("worker.commands.open_site")

# ── Словарь известных сайтов (название → URL) ─────────────────────────────────
# Добавляй сюда что угодно
KNOWN_SITES: dict[str, str] = {
    # Соцсети
    "вконтакте": "https://vk.com",
    "вк": "https://vk.com",
    "vk": "https://vk.com",
    "инстаграм": "https://instagram.com",
    "instagram": "https://instagram.com",
    "фейсбук": "https://facebook.com",
    "facebook": "https://facebook.com",
    "твиттер": "https://twitter.com",
    "twitter": "https://twitter.com",
    "икс": "https://x.com",
    "тикток": "https://tiktok.com",
    "tiktok": "https://tiktok.com",
    "телеграм": "https://web.telegram.org",
    "telegram": "https://web.telegram.org",
    "одноклассники": "https://ok.ru",
    "ок": "https://ok.ru",

    # Поисковики
    "гугл": "https://google.com",
    "google": "https://google.com",
    "яндекс": "https://yandex.ru",
    "yandex": "https://yandex.ru",
    "бинг": "https://bing.com",
    "bing": "https://bing.com",

    # Видео
    "ютуб": "https://youtube.com",
    "youtube": "https://youtube.com",
    "ютубе": "https://youtube.com",
    "twitch": "https://twitch.tv",
    "твич": "https://twitch.tv",
    "кинопоиск": "https://kinopoisk.ru",

    # Маркетплейсы
    "авито": "https://avito.ru",
    "wildberries": "https://wildberries.ru",
    "вайлдберриз": "https://wildberries.ru",
    "озон": "https://ozon.ru",
    "ozon": "https://ozon.ru",
    "алиэкспресс": "https://aliexpress.ru",
    "aliexpress": "https://aliexpress.ru",
    "сбермегамаркет": "https://sbermegamarket.ru",
    "яндекс маркет": "https://market.yandex.ru",
    "яндекс.маркет": "https://market.yandex.ru",

    # Банки
    "сбербанк": "https://sberbank.ru",
    "тинькофф": "https://tinkoff.ru",
    "тинькоф": "https://tinkoff.ru",
    "втб": "https://vtb.ru",
    "альфа банк": "https://alfabank.ru",
    "альфабанк": "https://alfabank.ru",
    "газпромбанк": "https://gazprombank.ru",

    # Разработка / IT
    "гитхаб": "https://github.com",
    "github": "https://github.com",
    "гитлаб": "https://gitlab.com",
    "gitlab": "https://gitlab.com",
    "стаковерфлоу": "https://stackoverflow.com",
    "stackoverflow": "https://stackoverflow.com",
    "хабр": "https://habr.com",
    "нпм": "https://npmjs.com",
    "пайпи": "https://pypi.org",

    # Новости
    "пикабу": "https://pikabu.ru",
    "риа новости": "https://ria.ru",
    "рбк": "https://rbc.ru",
    "медуза": "https://meduza.io",

    # Музыка
    "спотифай": "https://spotify.com",
    "spotify": "https://spotify.com",
    "яндекс музыка": "https://music.yandex.ru",
    "яндекс.музыка": "https://music.yandex.ru",
    "soundcloud": "https://soundcloud.com",
    "саундклауд": "https://soundcloud.com",

    # Почта
    "gmail": "https://mail.google.com",
    "гмейл": "https://mail.google.com",
    "яндекс почта": "https://mail.yandex.ru",
    "яндекс.почта": "https://mail.yandex.ru",
    "mail.ru": "https://mail.ru",
    "мейл ру": "https://mail.ru",

    # Карты
    "гугл карты": "https://maps.google.com",
    "яндекс карты": "https://yandex.ru/maps",
    "яндекс.карты": "https://yandex.ru/maps",

    # Прочее
    "wikipedia": "https://ru.wikipedia.org",
    "википедия": "https://ru.wikipedia.org",
    "перевод": "https://translate.yandex.ru",
    "гугл переводчик": "https://translate.google.com",
    "weather": "https://weather.com",
    "погода": "https://pogoda.yandex.ru",
    "claude": "https://claude.ai",
    "chatgpt": "https://chatgpt.com",
    "чатгпт": "https://chatgpt.com",
}

# Триггерные фразы для команды
_TRIGGER_RE = re.compile(
    r"(?:открой|зайди на|перейди на|открыть|запусти браузер|покажи сайт|открой сайт)\s+"
    r"(?:сайт\s+)?(.+)",
    re.IGNORECASE,
)

# Определение прямого URL (example.com, example.ru и т.д.)
_URL_RE = re.compile(
    r"^(?:https?://)?[\w\-]+\.(?:com|ru|org|net|io|dev|app|ai|co|рф|su|ua|by|kz|uk|де|fr|jp)\S*$",
    re.IGNORECASE,
)


def _resolve_site(query: str) -> tuple[str, str]:
    """
    По запросу возвращает (url, описание).
    Приоритет:
      1. Прямой URL (avito.ru, github.com)
      2. Словарь известных сайтов
      3. Поиск в Яндексе как fallback
    """
    q = query.strip().lower()

    # 1. Прямой URL?
    if _URL_RE.match(q):
        url = q if q.startswith("http") else "https://" + q
        return url, q

    # 2. Словарь
    if q in KNOWN_SITES:
        return KNOWN_SITES[q], q

    # Частичное совпадение — ищем подстроку
    for name, url in KNOWN_SITES.items():
        if name in q or q in name:
            return url, name

    # 3. Fallback — поиск в Яндексе
    search_url = "https://yandex.ru/search/?text=" + urllib.parse.quote_plus(query)
    return search_url, f"поиск «{query}»"


class OpenSiteCommand(BaseCommand):
    """Открывает сайт по названию без необходимости вводить URL."""

    TRIGGERS = [
        "открой сайт",
        "открой вк",
        "открой гугл",
        "открой ютуб",
        "открой яндекс",
        "открой инстаграм",
        "открой телеграм",
        "открой авито",
        "открой github",
        "открой гитхаб",
        "открой пикабу",
        "открой хабр",
        "открой wikipedia",
        "открой wikipedia",
        "зайди на",
        "перейди на",
    ]

    def matches(self, text: str) -> bool:
        return bool(_TRIGGER_RE.search(text))

    def execute(self, text: str) -> str:
        m = _TRIGGER_RE.search(text)
        if not m:
            msg = "Укажи сайт: «открой авито» или «открой сайт github.com»"
            self.respond(msg)
            return msg

        query   = m.group(1).strip()
        url, desc = _resolve_site(query)

        logger.info(f"OpenSite: '{query}' → {url}")
        webbrowser.open(url)

        msg = f"Открываю {desc}."
        self.respond(msg)
        return msg