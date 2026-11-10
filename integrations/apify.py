"""Structured extraction through Apify Actors.

Why Apify: Exa finds the pages, but a VK profile, a Telegram channel or a search
result page has to be read the same way every time. An Actor does that reading
and returns rows (handles, followers, posts, contacts) instead of HTML.

Why one run per call: an Actor run costs money and can take minutes. The client
already retries the API calls by itself, so this module never starts a second
run on its own; a failure is reported for the workflow to decide.
"""
import logging
from datetime import timedelta

from apify_client import ApifyClient
from apify_client.errors import ApifyClientError

from config import settings

log = logging.getLogger(__name__)

DEFAULT_WAIT_SECONDS = 300


class ApifyError(RuntimeError):
    """The run failed, or Apify refused the request."""


class ApifyNotConfigured(ApifyError):
    """No API token: the settings were not filled in."""


def is_configured() -> bool:
    """True when an Apify API token is set."""
    return bool(settings.APIFY_API_KEY)


def run_actor(
    actor_id: str,
    run_input: dict,
    *,
    max_items: int | None = None,
    wait_seconds: int = DEFAULT_WAIT_SECONDS,
) -> list[dict]:
    """Run one Actor and return every row of its dataset.

    ``actor_id`` is either the Actor's name (``apify/google-search-scraper``) or
    its ID. ``run_input`` is the Actor's own input object; it is passed through
    unchanged. ``max_items`` stops the run early once that many rows exist,
    which also caps the bill for pay-per-result Actors.

    Raises ``ApifyError`` when the run does not end in ``SUCCEEDED``, including
    the case where it is still running after ``wait_seconds``: use the run's
    console URL to follow it rather than starting a duplicate.
    """
    if not actor_id or not actor_id.strip():
        raise ValueError("Apify actor_id must not be empty")
    if not isinstance(run_input, dict):
        raise TypeError("Apify run_input must be a dict")
    if wait_seconds <= 0:
        raise ValueError("wait_seconds must be positive")

    if not is_configured():
        raise ApifyNotConfigured(
            "Apify is not configured: set APIFY_API_KEY in the .env file"
        )

    client = ApifyClient(settings.APIFY_API_KEY)
    call_options = {
        "run_input": run_input,
        "wait_duration": timedelta(seconds=wait_seconds),
    }
    if max_items is not None:
        call_options["max_items"] = max_items

    try:
        run = client.actor(actor_id).call(**call_options)
    except ApifyClientError as error:
        raise ApifyError(f"Apify refused the request: {_short(error)}") from error
    except Exception as error:
        # Transport errors can quote the request URL, so only the type is kept.
        raise ApifyError(
            f"Apify request failed ({type(error).__name__})"
        ) from error

    if run is None:
        raise ApifyError(f"Apify did not return a run for {actor_id}")

    if run.status != "SUCCEEDED":
        raise ApifyError(_failure_message(actor_id, run, wait_seconds))

    dataset_id = getattr(run, "default_dataset_id", None)
    if not dataset_id:
        raise ApifyError(f"Apify run {run.id} has no dataset to read")

    try:
        items = list(client.dataset(dataset_id).iterate_items())
    except ApifyClientError as error:
        raise ApifyError(
            f"Apify refused to read the dataset: {_short(error)}"
        ) from error
    except Exception as error:
        raise ApifyError(
            f"Reading the Apify dataset failed ({type(error).__name__})"
        ) from error

    log.info("Apify actor %s returned %s row(s)", actor_id, len(items))
    return items


def _failure_message(actor_id: str, run, wait_seconds: int) -> str:
    """Explain a run that is not successful, without guessing why."""
    if run.status in ("READY", "RUNNING"):
        return (
            f"Apify run {run.id} for {actor_id} is still {run.status} after "
            f"{wait_seconds}s; follow it instead of starting another run"
        )
    reason = getattr(run, "status_message", None) or "no message"
    return f"Apify run {run.id} for {actor_id} ended with {run.status}: {reason}"


def _short(error: Exception, limit: int = 300) -> str:
    """Keep error messages readable and bounded in a log line."""
    text = str(error).strip()
    return text if len(text) <= limit else f"{text[:limit]}..."
