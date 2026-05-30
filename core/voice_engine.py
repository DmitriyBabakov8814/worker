"""
core/voice_engine.py — исправленная версия

Ключевые исправления против дублирования:
  - on_command вызывается ТОЛЬКО из _execute_command
  - on_transcript вызывается ТОЛЬКО для голосовых команд (from_voice=True)
  - send_text_command больше не используется — app.py диспатчит напрямую
  - _loop_text_only читает из очереди но сам ничего не делает с on_transcript
"""

import threading
import queue
import time
import logging
import os
import tempfile

logger = logging.getLogger("worker.voice")

SAMPLE_RATE      = 16000
CHANNELS         = 1
PHRASE_SEC       = 7
SILENCE_SEC      = 1.2
ENERGY_THRESHOLD = 500
MIC_TOGGLE_WORD  = "микрофон"
MIC_TOGGLE_PHRASES = (
    "микрофон",
    "выключи микрофон",
    "включи микрофон",
    "заглуши микрофон",
    "отключи микрофон",
)


class VoiceEngine:
    def __init__(self, on_state_change=None, on_transcript=None,
                 on_command=None, on_mute_change=None):
        self.on_state_change = on_state_change
        self.on_transcript   = on_transcript
        self.on_command      = on_command
        self.on_mute_change  = on_mute_change

        self._state     = "listening"
        self._running   = False
        self._thread    = None

        self._sd_ok     = False
        self._sr_ok     = False
        self._recognizer = None

        self._muted     = False
        self._mute_lock = threading.Lock()

        self._load_libs()

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self):
        if self._running: return
        self._running = True
        self._set_state("listening")
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("VoiceEngine started")

    def stop(self):
        self._running = False

    @property
    def state(self): return self._state

    @property
    def is_muted(self) -> bool: return self._muted

    def mute(self):
        with self._mute_lock:
            if not self._muted:
                self._muted = True
                self._fire_mute(True)

    def unmute(self):
        with self._mute_lock:
            if self._muted:
                self._muted = False
                self._fire_mute(False)

    def toggle_mute(self) -> bool:
        with self._mute_lock:
            self._muted = not self._muted
            state = self._muted
        self._fire_mute(state)
        return state

    def speak(self, text: str):
        pass  # TTS отключён

    # ── Init ──────────────────────────────────────────────────────────────────

    def _load_libs(self):
        try:
            import sounddevice, scipy, numpy
            self._sd_ok = True
        except ImportError as e:
            logger.warning(f"sounddevice/scipy недоступны: {e}")
        try:
            import speech_recognition as sr
            self._recognizer = sr.Recognizer()
            self._recognizer.pause_threshold          = SILENCE_SEC
            self._recognizer.energy_threshold         = ENERGY_THRESHOLD
            self._recognizer.dynamic_energy_threshold = True
            self._sr_ok = True
        except ImportError as e:
            logger.warning(f"SpeechRecognition недоступен: {e}")

    def _set_state(self, state: str):
        self._state = state
        if self.on_state_change:
            try: self.on_state_change(state)
            except Exception: pass

    def _fire_mute(self, is_muted: bool):
        if self.on_mute_change:
            try: self.on_mute_change(is_muted)
            except Exception as e: logger.error(f"on_mute_change: {e}")

    @staticmethod
    def _is_mic_toggle(text: str) -> bool:
        t = text.strip().lower()
        return t in MIC_TOGGLE_PHRASES or t == MIC_TOGGLE_WORD

    # ── Loops ─────────────────────────────────────────────────────────────────

    def _listen_loop(self):
        if self._sd_ok and self._sr_ok:
            self._loop_sounddevice()
        else:
            logger.warning("Аудио недоступно → режим ожидания голоса")
            self._loop_idle()

    def _loop_sounddevice(self):
        import sounddevice as sd
        import numpy as np
        import speech_recognition as sr
        from scipy.io import wavfile

        BLOCK          = int(SAMPLE_RATE * 0.5)
        SILENCE_BLOCKS = int(SILENCE_SEC / 0.5)
        MAX_BLOCKS     = int(PHRASE_SEC / 0.5)

        audio_buf   = []
        silent_blks = 0
        recording   = False

        while self._running:
            try:
                block = sd.rec(BLOCK, samplerate=SAMPLE_RATE,
                               channels=CHANNELS, dtype="int16")
                sd.wait()
                flat = block.flatten()
                rms  = int(np.sqrt(np.mean(flat.astype(np.float32) ** 2)))

                if rms > ENERGY_THRESHOLD:
                    audio_buf.append(flat); silent_blks = 0; recording = True
                elif recording:
                    silent_blks += 1
                    audio_buf.append(flat)

                    if silent_blks >= SILENCE_BLOCKS:
                        data = np.concatenate(audio_buf)
                        audio_buf = []; silent_blks = 0; recording = False

                        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                        tmp_path = tmp.name; tmp.close()
                        wavfile.write(tmp_path, SAMPLE_RATE, data.astype(np.int16))

                        with sr.AudioFile(tmp_path) as src:
                            audio_sr = self._recognizer.record(src)
                        try: os.unlink(tmp_path)
                        except Exception: pass

                        try:
                            text = self._recognizer.recognize_google(
                                audio_sr, language="ru-RU").lower().strip()
                            logger.info(f"Распознано: '{text}'")
                            self._handle_voice(text)
                        except sr.UnknownValueError: pass
                        except sr.RequestError as e:
                            logger.error(f"Google API: {e}")

                    if len(audio_buf) > MAX_BLOCKS:
                        audio_buf = []; silent_blks = 0; recording = False

            except Exception as e:
                logger.error(f"Ошибка записи: {e}")
                time.sleep(0.5)

    def _loop_idle(self):
        """Когда аудио недоступно — просто держим поток живым."""
        while self._running:
            time.sleep(1)

    def _handle_voice(self, text: str):
        """
        Обработка распознанной голосовой команды.
        Единственное место где вызываются on_transcript и on_command.
        """
        if not text: return

        # Триггер мута — работает всегда (в т.ч. когда микрофон заглушён)
        if self._is_mic_toggle(text):
            new_state = self.toggle_mute()
            status = "выключен" if new_state else "включён"
            if self.on_transcript:
                try: self.on_transcript(f"Микрофон {status}", True)
                except Exception: pass
            return

        if self._muted:
            return

        # 1. Показываем что сказал пользователь (ОДИН РАЗ)
        if self.on_transcript:
            try: self.on_transcript(text, False)
            except Exception: pass

        # 2. Выполняем команду (ОДИН РАЗ)
        self._set_state("processing")
        if self.on_command:
            try: self.on_command(text)
            except Exception as e: logger.error(f"on_command: {e}")
        self._set_state("listening")