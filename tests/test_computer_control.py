"""
Tests for modules/computer_control.py.

No microphone, Ollama, or real apps needed. We mock os.startfile, subprocess.run,
and the security confirmation/validation functions.
"""

from __future__ import annotations

from unittest import mock

import pytest

from modules import computer_control


# ---------------------------------------------------------------------------
# App allowlist
# ---------------------------------------------------------------------------

def test_list_allowed_apps_returns_names():
    names = computer_control.list_allowed_apps()
    assert "notepad" in names
    assert "calculator" in names
    assert "code" in names


# ---------------------------------------------------------------------------
# launch_app
# ---------------------------------------------------------------------------

def test_launch_app_unknown_app():
    with pytest.raises(computer_control.ControlError) as info:
        computer_control.launch_app("photoshop", confirm=False)
    assert "Allowed apps" in str(info.value)


def test_launch_app_starts_without_shell(monkeypatch):
    started = []
    monkeypatch.setattr(computer_control.os, "startfile", lambda exe: started.append(exe))
    monkeypatch.setattr(computer_control.security, "requires_confirmation", lambda action: False)
    msg = computer_control.launch_app("notepad", confirm=False)
    assert started == ["notepad.exe"]
    assert "Launched notepad" in msg


def test_launch_app_requires_confirmation_no(monkeypatch):
    started = []
    monkeypatch.setattr(computer_control.os, "startfile", lambda exe: started.append(exe))
    monkeypatch.setattr(computer_control.security, "requires_confirmation", lambda action: True)
    monkeypatch.setattr(computer_control.security, "confirm_action", lambda action, detail="": False)
    msg = computer_control.launch_app("notepad")
    assert started == []
    assert "Cancelled" in msg


def test_launch_app_oserror_becomes_message(monkeypatch):
    monkeypatch.setattr(
        computer_control.os, "startfile", lambda exe: (_ for _ in ()).throw(OSError("missing"))
    )
    monkeypatch.setattr(computer_control.security, "requires_confirmation", lambda action: False)
    msg = computer_control.launch_app("notepad", confirm=False)
    assert "Could not launch notepad" in msg


# ---------------------------------------------------------------------------
# run_script
# ---------------------------------------------------------------------------

def test_run_script_only_py_files():
    msg = computer_control.run_script("setup.sh", confirm=False)
    assert "Only Python scripts" in msg


def _allow_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(computer_control, "SCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(
        computer_control.security.config, "APPROVED_DIRECTORIES", [str(tmp_path)]
    )


def test_run_script_rejects_outside_scripts_dir(tmp_path, monkeypatch):
    _allow_dir(monkeypatch, tmp_path)
    msg = computer_control.run_script("../evil.py", confirm=False)
    assert "not inside an approved directory" in msg or "Approved" in msg


def test_run_script_missing_file(tmp_path, monkeypatch):
    _allow_dir(monkeypatch, tmp_path)
    msg = computer_control.run_script("nope.py", confirm=False)
    assert "does not exist" in msg.lower()


def test_run_script_runs_and_returns_output(tmp_path, monkeypatch):
    _allow_dir(monkeypatch, tmp_path)
    script = tmp_path / "hello.py"
    script.write_text('print("hello from script")')

    monkeypatch.setattr(computer_control.security, "requires_confirmation", lambda action: False)

    class FakeResult:
        returncode = 0
        stdout = "hello from script\n"
        stderr = ""

    monkeypatch.setattr(
        computer_control.subprocess, "run", lambda *a, **k: FakeResult()
    )
    msg = computer_control.run_script("hello.py", confirm=False)
    assert "hello from script" in msg


def test_run_script_timeout(monkeypatch, tmp_path):
    _allow_dir(monkeypatch, tmp_path)
    script = tmp_path / "slow.py"
    script.write_text("import time; time.sleep(999)")

    monkeypatch.setattr(computer_control.security, "requires_confirmation", lambda action: False)

    def boom(*a, **k):
        raise __import__("subprocess").TimeoutExpired(cmd="x", timeout=30)

    monkeypatch.setattr(computer_control.subprocess, "run", boom)
    msg = computer_control.run_script("slow.py", confirm=False)
    assert "timed out" in msg


# ---------------------------------------------------------------------------
# open_file
# ---------------------------------------------------------------------------

def test_open_file_opens_with_startfile(tmp_path, monkeypatch):
    _allow_dir(monkeypatch, tmp_path)
    opened = []
    monkeypatch.setattr(computer_control.os, "startfile", lambda p: opened.append(p))
    monkeypatch.setattr(computer_control.security, "requires_confirmation", lambda action: False)
    f = tmp_path / "notes.txt"
    f.write_text("hi")
    msg = computer_control.open_file(str(f), confirm=False)
    assert opened == [str(f.resolve())]
    assert "Opened" in msg
