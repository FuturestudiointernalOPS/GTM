"""Tests for the command-line entry point.

Everything that reaches the outside is monkeypatched: the model provider, the
database and the run itself. These tests check the assembly, the summary and the
exit code, not the rules (they live in ``processing/``).
"""

import json
from fractions import Fraction

import pytest

from main import main, summary
from processing import eligibility
from processing.scoring import ScoreResult
from workflows.record_flow import CREATOR, RecordScore
from workflows.record_loop import LoopResult
from workflows.weekly_run import WeeklyRun

READ = "2026-11-10T12:00:00+00:00"


class FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def run(**overrides):
    values = {
        "collected_at": READ,
        "fresh_pages": 2,
        "scores": LoopResult(),
    }
    values.update(overrides)
    return WeeklyRun(**values)


def record():
    result = ScoreResult(
        proposal="PRESELECTED",
        score=79,
        total_exact=Fraction(79),
        lower_bound=Fraction(79),
        upper_bound=Fraction(79),
        incomplete=False,
        lines=(),
    )
    return RecordScore(
        kind=CREATOR,
        result=result,
        record_id="rec-1",
        source_url="https://vk.com/creator",
    )


@pytest.fixture(autouse=True)
def provider(monkeypatch):
    monkeypatch.setattr("main.get_ai_provider", lambda: object())


def test_a_dry_run_opens_no_database(monkeypatch, capsys):
    monkeypatch.setattr(
        "main.postgres.connect", lambda *args, **kwargs: pytest.fail("no database")
    )
    captured = {}

    def run_and_score(**kwargs):
        captured.update(kwargs)
        return run()

    monkeypatch.setattr("main.run_and_score", run_and_score)

    assert main(["--dry-run", "--week", "45"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert captured["week"] == 45


def test_a_real_run_uses_and_closes_the_connection(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr("main.postgres.connect", lambda: connection)
    captured = {}

    def postgres_run(**kwargs):
        captured.update(kwargs)
        return run()

    monkeypatch.setattr("main.postgres_run", postgres_run)

    assert main(["--week", "45", "--include-betting"]) == 0

    assert connection.closed is True
    assert captured["include_betting"] is True
    assert captured["verify"] is None


def test_the_verification_file_is_loaded_and_wired(monkeypatch, tmp_path):
    path = tmp_path / "verifications.json"
    path.write_text(
        json.dumps(
            {
                "https://vk.com/creator": {
                    "platform_covered": True,
                    "followers": 25_000,
                    "foreign_agent_label": False,
                    "rkn_status": "VERIFIED",
                    "sanction_status": "NOT_FOUND",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("main.postgres.connect", lambda: FakeConnection())
    captured = {}

    def postgres_run(**kwargs):
        captured.update(kwargs)
        return run()

    monkeypatch.setattr("main.postgres_run", postgres_run)

    assert main(["--verification", str(path)]) == 0

    verification = captured["verify"](record())
    assert isinstance(verification, eligibility.CreatorVerification)


def test_dry_run_ignores_the_verification_file(monkeypatch, tmp_path):
    path = tmp_path / "verifications.json"
    path.write_text("{}", encoding="utf-8")
    captured = {}

    def run_and_score(**kwargs):
        captured.update(kwargs)
        return run()

    monkeypatch.setattr("main.run_and_score", run_and_score)

    assert main(["--dry-run", "--verification", str(path)]) == 0
    assert "verify" not in captured


def test_a_failed_write_returns_one(monkeypatch):
    monkeypatch.setattr("main.postgres.connect", lambda: FakeConnection())
    monkeypatch.setattr(
        "main.postgres_run",
        lambda **kwargs: run(write_failed=(("rec-1", "base indisponible"),)),
    )

    assert main([]) == 1


def test_a_configuration_error_returns_two(monkeypatch):
    def connect():
        raise RuntimeError("DATABASE_URL is not set")

    monkeypatch.setattr("main.postgres.connect", connect)

    assert main([]) == 2


def test_the_summary_reports_every_outcome():
    result = summary(
        run(
            written=("run-1",),
            write_failed=(("rec-2", "boom"),),
            eligible=(("rec-1", "ELIGIBLE"),),
            eligibility_skipped=("rec-3",),
            eligibility_failed=(("rec-4", "registre muet"),),
        ),
        dry_run=False,
    )

    assert result["written"] == ["run-1"]
    assert result["write_failed"] == [{"record_id": "rec-2", "error": "boom"}]
    assert result["eligible"] == [{"record_id": "rec-1", "status": "ELIGIBLE"}]
    assert result["eligibility_skipped"] == ["rec-3"]
    assert result["eligibility_failed"] == [
        {"record_id": "rec-4", "error": "registre muet"}
    ]
    assert result["dry_run"] is False
