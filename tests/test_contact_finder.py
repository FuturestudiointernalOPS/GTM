from fractions import Fraction

from integrations.webreader import PageRead
from processing.contact_finder import contact_page_urls, find_in_text
from processing.contacts import PublicContact
from processing.scoring import ScoreResult
from workflows.contact_step import enrich_contacts
from workflows.record_flow import RecordScore
from workflows.record_loop import LoopResult

# --- find_in_text ----------------------------------------------------------


def test_email_with_its_role_and_quote():
    text = "Главная. По вопросам рекламы пишите: ads@studio.ru — ответим за день."
    (contact,) = find_in_text(text)
    assert contact.channel_type == "EMAIL"
    assert contact.channel_value == "ads@studio.ru"
    assert contact.role == "ADVERTISING_CONTACT"
    assert "ads@studio.ru" in contact.quote


def test_mailto_and_tel_links():
    contacts = find_in_text(
        "", ["mailto:partners@game.kz?subject=hi", "tel:+7 727 123 45 67"]
    )
    values = {c.channel_value for c in contacts}
    assert values == {"partners@game.kz", "+7 727 123 45 67"}


def test_noise_emails_are_ignored():
    text = "logo@2x.png noreply@site.ru user@example.com"
    assert find_in_text(text) == ()


def test_telegram_link_but_not_the_channel_itself():
    contacts = find_in_text(
        "По рекламе: @manager_ads",
        ["https://t.me/psychoclxn", "https://t.me/manager_ads", "https://t.me/share"],
        source_url="https://t.me/s/psychoclxn?before=233",
    )
    assert [c.channel_value for c in contacts] == ["@manager_ads"]
    assert contacts[0].role == "ADVERTISING_CONTACT"


def test_bare_handle_needs_a_contact_word_nearby():
    assert find_in_text("Сегодня играем с @friend_player в CS2") == ()
    (contact,) = find_in_text("Сотрудничество и реклама — @deals_manager")
    assert contact.channel_value == "@deals_manager"


def test_phone_formats():
    contacts = find_in_text("Отдел маркетинга: 8 (495) 123-45-67, факс нет")
    assert contacts[0].channel_type == "PHONE"
    assert contacts[0].role == "MARKETING"
    assert find_in_text("Заказ № 84951234567890") == ()


def test_best_contacts_first_and_capped():
    text = (
        "info@a.ru, hello@b.ru, team@c.ru, "
        "реклама: promo@d.ru, сотрудничество: collab@e.ru"
    )
    contacts = find_in_text(text)
    assert len(contacts) == 3
    assert contacts[0].channel_value == "promo@d.ru"
    assert contacts[1].channel_value == "collab@e.ru"


def test_found_on_is_kept_for_the_human_check():
    (contact,) = find_in_text("ads@x.ru", found_on="https://x.ru/contacts")
    assert contact.description == "trouvé sur https://x.ru/contacts"


# --- contact_page_urls -----------------------------------------------------


def test_company_site_prefers_its_own_contact_links():
    urls = contact_page_urls(
        "https://studio.ru/bloggers/",
        ["/about", "https://studio.ru/kontakty/", "https://vk.com/studio", "/games"],
        kind="BUYER",
    )
    assert urls == [
        "https://studio.ru/kontakty",
        "https://studio.ru/about",
        "https://studio.ru/contacts",
    ]


def test_news_articles_and_media_get_no_extra_read():
    assert contact_page_urls("https://adindex.ru/x", kind="BUYER") == []
    assert contact_page_urls("https://game.ru/news/launch", kind="BUYER") == []
    assert contact_page_urls("https://gov.kz/org/astana", kind="BUYER") == []
    assert contact_page_urls("https://shop.ru/catalog/pc/1234567", kind="BUYER") == []


def test_creator_pages():
    assert contact_page_urls("https://t.me/s/psychoclxn?before=1", kind="CREATOR") == [
        "https://t.me/psychoclxn"
    ]
    assert contact_page_urls("https://rutube.ru/channel/912314/", kind="CREATOR") == [
        "https://rutube.ru/channel/912314/about/"
    ]
    assert contact_page_urls("https://www.twitch.tv/x", kind="CREATOR") == []


# --- enrich_contacts -------------------------------------------------------


def _record(url, score, kind="BUYER", contacts=(), links=()):
    result = ScoreResult(
        proposal="TO_REVIEW",
        score=score,
        total_exact=Fraction(score or 0),
        lower_bound=None,
        upper_bound=None,
        incomplete=True,
        lines=(),
    )
    return RecordScore(
        kind=kind,
        result=result,
        source_url=url,
        contacts=contacts,
        page_links=links,
    )


def test_enrich_reads_contact_pages_best_scores_first():
    existing = PublicContact("OTHER", "EMAIL", "a@a.ru", quote="a@a.ru")
    scores = LoopResult(
        scored=(
            _record("https://low.ru/", 10),
            _record("https://high.ru/", 80),
            _record("https://done.ru/", 90, contacts=(existing,)),
            _record("https://none.ru/", None),
        ),
        failed=(),
    )
    reads = []

    def read(url):
        reads.append(url)
        if url == "https://high.ru/contacts":
            return PageRead(url=url, text="Реклама: ads@high.ru")
        return PageRead(url=url, error="404")

    result = enrich_contacts(scores, read=read, limit=1)

    assert reads == ["https://high.ru/contacts"]
    assert result.scored[1].contacts[0].channel_value == "ads@high.ru"
    assert result.scored[0].contacts == ()
    assert result.scored[2].contacts == (existing,)


def test_enrich_stops_at_the_first_page_with_a_contact():
    scores = LoopResult(scored=(_record("https://a.ru/", 50),), failed=())
    reads = []

    def read(url):
        reads.append(url)
        return PageRead(url=url, text="team@a.ru")

    enrich_contacts(scores, read=read, limit=5)
    assert reads == ["https://a.ru/contacts"]


def test_enrich_off_reads_nothing():
    scores = LoopResult(scored=(_record("https://a.ru/", 50),), failed=())
    assert enrich_contacts(scores, read=lambda url: 1 / 0, limit=0) is scores


def test_article_segments_are_matched_whole():
    assert contact_page_urls("https://mmo.ru/news/post-36508", kind="BUYER") == []
    assert contact_page_urls("https://game.ru/blog/", kind="BUYER") == []
    assert contact_page_urls(
        "https://tanki.su/ru/content/docs/blogger-program/", kind="BUYER"
    ) == [
        "https://tanki.su/contacts",
        "https://tanki.su/kontakty",
    ]


def test_channels_quoted_in_telegram_posts_are_not_contacts():
    source = "https://t.me/s/esports_uzbekistan?before=5396"
    text = "Турнир от @ucauz стартует! Смотрите @mlbbproliga. Реклама: @uz_ads_manager"
    links = [
        "https://t.me/ucauz",
        "https://t.me/mlbbproliga",
        "https://t.me/uz_ads_manager",
    ]
    contacts = find_in_text(text, links, source_url=source)
    assert [c.channel_value for c in contacts] == ["@uz_ads_manager"]


def test_company_site_telegram_link_counts_without_a_word():
    (contact,) = find_in_text(
        "Федерация", ["https://t.me/qcf_kz"], source_url="https://qcf.kz/"
    )
    assert contact.channel_value == "@qcf_kz"
