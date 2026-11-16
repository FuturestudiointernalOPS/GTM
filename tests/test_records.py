"""Tests for record creation: identity, idempotency, buyer promotion.

The store is in memory, which is the point: the identity rules are decided here,
not by a database.
"""
from workflows.record_flow import BUYER, CREATOR
from workflows.record_loop import Candidate
from workflows.records import (
    CreatorIdentity,
    MemoryRecordStore,
    creator_identity,
    ensure_buyer,
    ensure_creator,
    ensure_record,
)

READ = "2026-11-10T12:00:00+00:00"


def candidate(url, kind=CREATOR):
    return Candidate(
        kind=kind, record_id="page", source_url=url, text="t", read_at=READ
    )


# --- identity ---------------------------------------------------------------


def test_a_creator_identity_is_the_platform_and_the_handle():
    assert creator_identity("https://vk.com/creator?utm_source=x") == CreatorIdentity(
        "VK Video", "creator"
    )
    assert creator_identity("https://t.me/Creator") == CreatorIdentity(
        "Telegram", "creator"
    )
    assert creator_identity("https://www.twitch.tv/creator") == CreatorIdentity(
        "Twitch", "creator"
    )
    assert creator_identity("https://www.youtube.com/@creator") == CreatorIdentity(
        "YouTube", "@creator"
    )
    assert creator_identity("https://www.youtube.com/channel/UC123") == CreatorIdentity(
        "YouTube", "channel:uc123"
    )
    assert creator_identity("https://rutube.ru/channel/123") == CreatorIdentity(
        "Rutube", "channel:123"
    )


def test_a_page_that_is_not_a_profile_has_no_identity():
    assert creator_identity("https://vk.com/video-1_2") is None
    assert creator_identity("https://t.me/s/channel") is None
    assert creator_identity("https://www.youtube.com/watch?v=x") is None
    assert creator_identity("https://example.com/creator") is None


# --- creators ---------------------------------------------------------------


def test_creating_twice_returns_the_same_ids():
    store = MemoryRecordStore()

    first = ensure_creator(store, candidate("https://vk.com/creator"))
    second = ensure_creator(store, candidate("https://vk.com/creator?utm=x"))

    assert first.record_id == second.record_id
    assert first.account_id == second.account_id
    assert first.created is True
    assert second.created is False


def test_two_platforms_are_two_records_for_now():
    store = MemoryRecordStore()

    vk = ensure_creator(store, candidate("https://vk.com/creator"))
    telegram = ensure_creator(store, candidate("https://t.me/creator"))

    assert vk.record_id != telegram.record_id


def test_a_page_that_is_not_a_profile_creates_nothing():
    store = MemoryRecordStore()

    assert ensure_record(store, candidate("https://example.com/x")) is None


# --- buyers -----------------------------------------------------------------


def test_a_buyer_with_a_tax_id_is_keyed_on_it():
    store = MemoryRecordStore()

    first = ensure_buyer(
        store, candidate("https://brand.ru", BUYER), tax_id="7700000000"
    )
    second = ensure_buyer(
        store, candidate("https://other.ru", BUYER), tax_id="7700000000"
    )

    assert first.record_id == second.record_id
    assert first.provisional is False


def test_a_buyer_without_a_tax_id_is_provisional_by_domain():
    store = MemoryRecordStore()

    first = ensure_buyer(store, candidate("https://brand.ru", BUYER))
    second = ensure_buyer(store, candidate("https://www.brand.ru/about", BUYER))

    assert first.provisional is True
    assert second.record_id == first.record_id


def test_a_tax_id_promotes_the_provisional_record():
    store = MemoryRecordStore()

    provisional = ensure_buyer(store, candidate("https://brand.ru", BUYER))
    promoted = ensure_buyer(
        store, candidate("https://brand.ru", BUYER), tax_id="7700000000"
    )

    assert promoted.record_id == provisional.record_id
    assert promoted.provisional is False

    # The tax key now finds it, even from another domain.
    elsewhere = ensure_buyer(
        store, candidate("https://other.ru", BUYER), tax_id="7700000000"
    )
    assert elsewhere.record_id == provisional.record_id


def test_ensure_record_dispatches_on_the_kind():
    store = MemoryRecordStore()

    creator = ensure_record(store, candidate("https://vk.com/x", CREATOR))
    buyer = ensure_record(store, candidate("https://brand.ru", BUYER))

    assert creator.account_id is not None
    assert buyer.account_id is None
