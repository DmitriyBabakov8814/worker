"""
core/dialogue_manager.py  –  менеджер диалога

Хранит историю сообщений сессии, добавляет system-prompt,
обрезает историю при превышении лимита.

Не знает ничего об Ollama — только управляет структурой messages.
"""

import logging
from copy import deepcopy

from core.ai_config import MAX_HISTORY, SYSTEM_PROMPT

logger = logging.getLogger("worker.dialogue_manager")


class DialogueManager:
    """
    Управляет историей диалога в формате Ollama/OpenAI messages.

    История хранит только user/assistant пары.
    System-prompt добавляется динамически при каждом вызове get_messages(),
    чтобы его можно было менять без пересборки истории.
    """

    def __init__(self, system_prompt: str = SYSTEM_PROMPT, max_history: int = MAX_HISTORY):
        self._system_prompt = system_prompt
        self._max_history   = max_history          # число user+assistant сообщений
        self._history: list[dict] = []             # только user / assistant

    # ── Public ────────────────────────────────────────────────────────────────

    def add_user(self, text: str) -> None:
        """Добавляет сообщение пользователя в историю."""
        self._history.append({"role": "user", "content": text})
        self._trim()

    def add_assistant(self, text: str) -> None:
        """Добавляет ответ ассистента в историю."""
        self._history.append({"role": "assistant", "content": text})
        self._trim()

    def get_messages(self) -> list[dict]:
        """
        Возвращает полный список messages для отправки в Ollama:
        [system] + история.
        """
        system = {"role": "system", "content": self._system_prompt}
        return [system] + deepcopy(self._history)

    def clear(self) -> None:
        """Очищает историю (начать новый диалог)."""
        self._history.clear()
        logger.info("История диалога очищена")

    @property
    def turn_count(self) -> int:
        """Количество полных пар user/assistant."""
        return len(self._history) // 2

    # ── Private ───────────────────────────────────────────────────────────────

    def _trim(self) -> None:
        """Обрезает историю до _max_history последних сообщений."""
        if len(self._history) > self._max_history:
            # Удаляем с начала, сохраняя чётность (пары)
            excess = len(self._history) - self._max_history
            self._history = self._history[excess:]
            logger.debug(f"История обрезана до {len(self._history)} сообщений")