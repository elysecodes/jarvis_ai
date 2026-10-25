"""
Tests for modules/security.py.

No microphone or Ollama needed. We monkeypatch config.APPROVED_DIRECTORIES
to control which paths are allowed.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

import sys

from modules import security


# ---------------------------------------------------------------------------
# Approved-directory checks
# ---------------------------------------------------------------------------

def _set_approved(dirs):
    """Temporarily replace config.APPROVED_DIRECTORIES."""
    return mock.patch.object(security.config, "APPROVED_DIRECTORIES", list(dirs))


def test_approved_directory_inside_root(tmp_path):
    with _set_approved([str(tmp_path)]):
        inner = tmp_path / "sub" / "file.txt"
        inner.parent.mkdir(parents=True, exist_ok=True)
        assert security.is_approved_directory(inner) is True


def test_approved_directory_outside_root(tmp_path):
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    with _set_approved([str(tmp_path)]):
        assert security.is_approved_directory(outside) is False


def test_approved_directory_dotdot_escape(tmp_path):
    """A '..' escape must be rejected even if the string starts inside root."""
    evil = tmp_path / "sub" / ".." / ".." / "escape"
    with _set_approved([str(tmp_path)]):
        assert security.is_approved_directory(evil) is False


def test_no_approved_directories_denies_all(tmp_path):
    with _set_approved([]):
        assert security.is_approved_directory(tmp_path) is False


def test_validate_file_path_returns_resolved(tmp_path):
    with _set_approved([str(tmp_path)]):
        f = tmp_path / "a.txt"
        f.write_text("hi")
        result = security.validate_file_path(f, must_exist=True)
        assert result == f.resolve()


def test_validate_file_path_rejects_outside(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("hi")
    with _set_approved([str(tmp_path)]), pytest.raises(security.SecurityError):
        security.validate_file_path(outside, must_exist=True)


def test_validate_file_path_missing(tmp_path):
    with _set_approved([str(tmp_path)]), pytest.raises(security.SecurityError):
        security.validate_file_path(tmp_path / "nope.txt", must_exist=True)


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------

def test_requires_confirmation():
    assert security.requires_confirmation("delete") is True
    assert security.requires_confirmation("launch_app") is True
    assert security.requires_confirmation("run_script") is True
    assert security.requires_confirmation("read_file") is False


def test_confirm_action_yes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
    assert security.confirm_action("delete", "old.txt") is True


def test_confirm_action_y(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert security.confirm_action("delete") is True


def test_confirm_action_no(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")
    assert security.confirm_action("delete") is False


def test_confirm_action_ctrl_c(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(KeyboardInterrupt))
    assert security.confirm_action("delete") is False


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

def test_redact_none():
    assert security.redact(None) == ""


def test_redact_short_passthrough():
    assert security.redact("hello world") == "hello world"


def test_redact_long_truncated():
    long_text = "x" * 100
    result = security.redact(long_text)
    assert result.startswith("x" * 60)
    assert result.endswith("... [redacted]")


def test_redact_collapses_whitespace():
    assert security.redact("  a   b  ") == "a b"


# ---------------------------------------------------------------------------
# Symlink escape rejection
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform.startswith("win"), reason="Windows lacks symlink privileges by default")
def test_symlink_outside_approved_rejected(tmp_path):
    """A symlink inside an approved dir that points outside must be rejected."""
    approved = tmp_path / "approved"
    approved.mkdir()
    target = tmp_path.parent / "secret.txt"
    target.write_text("secret")
    link = approved / "link.txt"
    os.symlink(str(target), link)

    with _set_approved([str(approved)]):
        assert security.is_approved_directory(link) is False
        with pytest.raises(security.SecurityError):
            security.validate_file_path(link, must_exist=True)
