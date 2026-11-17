"""Collect the engagement sample for one candidate.

The loop scores a creator from its page plus a sample. This step turns a
candidate into that sample: it reads the platform from the page address, asks a
fetcher for the actor rows, and normalizes them into items stamped with the
candidate's read time.

The fetcher is injected on purpose: the actor choice and its input belong to the
operator (``docs/engagement.md``, E3), and no actor id is hardcoded here. A
fetcher receives the platform label and the profile address, and returns the raw
actor rows.

Cost: one actor run per creator. The operator budgets it; nothing here batches
creators into a single run.
"""

import json
from collections.abc import Callable, Iterable

from integrations import apify
from integrations.engagement_collectors import normalize_items
from processing.engagement import EngagementItem
from workflows.creator_hunt import platform_for
from workflows.record_flow import CREATOR
from workflows.record_loop import Candidate

# (platform label, profile address) -> raw actor rows
Fetcher = Callable[[str, str], Iterable[dict]]


def creator_sampler(
    fetch: Fetcher,
) -> Callable[[Candidate], tuple[EngagementItem, ...]]:
    """Build the ``sample_for`` hook the loop expects."""

    def sample(candidate: Candidate) -> tuple[EngagementItem, ...]:
        if candidate.kind != CREATOR:
            return ()
        platform = platform_for(candidate.source_url)
        if platform is None:
            return ()
        rows = fetch(platform, candidate.source_url)
        return normalize_items(platform, rows, read_at=candidate.read_at).items

    return sample


def apify_fetcher(
    actor_id: str | None,
    run_input: dict | str | None = None,
    *,
    max_items: int | None = None,
    run: Callable[..., Iterable[dict]] | None = None,
) -> Fetcher:
    """Build the fetcher the loop uses from one Apify Actor.

    ``run_input`` is the operator's own JSON object; ``{platform}`` and ``{url}``
    are replaced with the candidate's values before the run. Nothing is
    hardcoded here: no actor, no input shape, because those belong to the
    operator (``docs/engagement.md``, E3). An empty ``actor_id`` means no sample
    is collected, which sends creators to review instead of guessing one.

    ``run`` is injected so a test needs no network; it defaults to
    ``integrations.apify.run_actor``.
    """
    if not actor_id or not actor_id.strip():
        return lambda platform, url: ()

    payload = _input_dict(run_input)
    runner = run or apify.run_actor

    def fetch(platform: str, url: str) -> Iterable[dict]:
        return runner(
            actor_id,
            _substitute(payload, platform=platform, url=url),
            max_items=max_items,
        )

    return fetch


def _input_dict(run_input: dict | str | None) -> dict:
    """Accept the actor input as an object or as the JSON text from .env."""
    if run_input is None:
        return {}
    if isinstance(run_input, str):
        try:
            value = json.loads(run_input)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"engagement actor input is not valid JSON: {error}"
            ) from error
    else:
        value = run_input
    if not isinstance(value, dict):
        raise ValueError("engagement actor input must be a JSON object")
    return value


def _substitute(value, *, platform: str, url: str):
    """Replace the two placeholders, without touching the rest of the input."""
    if isinstance(value, str):
        return value.replace("{platform}", platform).replace("{url}", url)
    if isinstance(value, list):
        return [_substitute(item, platform=platform, url=url) for item in value]
    if isinstance(value, dict):
        return {
            key: _substitute(item, platform=platform, url=url)
            for key, item in value.items()
        }
    return value
