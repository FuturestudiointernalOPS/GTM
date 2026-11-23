"""Tests for the Monday technical check. No network: the provider is a fake."""

from datetime import datetime, timezone
from types import SimpleNamespace

from workflows import monday_check

NOW = datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)


class FakeProvider:
    model = "fake-model"

    def __init__(self, answer="Je suis joignable, nous sommes lundi."):
        self.answer = answer
        self.last_usage = SimpleNamespace(total_tokens=42)
        self.calls = []

    def chat(self, system, user):
        self.calls.append((system, user))
        return self.answer


def test_the_report_names_the_date_the_model_and_the_answer():
    report = monday_check.build_report(FakeProvider(), NOW)

    assert "2026-11-23 06:00 UTC" in report
    assert "FakeProvider (fake-model)" in report
    assert "Je suis joignable, nous sommes lundi." in report
    assert "Tokens : 42" in report


def test_the_question_carries_the_utc_date():
    provider = FakeProvider()

    monday_check.build_report(provider, NOW)

    assert "2026-11-23" in provider.calls[0][1]


def test_success_prints_the_report_and_returns_0(monkeypatch, capsys):
    monkeypatch.setattr(monday_check, "get_ai_provider", lambda: FakeProvider())

    assert monday_check.main() == 0
    out = capsys.readouterr()
    assert "test du lundi" in out.out
    assert out.err == ""


def test_a_missing_key_fails_on_stderr_with_code_1(monkeypatch, capsys):
    def no_key():
        raise RuntimeError("Missing setting: DEEPSEEK_API_KEY")

    monkeypatch.setattr(monday_check, "get_ai_provider", no_key)

    assert monday_check.main() == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "DEEPSEEK_API_KEY" in out.err


def test_an_unexpected_error_shows_only_its_type(monkeypatch, capsys):
    class Boom(Exception):
        pass

    def failing():
        raise Boom("request detail that must not leak")

    monkeypatch.setattr(monday_check, "get_ai_provider", failing)

    assert monday_check.main() == 1
    err = capsys.readouterr().err
    assert "Boom" in err
    assert "must not leak" not in err
