"""
core/project_context.py  –  глобальный контекст открытого проекта

AIEngine подхватывает его при каждом запросе и добавляет в system-prompt,
чтобы модель знала о коде пользователя.
"""

_project_context: str = ""
_project_dir: str = ""


def set_project_context(context: str, project_dir: str = "") -> None:
    global _project_context, _project_dir
    _project_context = context
    _project_dir     = project_dir


def get_project_context() -> str:
    return _project_context


def get_project_dir() -> str:
    return _project_dir


def clear_project_context() -> None:
    global _project_context, _project_dir
    _project_context = ""
    _project_dir     = ""


def has_project() -> bool:
    return bool(_project_dir)