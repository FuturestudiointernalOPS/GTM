"""Tests for the registry comparison.

The search is injected; what is tested here is what a returned entry proves.
The point of the module is that a name is never a key and that a service that
does not answer is not an absence.
"""

from processing.eligibility import (
    MANUAL_REVIEW,
    MISMATCH,
    NOT_FOUND,
    PARTIAL,
    PENDING,
    VERIFIED,
)
from processing.rkn import RegistryEntry, RegistrySearch, compare

PAGE = "https://vk.com/creator"


def search(*entries, query="vk.com/creator", unavailable=False, lookalike=False):
    return RegistrySearch(
        query=query,
        entries=tuple(entries),
        unavailable=unavailable,
        lookalike=lookalike,
    )


def test_an_unavailable_service_is_pending_not_absent():
    check = compare(PAGE, search(unavailable=True))

    assert check.status == PENDING
    assert check.reasons == ("SERVICE_UNAVAILABLE",)


def test_an_empty_result_is_an_absence_and_keeps_the_query():
    check = compare(PAGE, search())

    assert check.status == NOT_FOUND
    assert check.reasons[0] == "QUERY:vk.com/creator"


def test_a_matching_url_and_identifier_is_verified():
    check = compare(
        PAGE,
        search(RegistryEntry((PAGE,), account_id="123")),
        account_id="123",
    )

    assert check.status == VERIFIED
    assert "URL_AND_IDENTIFIER_MATCH" in check.reasons


def test_a_matching_url_without_identifiers_is_partial():
    check = compare(PAGE, search(RegistryEntry((PAGE,))), account_id="123")

    assert check.status == PARTIAL


def test_a_matching_url_with_another_identifier_is_a_mismatch():
    check = compare(
        PAGE,
        search(RegistryEntry((PAGE,), account_id="999")),
        account_id="123",
    )

    assert check.status == MISMATCH
    assert "IDENTIFIER_MISMATCH" in check.reasons


def test_the_comparison_ignores_tracking_parameters_and_www():
    check = compare(
        "https://www.vk.com/creator/?utm_source=x",
        search(RegistryEntry(("https://vk.com/creator",))),
    )

    assert check.status == PARTIAL


def test_a_same_name_entry_on_another_url_is_a_mismatch():
    check = compare(
        PAGE,
        search(RegistryEntry(("https://vk.com/other",), name="Креатор ✨")),
        display_name="креатор",
    )

    assert check.status == MISMATCH
    assert "NAME_MATCH_URL_DIFFERS" in check.reasons


def test_a_different_name_does_not_make_a_match():
    check = compare(
        PAGE,
        search(RegistryEntry(("https://vk.com/other",), name="Другой")),
        display_name="Креатор",
    )

    assert check.status == MANUAL_REVIEW


def test_several_unrelated_entries_are_ambiguous():
    check = compare(
        PAGE,
        search(
            RegistryEntry(("https://vk.com/a",), name="A"),
            RegistryEntry(("https://vk.com/b",), name="B"),
        ),
    )

    assert check.status == MANUAL_REVIEW
    assert "AMBIGUOUS_ENTRIES" in check.reasons


def test_one_unrelated_entry_is_a_review_not_an_absence():
    check = compare(PAGE, search(RegistryEntry(("https://vk.com/other",))))

    assert check.status == MANUAL_REVIEW
    assert "NO_MATCHING_ENTRY" in check.reasons


def test_a_page_address_that_cannot_be_normalised_is_pending():
    check = compare("", search())

    assert check.status == PENDING
    assert "PAGE_URL_UNUSABLE" in check.reasons


def test_an_answer_from_an_imitated_host_is_a_review():
    check = compare(PAGE, search(lookalike=True))

    assert check.status == MANUAL_REVIEW
    assert check.reasons == ("LOOKALIKE_DOMAIN",)


def test_a_row_matches_when_any_of_its_addresses_matches():
    check = compare(
        PAGE,
        search(
            RegistryEntry(
                ("https://rutube.ru/channel/9", "https://vk.com/creator?utm_source=x")
            )
        ),
    )

    assert check.status == PARTIAL
