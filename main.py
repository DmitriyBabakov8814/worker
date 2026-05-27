"""
main.py  –  W.O.R.K.E.R  точка запуска

Функции:
  - Иконка в системном трее
  - Крестик только сворачивает в трей, не закрывает
  - Закрыть можно только через трей → «Выход»
  - Регистрирует себя в автозапуске Windows
  - Запускает Ollama при старте (ollama serve) если она ещё не запущена
"""

import sys
import os
import subprocess
import threading
import logging
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ── Логирование ───────────────────────────────────────────────────────────────
log_path = os.path.join(BASE_DIR, "worker.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("worker.main")


# ── Ollama автозапуск ─────────────────────────────────────────────────────────

def _ollama_is_running() -> bool:
    """Проверяет, отвечает ли Ollama на localhost:11434."""
    try:
        import requests
        requests.get("http://localhost:11434", timeout=2)
        return True
    except Exception:
        return False


def _find_ollama() -> str | None:
    """Ищет исполняемый файл ollama.exe в стандартных местах."""
    candidates = [
        r"C:\Users\{}\AppData\Local\Programs\Ollama\ollama.exe".format(
            os.environ.get("USERNAME", "")
        ),
        r"C:\Program Files\Ollama\ollama.exe",
        r"C:\Program Files (x86)\Ollama\ollama.exe",
    ]
    # Также ищем в PATH
    import shutil
    in_path = shutil.which("ollama")
    if in_path:
        return in_path

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def start_ollama() -> None:
    """
    Запускает `ollama serve` в фоне если Ollama ещё не запущена.
    Вызывается из фонового потока, чтобы не тормозить старт UI.
    """
    if _ollama_is_running():
        logger.info("Ollama уже запущена")
        return

    ollama_exe = _find_ollama()
    if not ollama_exe:
        logger.warning(
            "ollama.exe не найден. Скачайте с https://ollama.com и установите. "
            "AI-функции будут недоступны."
        )
        return

    try:
        subprocess.Popen(
            [ollama_exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32" else 0
            ),
        )
        logger.info(f"Ollama запущена: {ollama_exe}")

        # Ждём до 15 секунд пока Ollama поднимется
        for _ in range(15):
            time.sleep(1)
            if _ollama_is_running():
                logger.info("Ollama готова к работе")
                return
        logger.warning("Ollama запущена, но долго не отвечает — продолжаем без неё")

    except Exception as e:
        logger.error(f"Не удалось запустить Ollama: {e}")


# ── Автозапуск Windows ────────────────────────────────────────────────────────

def _build_autostart_cmd() -> str:
    python_dir = os.path.dirname(sys.executable)
    pythonw    = os.path.join(python_dir, "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return f'"{pythonw}" "{os.path.abspath(__file__)}"'


def setup_autostart() -> None:
    """Прописывает Jarvis в реестр Windows. Пропускается если уже актуально."""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "WORKER_Assistant"
        cmd      = _build_autostart_cmd()

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path,
                                0, winreg.KEY_READ) as key:
                current, _ = winreg.QueryValueEx(key, app_name)
                if current == cmd:
                    logger.debug("Автозапуск актуален")
                    return
        except FileNotFoundError:
            pass

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path,
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
        logger.info(f"Автозапуск зарегистрирован: {cmd}")

    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Не удалось зарегистрировать автозапуск: {e}")


def remove_autostart() -> None:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path,
                            0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, "WORKER_Assistant")
                logger.info("Автозапуск удалён")
            except FileNotFoundError:
                pass
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Ошибка удаления автозапуска: {e}")


# ── Иконка трея ──────────────────────────────────────────────────────────────

def _make_tray_icon():
    try:
        from PIL import Image, ImageDraw, ImageFont
        img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 62, 62], fill="#030c15", outline="#00d4ff", width=3)
        try:
            font = ImageFont.truetype("arial.ttf", 28)
        except Exception:
            font = ImageFont.load_default()
        draw.text((14, 16), "W", fill="#00d4ff", font=font)
        return img
    except ImportError:
        return None


class TrayManager:
    def __init__(self, app_ref):
        self._app  = app_ref
        self._icon = None

    def start(self) -> None:
        threading.Thread(target=self._run_tray, daemon=True).start()

    def _run_tray(self) -> None:
        try:
            import pystray
            from pystray import MenuItem as Item, Menu

            icon_img = _make_tray_icon()
            if icon_img is None:
                logger.warning("Не удалось создать иконку трея — PIL не установлен")
                return

            menu = Menu(
                Item("W.O.R.K.E.R", lambda: None, enabled=False),
                Menu.SEPARATOR,
                Item("Открыть",  self._on_show),
                Item("Свернуть", self._on_hide),
                Menu.SEPARATOR,
                Item("Выход",    self._on_exit),
            )
            self._icon = pystray.Icon(
                "WORKER", icon_img,
                "W.O.R.K.E.R – Personal AI Assistant",
                menu,
            )
            self._icon.default_action = self._on_show
            self._icon.run()

        except ImportError:
            logger.warning("pystray не установлен: pip install pystray pillow")
        except Exception as e:
            logger.error(f"Ошибка трея: {e}")

    def _on_show(self, icon=None, item=None): self._schedule(self._app.show_window)
    def _on_hide(self, icon=None, item=None): self._schedule(self._app.hide_window)

    def _on_exit(self, icon=None, item=None):
        logger.info("Выход через трей")
        if self._icon:
            self._icon.stop()
        self._schedule(self._app._root.destroy)

    def _schedule(self, fn) -> None:
        if self._app and self._app._root:
            try:
                self._app._root.after(0, fn)
            except Exception:
                pass

    def stop(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass


# ── Запуск ────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=== W.O.R.K.E.R запуск ===")

    setup_autostart()

    # Запускаем Ollama в фоне — не блокирует старт UI
    threading.Thread(target=start_ollama, daemon=True).start()

    from ui.app import JarvisApp
    app  = JarvisApp()
    tray = TrayManager(app)
    app.set_tray(tray)
    tray.start()
    app.run()

    logger.info("=== W.O.R.K.E.R завершён ===")


if __name__ == "__main__":
    main()