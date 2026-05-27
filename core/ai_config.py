"""
core/ai_config.py  –  конфигурация AI-слоя

Все настройки AI в одном месте. Менять здесь, не трогая логику.
"""

# ── Ollama ────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL  = "http://localhost:11434"
OLLAMA_CHAT_URL  = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_MODEL     = "qwen2.5:7b"
OLLAMA_TIMEOUT   = 60        # секунды ожидания ответа
OLLAMA_STREAM    = False     # True = стриминг (пока не используем)

# ── Диалог ────────────────────────────────────────────────────────────────────
MAX_HISTORY      = 20        # максимум сообщений в истории (user + assistant пары)

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are Jarvis, a local AI assistant running on the user's PC. "
    "You answer clearly and intelligently. "
    "You help the user solve tasks and answer questions. "
    "You are technical, concise and helpful. "
    "Always respond in the same language the user writes in."
)

# ── Триггеры — какие фразы отправляются в AI, а не в команды ─────────────────
# Если CommandDispatcher не нашёл команду, UnknownCommand может передать
# управление сюда. Также можно явно адресовать AI:
AI_PREFIXES = (
    "скажи", "объясни", "что такое", "расскажи", "как работает",
    "почему", "зачем", "помоги", "напиши", "придумай", "переведи",
    "реши", "посчитай", "вычисли", "сравни", "что лучше",
    "ии", "нейросеть", "jarvis", "джарвис",
)