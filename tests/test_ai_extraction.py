"""Tests for the model's extraction answer: prompt, strict schema, quotes.

The contract is the same list of keys as the enrichment step. A test asserts
that, so a model prompt and a criterion cannot drift apart silently.
"""

import pytest
from pydantic import ValidationError

from ai.provider import AIProvider
from ai.schemas.extraction import BuyerClaims, CreatorClaims
from processing.enrichment import BUYER_FACT_KEYS, CREATOR_FACT_KEYS

CREATOR_ANSWER = """{
  "claims": {
    "gaming_share": 60,
    "gaming_window": 30,
    "followers": 25000,
    "published_last_30_days": 7,
    "ad_contact_or_rate_card": true,
    "past_labeled_ads": false,
    "main_platform": "VK Video",
    "russian_comment_share": 70,
    "comment_sample": 50
  },
  "quotes": {"gaming_share": "60 % гейминг"}
}"""

BUYER_ANSWER = """{
  "claims": {
    "creators_paid": 1,
    "sells_to_gamers": true,
    "decision_maker_role": "CMO",
    "decision_maker_email_verified": true,
    "employee_band": "50-199",
    "recent_event": true
  },
  "quotes": {"creators_paid": "2 интеграции с erid"}
}"""


class FakeProvider(AIProvider):
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.answer


def test_the_prompt_is_read_and_the_answer_validated():
    provider = FakeProvider(CREATOR_ANSWER)

    extraction = provider.extract_creator({"url": "https://vk.com/x"})

    assert extraction.claims.gaming_share == 60
    assert extraction.claims.main_platform == "VK Video"
    assert extraction.quotes["gaming_share"] == "60 % гейминг"
    system, user = provider.calls[0]
    assert "gaming_share" in system
    assert "verbatim" in system
    assert user == '{"url": "https://vk.com/x"}'


def test_an_unknown_key_is_refused():
    provider = FakeProvider(
        CREATOR_ANSWER.replace('"gaming_share": 60,', '"is_gaming": true,')
    )

    with pytest.raises(ValidationError):
        provider.extract_creator({})


def test_a_claim_without_a_quote_is_still_a_valid_answer():
    # The schema does not decide: the loop drops it when the quote is checked.
    extraction = FakeProvider('{"claims": {"gaming_share": 60}}').extract_creator({})

    assert extraction.claims.gaming_share == 60
    assert extraction.quotes == {}


def test_a_wrapped_answer_is_unwrapped():
    extraction = FakeProvider(
        '```json\n{"claims": {"gaming_share": 60}}\n```'
    ).extract_creator({})

    assert extraction.claims.gaming_share == 60


def test_a_text_where_a_number_is_expected_is_refused():
    with pytest.raises(ValidationError):
        FakeProvider('{"claims": {"gaming_share": "beaucoup"}}').extract_creator({})


def test_the_claims_are_the_contract_keys():
    assert set(CreatorClaims.model_fields) == CREATOR_FACT_KEYS
    assert set(BuyerClaims.model_fields) == BUYER_FACT_KEYS


def test_the_buyer_prompt_exists_and_validates():
    extraction = FakeProvider(BUYER_ANSWER).extract_buyer({})

    assert extraction.claims.creators_paid == 1
    assert extraction.claims.employee_band == "50-199"
