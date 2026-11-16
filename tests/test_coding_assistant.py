"""
Tests for modules/coding_assistant.py.

No microphone or Ollama needed. We mock ai_engine.chat, security functions,
and config.GENERATED_CODE_DIR / APPROVED_DIRECTORIES.
"""

from __future__ import annotations

from unittest import mock

import pytest

from modules import coding_assistant


# ---------------------------------------------------------------------------
# answer_coding_question
# ---------------------------------------------------------------------------

def test_answer_coding_question_returns_reply(monkeypatch):
    monkeypatch.setattr(
        coding_assistant.ai_engine, "chat", lambda messages: "Use a list."
    )
    result = coding_assistant.answer_coding_question("how do I make a list?")
    assert result == "Use a list."


# ---------------------------------------------------------------------------
# load_code / review_code (reading a file for review)
# ---------------------------------------------------------------------------

def test_load_code_reads_from_generated_code(monkeypatch, tmp_path):
    _setup_code_dir(monkeypatch, tmp_path)  # approved + GENERATED_CODE_DIR
    (tmp_path / "hello.py").write_text("print('hi')", encoding="utf-8")
    assert coding_assistant.load_code("hello.py") == "print('hi')"


def test_load_code_strips_folders_so_traversal_is_impossible(monkeypatch, tmp_path):
    _setup_code_dir(monkeypatch, tmp_path)
    (tmp_path / "hello.py").write_text("x = 1", encoding="utf-8")
    # "../../hello.py" loses its folders and simply looks for hello.py
    assert coding_assistant.load_code("../../hello.py") == "x = 1"


def test_load_code_rejects_non_python(monkeypatch, tmp_path):
    _setup_code_dir(monkeypatch, tmp_path)
    with pytest.raises(coding_assistant.CodingError):
        coding_assistant.load_code("notes.txt")


def test_load_code_reports_missing_file(monkeypatch, tmp_path):
    _setup_code_dir(monkeypatch, tmp_path)
    with pytest.raises(coding_assistant.CodingError) as info:
        coding_assistant.load_code("nope.py")
    assert "could not find" in str(info.value)


def test_load_code_blocks_unapproved_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(coding_assistant.config, "GENERATED_CODE_DIR", tmp_path)
    (tmp_path / "hello.py").write_text("x = 1", encoding="utf-8")
    with pytest.raises(coding_assistant.CodingError):
        coding_assistant.load_code("hello.py")


def test_load_code_cuts_very_long_files(monkeypatch, tmp_path):
    _setup_code_dir(monkeypatch, tmp_path)
    (tmp_path / "big.py").write_text("x = 1\n" * 5000, encoding="utf-8")
    text = coding_assistant.load_code("big.py")
    assert len(text) < coding_assistant.MAX_CODE_CHARS + 200
    assert "cut off" in text


def test_review_code_sends_the_code_to_the_model(monkeypatch):
    seen = {}

    def fake_chat(messages):
        seen["prompt"] = messages[-1]["content"]
        return "Looks fine."

    monkeypatch.setattr(coding_assistant.ai_engine, "chat", fake_chat)
    result = coding_assistant.review_code("print('hi')", "hello.py")
    assert result == "Looks fine."
    assert "print('hi')" in seen["prompt"]
    assert "hello.py" in seen["prompt"]


def test_review_code_with_nothing_to_review(monkeypatch):
    monkeypatch.setattr(
        coding_assistant.ai_engine,
        "chat",
        lambda messages: (_ for _ in ()).throw(AssertionError("must not call the model")),
    )
    assert "no code" in coding_assistant.review_code("   ")


def test_answer_coding_question_sends_system_prompt(monkeypatch):
    captured = []
    monkeypatch.setattr(
        coding_assistant.ai_engine, "chat", lambda messages: captured.append(messages) or "ok"
    )
    coding_assistant.answer_coding_question("hi")
    assert captured[0][0]["role"] == "system"
    assert "JARVIS" in captured[0][0]["content"]
    assert captured[0][-1]["content"] == "hi"


def test_answer_coding_question_ollama_error(monkeypatch):
    from modules.ai_engine import OllamaError

    monkeypatch.setattr(
        coding_assistant.ai_engine,
        "chat",
        lambda messages: (_ for _ in ()).throw(OllamaError("Ollama is down.")),
    )
    result = coding_assistant.answer_coding_question("hi")
    assert "Ollama is down" in result


# ---------------------------------------------------------------------------
# list_generated_code
# ---------------------------------------------------------------------------

def test_list_generated_code_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(coding_assistant.config, "GENERATED_CODE_DIR", tmp_path)
    assert coding_assistant.list_generated_code() == []


def test_list_generated_code_returns_files(tmp_path, monkeypatch):
    monkeypatch.setattr(coding_assistant.config, "GENERATED_CODE_DIR", tmp_path)
    (tmp_path / "a.py").write_text("x=1")
    (tmp_path / "b.py").write_text("y=2")
    (tmp_path / "sub").mkdir()
    assert coding_assistant.list_generated_code() == ["a.py", "b.py"]


# ---------------------------------------------------------------------------
# save_code_snippet
# ---------------------------------------------------------------------------

def _setup_code_dir(monkeypatch, tmp_path):
    """Point GENERATED_CODE_DIR at tmp_path and approve it."""
    monkeypatch.setattr(coding_assistant.config, "GENERATED_CODE_DIR", tmp_path)
    monkeypatch.setattr(
        coding_assistant.security.config, "APPROVED_DIRECTORIES", [str(tmp_path)]
    )


def test_save_code_snippet_requires_confirmation_no(monkeypatch, tmp_path):
    _setup_code_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(coding_assistant.security, "confirm_action", lambda action, detail="": False)
    msg = coding_assistant.save_code_snippet("hello.py", "print('hi')")
    assert "Cancelled" in msg


def test_save_code_snippet_writes_file(monkeypatch, tmp_path):
    _setup_code_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(coding_assistant.security, "requires_confirmation", lambda action: False)
    msg = coding_assistant.save_code_snippet("hello.py", "print('hi')")
    assert "Saved" in msg
    assert (tmp_path / "hello.py").read_text() == "print('hi')"


def test_save_code_snippet_blocks_path_traversal(monkeypatch, tmp_path):
    _setup_code_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(coding_assistant.security, "requires_confirmation", lambda action: False)
    msg = coding_assistant.save_code_snippet("../evil.py", "x=1")
    assert "approved" in msg.lower()


def test_save_code_snippet_not_approved_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(coding_assistant.config, "GENERATED_CODE_DIR", tmp_path)
    # APPROVED_DIRECTORIES stays empty -> not approved
    monkeypatch.setattr(coding_assistant.security, "requires_confirmation", lambda action: False)
    msg = coding_assistant.save_code_snippet("hello.py", "x=1")
    assert "not an approved directory" in msg
