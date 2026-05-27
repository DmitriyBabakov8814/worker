"""
core/voice_engine.py

Режим: БЕЗ wake-word, БЕЗ озвучки.
Программа всегда слушает микрофон и сразу выполняет команды.
Распознавание: Google Speech API через sounddevice + scipy.
TTS: отключён полностью — Jarvis молчит.
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


class VoiceEngine:
    def __init__(self, on_state_change=None, on_transcript=None, on_command=None):
        self.on_state_change = on_state_change
        self.on_transcript   = on_transcript
        self.on_command      = on_command

        self._state     = "listening"
        self._running   = False
        self._thread    = None
        self._cmd_queue: queue.Queue = queue.Queue()

        self._sd_ok      = False
        self._sr_ok      = False
        self._recognizer = None

        self._load_libs()

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._set_state("listening")
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("VoiceEngine started (no wake-word, no TTS)")

    def stop(self):
        self._running = False

    @property
    def state(self):
        return self._state

    def speak(self, text: str):
        """Озвучка отключена — метод оставлен для совместимости, но ничего не делает."""
        logger.debug(f"[SPEAK disabled] {text}")

    def send_text_command(self, text: str):
        self._cmd_queue.put(text)

    # ── Init ──────────────────────────────────────────────────────────────────

    def _load_libs(self):
        try:
            import sounddevice
            import scipy
            import numpy
            self._sd_ok = True
            logger.info("sounddevice OK")
        except ImportError as e:
            logger.warning(f"sounddevice/scipy недоступны: {e}")

        try:
            import speech_recognition as sr
            self._recognizer = sr.Recognizer()
            self._recognizer.pause_threshold        = SILENCE_SEC
            self._recognizer.energy_threshold       = ENERGY_THRESHOLD
            self._recognizer.dynamic_energy_threshold = True
            self._sr_ok = True
            logger.info("SpeechRecognition OK")
        except ImportError as e:
            logger.warning(f"SpeechRecognition недоступен: {e}")

    # ── State ─────────────────────────────────────────────────────────────────

    def _set_state(self, state: str):
        self._state = state
        if self.on_state_change:
            self.on_state_change(state)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _listen_loop(self):
        if self._sd_ok and self._sr_ok:
            logger.info("Режим: sounddevice + Google Speech API")
            self._loop_sounddevice()
        else:
            logger.warning("Аудио недоступно → текстовый режим")
            self._loop_text_only()

    # ── sounddevice loop ──────────────────────────────────────────────────────

    def _loop_sounddevice(self):
        import sounddevice as sd
        import numpy as np
        import speech_recognition as sr
        from scipy.io import wavfile

        BLOCK         = int(SAMPLE_RATE * 0.5)
        SILENCE_BLOCKS = int(SILENCE_SEC / 0.5)
        MAX_BLOCKS    = int(PHRASE_SEC / 0.5)

        audio_buf  = []
        silent_blks = 0
        recording  = False

        while self._running:
            try:
                cmd = self._cmd_queue.get_nowait()
                self._execute_command(cmd)
            except queue.Empty:
                pass

            try:
                block = sd.rec(BLOCK, samplerate=SAMPLE_RATE,
                               channels=CHANNELS, dtype="int16")
                sd.wait()
                flat = block.flatten()
                rms  = int(np.sqrt(np.mean(flat.astype(np.float32) ** 2)))

                if rms > ENERGY_THRESHOLD:
                    audio_buf.append(flat)
                    silent_blks = 0
                    recording   = True
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
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass

                        try:
                            text = self._recognizer.recognize_google(
                                audio_sr, language="ru-RU"
                            ).lower().strip()
                            logger.debug(f"Распознано: '{text}'")
                            self._execute_command(text)
                        except sr.UnknownValueError:
                            pass
                        except sr.RequestError as e:
                            logger.error(f"Google API: {e}")

                    if len(audio_buf) > MAX_BLOCKS:
                        audio_buf = []; silent_blks = 0; recording = False

            except Exception as e:
                logger.error(f"Ошибка записи: {e}")
                time.sleep(0.5)

    # ── Текстовый режим ───────────────────────────────────────────────────────

    def _loop_text_only(self):
        while self._running:
            try:
                cmd = self._cmd_queue.get(timeout=1)
                self._execute_command(cmd)
            except queue.Empty:
                pass

    # ── Выполнение команды ────────────────────────────────────────────────────

    def _execute_command(self, text: str):
        if not text:
            return
        text = text.lower().strip()
        if self.on_transcript:
            self.on_transcript(text, False)
        self._set_state("processing")
        if self.on_command:
            self.on_command(text)
        self._set_state("listening")