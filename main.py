"""
main.py  –  W.O.R.K.E.R  точка запуска

Функции:
  - Иконка в системном трее (правый нижний угол, стрелочка)
  - Скрыт из панели задач и рабочего стола
  - Крестик только сворачивает в трей, не закрывает
  - Закрыть можно только через трей → «Выход»
  - При первом запуске регистрирует себя в автозапуске Windows
"""

import sys
import os
import threading
import logging

# Добавляем папку проекта в путь
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
    ]
)
logger = logging.getLogger("worker.main")


# ── Автозапуск Windows ────────────────────────────────────────────────────────

def setup_autostart():
    """
    Прописывает программу в реестр Windows для автозапуска.
    HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
    Работает только на Windows, на других ОС молча пропускается.
    """
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "WORKER_Assistant"

        # Путь к pythonw.exe (без консоли) + скрипт
        python_dir = os.path.dirname(sys.executable)
        pythonw    = os.path.join(python_dir, "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable  # fallback

        script = os.path.abspath(__file__)
        cmd    = f'"{pythonw}" "{script}"'

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path,
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
        logger.info(f"Автозапуск зарегистрирован: {cmd}")
    except ImportError:
        pass  # не Windows
    except Exception as e:
        logger.warning(f"Не удалось зарегистрировать автозапуск: {e}")


def remove_autostart():
    """Удаляет запись автозапуска (вызывается при выходе через трей)."""
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
    """Создаёт иконку для трея программно (синий круг с буквой W)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Тёмно-синий фон
        draw.ellipse([2, 2, 62, 62], fill="#030c15", outline="#00d4ff", width=3)
        # Буква W
        try:
            font = ImageFont.truetype("arial.ttf", 28)
        except Exception:
            font = ImageFont.load_default()
        draw.text((14, 16), "W", fill="#00d4ff", font=font)
        return img
    except ImportError:
        # PIL нет — минимальный 16x16 PNG через bytes
        import struct, zlib
        def _png1x1(r, g, b):
            # 16x16 однотонная иконка
            raw = bytes([r, g, b, 255] * 16) * 16
            def chunk(name, data):
                c = zlib.crc32(name + data) & 0xffffffff
                return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)
            ihdr = struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0)
            idat = zlib.compress(b"".join(b"\x00" + raw[i*64:(i+1)*64] for i in range(16)))
            data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
            import io
            from tkinter import PhotoImage
            return data  # вернём bytes, pystray примет
        # pystray умеет работать с PIL Image, без PIL используем заглушку
        try:
            from PIL import Image
            img = Image.new("RGB", (16, 16), "#030c15")
            return img
        except Exception:
            return None


class TrayManager:
    """Управляет иконкой в системном трее."""

    def __init__(self, app_ref):
        self._app  = app_ref   # ссылка на JarvisApp
        self._icon = None

    def start(self):
        """Запускает трей в отдельном потоке."""
        t = threading.Thread(target=self._run_tray, daemon=True)
        t.start()

    def _run_tray(self):
        try:
            import pystray
            from pystray import MenuItem as Item, Menu

            icon_img = _make_tray_icon()
            if icon_img is None:
                logger.warning("Не удалось создать иконку трея")
                return

            menu = Menu(
                Item("W.O.R.K.E.R", lambda: None, enabled=False),
                Menu.SEPARATOR,
                Item("Открыть",    self._on_show),
                Item("Свернуть",   self._on_hide),
                Menu.SEPARATOR,
                Item("Выход",      self._on_exit),
            )

            self._icon = pystray.Icon(
                "WORKER",
                icon_img,
                "W.O.R.K.E.R – Personal AI Assistant",
                menu,
            )
            # Двойной клик — показать окно
            self._icon.default_action = self._on_show
            self._icon.run()
        except ImportError:
            logger.warning("pystray не установлен — трей недоступен. "
                           "Установите: pip install pystray pillow")
        except Exception as e:
            logger.error(f"Ошибка трея: {e}")

    def _on_show(self, icon=None, item=None):
        if self._app and self._app._root:
            try:
                self._app._root.after(0, self._app.show_window)
            except Exception:
                pass

    def _on_hide(self, icon=None, item=None):
        if self._app and self._app._root:
            try:
                self._app._root.after(0, self._app.hide_window)
            except Exception:
                pass

    def _on_exit(self, icon=None, item=None):
        """Настоящий выход — только через трей."""
        logger.info("Выход через трей")
        if self._icon:
            self._icon.stop()
        if self._app and self._app._root:
            try:
                self._app._root.after(0, self._app._root.destroy)
            except Exception:
                pass

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass


# ── Запуск ────────────────────────────────────────────────────────────────────

def main():
    logger.info("=== W.O.R.K.E.R запуск ===")

    # Регистрируем автозапуск
    setup_autostart()

    # Импортируем UI
    from ui.app import JarvisApp

    app  = JarvisApp()
    tray = TrayManager(app)

    # Передаём ссылку на трей в app (для кнопки выхода и закрытия)
    app.set_tray(tray)

    # Запускаем трей (фон)
    tray.start()

    # Запускаем UI — блокирует до закрытия окна
    app.run()

    logger.info("=== W.O.R.K.E.R завершён ===")


if __name__ == "__main__":
    main()