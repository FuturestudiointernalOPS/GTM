"""Tests for the Russian INN and OGRN control digits."""

from processing.russian_ids import is_valid_inn, is_valid_ogrn


def test_a_ten_digit_inn():
    assert is_valid_inn("7707083893")
    assert not is_valid_inn("7707083894")


def test_a_twelve_digit_inn():
    assert is_valid_inn("500100732259")
    assert not is_valid_inn("500100732258")


def test_an_ogrn_and_an_ogrnip():
    assert is_valid_ogrn("1027700132195")
    assert not is_valid_ogrn("1027700132194")
    assert is_valid_ogrn("304500116000157")
    assert not is_valid_ogrn("304500116000158")


def test_separators_are_tolerated_but_letters_are_not():
    assert is_valid_inn("7707 083 893")
    assert is_valid_inn("7707-083-893")
    assert not is_valid_inn("7707O83893")


def test_empty_or_wrong_length_is_invalid():
    assert not is_valid_inn("")
    assert not is_valid_inn("123")
    assert not is_valid_ogrn(None)
    assert not is_valid_ogrn("123")
