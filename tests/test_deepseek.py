"""Tests for the DeepSeek provider's configuration.

No network and no real key: the OpenAI client is replaced, and the settings are
monkeypatched, so these tests only check precedence and the failure message.
"""

import pytest

from ai import deepseek


class FakeOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def use_client(monkeypatch):
    monkeypatch.setattr(deepseek, "OpenAI", FakeOpenAI)


def test_a_missing_key_stops_with_a_clear_message(monkeypatch):
    use_client(monkeypatch)
    monkeypatch.setattr(deepseek.settings, "DEEPSEEK_API_KEY", None)

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        deepseek.DeepSeekProvider()


def test_the_key_comes_from_the_settings(monkeypatch):
    use_client(monkeypatch)
    monkeypatch.setattr(deepseek.settings, "DEEPSEEK_API_KEY", "sk-test")

    provider = deepseek.DeepSeekProvider()

    assert provider.client.kwargs["api_key"] == "sk-test"


def test_the_model_precedence(monkeypatch):
    use_client(monkeypatch)
    monkeypatch.setattr(deepseek.settings, "AI_MODEL", None)
    monkeypatch.setattr(deepseek.settings, "DEEPSEEK_MODEL", "custom-model")

    assert deepseek.DeepSeekProvider(api_key="k").model == "custom-model"
    assert deepseek.DeepSeekProvider(model="explicit", api_key="k").model == "explicit"


def test_the_default_model_is_used_last(monkeypatch):
    use_client(monkeypatch)
    monkeypatch.setattr(deepseek.settings, "AI_MODEL", None)
    monkeypatch.setattr(deepseek.settings, "DEEPSEEK_MODEL", None)

    assert deepseek.DeepSeekProvider(api_key="k").model == deepseek.DEFAULT_MODEL
