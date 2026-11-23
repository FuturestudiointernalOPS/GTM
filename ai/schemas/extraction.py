"""Strict shape of a model's extraction answer.

Unknown keys are refused at the border: the model may only answer about the
criteria the score knows. Value ranges are deliberately not enforced here — a
bad value must degrade one measure to unknown (S-02), not make the whole record
fail. The enrichment step owns that judgement.

Every claim must come with a **verbatim quote** from the page it was read on. The
quote is checked against the page by the loop; a claim without a quote is
discarded, which is what separates an extraction from an invention.

The field lists must match ``processing/enrichment.py``: the fact keys are the
contract, and a test asserts the two lists are equal.
"""

from pydantic import BaseModel, ConfigDict, Field


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


class ContactClaim(BaseModel):
    """One public professional contact proposed by the model."""

    model_config = ConfigDict(extra="forbid")

    role: str
    channel_type: str
    channel_value: str
    person_name: str | None = None
    description: str | None = None
    quote: str = ""


class ProgramClaim(BaseModel):
    """What a company offers or asks for, and how to submit something."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str
    submission_method: str | None = None
    submission_url: str | None = None
    quote: str = ""


class CreatorExtraction(BaseModel):
    """Claims, public contacts and the excerpts that support them."""

    model_config = ConfigDict(extra="forbid")

    claims: CreatorClaims
    quotes: dict[str, str] = Field(default_factory=dict)
    contacts: list[ContactClaim] = Field(default_factory=list)


class BuyerExtraction(BaseModel):
    """Claims, identity, public contacts, programmes and their excerpts."""

    model_config = ConfigDict(extra="forbid")

    claims: BuyerClaims
    quotes: dict[str, str] = Field(default_factory=dict)
    contacts: list[ContactClaim] = Field(default_factory=list)
    programs: list[ProgramClaim] = Field(default_factory=list)
    legal_name: str | None = None
