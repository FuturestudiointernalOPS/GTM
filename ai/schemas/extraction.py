"""Strict shape of a model's extraction answer.

Unknown keys are refused at the border: the model may only answer about the
criteria the score knows. Value ranges are deliberately not enforced here — a
bad value must degrade one measure to unknown (S-02), not make the whole record
fail. The enrichment step owns that judgement.

The field lists must match ``processing/enrichment.py``: the fact keys are the
contract, and a test asserts the two lists are equal.
"""
from pydantic import BaseModel, ConfigDict


class CreatorClaims(BaseModel):
    """What the model may assert about one creator."""

    model_config = ConfigDict(extra="forbid")

    gaming_share: float | None = None
    gaming_window: int | None = None
    followers: int | None = None
    published_last_30_days: int | None = None
    ad_contact_or_rate_card: bool | None = None
    past_labeled_ads: bool | None = None
    main_platform: str | None = None
    russian_comment_share: float | None = None
    comment_sample: int | None = None


class BuyerClaims(BaseModel):
    """What the model may assert about one buyer."""

    model_config = ConfigDict(extra="forbid")

    creators_paid: int | None = None
    sells_to_gamers: bool | None = None
    decision_maker_role: str | None = None
    decision_maker_email_verified: bool | None = None
    employee_band: str | None = None
    recent_event: bool | None = None
