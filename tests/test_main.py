"""
Tests for main.py - the flags and the --doctor health check.

These tests never touch a real microphone, Ollama, or speakers: every check is
mocked, so they run in a second on any machine.

The health check prints a checklist, so most tests just capture what it printed
with capsys.
"""

from __future__ import annotations

import main


# ---------------------------------------------------------------------------
# Command line flags
# ---------------------------------------------------------------------------

def test_doctor_flag_is_accepted():
    args = main.parse_args(["--doctor"])
    assert args.doctor is True
    assert args.text is False


def test_default_mode_is_voice():
    args = main.parse_args([])
    assert args.text is False
    assert args.doctor is False


def test_device_can_be_a_number_or_a_name():
    assert main.parse_device("2") == 2
    assert main.parse_device("realtek") == "realtek"
    assert main.parse_device(None) is None


# ---------------------------------------------------------------------------
# --doctor: one check at a time (all mocked)
# ---------------------------------------------------------------------------

def test_doctor_ollama_uses_ping(monkeypatch):
    monkeypatch.setattr(main.ai_engine, "ping", lambda: (True, "Ollama is ready."))
    assert main._doctor_ollama() == ("ok", "Ollama is ready.")


def test_doctor_ollama_failure_is_reported(monkeypatch):
    monkeypatch.setattr(main.ai_engine, "ping", lambda: (False, "Start Ollama."))
    status, message = main._doctor_ollama()
    assert status == "fail"
    assert message == "Start Ollama."


def test_doctor_folders_warns_when_empty(monkeypatch):
    monkeypatch.setattr(main.config, "APPROVED_DIRECTORIES", [])
    status, message = main._doctor_folders()
    assert status == "warn"
    assert "no approved folders" in message


def test_doctor_folders_ok_when_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(main.config, "APPROVED_DIRECTORIES", [str(tmp_path)])
    status, message = main._doctor_folders()
    assert status == "ok"
    assert "1 approved folder" in message


def test_doctor_tts_warns_when_disabled(monkeypatch):
    monkeypatch.setattr(main.config, "ENABLE_TTS", False)
    status, message = main._doctor_tts()
    assert status == "warn"
    assert "switched off" in message


# ---------------------------------------------------------------------------
# --doctor: the whole checklist
# ---------------------------------------------------------------------------

def _all_ok(monkeypatch):
    monkeypatch.setattr(main, "_doctor_ollama", lambda: ("ok", "ready"))
    monkeypatch.setattr(main, "_doctor_microphone", lambda device=None: ("ok", "mic"))
    monkeypatch.setattr(main, "_doctor_speech_model", lambda: ("ok", "model"))
    monkeypatch.setattr(main, "_doctor_tts", lambda: ("ok", "tts"))
    monkeypatch.setattr(main, "_doctor_folders", lambda: ("warn", "none"))


def test_doctor_returns_zero_when_healthy(monkeypatch, capsys):
    _all_ok(monkeypatch)
    assert main.run_doctor() == 0
    out = capsys.readouterr().out
    assert "health check" in out
    assert "[warn]" in out  # warnings do not fail the run
    assert "notepad" in out  # the app allowlist is listed


def test_doctor_returns_one_when_a_check_fails(monkeypatch, capsys):
    _all_ok(monkeypatch)
    monkeypatch.setattr(main, "_doctor_speech_model", lambda: ("fail", "model missing"))
    assert main.run_doctor() == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "model missing" in out
