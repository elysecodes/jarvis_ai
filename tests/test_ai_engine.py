"""
Tests for ai_engine.py.

We never call the real Ollama server here. Instead we mock `requests.post`
and `requests.get` so the tests are fast and work offline.
"""

from __future__ import annotations

from unittest import mock

import pytest
import requests

from modules import ai_engine


class FakeResponse:
    """A stand-in for requests.Response with just what we use."""

    def __init__(self, status_code: int = 200, json_data=None, raise_json: bool = False):
        self.status_code = status_code
        self._json_data = json_data
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


# --- happy path -------------------------------------------------------------

def test_chat_returns_model_reply():
    fake = FakeResponse(json_data={"message": {"role": "assistant", "content": "Hello there."}})
    with mock.patch.object(ai_engine.requests, "post", return_value=fake) as post:
        answer = ai_engine.chat([{"role": "user", "content": "hi"}])
    assert answer == "Hello there."
    # We must send the right JSON body and never use streaming.
    sent = post.call_args.kwargs["json"]
    assert sent["stream"] is False
    assert sent["messages"][0]["content"] == "hi"


def test_chat_accepts_plain_response_field():
    fake = FakeResponse(json_data={"response": "42"})
    with mock.patch.object(ai_engine.requests, "post", return_value=fake):
        assert ai_engine.chat([{"role": "user", "content": "?"}]) == "42"


# --- error paths ------------------------------------------------------------

def test_chat_when_ollama_not_running():
    with mock.patch.object(
        ai_engine.requests, "post", side_effect=requests.exceptions.ConnectionError
    ):
        with pytest.raises(ai_engine.OllamaError) as info:
            ai_engine.chat([{"role": "user", "content": "hi"}])
    # The message must tell the user exactly what to do.
    assert "ollama serve" in str(info.value)


def test_chat_when_model_missing_gives_pull_command():
    fake = FakeResponse(status_code=404)
    installed = FakeResponse(json_data={"models": [{"name": "llama3.2:1b"}]})
    with mock.patch.object(ai_engine.requests, "post", return_value=fake), mock.patch.object(
        ai_engine.requests, "get", return_value=installed
    ):
        with pytest.raises(ai_engine.OllamaError) as info:
            ai_engine.chat([{"role": "user", "content": "hi"}])
    message = str(info.value)
    assert "ollama pull" in message
    assert ai_engine.config.OLLAMA_MODEL in message


def test_chat_on_timeout():
    with mock.patch.object(
        ai_engine.requests, "post", side_effect=requests.exceptions.Timeout
    ):
        with pytest.raises(ai_engine.OllamaError) as info:
            ai_engine.chat([{"role": "user", "content": "hi"}])
    assert "longer than" in str(info.value)


def test_chat_on_server_error():
    fake = FakeResponse(status_code=500)
    with mock.patch.object(ai_engine.requests, "post", return_value=fake):
        with pytest.raises(ai_engine.OllamaError) as info:
            ai_engine.chat([{"role": "user", "content": "hi"}])
    assert "HTTP 500" in str(info.value)


def test_chat_on_unreadable_json():
    fake = FakeResponse(json_data=None, raise_json=True)
    with mock.patch.object(ai_engine.requests, "post", return_value=fake):
        with pytest.raises(ai_engine.OllamaError):
            ai_engine.chat([{"role": "user", "content": "hi"}])


def test_chat_on_empty_answer():
    fake = FakeResponse(json_data={"message": {"content": "   "}})
    with mock.patch.object(ai_engine.requests, "post", return_value=fake):
        with pytest.raises(ai_engine.OllamaError):
            ai_engine.chat([{"role": "user", "content": "hi"}])


# --- ping / list_models -----------------------------------------------------

def test_ping_success_when_model_present():
    tags = FakeResponse(json_data={"models": [{"name": ai_engine.config.OLLAMA_MODEL}]})
    with mock.patch.object(ai_engine.requests, "get", return_value=tags):
        ok, message = ai_engine.ping()
    assert ok is True
    assert ai_engine.config.OLLAMA_MODEL in message


def test_ping_fails_when_model_missing():
    tags = FakeResponse(json_data={"models": [{"name": "llama3.2:1b"}]})
    with mock.patch.object(ai_engine.requests, "get", return_value=tags):
        ok, message = ai_engine.ping()
    assert ok is False
    assert "ollama pull" in message


def test_ping_fails_when_ollama_down():
    with mock.patch.object(
        ai_engine.requests, "get", side_effect=requests.exceptions.ConnectionError
    ):
        ok, message = ai_engine.ping()
    assert ok is False
    assert "ollama serve" in message


def test_list_models_returns_empty_when_down():
    with mock.patch.object(
        ai_engine.requests, "get", side_effect=requests.exceptions.ConnectionError
    ):
        assert ai_engine.list_models() == []
