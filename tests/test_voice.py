"""
Tests for voice.py.

None of these tests need a microphone. We test the wake-word / command
extraction logic with fake transcripts, and drive the listener with fake audio
blocks and a fake speech engine.
"""

from __future__ import annotations

import types
from unittest import mock

import pytest

from modules import voice


# ---------------------------------------------------------------------------
# Wake-word logic with fake transcripts
# ---------------------------------------------------------------------------
def test_normalise_text():
    assert voice.normalise_text("Hey, JARVIS!  What's   up?") == "hey jarvis what's up"
    assert voice.normalise_text(None) == ""


@pytest.mark.parametrize(
    "transcript, expected_command",
    [
        ("hey jarvis", ""),
        ("hey jarvis what is the time", "what is the time"),
        ("Hey Jarvis, open notepad", "open notepad"),
        ("jarvis tell me a joke", "tell me a joke"),
        ("so hey jarvis search for python", "search for python"),
    ],
)
def test_find_wake_word_found(transcript, expected_command):
    result = voice.find_wake_word(transcript)
    assert result.found is True
    assert result.command == expected_command


@pytest.mark.parametrize(
    "transcript",
    ["hello there", "", None, "jarv is here", "the garden is nice"],
)
def test_find_wake_word_not_found(transcript):
    assert voice.find_wake_word(transcript).found is False


def test_custom_wake_word_is_also_accepted():
    result = voice.find_wake_word("computer what time is it", "computer")
    assert result.found is True
    assert result.command == "what time is it"
    # "jarvis" still works as the friendly fallback.
    assert voice.find_wake_word("jarvis stop").found is True


def test_extract_command_without_wake_word_returns_everything():
    assert voice.extract_command("what is the time") == "what is the time"
    assert voice.extract_command("hey jarvis search cats") == "search cats"


def test_wake_word_is_not_matched_inside_a_word():
    # "jarvissomething" must not trigger the wake word.
    assert voice.find_wake_word("jarvissing a song").found is False


# ---------------------------------------------------------------------------
# Friendly errors (no microphone / model needed)
# ---------------------------------------------------------------------------
def test_missing_model_gives_friendly_error(tmp_path):
    with pytest.raises(voice.VoiceError) as info:
        voice.VoskSTT(model_path=tmp_path / "does-not-exist")
    message = str(info.value)
    assert "models" in message.lower()
    assert "README" in message


def test_list_input_devices_filters_outputs():
    fake_sd = types.SimpleNamespace(
        query_devices=lambda *a, **k: [
            {"name": "Speakers", "max_input_channels": 0},
            {"name": "Microphone", "max_input_channels": 2},
            {"name": "Headset mic", "max_input_channels": 1},
        ]
    )
    with mock.patch.object(voice, "_import_sounddevice", return_value=fake_sd):
        devices = voice.list_input_devices()
    assert devices == [(1, "Microphone"), (2, "Headset mic")]


def test_microphone_error_message_is_friendly():
    message = voice._microphone_message(None, RuntimeError("boom"))
    assert "microphone" in message.lower()
    assert "--text" in message


# ---------------------------------------------------------------------------
# The listener loop, driven with fake audio + a fake engine
# ---------------------------------------------------------------------------
class FakeSTT(voice.SpeechToText):
    """Replays a scripted list of (text, is_final) events."""

    def __init__(self, events, leftover=""):
        self._events = list(events)
        self._leftover = leftover
        self._index = 0

    def reset(self):
        self._index = 0

    def feed(self, pcm):
        if self._index < len(self._events):
            event = self._events[self._index]
            self._index += 1
            return event
        return "", False

    def flush(self):
        return self._leftover

    def close(self):
        pass


def _make_fake_sounddevice(block_count):
    class FakeStream:
        def __init__(self, *a, **k):
            self.remaining = block_count

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, frames):
            if self.remaining <= 0:
                raise RuntimeError("fake stream ran dry")
            self.remaining -= 1
            return b"\x00\x00" * (frames // 2), False

    return types.SimpleNamespace(
        query_devices=lambda *a, **k: None,
        InputStream=FakeStream,
        RawInputStream=FakeStream,
    )


def _listener(events, leftover="", **kwargs):
    fake_sd = _make_fake_sounddevice(len(events) + 2)
    stt = FakeSTT(events, leftover)
    listener = voice.VoiceListener(stt_factory=lambda: stt, **kwargs)
    return listener, fake_sd


def test_listener_returns_command_after_wake_word():
    listener, fake_sd = _listener(
        [
            ("hey jarvis", False),  # partial wake word
            ("hey jarvis", True),  # wake word confirmed
            ("what is the time", True),  # the command
        ]
    )
    with mock.patch.object(voice, "_import_sounddevice", return_value=fake_sd):
        command = listener.listen_for_command()
    assert command == "what is the time"


def test_listener_handles_wake_word_and_command_in_one_sentence():
    # "hey jarvis what's the time" arrives as one final result, then silence.
    listener, fake_sd = _listener(
        [("hey jarvis what's the time", True)],
        command_timeout=0.0,  # don't wait for extra speech
    )
    with mock.patch.object(voice, "_import_sounddevice", return_value=fake_sd):
        command = listener.listen_for_command()
    assert command == "what's the time"


def test_listener_returns_none_on_silence():
    listener, fake_sd = _listener(
        [("", False)] * 5,
        wake_timeout=2.0,
    )
    ticks = iter(range(0, 1000))
    with mock.patch.object(voice, "_import_sounddevice", return_value=fake_sd), mock.patch.object(
        voice.time, "monotonic", side_effect=lambda: next(ticks)
    ):
        assert listener.listen_for_command() is None
