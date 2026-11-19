"""Close the regulatory step after scoring: verification -> decision -> write.

The checks themselves are established by the procedures of
``docs/verification.md`` — the registry lookup, the label, the sanctions
screening and the licence. This module never searches a registry and never reads
a page: it takes the *results* of those procedures, applies the decision table of
``docs/eligibility.md``, and hands the verdict to the writer.

Why a JSON file: the checks are still performed by a human (``docs/scope.md``
§14.2). The file is the hand-over between that procedure and the run, and it is
what makes the step executable today without inventing a collector. A record
with no entry gets no verdict at all — a missing check is never a pass.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from processing import eligibility
from workflows.record_flow import BUYER, CREATOR, RecordScore

Verification = eligibility.CreatorVerification | eligibility.BuyerVerification
VerifyFor = Callable[[RecordScore], Verification | None]
EligibilityWriter = Callable[[RecordScore, eligibility.EligibilityDecision], str | None]


def decide(kind: str, verification: Verification) -> eligibility.EligibilityDecision:
    """Apply the filon's decision table to one verification.

    The filon is checked against the verification type: a creator verdict can
    never be computed from a buyer's checks, or the other way round.
    """
    if kind == CREATOR:
        if not isinstance(verification, eligibility.CreatorVerification):
            raise TypeError("a creator needs a CreatorVerification")
        return eligibility.decide_creator(verification)
    if kind == BUYER:
        if not isinstance(verification, eligibility.BuyerVerification):
            raise TypeError("a buyer needs a BuyerVerification")
        return eligibility.decide_buyer(verification)
    raise ValueError(f"unknown record kind: {kind!r}")


@dataclass(frozen=True)
class VerificationFile:
    """Verifications read from the operator's JSON hand-over.

    The key is the page address the run used as a handle (the record id is only
    known after the run, so it is accepted as a fallback for a replay). Each
    value carries the check results, and may name its ``kind``; without it, the
    record's filon is used.
    """

    entries: Mapping[str, Mapping]

    @classmethod
    def load(cls, path: str | Path) -> "VerificationFile":
        text = Path(path).read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"verification file is not valid JSON: {error}") from error
        if not isinstance(data, dict):
            raise ValueError("a verification file must hold an object keyed by URL")
        for key, entry in data.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                raise ValueError("each verification must be an object keyed by URL")
        return cls(entries=data)

    def for_record(self, record: RecordScore) -> Verification | None:
        """The verification for this record, or None when the file has none."""
        entry = None
        for key in (record.source_url, record.record_id):
            if key and key in self.entries:
                entry = self.entries[key]
                break
        if entry is None:
            return None
        return build_verification(record.kind, entry)


def build_verification(kind: str, entry: Mapping) -> Verification:
    """Validate one file entry into the dataclass the decision table expects."""
    payload = dict(entry)
    declared = str(payload.pop("kind", kind)).strip().upper()
    if declared != kind:
        raise ValueError(
            f"verification kind {declared!r} does not match record kind {kind!r}"
        )

    try:
        if kind == CREATOR:
            return eligibility.CreatorVerification(**payload)
        if kind == BUYER:
            return eligibility.BuyerVerification(**payload)
    except TypeError as error:
        raise ValueError(f"invalid {kind} verification: {error}") from error
    raise ValueError(f"unknown record kind: {kind!r}")
