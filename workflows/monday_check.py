"""Monday technical check: Hermes wakes up, Python asks the AI, Telegram shows it.

This is not the weekly run. It only proves that the whole chain works on the
server: Hermes cron -> this script -> the AI provider -> Hermes -> Telegram.

Hermes runs it with ``--no-agent``: whatever this script prints on stdout is
delivered verbatim to Telegram, so the script never calls Telegram itself (that
would send the message twice). On failure it prints one line on stderr and
exits with code 1, and Hermes sends its failure notice instead.

Run from the repo root::

    python -m workflows.monday_check
"""

import sys
from datetime import datetime, timezone

from ai import get_ai_provider

SYSTEM = "You are a health check. Answer in one short sentence, in French."
QUESTION = "Confirme que tu es joignable et donne le jour de la semaine en UTC."


def build_report(provider, now: datetime) -> str:
    """Ask the provider one short question and return the text to deliver."""
    answer = provider.chat(SYSTEM, f"{QUESTION} (date UTC : {now:%Y-%m-%d})")
    usage = getattr(provider, "last_usage", None)
    tokens = getattr(usage, "total_tokens", "?")

    return (
        "GTM Tool - test du lundi\n"
        f"Date : {now:%Y-%m-%d %H:%M} UTC\n"
        f"IA : {type(provider).__name__} ({provider.model})\n"
        f"Réponse : {answer.strip()}\n"
        f"Tokens : {tokens}"
    )


def main() -> int:
    try:
        report = build_report(get_ai_provider(), datetime.now(timezone.utc))
    except Exception as error:  # noqa: BLE001 - any failure must reach Hermes
        # Only the error type and our own messages: a raw provider error could
        # quote a request detail, and stderr is forwarded to Telegram.
        detail = str(error) if isinstance(error, (RuntimeError, ValueError)) else ""
        print(
            f"Test du lundi en échec : {type(error).__name__} {detail}".strip(),
            file=sys.stderr,
        )
        return 1

    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
