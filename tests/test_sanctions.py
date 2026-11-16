"""Tests for sanctions screening, and for the list reader.

The screen is generous by design: a match opens a review, it never rejects. What
must not happen is a clear result obtained from a list nobody could read.
"""
import pytest

from config import settings
from integrations import sanctions as client
from processing.eligibility import MANUAL_REVIEW, NOT_FOUND, PENDING, VERIFIED
from processing.sanctions import SanctionsList, SanctionsScreening, screen


def screening(*sources, unavailable=()):
    return SanctionsScreening(
        lists=tuple(SanctionsList(source, names=names) for source, names in sources),
        unavailable=tuple(unavailable),
    )


# --- the screen -------------------------------------------------------------


def test_an_identical_name_opens_a_review():
    check = screen("ООО Ромашка", screening(("OFAC_SDN", ("ООО Ромашка",))))

    assert check.status == MANUAL_REVIEW
    assert check.reasons == ("MATCH:OFAC_SDN",)


def test_punctuation_and_case_do_not_hide_a_match():
    check = screen("ООО «РОМАШКА»", screening(("EU", ("ооо ромашка",))))

    assert check.status == MANUAL_REVIEW


def test_an_alias_is_screened_too():
    check = screen(
        "Иван Петров",
        screening(("UK_OFSI", ("Пётр Иванов",))),
        aliases=("Пётр Иванов",),
    )

    assert check.status == MANUAL_REVIEW


def test_a_listed_name_inside_a_longer_company_name_is_a_match():
    check = screen(
        "ООО Ромашка Групп", screening(("OFAC_SDN", ("Ромашка",)))
    )

    assert check.status == MANUAL_REVIEW


def test_a_short_name_inside_another_is_not_noise():
    check = screen("АО Ромашка", screening(("OFAC_SDN", ("АО",))))

    assert check.status == NOT_FOUND


def test_no_list_at_all_suspends_the_screen():
    check = screen("ООО Ромашка", SanctionsScreening())

    assert check.status == PENDING
    assert check.reasons == ("NOT_CHECKED",)


def test_an_unreadable_source_suspends_the_screen():
    check = screen(
        "ООО Ромашка",
        screening(("OFAC_SDN", ("Ромашка",)), unavailable=("EU",)),
    )

    assert check.status == PENDING
    assert check.reasons == ("SOURCE_UNAVAILABLE:EU",)


def test_a_clean_screen_names_the_sources_it_read():
    check = screen("ООО Ромашка", screening(("OFAC_SDN", ("Другое",))))

    assert check.status == NOT_FOUND
    assert check.reasons == ("NO_MATCH", "SCREENED:OFAC_SDN")


def test_an_unusable_subject_suspends_rather_than_clears():
    check = screen("   ", screening(("OFAC_SDN", ("Ромашка",))))

    assert check.status == PENDING
    assert check.reasons == ("SUBJECT_UNUSABLE",)


# --- reading the lists ------------------------------------------------------


def test_a_json_list_of_names_is_read():
    reading = client.parse_list('["ООО Ромашка", "Acme Ltd"]', source="EU")

    assert reading.names == ("ООО Ромашка", "Acme Ltd")


def test_a_json_list_of_objects_keeps_names_and_aliases():
    text = '[{"name": "ООО Ромашка", "aliases": ["Romashka", "Ромашка"]}]'

    reading = client.parse_list(text, source="EU")

    assert set(reading.names) == {"ООО Ромашка", "Romashka", "Ромашка"}


def test_a_csv_with_a_name_column_is_read():
    text = "SDN_Name,Program\nООО Ромашка,UKRAINE\nAcme Ltd,SDGT\n"

    reading = client.parse_list(text, source="OFAC_SDN")

    assert reading.names == ("ООО Ромашка", "Acme Ltd")


def test_a_csv_without_a_header_uses_the_first_column():
    text = "ООО Ромашка,1\nAcme Ltd,2\n"

    reading = client.parse_list(text, source="OFAC_SDN")

    assert reading.names == ("ООО Ромашка", "Acme Ltd")


def test_a_csv_alias_cell_holds_several_names():
    text = "Name,Aliases\nAcme Ltd,Acme;ACME Limited\n"

    reading = client.parse_list(text, source="EU")

    assert set(reading.names) == {"Acme Ltd", "Acme", "ACME Limited"}


def test_an_empty_list_is_refused():
    with pytest.raises(client.SanctionsError):
        client.parse_list("   ", source="EU")


def test_a_broken_json_export_is_refused():
    with pytest.raises(client.SanctionsError, match="invalid JSON"):
        client.parse_list("[{", source="EU")


# --- loading ----------------------------------------------------------------


def test_the_sources_come_from_one_setting(monkeypatch):
    monkeypatch.setattr(
        settings,
        "SANCTIONS_LIST_URLS",
        "OFAC_SDN=https://a.example/sdn.csv, EU=https://b.example/eu.json",
    )

    assert client.configured_sources() == {
        "OFAC_SDN": "https://a.example/sdn.csv",
        "EU": "https://b.example/eu.json",
    }
    assert client.is_configured() is True


def test_nothing_configured_is_an_error_not_a_clear_screen(monkeypatch):
    monkeypatch.setattr(settings, "SANCTIONS_LIST_URLS", "")

    assert client.is_configured() is False
    with pytest.raises(client.SanctionsError):
        client.load()


def test_an_unreachable_source_is_reported_not_ignored(monkeypatch):
    monkeypatch.setattr(
        settings, "SANCTIONS_LIST_URLS", "OFAC_SDN=https://a.example/sdn.csv"
    )

    reading = client.load(fetch=lambda url: None)

    assert reading.unavailable == ("OFAC_SDN",)
    assert reading.lists == ()


def test_one_broken_source_does_not_lose_the_others(monkeypatch):
    monkeypatch.setattr(
        settings,
        "SANCTIONS_LIST_URLS",
        "OFAC_SDN=https://a.example/sdn.csv,EU=https://b.example/eu.json",
    )

    def fetch(url):
        if "a.example" in url:
            return "Name\nООО Ромашка\n"
        return "[{"

    reading = client.load(fetch=fetch)

    assert [item.source for item in reading.lists] == ["OFAC_SDN"]
    assert reading.unavailable == ("EU",)


def test_the_client_screens_with_the_loaded_lists(monkeypatch):
    monkeypatch.setattr(
        settings, "SANCTIONS_LIST_URLS", "OFAC_SDN=https://a.example/sdn.csv"
    )

    check = client.screen(
        "ООО Ромашка", fetch=lambda url: "Name\nООО Ромашка\n"
    )

    assert check.status == MANUAL_REVIEW


def test_a_match_holds_the_fiche_for_compliance():
    from processing.eligibility import (
        COMPLIANCE_REVIEW,
        CreatorVerification,
        decide_creator,
    )

    check = screen("ООО Ромашка", screening(("OFAC_SDN", ("Ромашка",))))
    decision = decide_creator(
        CreatorVerification(
            platform_covered=True,
            followers=25_000,
            foreign_agent_label=False,
            rkn_status=VERIFIED,
            sanction_status=check.status,
            sanction_reasons=check.reasons,
        )
    )

    assert decision.workflow_status == COMPLIANCE_REVIEW
    assert decision.status is None
