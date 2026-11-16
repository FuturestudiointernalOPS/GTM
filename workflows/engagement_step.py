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
from collections.abc import Callable, Iterable

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
