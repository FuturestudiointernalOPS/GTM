"""Run one week: collect, score, and persist. The command a human or cron calls.

Examples::

    python -m main --dry-run --week 45
    python -m main --week 45
    python -m main --week 45 --verification verifications.json

``--dry-run`` still collects, calls the model and the actor, but opens no
database connection and writes nothing. Without ``--verification`` the run stops
after the score: the regulatory checks are a separate procedure, and no verdict
is invented. With it, each written score is followed by its eligibility
decision, read from a JSON hand-over (see ``docs/eligibility.md``).

Every external service is reached through the existing modules; this file only
assembles them and prints a summary. It decides no rule.
"""

import argparse
import json
import logging
import sys

from ai import get_ai_provider
from config import settings
from integrations import postgres, telegram
from workflows import outreach, run_report, telegram_report
from workflows.eligibility_step import VerificationFile
from workflows.engagement_step import apify_fetcher
from workflows.postgres_run import postgres_run
from workflows.weekly_run import WeeklyRun, run_and_score

log = logging.getLogger("gtm")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m main",
        description="Collect, score and persist one week of GTM candidates.",
    )
    parser.add_argument("--week", type=int, default=None, help="rotation week")
    parser.add_argument(
        "--include-betting",
        action="store_true",
        help="include the betting-brand queries (off by default)",
    )
    parser.add_argument("--num-results", type=int, default=10)
    parser.add_argument("--read-top", type=int, default=3)
    parser.add_argument(
        "--contact-pages",
        type=int,
        default=20,
        metavar="N",
        help="read the contact pages of the N best records without a contact (0: off)",
    )
    parser.add_argument(
        "--with-text",
        action="store_true",
        help="ask the search providers for the page text too",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="collect and score, but write nothing (no database connection)",
    )
    parser.add_argument(
        "--verification",
        default=None,
        metavar="PATH",
        help="JSON file of check results, keyed by page URL",
    )
    parser.add_argument(
        "--engagement-actor",
        default=settings.ENGAGEMENT_ACTOR_ID,
        metavar="ACTOR_ID",
        help="Apify Actor that samples engagement (empty: no sample)",
    )
    parser.add_argument(
        "--engagement-input",
        default=settings.ENGAGEMENT_ACTOR_INPUT,
        metavar="JSON",
        help="actor input, with {platform} and {url} placeholders",
    )
    parser.add_argument(
        "--engagement-max-items",
        default=settings.ENGAGEMENT_ACTOR_MAX_ITEMS,
        metavar="N",
        help="cap the actor rows read per creator",
    )
    parser.add_argument(
        "--computed-by",
        default="weekly-run",
        help="actor name written in the score, measure and decisions",
    )
    parser.add_argument(
        "--send-telegram",
        action="store_true",
        help="send the run report to the configured Telegram chat",
    )
    parser.add_argument(
        "--send-draft",
        action="store_true",
        help="send every outreach draft to the supervisor for approval",
    )
    parser.add_argument(
        "--max-drafts",
        type=int,
        default=outreach.DEFAULT_MAX_DRAFTS,
        metavar="N",
        help="maximum drafts to generate; 0 means no limit",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        run = execute(args)
    except (RuntimeError, ValueError) as error:
        log.error("%s", error)
        return 2

    drafted: tuple = ()
    wants_drafts = args.send_draft
    if wants_drafts:
        drafted = outreach.build_drafts(
            run.scores.scored,
            get_ai_provider(),
            max_drafts=args.max_drafts,
        )

    report_sent = None
    if args.send_telegram:
        report = run_report.build_report(run, drafted, drafts_requested=args.send_draft)
        parts = telegram_report.split(telegram_report.render(report))
        report_sent = all([telegram.send_message_safely(part) for part in parts])

    drafts_sent = None
    if args.send_draft:
        text = outreach.validation_text(drafted)
        if text:
            parts = telegram_report.split(text)
            drafts_sent = all([telegram.send_message_safely(part) for part in parts])
        else:
            drafts_sent = True

    output = summary(run, dry_run=args.dry_run)
    output["drafts"] = [
        {
            "name": item.recipient.get("name"),
            "channel": item.channel,
            "error": item.error,
        }
        for item in drafted
    ]
    output["telegram_sent"] = report_sent
    output["drafts_sent"] = drafts_sent
    print(json.dumps(output, ensure_ascii=False, indent=2))

    failed = bool(run.write_failed or run.eligibility_failed)
    failed = failed or (args.send_telegram and not report_sent)
    failed = failed or (args.send_draft and not drafts_sent)
    return 1 if failed else 0


def execute(args) -> WeeklyRun:
    """Assemble the run from the arguments, and call the right entry point."""
    provider = get_ai_provider()
    fetch = apify_fetcher(
        args.engagement_actor,
        args.engagement_input,
        max_items=_max_items(args.engagement_max_items),
    )
    collection = {
        "week": args.week,
        "include_betting": args.include_betting,
        "num_results": args.num_results,
        "read_top": args.read_top,
        "with_text": args.with_text,
        "contact_pages": args.contact_pages,
    }

    if args.dry_run:
        if args.verification:
            log.warning(
                "--verification needs a database: eligibility is skipped in dry-run"
            )
        return run_and_score(provider=provider, fetch=fetch, **collection)

    verify = None
    if args.verification:
        verify = VerificationFile.load(args.verification).for_record

    connection = postgres.connect()
    try:
        return postgres_run(
            connection=connection,
            provider=provider,
            fetch=fetch,
            computed_by=args.computed_by,
            verify=verify,
            **collection,
        )
    finally:
        connection.close()


def summary(run: WeeklyRun, *, dry_run: bool) -> dict:
    """What the operator needs to see, without reading the logs."""
    return {
        "dry_run": dry_run,
        "collected_at": run.collected_at,
        "fresh_pages": run.fresh_pages,
        "scored": len(run.scores.scored),
        "failed_candidates": [
            {"record_id": record_id, "error": error}
            for record_id, error in run.scores.failed
        ],
        "written": list(run.written),
        "write_failed": [
            {"record_id": record_id, "error": error}
            for record_id, error in run.write_failed
        ],
        "eligible": [
            {"record_id": record_id, "status": status}
            for record_id, status in run.eligible
        ],
        "eligibility_skipped": list(run.eligibility_skipped),
        "eligibility_failed": [
            {"record_id": record_id, "error": error}
            for record_id, error in run.eligibility_failed
        ],
    }


def _max_items(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        items = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"engagement max items must be an integer: {value!r}"
        ) from error
    if items <= 0:
        raise ValueError("engagement max items must be positive")
    return items


if __name__ == "__main__":
    sys.exit(main())
