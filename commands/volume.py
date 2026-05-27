"""
commands/volume.py  –  управление громкостью системы Windows

Использует pycaw (Windows Core Audio API).
Установка: pip install pycaw comtypes

Команды:
  «прибавь громкость» / «громче»        → +10%
  «убавь громкость»  / «тише»           → -10%
  «прибавь громкость на 20»             → +20%
  «убавь громкость на 30»               → -30%
  «максимальная громкость»              → 100%
  «минимальная громкость» / «выключи звук» → 0%

ИСПРАВЛЕНО:
  - CoInitialize вызывается в каждом потоке перед обращением к COM
  - Используется прямой способ получения IAudioEndpointVolume
    через AudioUtilities.GetSpeakers() → Activate() с правильным интерфейсом
"""

import re
import logging
from core.command_dispatcher import BaseCommand

logger = logging.getLogger("worker.commands.volume")

DEFAULT_STEP = 10   # % по умолчанию


def _get_volume_controller():
    """Возвращает объект управления громкостью или None если недоступно."""
    try:
        import comtypes
        # ОБЯЗАТЕЛЬНО инициализируем COM в текущем потоке
        comtypes.CoInitialize()
    except Exception:
        pass  # уже инициализирован — не страшно

    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()

        # Некоторые версии pycaw возвращают объект с методом Activate,
        # другие — уже готовый интерфейс. Обрабатываем оба случая.
        if hasattr(devices, 'Activate'):
            interface = devices.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None
            )
            volume = cast(interface, POINTER(IAudioEndpointVolume))
        else:
            # Новый API pycaw — устройство уже является интерфейсом
            from pycaw.pycaw import AudioUtilities
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL

            # Получаем через IMMDeviceEnumerator напрямую
            from comtypes.client import CreateObject
            from pycaw.pycaw import IMMDeviceEnumerator, EDataFlow, ERole

            enumerator = CreateObject(
                "{BCDE0395-E52F-467C-8E3D-C4579291692E}",
                interface=IMMDeviceEnumerator
            )
            endpoint = enumerator.GetDefaultAudioEndpoint(
                EDataFlow.eRender.value,
                ERole.eMultimedia.value
            )
            interface = endpoint.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None
            )
            volume = cast(interface, POINTER(IAudioEndpointVolume))

        return volume

    except Exception as e:
        logger.error(f"Ошибка контроллера громкости: {type(e).__name__}: {e}")
        return None


def _get_volume_controller_simple():
    """
    Упрощённый способ через ctypes напрямую — работает на любой версии Python/pycaw.
    Используется как fallback если основной способ не работает.
    """
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass

    try:
        from ctypes import cast, POINTER, c_float, windll, pointer, c_uint32
        import comtypes.client as cc

        # GUID интерфейсов
        CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
        IID_IMMDeviceEnumerator  = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
        IID_IAudioEndpointVolume = "{5CDF2C82-841E-4546-9722-0CF74078229A}"

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        # Пробуем через утилиту pycaw напрямую
        speakers = AudioUtilities.GetSpeakers()
        interface = speakers.Activate(
            IAudioEndpointVolume._iid_, CLSCTX_ALL, None
        )
        return cast(interface, POINTER(IAudioEndpointVolume))
    except Exception as e:
        logger.error(f"Fallback контроллер: {type(e).__name__}: {e}")
        return None


def _get_vol():
    """Получает контроллер громкости, пробуя разные способы."""
    vol = _get_volume_controller()
    if vol is None:
        vol = _get_volume_controller_simple()
    return vol


def _get_current_volume_pct() -> float | None:
    """Текущая громкость в % (0–100)."""
    vol = _get_vol()
    if vol is None:
        return None
    try:
        return round(vol.GetMasterVolumeLevelScalar() * 100)
    except Exception as e:
        logger.error(f"Ошибка чтения громкости: {e}")
        return None


def _set_volume_pct(pct: float) -> bool:
    """Устанавливает громкость pct% (0–100). Возвращает True при успехе."""
    pct = max(0.0, min(100.0, pct))
    vol = _get_vol()
    if vol is None:
        return False
    try:
        vol.SetMasterVolumeLevelScalar(pct / 100.0, None)
        logger.info(f"Громкость установлена: {pct:.0f}%")
        return True
    except Exception as e:
        logger.error(f"Ошибка установки громкости: {e}")
        return False


def _extract_step(text: str) -> int:
    """Ищет число в тексте команды, например 'прибавь на 20' → 20."""
    m = re.search(r"\b(\d{1,3})\b", text)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 100:
            return val
    return DEFAULT_STEP


class VolumeUpCommand(BaseCommand):
    TRIGGERS = [
        "прибавь громкость",
        "прибавить громкость",
        "увеличь громкость",
        "сделай громче",
        "громче",
        "увеличить звук",
        "прибавь звук",
    ]

    def execute(self, text: str) -> str:
        step = _extract_step(text)
        current = _get_current_volume_pct()

        if current is None:
            msg = "Не удалось получить доступ к звуку системы."
            self.respond(msg)
            return msg

        new_vol = min(100.0, current + step)
        if _set_volume_pct(new_vol):
            msg = f"Громкость увеличена до {new_vol:.0f}%."
        else:
            msg = "Не удалось изменить громкость."
        self.respond(msg)
        return msg


class VolumeDownCommand(BaseCommand):
    TRIGGERS = [
        "убавь громкость",
        "убавить громкость",
        "уменьши громкость",
        "сделай тише",
        "тише",
        "уменьшить звук",
        "убавь звук",
    ]

    def execute(self, text: str) -> str:
        step = _extract_step(text)
        current = _get_current_volume_pct()

        if current is None:
            msg = "Не удалось получить доступ к звуку системы."
            self.respond(msg)
            return msg

        new_vol = max(0.0, current - step)
        if _set_volume_pct(new_vol):
            msg = f"Громкость уменьшена до {new_vol:.0f}%."
        else:
            msg = "Не удалось изменить громкость."
        self.respond(msg)
        return msg


class VolumeMaxCommand(BaseCommand):
    TRIGGERS = [
        "максимальная громкость",
        "максимальный звук",
        "громкость на максимум",
        "звук на максимум",
    ]

    def execute(self, text: str) -> str:
        if _set_volume_pct(100):
            msg = "Громкость на максимуме."
        else:
            msg = "Не удалось изменить громкость."
        self.respond(msg)
        return msg


class VolumeMuteCommand(BaseCommand):
    TRIGGERS = [
        "выключи звук",
        "отключи звук",
        "минимальная громкость",
        "звук на ноль",
        "без звука",
        "mute",
    ]

    def execute(self, text: str) -> str:
        if _set_volume_pct(0):
            msg = "Звук выключен."
        else:
            msg = "Не удалось выключить звук."
        self.respond(msg)
        return msg