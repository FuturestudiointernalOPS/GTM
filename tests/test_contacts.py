"""Tests for public contact and programme verification. No network."""

from processing.contacts import (
    BuyerProgram,
    verify_contacts,
    verify_programs,
)


PAGE = (
    "По вопросам рекламы: press@studio.ru. "
    "Подать заявку можно через форму на странице. "
    "Наш Telegram: @studiopress."
)


def contact(**overrides):
    values = {
        "role": "ADVERTISING_CONTACT",
        "channel_type": "EMAIL",
        "channel_value": "press@studio.ru",
        "person_name": None,
        "description": "publicité",
        "quote": "По вопросам рекламы: press@studio.ru",
    }
    values.update(overrides)
    return values


def program(**overrides):
    values = {
        "title": "Programme créateurs",
        "description": "Nous payons des créateurs pour des intégrations.",
        "submission_method": "formulaire",
        "submission_url": "https://studio.example/creators",
        "quote": "Подать заявку можно через форму на странице",
    }
    values.update(overrides)
    return values


def test_a_published_email_is_kept():
    (kept,) = verify_contacts(
        [contact()],
        text=PAGE,
        source_url="https://studio.example",
    )

    assert kept.role == "ADVERTISING_CONTACT"
    assert kept.channel_type == "EMAIL"
    assert kept.channel_value == "press@studio.ru"
    assert kept.role_label == "contact publicitaire"
    assert "press@studio.ru" in kept.summary()


def test_a_contact_not_on_the_page_is_dropped():
    assert (
        verify_contacts(
            [contact(channel_value="other@studio.ru")],
            text=PAGE,
            source_url="https://studio.example",
        )
        == ()
    )


def test_a_quote_not_on_the_page_is_dropped():
    assert (
        verify_contacts(
            [contact(quote="Cette phrase n'existe pas sur la page")],
            text=PAGE,
            source_url="https://studio.example",
        )
        == ()
    )


def test_a_contact_without_a_known_role_is_dropped():
    assert (
        verify_contacts(
            [contact(role="UNKNOWN")],
            text=PAGE,
            source_url="https://studio.example",
        )
        == ()
    )


def test_a_telegram_handle_is_verified_through_the_page_link():
    (kept,) = verify_contacts(
        [
            contact(
                role="INFLUENCE_PARTNERSHIPS",
                channel_type="TELEGRAM",
                channel_value="@studiopress",
                quote="Наш Telegram: @studiopress",
            )
        ],
        text=PAGE,
        links=("https://t.me/studiopress",),
        source_url="https://studio.example",
    )

    assert kept.channel_type == "TELEGRAM"
    assert kept.channel_value == "@studiopress"


def test_a_form_on_the_page_needs_a_form_quote():
    (kept,) = verify_contacts(
        [
            contact(
                role="INFLUENCE_PARTNERSHIPS",
                channel_type="FORM",
                channel_value="",
                quote="Подать заявку можно через форму на странице",
            )
        ],
        text=PAGE,
        source_url="https://studio.example",
    )

    assert kept.channel_type == "FORM"
    assert kept.channel_value == "https://studio.example"


def test_contacts_are_capped_and_deduplicated():
    kept = verify_contacts(
        [
            contact(),
            contact(),
            contact(
                channel_type="TELEGRAM",
                channel_value="@studiopress",
                quote="Наш Telegram: @studiopress",
            ),
            contact(
                role="AGENCY",
                channel_type="PHONE",
                channel_value="+7 999 123-45-67",
                quote="По вопросам рекламы: press@studio.ru",
            ),
        ],
        text=PAGE + " +7 999 123-45-67",
        source_url="https://studio.example",
    )

    assert len(kept) <= 3
    assert len(
        {(item.channel_type, item.channel_value.lower()) for item in kept}
    ) == len(kept)


def test_a_programme_needs_a_quote_and_a_known_submission_link():
    (kept,) = verify_programs(
        [program()],
        text=PAGE,
        links=("https://studio.example/creators",),
    )

    assert kept.title == "Programme créateurs"
    assert kept.submission_url == "https://studio.example/creators"
    assert "soumission" in kept.summary()


def test_a_programme_with_an_unknown_link_is_dropped():
    assert (
        verify_programs(
            [program(submission_url="https://elsewhere.example/form")],
            text=PAGE,
            links=("https://studio.example/creators",),
        )
        == ()
    )


def test_the_programme_limit_is_three():
    items = [program(title=f"Programme {index}") for index in range(5)]

    assert len(verify_programs(items, text=PAGE)) <= 3


def test_labels_fall_back_to_readable_words():
    assert BuyerProgram(description="x").summary().startswith("Programme")
