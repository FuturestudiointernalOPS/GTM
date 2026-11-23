"""Check the control digit of a Russian INN or OGRN.

The advertisement label carries the advertiser's INN or OGRN. The database
stores whether the check digit is valid; the score and the extraction quality
report use that flag. Hyphens and spaces are tolerated, any other character
makes the identifier invalid rather than being silently removed.
"""

from __future__ import annotations


def is_valid_inn(value: str | None) -> bool:
    digits = _digits(value)
    if digits is None:
        return False
    if len(digits) == 10:
        weights = (2, 4, 10, 3, 5, 9, 4, 6, 8)
        control = sum(int(d) * w for d, w in zip(digits[:9], weights)) % 11 % 10
        return control == int(digits[9])
    if len(digits) == 12:
        weights_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        weights_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        control_11 = sum(int(d) * w for d, w in zip(digits[:10], weights_11)) % 11 % 10
        control_12 = sum(int(d) * w for d, w in zip(digits[:11], weights_12)) % 11 % 10
        return control_11 == int(digits[10]) and control_12 == int(digits[11])
    return False


def is_valid_ogrn(value: str | None) -> bool:
    digits = _digits(value)
    if digits is None:
        return False
    if len(digits) == 13:
        control = int(digits[:12]) % 11 % 10
        return control == int(digits[12])
    if len(digits) == 15:
        control = int(digits[:14]) % 13 % 10
        return control == int(digits[14])
    return False


def _digits(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    cleaned = text.replace("-", "").replace(" ", "")
    if not cleaned.isdigit():
        return None
    return cleaned
