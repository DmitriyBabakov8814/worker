"""
core/user_memory.py  –  долгосрочная память о пользователе

Сохраняет факты о пользователе в JSON-файл user_memory.json рядом с проектом.
AIEngine подгружает память при каждом запросе и добавляет её в system-prompt.

Поддерживает:
  - имя, возраст, город, профессия и любые произвольные факты
  - автоматическое определение: «меня зовут X» → {name: X}
  - команды: «что ты знаешь обо мне», «забудь всё что знаешь обо мне»
"""

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger("worker.user_memory")

_BASE_DIR   = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
MEMORY_FILE = os.path.join(_BASE_DIR, "user_memory.json")

# ── Паттерны для авто-извлечения фактов ──────────────────────────────────────

_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # (ключ, метка, паттерн)
    ("name", "имя",
     re.compile(
         r"меня зовут\s+([а-яёa-z][а-яёa-z\-]{1,30})"
         r"|моё имя\s+([а-яёa-z][а-яёa-z\-]{1,30})"
         r"|мое имя\s+([а-яёa-z][а-яёa-z\-]{1,30})"
         r"|зови меня\s+([а-яёa-z][а-яёa-z\-]{1,30})",
         re.IGNORECASE,
     )),
    ("age", "возраст",
     re.compile(
         r"мне\s+(\d{1,3})\s*(?:лет|год|года|годик|годиков)"
         r"|мой возраст\s+(\d{1,3})"
         r"|мне\s+исполнилось\s+(\d{1,3})",
         re.IGNORECASE,
     )),
    ("city", "город",
     re.compile(
         r"я\s+(?:живу|нахожусь|из)\s+(?:в\s+|из\s+)?([а-яёa-z][а-яёa-z\-\s]{2,30}?)(?:\s*[,.]|$)"
         r"|мой город\s+([а-яёa-z][а-яёa-z\-\s]{2,30}?)(?:\s*[,.]|$)",
         re.IGNORECASE,
     )),
    ("job", "профессия",
     re.compile(
         r"я\s+(?:работаю\s+)?(?:как\s+)?([а-яёa-z][а-яёa-z\-\s]{2,40}?)(?:\s+по профессии|$)"
         r"|моя профессия\s+([а-яёa-z][а-яёa-z\-\s]{2,40}?)(?:\s*[,.]|$)"
         r"|я\s+по профессии\s+([а-яёa-z][а-яёa-z\-\s]{2,40}?)(?:\s*[,.]|$)",
         re.IGNORECASE,
     )),
]

# Фразы-триггеры «запомни что…» / «запиши…»
_REMEMBER_RE = re.compile(
    r"(?:запомни|запиши|сохрани|зафиксируй)[,\s]+(?:что\s+|:?\s*)(.*)",
    re.IGNORECASE,
)

# Фразы «что ты знаешь обо мне»
RECALL_TRIGGERS = (
    "что ты знаешь обо мне",
    "что знаешь обо мне",
    "расскажи что знаешь обо мне",
    "что ты помнишь обо мне",
    "что ты обо мне знаешь",
)

# Фразы «забудь всё обо мне»
FORGET_TRIGGERS = (
    "забудь всё что знаешь обо мне",
    "забудь всё обо мне",
    "удали мои данные",
    "очисти память о себе",
    "сотри память обо мне",
)


# ── Класс ─────────────────────────────────────────────────────────────────────

class UserMemory:
    """
    Хранит факты о пользователе в JSON.

    Использование:
        mem = UserMemory()
        changed = mem.extract_and_save(user_text)   # авто-извлечение
        snippet = mem.as_prompt_snippet()            # для system-prompt
    """

    def __init__(self, path: str = MEMORY_FILE):
        self._path = path
        self._data: dict[str, Any] = {}
        self._load()

    # ── Public ────────────────────────────────────────────────────────────────

    def extract_and_save(self, text: str) -> list[str]:
        """
        Пытается извлечь факты из текста пользователя.
        Возвращает список описаний изменений (пустой если ничего не нашло).
        """
        changed: list[str] = []

        # 1. Паттерны авто-извлечения
        for key, label, pattern in _PATTERNS:
            m = pattern.search(text)
            if m:
                value = next((g for g in m.groups() if g), None)
                if value:
                    value = value.strip().capitalize()
                    if self._data.get(key) != value:
                        self._data[key] = value
                        changed.append(f"{label} → {value}")

        # 2. «запомни что …»
        m2 = _REMEMBER_RE.search(text)
        if m2:
            fact = m2.group(1).strip()
            if fact:
                facts: list[str] = self._data.setdefault("facts", [])
                if fact.lower() not in [f.lower() for f in facts]:
                    facts.append(fact)
                    changed.append(f"факт → {fact}")

        if changed:
            self._save()
            logger.info(f"UserMemory обновлена: {changed}")

        return changed

    def as_prompt_snippet(self) -> str:
        """Возвращает строку для вставки в system-prompt. Пустая если данных нет."""
        if not self._data:
            return ""
        parts: list[str] = []
        if "name" in self._data:
            parts.append(f"имя пользователя: {self._data['name']}")
        if "age" in self._data:
            parts.append(f"возраст: {self._data['age']}")
        if "city" in self._data:
            parts.append(f"город: {self._data['city']}")
        if "job" in self._data:
            parts.append(f"профессия: {self._data['job']}")
        for fact in self._data.get("facts", []):
            parts.append(f"факт: {fact}")
        if not parts:
            return ""
        return "Известные факты о пользователе: " + "; ".join(parts) + "."

    def recall_text(self) -> str:
        """Человекочитаемый список того, что помним."""
        if not self._data:
            return "Я пока ничего о вас не знаю."
        lines = []
        labels = {"name": "Имя", "age": "Возраст", "city": "Город", "job": "Профессия"}
        for key, label in labels.items():
            if key in self._data:
                lines.append(f"{label}: {self._data[key]}")
        for fact in self._data.get("facts", []):
            lines.append(f"Факт: {fact}")
        return "Вот что я о вас помню:\n" + "\n".join(lines)

    def forget_all(self) -> str:
        """Стирает всю память."""
        self._data = {}
        self._save()
        logger.info("UserMemory очищена")
        return "Память о вас полностью удалена."

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._save()

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    # ── Private ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.info(f"UserMemory загружена: {list(self._data.keys())}")
            except Exception as e:
                logger.warning(f"UserMemory load error: {e}")
                self._data = {}

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"UserMemory save error: {e}")


# Singleton
_instance: UserMemory | None = None


def get_memory() -> UserMemory:
    global _instance
    if _instance is None:
        _instance = UserMemory()
    return _instance