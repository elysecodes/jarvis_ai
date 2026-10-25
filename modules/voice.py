"""
voice.py - offline speech recognition (Phase 2).

How it works:
  * sounddevice records small blocks of audio from your microphone.
  * Vosk turns those blocks into text, completely offline on your computer.
  * JARVIS waits for the wake word ("hey jarvis" - "jarvis" alone also works),
    then listens for exactly ONE command and hands the text to command_router.

Privacy: audio lives in memory for a fraction of a second and is never written
to disk and never sent anywhere. Only the recognised text is used.

The speech-recognition engine sits behind one small interface (`SpeechToText`),
so it can be swapped later without touching the rest of the program.
"""

from __future__ import annotations

import array
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import config

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # Vosk's small English model expects 16 kHz audio
BLOCK_SIZE = 4000  # 0.25 seconds per audio block: responsive without being heavy

# Where --debug-voice writes what it sees, so it can be inspected afterwards.
DEBUG_LOG = config.LOG_DIR / "voice_debug.log"


class VoiceError(Exception):
    """A microphone / model problem. The message is written for the user."""


# ---------------------------------------------------------------------------
# Wake-word logic (pure functions - easy to test without a microphone)
# ---------------------------------------------------------------------------
@dataclass
class WakeResult:
    found: bool
    command: str = ""  # whatever was said after the wake word, if anything


def normalise_text(text: str | None) -> str:
    """Lower-case and tidy a transcript so matching is reliable."""
    cleaned = re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def find_wake_word(text: str | None, wake_word: str | None = None) -> WakeResult:
    """Look for the wake word and return it plus anything said afterwards.

    Examples:
        "hey jarvis"                     -> found, command ""
        "jarvis what is the time"        -> found, command "what is the time"
        "hey jarvis, open notepad"       -> found, command "open notepad"
        "hello there"                    -> not found
    """
    cleaned = normalise_text(text)
    if not cleaned:
        return WakeResult(False)

    # Always accept the plain word "jarvis" as well as the configured phrase.
    phrases = {"jarvis"}
    if wake_word:
        phrases.add(normalise_text(wake_word))
    phrases = {p for p in phrases if p}

    best: WakeResult | None = None
    for phrase in phrases:
        pattern = r"\b" + r"\s+".join(re.escape(word) for word in phrase.split()) + r"\b"
        match = re.search(pattern, cleaned)
        if match:
            command = cleaned[match.end():].strip()
            # Prefer the match that leaves the most useful command behind.
            if best is None or len(command) > len(best.command):
                best = WakeResult(True, command)
    return best or WakeResult(False)


def extract_command(text: str | None, wake_word: str | None = None) -> str:
    """Return the command part of a transcript (everything after the wake word).

    If there is no wake word we assume the whole transcript is the command, so
    the function also works for the second and later phrases of a sentence.
    """
    result = find_wake_word(text, wake_word)
    return result.command if result.found else normalise_text(text)


# ---------------------------------------------------------------------------
# Swappable speech-to-text engine
# ---------------------------------------------------------------------------
class SpeechToText:
    """The small interface every speech engine must follow.

    feed(pcm)  -> (text, is_final). `is_final` is True when Vosk decided a
                  sentence ended; `text` is a partial guess otherwise.
    flush()    -> the last unfinished text (used when a timer runs out).
    reset()    -> start a fresh utterance.
    """

    def reset(self) -> None:  # pragma: no cover - overridden by subclasses
        raise NotImplementedError

    def feed(self, pcm: bytes) -> tuple[str, bool]:  # pragma: no cover
        raise NotImplementedError

    def flush(self) -> str:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover
        pass


class VoskSTT(SpeechToText):
    """Offline speech recognition using the Vosk library and a local model."""

    def __init__(self, model_path: Path | str | None = None, sample_rate: int = SAMPLE_RATE):
        self.model_path = Path(model_path or config.VOSK_MODEL_PATH)
        self.sample_rate = sample_rate
        self._vosk = None
        self._model = None
        self._recognizer = None
        self._start()

    def _start(self) -> None:
        try:
            import vosk  # imported here so a missing package cannot break start-up
        except Exception:
            raise VoiceError(
                "Speech recognition is not installed. Run: pip install vosk"
            ) from None

        if not self.model_path.is_dir():
            raise VoiceError(
                f"The offline speech model was not found at: {self.model_path}\n"
                "Download 'vosk-model-small-en-us-0.15' and unzip it into the models "
                "folder (see README.md, Phase 2)."
            )

        self._vosk = vosk
        try:
            vosk.SetLogLevel(-1)  # keep the console tidy
            self._model = vosk.Model(str(self.model_path))
        except Exception as exc:
            logger.warning("Could not load Vosk model: %s", exc.__class__.__name__)
            raise VoiceError(
                "The speech model could not be loaded. Try downloading it again "
                "(see README.md, Phase 2)."
            ) from None
        self.reset()

    def reset(self) -> None:
        self._recognizer = self._vosk.KaldiRecognizer(self._model, self.sample_rate)

    def feed(self, pcm: bytes) -> tuple[str, bool]:
        """Give the engine 0.25 s of audio and get text back."""
        if self._recognizer.AcceptWaveform(pcm):
            text = json.loads(self._recognizer.Result()).get("text", "")
            return text.strip(), True
        partial = json.loads(self._recognizer.PartialResult()).get("partial", "")
        return partial.strip(), False

    def flush(self) -> str:
        """Finish the current utterance and return whatever it recognised."""
        text = json.loads(self._recognizer.FinalResult()).get("text", "")
        self.reset()
        return text.strip()

    def close(self) -> None:
        self._recognizer = None
        self._model = None


# ---------------------------------------------------------------------------
# Microphone handling
# ---------------------------------------------------------------------------
def _import_sounddevice():
    try:
        import sounddevice as sd
    except Exception:
        raise VoiceError(
            "Microphone support is not installed. Run: pip install sounddevice"
        ) from None
    return sd


def list_input_devices() -> list[tuple[int, str]]:
    """Return (index, name) for every device that can record audio."""
    sd = _import_sounddevice()
    found: list[tuple[int, str]] = []
    try:
        devices = sd.query_devices()
    except Exception as exc:
        raise VoiceError(_microphone_message(None, exc)) from None
    for index, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) > 0:
            found.append((index, str(device.get("name", "unknown"))))
    return found


def _microphone_message(device, exc: Exception) -> str:
    where = "the default microphone" if device is None else f"device {device!r}"
    return (
        f"I could not use {where} ({exc.__class__.__name__}). "
        "Check that a microphone is connected, that Windows lets apps use it "
        "(Settings > Privacy > Microphone), and pick one with --list-devices "
        "and --device N. You can also run with --text."
    )


def check_microphone(device=None) -> None:
    """Raise VoiceError if sounddevice cannot find a usable input device."""
    sd = _import_sounddevice()
    try:
        sd.query_devices(device, kind="input")
    except Exception as exc:
        raise VoiceError(_microphone_message(device, exc)) from None


# ---------------------------------------------------------------------------
# The listener: wake word -> one command
# ---------------------------------------------------------------------------
class VoiceListener:
    """Waits for the wake word, records one command, and returns its text."""

    def __init__(
        self,
        stt_factory=VoskSTT,
        device=None,
        wake_word: str | None = None,
        command_timeout: float | None = None,
        wake_timeout: float | None = None,
        on_wake=None,
        on_partial=None,
        debug: bool = False,
    ):
        self._stt_factory = stt_factory
        self.device = config.INPUT_DEVICE if device is None else device
        self.wake_word = wake_word or config.WAKE_WORD
        self.command_timeout = (
            config.COMMAND_TIMEOUT if command_timeout is None else command_timeout
        )
        self.wake_timeout = config.WAKE_TIMEOUT if wake_timeout is None else wake_timeout
        self.on_wake = on_wake  # called (no args) the moment the wake word is heard
        self.on_partial = on_partial  # called with the running transcript
        self.debug = debug  # print the live mic level and every word recognised
        self._stt: SpeechToText | None = None
        self._last_file_meter = 0.0

    # -- public API ---------------------------------------------------------
    def listen_for_command(self) -> str | None:
        """Block until the wake word plus one command are heard.

        Returns the command text, or None if nothing was said in time.
        Raises VoiceError for microphone / model problems.
        """
        if self.debug:
            self._dbg(f"--- listening, device={self.device!r} ---")
        sd = _import_sounddevice()
        stt = self._ensure_stt()
        stt.reset()

        try:
            # RawInputStream returns plain bytes - no numpy needed, one less
            # package to install (Vosk reads bytes directly).
            stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                channels=1,
                dtype="int16",
                device=self.device,
            )
        except Exception as exc:
            logger.warning("Could not open microphone: %s", exc.__class__.__name__)
            raise VoiceError(_microphone_message(self.device, exc)) from None

        wake_found = False
        command_text = ""
        started = time.monotonic()
        command_deadline = started + 1e9  # replaced as soon as the wake word is heard
        last_meter = started

        with stream:
            while True:
                try:
                    block, overflowed = stream.read(BLOCK_SIZE)
                except Exception as exc:
                    logger.warning("Microphone read failed: %s", exc.__class__.__name__)
                    raise VoiceError(_microphone_message(self.device, exc)) from None
                if overflowed:
                    logger.debug("Audio input overflow (block dropped)")

                pcm = bytes(block)
                now = time.monotonic()

                if self.debug and now - last_meter > 0.5:
                    samples = array.array("h")
                    samples.frombytes(pcm)
                    peak = max((abs(v) for v in samples), default=0)
                    bar = "#" * min(20, peak // 600) + "." * (20 - min(20, peak // 600))
                    print(f"\r  [{bar}] peak={peak:<5}", end="", flush=True)
                    self._dbg_meter(peak)
                    last_meter = now

                text, is_final = stt.feed(pcm)

                if not wake_found:
                    result = find_wake_word(text, self.wake_word)
                    if result.found:
                        wake_found = True
                        command_deadline = now + self.command_timeout
                        logger.info("Wake word detected")
                        self._dbg(f"[heard] {text!r}  -> WAKE WORD")
                        if self.on_wake:
                            self.on_wake()
                        if result.command:
                            command_text = result.command
                    else:
                        if self.debug and text:
                            kind = "final " if is_final else "partial"
                            self._dbg(f"[{kind}] {text!r}")
                        if self.wake_timeout and now - started > self.wake_timeout:
                            return None
                    continue

                # --- listening for the one command -------------------------
                if self.debug and text:
                    kind = "final " if is_final else "partial"
                    self._dbg(f"[{kind}] {text!r}")
                if self.on_partial and text:
                    self.on_partial(extract_command(text, self.wake_word))

                if is_final and text:
                    spoken = extract_command(text, self.wake_word)
                    if spoken:
                        command_text = f"{command_text} {spoken}".strip()
                        logger.info("Command captured")
                        return command_text

                if now > command_deadline:
                    leftover = stt.flush()
                    leftover = extract_command(leftover, self.wake_word) if leftover else ""
                    if leftover and not command_text:
                        return leftover
                    return command_text or None

    def close(self) -> None:
        if self._stt is not None:
            self._stt.close()
            self._stt = None

    # -- internals ----------------------------------------------------------
    def _dbg(self, message: str) -> None:
        """Show a debug line on screen and append it to logs\\voice_debug.log."""
        if not self.debug:
            return
        print(f"\n  {message}", flush=True)
        self._append_log(message)

    def _dbg_meter(self, peak: int) -> None:
        """Write the mic level to the debug file (at most every 2 seconds)."""
        now = time.time()
        if now - self._last_file_meter >= 2.0:
            self._append_log(f"mic peak={peak}")
            self._last_file_meter = now

    @staticmethod
    def _append_log(line: str) -> None:
        try:
            config.LOG_DIR.mkdir(parents=True, exist_ok=True)
            with DEBUG_LOG.open("a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%H:%M:%S')} {line}\n")
        except OSError:  # a missing log file must never break listening
            pass

    def _ensure_stt(self) -> SpeechToText:
        if self._stt is None:
            self._stt = self._stt_factory()
        return self._stt
