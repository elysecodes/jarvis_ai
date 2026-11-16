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


# --- safe actions on the PC (Phase 3) ---------------------------------------

def test_list_apps_uses_the_allowlist():
    response = command_router.route("what apps can you open?")
    assert response.source == "rule"
    assert "notepad" in response.text


def test_open_app_calls_the_allowlist(monkeypatch):
    called = []
    monkeypatch.setattr(
        command_router.computer_control,
        "launch_app",
        lambda name: called.append(name) or f"Launched {name}.",
    )
    response = command_router.route("open notepad")
    assert called == ["notepad"]
    assert response.source == "action"
    assert "Launched notepad" in response.text


def test_open_unknown_app_is_explained(monkeypatch):
    def refuse(name):
        raise command_router.computer_control.ControlError(f"no app {name}")

    monkeypatch.setattr(command_router.computer_control, "launch_app", refuse)
    response = command_router.route("open photoshop")
    assert response.source == "rule"
    assert "no app photoshop" in response.text


def test_run_script_is_routed(monkeypatch):
    called = []
    monkeypatch.setattr(
        command_router.computer_control,
        "run_script",
        lambda name: called.append(name) or "done",
    )
    response = command_router.route("run script hello.py")
    assert called == ["hello.py"]
    assert response.text == "done"


def test_open_file_is_routed_with_quotes_stripped(monkeypatch):
    called = []
    monkeypatch.setattr(
        command_router.computer_control,
        "open_file",
        lambda name: called.append(name) or "opened",
    )
    command_router.route('open the file "notes.txt"')
    assert called == ["notes.txt"]


# --- coding assistant (Phase 4) ---------------------------------------------

def test_coding_questions_use_the_coding_assistant(monkeypatch):
    seen = {}

    def fake_answer(question, history=None):
        seen["question"] = question
        return "Use a list."

    monkeypatch.setattr(
        command_router.coding_assistant, "answer_coding_question", fake_answer
    )
    response = command_router.route("how do I sort a python list?")
    assert response.source == "coding"
    assert response.text == "Use a list."
    assert "sort a python list" in seen["question"]


def test_coding_answers_are_remembered(monkeypatch):
    monkeypatch.setattr(
        command_router.coding_assistant,
        "answer_coding_question",
        lambda question, history=None: "Answer.",
    )
    response = command_router.route("what is a python function?")
    assert len(response.history) == 2
    assert response.history[0]["role"] == "user"


# --- coding assistant commands: save / list / review -------------------------

def test_list_code_says_nothing_saved_yet(monkeypatch):
    monkeypatch.setattr(command_router.coding_assistant, "list_generated_code", lambda: [])
    response = command_router.route("show my code")
    assert response.source == "rule"
    assert "not saved any code" in response.text


def test_list_code_shows_saved_names(monkeypatch):
    monkeypatch.setattr(
        command_router.coding_assistant, "list_generated_code", lambda: ["a.py", "b.py"]
    )
    response = command_router.route("list my saved snippets")
    assert "a.py, b.py" in response.text


def test_save_that_as_uses_the_previous_answer(monkeypatch):
    saved = {}

    def fake_save(filename, code, confirm=True):
        saved["filename"] = filename
        saved["code"] = code
        return f"Saved {filename}."

    monkeypatch.setattr(command_router.coding_assistant, "save_code_snippet", fake_save)
    history = [
        {"role": "user", "content": "write a hello world script"},
        {"role": "assistant", "content": "print('hello')"},
    ]
    response = command_router.route("save that as hello.py", history)
    assert saved["filename"] == "hello.py"
    assert saved["code"] == "print('hello')"
    assert response.text == "Saved hello.py."


def test_save_that_as_without_history_explains(monkeypatch):
    monkeypatch.setattr(
        command_router.coding_assistant,
        "save_code_snippet",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not save")),
    )
    response = command_router.route("save that as hello.py", [])
    assert response.source == "rule"
    assert "no code to save" in response.text


def test_review_file_reads_and_asks_the_model(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        command_router.coding_assistant, "load_code", lambda name: "print('hi')"
    )

    def fake_review(code, filename=""):
        seen["code"] = code
        seen["filename"] = filename
        return "That prints hi."

    monkeypatch.setattr(command_router.coding_assistant, "review_code", fake_review)
    response = command_router.route("review the file hello.py")
    assert response.source == "coding"
    assert response.text == "That prints hi."
    assert seen == {"code": "print('hi')", "filename": "hello.py"}


def test_review_missing_file_is_explained(monkeypatch):
    def fail(name):
        raise command_router.coding_assistant.CodingError("I could not find it.")

    monkeypatch.setattr(command_router.coding_assistant, "load_code", fail)
    response = command_router.route("explain hello.py")
    assert response.source == "rule"
    assert "could not find" in response.text


