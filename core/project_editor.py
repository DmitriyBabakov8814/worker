"""
core/project_editor.py — чтение/запись файлов проекта и применение правок от AI.
"""

import os
import re
import logging

logger = logging.getLogger("worker.project_editor")

# Расширения текстовых файлов для чтения
TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".md",
    ".txt", ".xml", ".sql", ".sh", ".bat", ".ps1", ".cs", ".cpp",
    ".c", ".h", ".java", ".go", ".rs", ".php", ".rb", ".swift",
    ".kt", ".dart", ".vue", ".svelte", ".env", ".log",
}

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".idea", ".vscode", "dist", "build", ".next", ".nuxt",
    "coverage", ".cursor",
}

MAX_FILE_SIZE = 200 * 1024
MAX_TOTAL_CHARS = 120_000


def scan_all_files(project_dir: str) -> list[str]:
    if not project_dir or not os.path.isdir(project_dir):
        return []
    found: list[str] = []
    for root_dir, dirs, filenames in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in sorted(filenames):
            fpath = os.path.join(root_dir, fname)
            rel = os.path.relpath(fpath, project_dir).replace("\\", "/")
            found.append(rel)
    return found


def read_project_files(project_dir: str) -> tuple[dict[str, str], int, list[str]]:
    """Читает текстовые файлы. Возвращает (files, skipped_count, all_paths)."""
    all_paths = scan_all_files(project_dir)
    files: dict[str, str] = {}
    total_chars = 0
    skipped = 0

    if not project_dir or not os.path.isdir(project_dir):
        return files, skipped, all_paths

    for rel in all_paths:
        ext = os.path.splitext(rel)[1].lower()
        if ext not in TEXT_EXTENSIONS:
            continue
        fpath = os.path.join(project_dir, rel.replace("/", os.sep))
        try:
            size = os.path.getsize(fpath)
            if size > MAX_FILE_SIZE:
                skipped += 1
                continue
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if total_chars + len(content) > MAX_TOTAL_CHARS:
                skipped += 1
                continue
            files[rel] = content
            total_chars += len(content)
        except Exception as e:
            logger.debug(f"skip {fpath}: {e}")
            skipped += 1

    return files, skipped, all_paths


def build_context(files: dict[str, str]) -> str:
    parts = [f"=== {path} ===\n{content}" for path, content in files.items()]
    return "\n\n".join(parts)


def write_file(project_dir: str, rel_path: str, content: str) -> None:
    fpath = os.path.join(project_dir, rel_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    logger.info(f"Записан файл: {rel_path}")


def parse_ai_edits(text: str) -> list[tuple[str, str]]:
    """
    Извлекает блоки правок из ответа AI:
      EDIT: path/to/file.py
      ```python
      ...содержимое...
      ```
    """
    edits: list[tuple[str, str]] = []
    pattern = re.compile(
        r"EDIT:\s*([^\n\r`]+)\s*\n```(?:\w*\n)?([\s\S]*?)```",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        path = m.group(1).strip().replace("\\", "/")
        content = m.group(2)
        if content.endswith("\n"):
            content = content[:-1]
        edits.append((path, content))
    return edits


def apply_ai_edits(project_dir: str, text: str) -> list[str]:
    """Применяет правки из ответа AI. Возвращает список изменённых файлов."""
    changed: list[str] = []
    for path, content in parse_ai_edits(text):
        try:
            write_file(project_dir, path, content)
            changed.append(path)
        except Exception as e:
            logger.error(f"apply edit {path}: {e}")
    return changed
