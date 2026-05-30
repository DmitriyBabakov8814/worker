"""
core/ai_engine.py  –  AI-ядро W.O.R.K.E.R

Подхватывает:
  - UserMemory  — долгосрочная память о пользователе
  - ProjectContext — контекст открытого проекта (код файлов)
"""

import logging
from core.ollama_client    import OllamaClient, OllamaConnectionError, OllamaError
from core.dialogue_manager import DialogueManager
from core.ai_config        import SYSTEM_PROMPT, MAX_HISTORY
from core.user_memory      import get_memory, RECALL_TRIGGERS, FORGET_TRIGGERS

logger = logging.getLogger("worker.ai_engine")


class AIEngine:
    def __init__(self, system_prompt=SYSTEM_PROMPT, max_history=MAX_HISTORY):
        self._client      = OllamaClient()
        self._base_prompt = system_prompt
        self._dialogue    = DialogueManager(
            system_prompt=system_prompt, max_history=max_history)
        self._enabled = True
        logger.info("AIEngine инициализирован")

    def ask(self, text: str) -> str:
        if not self._enabled:
            return "AI-модуль отключён."
        if not text or not text.strip():
            return "Пустой запрос."

        text = text.strip()
        logger.info(f"AI запрос: {text[:80]}")

        # Режим проекта: контекст только открытой папки, без общей памяти
        try:
            from core.project_context import has_project, get_project_context, get_project_dir
            in_project = has_project()
        except Exception:
            in_project = False
            get_project_context = lambda: ""  # noqa: E731
            get_project_dir = lambda: ""  # noqa: E731

        if not in_project:
            mem = get_memory()
            tl  = text.lower()

            if any(tl.startswith(t) or t in tl for t in RECALL_TRIGGERS):
                return mem.recall_text()
            if any(tl.startswith(t) or t in tl for t in FORGET_TRIGGERS):
                return mem.forget_all()

            changes = mem.extract_and_save(text)
        else:
            changes = []

        prompt_parts = []

        if in_project:
            import os
            dir_name = os.path.basename(get_project_dir()) or "проект"
            ctx = get_project_context()
            prompt_parts.append(
                "Ты — AI-программист, работающий с открытым проектом пользователя.\n"
                "КРИТИЧЕСКИ ВАЖНО: отвечай ТОЛЬКО на русском языке.\n\n"
                "У тебя есть полный доступ к файлам проекта. Ты знаешь каждый файл "
                "и каждую строку кода. Пользователь работает ТОЛЬКО через тебя — "
                "ты анализируешь код, предлагаешь решения и РЕДАКТИРУЕШЬ файлы.\n\n"
                f"Проект «{dir_name}». Файлы:\n\n{ctx}\n\n"
                "Когда нужно изменить код — ОБЯЗАТЕЛЬНО используй формат:\n"
                "EDIT: путь/к/файлу.py\n"
                "```python\n"
                "полное новое содержимое файла\n"
                "```\n\n"
                "Можно изменить несколько файлов — несколько блоков EDIT.\n"
                "Сначала кратко объясни что делаешь, потом блоки EDIT.\n"
                "Если пользователь просит изменить поведение — сам найди нужный файл "
                "и внеси правки. Не проси пользователя копировать код."
            )
        else:
            prompt_parts.append(self._base_prompt)
            mem = get_memory()
            mem_snippet = mem.as_prompt_snippet()
            if mem_snippet:
                prompt_parts.append(mem_snippet)

        self._dialogue._system_prompt = "\n\n".join(prompt_parts)

        self._dialogue.add_user(text)
        messages = self._dialogue.get_messages()

        try:
            reply = self._client.chat(messages)
        except OllamaConnectionError as e:
            logger.warning(str(e))
            self._dialogue._history.pop()
            return "Ollama не запущена. Запустите: ollama serve"
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

        if changes:
            return reply + "  [запомнил: " + ", ".join(changes) + "]"
        return reply

    def clear_history(self) -> str:
        self._dialogue.clear()
        return "История диалога очищена."

    def enable(self):  self._enabled = True
    def disable(self): self._enabled = False

    @property
    def is_available(self) -> bool:
        return self._client.is_available()

    @property
    def turn_count(self) -> int:
        return self._dialogue.turn_count