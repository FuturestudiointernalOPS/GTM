"""Tests for the model's extraction answer: prompt, strict schema, claims.

The contract is the same list of keys as the enrichment step. A test asserts
that, so a model prompt and a criterion cannot drift apart silently.
"""
import pytest
from pydantic import ValidationError

from ai.provider import AIProvider
from ai.schemas.extraction import BuyerClaims, CreatorClaims
from processing.enrichment import BUYER_FACT_KEYS, CREATOR_FACT_KEYS

CREATOR_ANSWER = """{
  "gaming_share": 60,
  "gaming_window": 30,
  "followers": 25000,
  "published_last_30_days": 7,
  "ad_contact_or_rate_card": true,
  "past_labeled_ads": false,
  "main_platform": "VK Video",
  "russian_comment_share": 70,
  "comment_sample": 50
}"""

BUYER_ANSWER = """{
  "creators_paid": 1,
  "sells_to_gamers": true,
  "decision_maker_role": "CMO",
  "decision_maker_email_verified": true,
  "employee_band": "50-199",
  "recent_event": true
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

    claims = provider.extract_creator({"url": "https://vk.com/x"})

    assert claims.gaming_share == 60
    assert claims.main_platform == "VK Video"
    system, user = provider.calls[0]
    assert "gaming_share" in system
    assert user == '{"url": "https://vk.com/x"}'


def test_an_unknown_key_is_refused():
    provider = FakeProvider(CREATOR_ANSWER.replace("{", '{"is_gaming": true,'))

    with pytest.raises(ValidationError):
        provider.extract_creator({})


def test_missing_keys_stay_null():
    claims = FakeProvider('{"gaming_share": 60}').extract_creator({})

    assert claims.gaming_share == 60
    assert claims.followers is None


def test_a_wrapped_answer_is_unwrapped():
    claims = FakeProvider('```json\n{"gaming_share": 60}\n```').extract_creator({})

    assert claims.gaming_share == 60


def test_a_text_where_a_number_is_expected_is_refused():
    with pytest.raises(ValidationError):
        FakeProvider('{"gaming_share": "beaucoup"}').extract_creator({})


def test_the_claims_are_the_contract_keys():
    assert set(CreatorClaims.model_fields) == CREATOR_FACT_KEYS
    assert set(BuyerClaims.model_fields) == BUYER_FACT_KEYS


def test_the_buyer_prompt_exists_and_validates():
    claims = FakeProvider(BUYER_ANSWER).extract_buyer({})

    assert claims.creators_paid == 1
    assert claims.employee_band == "50-199"
