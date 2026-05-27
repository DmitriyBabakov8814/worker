"""
core/ai_engine.py  –  AI-ядро W.O.R.K.E.R

Склеивает OllamaClient + DialogueManager в единый интерфейс.
Это единственная точка входа для всего AI-функционала.

Добавление новых возможностей (memory, tools, web) — только здесь,
остальные слои не трогаются.
"""

import logging
from typing import Optional

from core.ollama_client  import OllamaClient, OllamaConnectionError, OllamaError
from core.dialogue_manager import DialogueManager
from core.ai_config       import SYSTEM_PROMPT, MAX_HISTORY

logger = logging.getLogger("worker.ai_engine")


class AIEngine:
    """
    Высокоуровневый AI-слой.

    Пример использования:
        engine = AIEngine()
        reply  = engine.ask("что такое экономика")
        print(reply)
    """

    def __init__(
        self,
        system_prompt: str = SYSTEM_PROMPT,
        max_history:   int = MAX_HISTORY,
    ):
        self._client   = OllamaClient()
        self._dialogue = DialogueManager(
            system_prompt=system_prompt,
            max_history=max_history,
        )
        self._enabled  = True    # можно отключить через disable()
        logger.info("AIEngine инициализирован")

    # ── Public ────────────────────────────────────────────────────────────────

    def ask(self, text: str) -> str:
        """
        Главный метод: принимает текст пользователя, возвращает ответ AI.

        Всегда возвращает строку — никогда не бросает наружу.
        При ошибках возвращает понятное сообщение для пользователя.
        """
        if not self._enabled:
            return "AI-модуль отключён."

        if not text or not text.strip():
            return "Пустой запрос."

        text = text.strip()
        logger.info(f"AI запрос: {text[:80]}")

        self._dialogue.add_user(text)
        messages = self._dialogue.get_messages()

        try:
            reply = self._client.chat(messages)
        except OllamaConnectionError as e:
            logger.warning(str(e))
            # Убираем последнее user-сообщение из истории — запрос не состоялся
            self._dialogue._history.pop()
            return (
                "Ollama не запущена. "
                "Запустите её командой: ollama serve"
            )
        except OllamaError as e:
            logger.error(str(e))
            self._dialogue._history.pop()
            return f"Ошибка AI: {e}"
        except Exception as e:
            logger.exception("Неожиданная ошибка AI")
            self._dialogue._history.pop()
            return f"Внутренняя ошибка AI: {e}"

        self._dialogue.add_assistant(reply)
        logger.info(f"AI ответ: {reply[:80]}")
        return reply

    def clear_history(self) -> str:
        """Очищает историю диалога. Возвращает подтверждение."""
        self._dialogue.clear()
        return "История диалога очищена."

    def enable(self) -> None:
        self._enabled = True
        logger.info("AIEngine включён")

    def disable(self) -> None:
        self._enabled = False
        logger.info("AIEngine отключён")

    @property
    def is_available(self) -> bool:
        """Проверяет доступность Ollama (быстро, без диалога)."""
        return self._client.is_available()

    @property
    def turn_count(self) -> int:
        return self._dialogue.turn_count