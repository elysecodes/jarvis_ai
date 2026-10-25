"""
Tests for command_router.py.

Rule-based commands are tested for real. The AI fallback is tested by mocking
`ai_engine.chat`, including its error path.
"""

from __future__ import annotations

from unittest import mock

from modules import command_router
from modules.ai_engine import OllamaError


# --- rule-based answers -----------------------------------------------------

def test_time_command():
    response = command_router.route("what is the time?")
    assert response.source == "rule"
    assert "It is" in response.text


def test_date_command():
    response = command_router.route("what's today's date")
    assert response.source == "rule"
    assert "Today is" in response.text


def test_greeting():
    response = command_router.route("hello")
    assert response.source == "rule"
    assert "JARVIS" in response.text


def test_help_lists_examples():
    response = command_router.route("help")
    assert response.source == "rule"
    assert "exit" in response.text.lower()


def test_identity_question():
    response = command_router.route("who are you?")
    assert response.source == "rule"
    assert "JARVIS" in response.text


def test_thanks():
    response = command_router.route("thank you")
    assert response.source == "rule"


# --- exit handling ----------------------------------------------------------

def test_exit_words():
    for phrase in [
        "exit",
        "quit",
        "goodbye jarvis",
        "goodbye",
        "bye",
        "stop",
        "stop listening",
    ]:
        response = command_router.route(phrase)
        assert response.exit is True, f"{phrase!r} should exit"


def test_is_exit_ignores_punctuation_and_case():
    assert command_router.is_exit("  Goodbye JARVIS! ") is True
    assert command_router.is_exit("good afternoon") is False


def test_empty_input_is_handled():
    response = command_router.route("   ")
    assert response.exit is False
    assert "did not catch" in response.text


def test_long_input_is_refused():
    response = command_router.route("x" * 600)
    assert response.source == "rule"
    assert "too long" in response.text.lower()


# --- AI fallback ------------------------------------------------------------

def test_unknown_text_goes_to_the_model():
    with mock.patch.object(command_router.ai_engine, "chat", return_value="Paris.") as chat:
        response = command_router.route("What is the capital of France?")
    assert response.source == "llm"
    assert response.text == "Paris."
    # The system prompt must be sent first, so JARVIS keeps its personality.
    messages = chat.call_args.args[0]
    assert messages[0]["role"] == "system"
    assert messages[-1]["content"] == "what is the capital of france?"


def test_history_is_passed_and_grows():
    with mock.patch.object(command_router.ai_engine, "chat", return_value="Sure."):
        first = command_router.route("hello there friend")
    with mock.patch.object(command_router.ai_engine, "chat", return_value="Yes.") as chat:
        second = command_router.route("and again", first.history)
    messages = chat.call_args.args[0]
    assert any(m["content"] == "Sure." for m in messages)
    assert len(second.history) <= 6


def test_model_error_becomes_friendly_message():
    with mock.patch.object(
        command_router.ai_engine, "chat", side_effect=OllamaError("Ollama is not running.")
    ):
        response = command_router.route("tell me a story")
    assert response.source == "error"
    assert response.text == "Ollama is not running."


def test_unexpected_error_is_caught():
    with mock.patch.object(
        command_router.ai_engine, "chat", side_effect=RuntimeError("boom")
    ):
        response = command_router.route("tell me a story")
    assert response.source == "error"
    assert "went wrong" in response.text
