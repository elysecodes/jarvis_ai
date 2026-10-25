"""
speech.py - text to speech using pyttsx3 (offline, Windows SAPI5).

Design goals (from AGENTS.md):
  * never crash the program if speech fails - we just switch speech off
  * never block the main loop badly
  * never save audio anywhere

To keep the main loop responsive while still being simple and safe, speech runs
in one background worker thread that owns the pyttsx3 engine. `say()` only puts
text on a queue and returns immediately.
"""

from __future__ import annotations

import logging
import queue
import threading

logger = logging.getLogger(__name__)


class Speaker:
    """A tiny wrapper around pyttsx3 that is safe to call from anywhere."""

    _STOP = object()  # special marker meaning "worker, please finish"

    def __init__(self, enabled: bool = True, rate: int = 175, volume: float = 1.0):
        self.enabled = enabled
        self.rate = rate
        self.volume = volume
        self.available = False  # becomes True once the engine really works
        self._queue: "queue.Queue[object]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._engine = None
        self._warned = False

    # -- public API ---------------------------------------------------------
    def say(self, text: str) -> None:
        """Queue text to be spoken. Returns immediately; never raises."""
        if not self.enabled or not text:
            return
        if self._thread is None or not self._thread.is_alive():
            self._start_worker()
        if self._thread is None:
            return  # worker could not start; speech simply stays off
        try:
            self._queue.put_nowait(str(text))
        except Exception as exc:  # extremely unlikely, but never crash
            self._warn_once(f"Could not queue speech: {exc.__class__.__name__}")

    def stop(self) -> None:
        """Stop speaking the current sentence. Safe to call at any time."""
        try:
            if self._engine is not None:
                self._engine.stop()
        except Exception as exc:  # pyttsx3 can raise on some systems
            logger.debug("speaker.stop() ignored error: %s", exc.__class__.__name__)

    def shutdown(self) -> None:
        """Finish speaking what is queued, then stop the worker thread."""
        if self._thread is None:
            return
        self._queue.put(self._STOP)
        self._thread.join(timeout=10)
        self._thread = None
        self._engine = None

    # -- internals ----------------------------------------------------------
    def _start_worker(self) -> None:
        self._thread = threading.Thread(target=self._run, name="jarvis-speaker", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """Own the pyttsx3 engine here, in this one thread."""
        try:
            import pyttsx3
        except Exception as exc:
            self._warn_once(
                "Speech is off: pyttsx3 is not installed. Run: pip install pyttsx3"
            )
            logger.warning("pyttsx3 import failed: %s", exc.__class__.__name__)
            self._drain_without_speaking()
            return

        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            engine.setProperty("volume", self.volume)
        except Exception as exc:
            self._warn_once(
                "Speech is off: no working Windows voice was found. JARVIS will answer in text only."
            )
            logger.warning("pyttsx3 init failed: %s", exc.__class__.__name__)
            self._drain_without_speaking()
            return

        self._engine = engine
        self.available = True

        while True:
            item = self._queue.get()
            if item is self._STOP:
                break
            try:
                engine.say(str(item))
                engine.runAndWait()
            except Exception as exc:
                # Speaking one sentence failed: keep the assistant alive.
                self._warn_once(
                    "Speech had a problem and was switched off. JARVIS continues in text."
                )
                logger.warning("pyttsx3 failed while speaking: %s", exc.__class__.__name__)
                self.enabled = False
                break

        try:
            engine.stop()
        except Exception:
            pass

    def _drain_without_speaking(self) -> None:
        """If speech is dead, still consume the queue so it cannot grow forever."""
        while True:
            item = self._queue.get()
            if item is self._STOP:
                return

    def _warn_once(self, message: str) -> None:
        if not self._warned:
            self._warned = True
            print(f"[speech] {message}")

    def shutdown_and_wait(self, seconds: float = 5.0) -> None:
        """Convenience: wait up to `seconds` for queued speech, then stop."""
        if self._thread is None:
            return
        self._queue.put(self._STOP)
        self._thread.join(timeout=seconds)
        self._thread = None
        self._engine = None
