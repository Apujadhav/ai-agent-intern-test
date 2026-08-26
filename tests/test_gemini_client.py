import pytest

from app.gemini_client import GeminiClient


def test_gemini_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError):
        GeminiClient()


def test_gemini_model_has_default(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    client = GeminiClient()

    assert client.model == "gemini-3.6-flash"