"""
commands/custom_commands.py  –  пользовательские команды Jarvis

Хранит произвольные команды в custom_commands.json.
Каждая запись:
  {
    "triggers": ["открой гугл", "гугл"],   ← фразы-триггеры
    "action":   "browser",                 ← тип действия
    "params":   {"url": "https://google.com"}
  }

Типы действий (action):
  "browser"    → открыть URL в браузере по умолчанию
  "app"        → запустить .exe / команду
  "folder"     → открыть папку в проводнике
  "keys"       → нажать комбинацию клавиш (pyautogui)
  "say"        → ответить заданным текстом
  "clipboard"  → вставить текст в буфер обмена
  "search"     → поиск в браузере по умолчанию

Управление через голос / текст:
  «добавь команду»        → интерактивное добавление
  «покажи мои команды»    → список всех кастомных команд
  «удали команду СЛОВО»   → удалить по триггеру

Примеры готовых команд добавляются при первом запуске.
"""

import json
import logging
import os
import re
import subprocess
import sys
import webbrowser
from typing import Any

from core.command_dispatcher import BaseCommand

logger = logging.getLogger("worker.commands.custom")

_BASE_DIR    = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
COMMANDS_FILE = os.path.join(_BASE_DIR, "custom_commands.json")


# ── Хранилище ─────────────────────────────────────────────────────────────────

def _load() -> list[dict]:
    if os.path.exists(COMMANDS_FILE):
        try:
            with open(COMMANDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"custom_commands load: {e}")
    return []


def _save(commands: list[dict]) -> None:
    try:
        with open(COMMANDS_FILE, "w", encoding="utf-8") as f:
            json.dump(commands, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"custom_commands save: {e}")


def _seed_defaults():
    """Добавляет примеры команд если файл пустой."""
    cmds = _load()
    if cmds:
        return
    defaults = [
        {
            "triggers": ["открой гугл", "гугл", "google"],
            "action":   "browser",
            "params":   {"url": "https://google.com"},
            "desc":     "Открывает Google в браузере"
        },
        {
            "triggers": ["открой ютуб", "youtube", "ютуб"],
            "action":   "browser",
            "params":   {"url": "https://youtube.com"},
            "desc":     "Открывает YouTube"
        },
        {
            "triggers": ["открой github", "гитхаб"],
            "action":   "browser",
            "params":   {"url": "https://github.com"},
            "desc":     "Открывает GitHub"
        },
        {
            "triggers": ["открой телеграм", "телеграм"],
            "action":   "app",
            "params":   {"cmd": "start", "args": ["", "telegram.exe"]},
            "desc":     "Запускает Telegram"
        },
        {
            "triggers": ["открой рабочий стол", "рабочий стол"],
            "action":   "keys",
            "params":   {"keys": "win+d"},
            "desc":     "Показывает рабочий стол"
        },
        {
            "triggers": ["сделай скриншот", "скриншот"],
            "action":   "keys",
            "params":   {"keys": "win+shift+s"},
            "desc":     "Запускает скриншот (Snip & Sketch)"
        },
        {
            "triggers": ["открой диспетчер задач", "диспетчер"],
            "action":   "app",
            "params":   {"cmd": "taskmgr"},
            "desc":     "Открывает диспетчер задач"
        },
        {
            "triggers": ["поищи", "найди в интернете"],
            "action":   "search",
            "params":   {"engine": "https://google.com/search?q="},
            "desc":     "Поиск в Google (поищи [запрос])"
        },
    ]
    _save(defaults)
    logger.info(f"Добавлено {len(defaults)} дефолтных команд")


# ── Выполнение действий ───────────────────────────────────────────────────────

def _run_action(action: str, params: dict, trigger_text: str = "") -> str:
    """Выполняет действие команды, возвращает строку-ответ."""
    try:
        if action == "browser":
            url = params.get("url", "")
            webbrowser.open(url)
            return f"Открываю {url}"

        elif action == "app":
            cmd  = params.get("cmd", "")
            args = params.get("args", [])
            if sys.platform == "win32":
                subprocess.Popen(
                    [cmd] + args,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    shell=True,
                )
            else:
                subprocess.Popen([cmd] + args)
            return f"Запускаю {cmd}"

        elif action == "folder":
            path = os.path.expandvars(params.get("path", ""))
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
            return f"Открываю папку {path}"

        elif action == "keys":
            keys = params.get("keys", "")
            try:
                import pyautogui
                # Преобразуем "win+d" → pyautogui.hotkey("win", "d")
                parts = [k.strip() for k in keys.replace("+", " ").split()]
                pyautogui.hotkey(*parts)
                return f"Нажал {keys}"
            except ImportError:
                return "pyautogui не установлен: pip install pyautogui"

        elif action == "say":
            return params.get("text", "Готово.")

        elif action == "clipboard":
            text = params.get("text", "")
            try:
                import pyperclip
                pyperclip.copy(text)
                return "Скопировано в буфер обмена."
            except ImportError:
                return "pyperclip не установлен: pip install pyperclip"

        elif action == "search":
            engine = params.get("engine", "https://google.com/search?q=")
            # Извлекаем запрос из trigger_text
            query = trigger_text
            for word in ["поищи", "найди в интернете", "найди", "поиск"]:
                query = query.replace(word, "").strip()
            import urllib.parse
            url = engine + urllib.parse.quote_plus(query)
            webbrowser.open(url)
            return f"Ищу: {query}"

        else:
            return f"Неизвестное действие: {action}"

    except Exception as e:
        logger.error(f"_run_action {action}: {e}")
        return f"Ошибка выполнения: {e}"


# ── Команды управления ────────────────────────────────────────────────────────

class CustomCommandRunner(BaseCommand):
    """
    Основной runner — матчит пользовательские команды из JSON.
    Загружает список при каждом matches() чтобы всегда видеть актуальный.
    """
    TRIGGERS = []  # динамические — определяем в matches()

    def matches(self, text: str) -> bool:
        cmds = _load()
        for cmd in cmds:
            for trig in cmd.get("triggers", []):
                if trig.lower() in text:
                    return True
        return False

    def execute(self, text: str) -> str:
        cmds = _load()
        for cmd in cmds:
            for trig in cmd.get("triggers", []):
                if trig.lower() in text:
                    action = cmd.get("action", "say")
                    params = cmd.get("params", {})
                    msg    = _run_action(action, params, trigger_text=text)
                    logger.info(f"CustomCmd [{trig}] → {action}: {msg}")
                    self.respond(msg)
                    return msg
        msg = "Команда не найдена."
        self.respond(msg)
        return msg


class ListCustomCommandsCommand(BaseCommand):
    """Показывает список всех кастомных команд."""
    TRIGGERS = [
        "покажи мои команды",
        "список команд",
        "мои команды",
        "что ты умеешь",
        "покажи команды",
    ]

    def execute(self, text: str) -> str:
        cmds = _load()
        if not cmds:
            msg = "Кастомных команд пока нет. Скажи «добавь команду» чтобы создать."
            self.respond(msg)
            return msg
        lines = [f"У меня {len(cmds)} команд:\n"]
        for i, cmd in enumerate(cmds, 1):
            trigs = ", ".join(f'«{t}»' for t in cmd.get("triggers", []))
            desc  = cmd.get("desc", cmd.get("action", ""))
            lines.append(f"{i}. {trigs} → {desc}")
        msg = "\n".join(lines)
        self.respond(msg)
        return msg


class AddCustomCommandCommand(BaseCommand):
    """
    Добавляет новую кастомную команду через текстовый диалог.

    Синтаксис в одну строку:
      добавь команду [триггер] делать [действие] [параметр]

    Примеры:
      добавь команду «открой вк» делать browser https://vk.com
      добавь команду «открой блокнот» делать app notepad
      добавь команду «рабочий стол» делать keys win+d
      добавь команду «привет джарвис» делать say Привет! Чем могу помочь?
    """
    TRIGGERS = [
        "добавь команду",
        "добавить команду",
        "научись команде",
        "новая команда",
        "создай команду",
    ]

    # Паттерн: добавь команду «триггер» делать ACTION параметр
    _RE = re.compile(
        r'(?:добавь|добавить|научись|новая|создай)\s+команду?\s+'
        r'[«"]?(.+?)[»"]?\s+делать\s+(\w+)\s*(.*)',
        re.IGNORECASE,
    )

    def execute(self, text: str) -> str:
        m = self._RE.search(text)
        if not m:
            msg = (
                "Не понял формат. Пример:\n"
                "добавь команду «открой вк» делать browser https://vk.com\n"
                "добавь команду «открой блокнот» делать app notepad\n"
                "добавь команду «рабочий стол» делать keys win+d\n"
                "добавь команду «привет» делать say Привет!"
            )
            self.respond(msg)
            return msg

        trigger = m.group(1).strip().lower()
        action  = m.group(2).strip().lower()
        param   = m.group(3).strip()

        # Строим params в зависимости от действия
        params: dict[str, Any] = {}
        if action == "browser":
            if not param.startswith("http"):
                param = "https://" + param
            params = {"url": param}
        elif action == "app":
            params = {"cmd": param}
        elif action == "folder":
            params = {"path": param}
        elif action == "keys":
            params = {"keys": param}
        elif action == "say":
            params = {"text": param}
        elif action == "search":
            params = {"engine": param or "https://google.com/search?q="}
        elif action == "clipboard":
            params = {"text": param}
        else:
            msg = (
                f"Неизвестное действие «{action}».\n"
                "Доступные: browser, app, folder, keys, say, search, clipboard"
            )
            self.respond(msg)
            return msg

        # Проверяем не занят ли триггер
        cmds = _load()
        for cmd in cmds:
            if trigger in [t.lower() for t in cmd.get("triggers", [])]:
                # Обновляем существующую
                cmd["action"] = action
                cmd["params"] = params
                _save(cmds)
                msg = f"Команда «{trigger}» обновлена → {action}."
                self.respond(msg)
                return msg

        # Добавляем новую
        cmds.append({
            "triggers": [trigger],
            "action":   action,
            "params":   params,
            "desc":     f"{action}: {param[:40]}",
        })
        _save(cmds)
        msg = f"Команда «{trigger}» добавлена! Теперь скажи «{trigger}»."
        self.respond(msg)
        return msg


class DeleteCustomCommandCommand(BaseCommand):
    """Удаляет кастомную команду по триггеру."""
    TRIGGERS = [
        "удали команду",
        "удалить команду",
        "убери команду",
    ]

    _RE = re.compile(
        r'(?:удали|удалить|убери)\s+команду?\s+[«"]?(.+?)[»"]?$',
        re.IGNORECASE,
    )

    def execute(self, text: str) -> str:
        m = self._RE.search(text)
        if not m:
            msg = "Укажи триггер: «удали команду открой гугл»"
            self.respond(msg)
            return msg

        trigger = m.group(1).strip().lower()
        cmds    = _load()
        before  = len(cmds)
        cmds    = [c for c in cmds
                   if trigger not in [t.lower() for t in c.get("triggers", [])]]
        if len(cmds) < before:
            _save(cmds)
            msg = f"Команда «{trigger}» удалена."
        else:
            msg = f"Команда «{trigger}» не найдена."
        self.respond(msg)
        return msg


# Инициализируем дефолтные команды при импорте
_seed_defaults()