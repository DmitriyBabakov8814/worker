"""
core/ollama_client.py  –  тонкий клиент для Ollama API

Отвечает только за HTTP-общение с Ollama.
Никакой бизнес-логики — только запрос / ответ.
"""

import json
import logging
from typing import Optional

import requests

from core.ai_config import OLLAMA_CHAT_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT

logger = logging.getLogger("worker.ollama_client")


class OllamaError(Exception):
    """Базовое исключение для ошибок Ollama."""


class OllamaConnectionError(OllamaError):
    """Ollama недоступна (не запущена / неверный адрес)."""


class OllamaClient:
    """
    Низкоуровневый клиент Ollama /api/chat.

    Использование:
        client = OllamaClient()
        reply  = client.chat(messages)   # messages — список dict role/content
    """

    def __init__(
        self,
        url:     str = OLLAMA_CHAT_URL,
        model:   str = OLLAMA_MODEL,
        timeout: int = OLLAMA_TIMEOUT,
    ):
        self._url     = url
        self._model   = model
        self._timeout = timeout

    # ── Public ────────────────────────────────────────────────────────────────

    def chat(self, messages: list[dict]) -> str:
        """
        Отправляет messages в Ollama и возвращает строку ответа.

        Args:
            messages: [{"role": "system"|"user"|"assistant", "content": "..."}]

        Returns:
            Текст ответа модели.

        Raises:
            OllamaConnectionError: если Ollama не запущена.
            OllamaError:           прочие HTTP / JSON ошибки.
        """
        payload = {
            "model":    self._model,
            "messages": messages,
            "stream":   False,
        }

        logger.debug(f"→ Ollama  model={self._model}  msgs={len(messages)}")

        try:
            resp = requests.post(
                self._url,
                json=payload,
                timeout=self._timeout,
            )
        except requests.exceptions.ConnectionError as e:
            raise OllamaConnectionError(
                f"Ollama недоступна по адресу {self._url}. "
                "Убедитесь, что Ollama запущена (`ollama serve`)."
            ) from e
        except requests.exceptions.Timeout as e:
            raise OllamaError(
                f"Ollama не ответила за {self._timeout} сек."
            ) from e
        except requests.exceptions.RequestException as e:
            raise OllamaError(f"HTTP ошибка: {e}") from e

        if resp.status_code != 200:
            raise OllamaError(
                f"Ollama вернула статус {resp.status_code}: {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise OllamaError(f"Некорректный JSON от Ollama: {e}") from e

        content = (
            data.get("message", {}).get("content")
            or data.get("response")
            or ""
        )

        if not content:
            raise OllamaError(f"Ollama вернула пустой ответ: {data}")

        logger.debug(f"← Ollama  {len(content)} символов")
        return content.strip()

    def is_available(self) -> bool:
        """Быстрая проверка — запущена ли Ollama."""
        try:
            from core.ai_config import OLLAMA_BASE_URL
            requests.get(OLLAMA_BASE_URL, timeout=2)
            return True
        except Exception:
            return False