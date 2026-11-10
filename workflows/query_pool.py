"""The rotating query pool for creator and buyer discovery.

The pool comes from the supervisor's list (~100 queries, about 25 per week).
It was written for classic search engines, which understand ``site:``, quotes
and ``-``. Exa does not, so every query carries both forms:

- ``text``: natural-language text for Exa;
- ``engine_query``: the original classic-engine form, kept for audit and for a
  later SerpApi/Yandex integration;
- ``include_domains``: the ``site:`` replacement;
- ``exclude_text``: the ``-keyword`` replacement.

Rotation: 25 queries on a normal week, 21 on a CIS week (one week in three),
because the CIS block replaces the eight creator-model queries. Betting
queries are off by default: they may only run for licensed operators.

Tracking: every query has a stable ``id``. Workflows copy it to ``query_used``
so the tracker can tell which query produced a lead that later scores 70+.
"""
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import TypeVar

from workflows.search import SearchSpec

T = TypeVar("T")

# Scope §5.2 allows these platforms; Instagram and Facebook never enter collection.
CREATOR_PLATFORM_DOMAINS = (
    "twitch.tv",
    "vk.com",
    "vkvideo.ru",
    "rutube.ru",
    "t.me",
    "youtube.com",
    "youtu.be",
)
CREATOR_EXCLUDED_DOMAINS = ("instagram.com", "facebook.com")

# The supervisor's negative filters, kept separate for audit and passed to
# Exa's exclude_text instead of being written into the query text.
CASINO_NEGATIVES = ("казино", "слоты", "заносы")
CHEAT_NEGATIVES = ("читы", "взлом")
PIRACY_NEGATIVES = ("скачать", "торрент")
CREATOR_NEGATIVE_TERMS = CASINO_NEGATIVES + CHEAT_NEGATIVES + PIRACY_NEGATIVES


@dataclass(frozen=True)
class Game:
    key: str
    name: str
    young_audience: bool = False


# Brawl Stars, Roblox and Minecraft attract a young audience: they must never
# be used for betting campaigns (scope §6.4 and the supervisor's note).
GAMES = (
    Game("cs2", "CS2"),
    Game("dota2", "Dota 2"),
    Game("valorant", "Valorant"),
    Game("standoff2", "Standoff 2"),
    Game("minecraft", "Minecraft", young_audience=True),
    Game("mir_tankov", "Мир танков"),
    Game("escape_from_tarkov", "Escape from Tarkov"),
    Game("gta5_rp", "GTA 5 RP"),
    Game("brawl_stars", "Brawl Stars", young_audience=True),
    Game("roblox", "Roblox", young_audience=True),
)


@dataclass(frozen=True)
class Query:
    """One search query with both syntaxes and its tracking metadata."""

    id: str
    block: str
    text: str
    engine_query: str | None = None
    target: str = ""
    include_domains: tuple[str, ...] = ()
    exclude_domains: tuple[str, ...] = ()
    exclude_text: tuple[str, ...] = ()
    market: str = "RU"
    young_audience: bool = False
    betting: bool = False

    def as_search_spec(self) -> SearchSpec:
        """Convert to the execution layer, keeping the stable id for tracking."""
        return SearchSpec(
            text=self.text,
            query_id=self.id,
            include_domains=self.include_domains,
            exclude_domains=self.exclude_domains,
            exclude_text=self.exclude_text,
        )


@dataclass(frozen=True)
class CreatorTemplate:
    key: str
    engine: str
    text: str
    target: str
    include_domains: tuple[str, ...] = ()


CREATOR_TEMPLATES = (
    CreatorTemplate(
        "twitch",
        "русскоязычные стримеры {game} Twitch",
        "русскоязычный стример по {game}",
        "Streamers Twitch",
        ("twitch.tv",),
    ),
    CreatorTemplate(
        "vk_live",
        "стримеры {game} VK Видео Live",
        "русскоязычный стример по {game} на VK Видео Live",
        "Streamers VK Video Live",
        ("vk.com", "vkvideo.ru"),
    ),
    CreatorTemplate(
        "telegram",
        "игровой телеграм-канал {game}",
        "игровой телеграм-канал по {game}",
        "Chaînes Telegram",
        ("t.me",),
    ),
    CreatorTemplate(
        "rutube",
        "блогер {game} Rutube",
        "русскоязычный блогер по {game} на Rutube",
        "Créateurs Rutube",
        ("rutube.ru",),
    ),
    CreatorTemplate(
        "ad_ready",
        '{game} стример "по вопросам рекламы"',
        "стример по {game} реклама сотрудничество",
        "Prêt pour la publicité",
    ),
    CreatorTemplate(
        "rkn",
        '{game} блогер "реестр Роскомнадзора"',
        "блогер по {game} реестр Роскомнадзора",
        "Inscrit au registre RKN",
    ),
    CreatorTemplate(
        "tgstat",
        "рейтинг каналов {game} tgstat",
        "рейтинг телеграм-каналов по {game}",
        "Annuaire tgstat",
        ("tgstat.com",),
    ),
)

GENERAL_CREATOR_QUERIES = (
    Query(
        "creator.general.telegram_rating_2026",
        "creators.general",
        "рейтинг игровых телеграм-каналов 2026",
        "рейтинг игровых телеграм-каналов 2026",
        "Classement des canaux Telegram",
        exclude_domains=CREATOR_EXCLUDED_DOMAINS,
        exclude_text=CREATOR_NEGATIVE_TERMS,
    ),
    Query(
        "creator.general.vk_live_rating_2026",
        "creators.general",
        "рейтинг стримеров VK Видео Live 2026",
        "рейтинг стримеров VK Видео Live 2026",
        "Classement des streamers VK Video Live",
        include_domains=("vk.com", "vkvideo.ru"),
        exclude_domains=CREATOR_EXCLUDED_DOMAINS,
        exclude_text=CREATOR_NEGATIVE_TERMS,
    ),
    Query(
        "creator.general.rutube_top",
        "creators.general",
        "топ игровых блогеров Rutube",
        "топ игровых блогеров Rutube",
        "Top des créateurs Rutube",
        include_domains=("rutube.ru",),
        exclude_domains=CREATOR_EXCLUDED_DOMAINS,
        exclude_text=CREATOR_NEGATIVE_TERMS,
    ),
    Query(
        "creator.general.small_streamers",
        "creators.general",
        "небольшие игровые стримеры русскоязычные",
        "небольшие игровые стримеры русскоязычные",
        "Petits streamers russophones",
        exclude_domains=CREATOR_EXCLUDED_DOMAINS,
        exclude_text=CREATOR_NEGATIVE_TERMS,
    ),
)

BUYER_ADS = (
    Query(
        "buyer.ads.games_promo",
        "buyers.ads",
        "реклама erid ИНН игры промокод",
        '"Реклама" "erid" "ИНН" игры промокод',
        "Annonceurs — jeux et codes promo",
    ),
    Query(
        "buyer.ads.esports",
        "buyers.ads",
        "реклама erid киберспорт",
        '"Реклама" "erid" киберспорт',
        "Annonceurs — esport",
    ),
    Query(
        "buyer.ads.gaming_pcs",
        "buyers.ads",
        "реклама erid игровые компьютеры",
        '"Реклама" "erid" игровые компьютеры',
        "Annonceurs — PC gaming",
    ),
    Query(
        "buyer.ads.peripherals",
        "buyers.ads",
        "реклама erid игровая периферия",
        '"Реклама" "erid" игровая периферия',
        "Annonceurs — périphériques",
    ),
    Query(
        "buyer.ads.mobile_prereg",
        "buyers.ads",
        "реклама erid мобильная игра предрегистрация",
        '"Реклама" "erid" мобильная игра предрегистрация',
        "Annonceurs — jeu mobile en préinscription",
    ),
    Query(
        "buyer.ads.lan_club",
        "buyers.ads",
        "реклама erid компьютерный клуб",
        '"Реклама" "erid" компьютерный клуб',
        "Annonceurs — club informatique",
    ),
    Query(
        "buyer.ads.betting_esports",
        "buyers.ads",
        "реклама erid 18+ ставки киберспорт",
        '"Реклама" "erid" "18+" ставки киберспорт',
        "Annonceurs — paris esport (licence requise)",
        betting=True,
    ),
)

BUYER_SPONSORS = (
    Query(
        "buyer.sponsors.cs2_2026",
        "buyers.sponsors",
        "спонсор турнира по CS2 2026",
        "спонсор турнира по CS2 2026",
        "Sponsor d'un tournoi CS2",
    ),
    Query(
        "buyer.sponsors.dota2_general",
        "buyers.sponsors",
        "генеральный партнёр турнира по Dota 2",
        "генеральный партнёр турнира по Dota 2",
        "Partenaire général d'un tournoi Dota 2",
    ),
    Query(
        "buyer.sponsors.team_partners",
        "buyers.sponsors",
        "официальные партнёры киберспортивной команды",
        "официальные партнёры киберспортивной команды",
        "Partenaires officiels d'une équipe esport",
    ),
    Query(
        "buyer.sponsors.standoff2_prize",
        "buyers.sponsors",
        "призовой фонд турнира Standoff 2 партнёры",
        "призовой фонд турнира Standoff 2 партнёры",
        "Partenaires d'un tournoi Standoff 2",
    ),
    Query(
        "buyer.sponsors.tournament_seeking",
        "buyers.sponsors",
        "организатор киберспортивного турнира ищет спонсоров",
        "организатор киберспортивного турнира ищет спонсоров",
        "Organisateur cherchant des sponsors",
    ),
    Query(
        "buyer.sponsors.org_press_release",
        "buyers.sponsors",
        "партнёрство киберспортивная организация пресс-релиз 2026",
        "партнёрство киберспортивная организация пресс-релиз 2026",
        "Communiqué de partenariat esport",
    ),
)

BUYER_CATEGORIES = (
    Query(
        "buyer.category.mobile_publishers",
        "buyers.categories",
        "российский издатель мобильных игр маркетинг",
        "российский издатель мобильных игр маркетинг",
        "Éditeur russe de jeux mobiles",
    ),
    Query(
        "buyer.category.game_studios",
        "buyers.categories",
        "студия разработки игр сотрудничество с блогерами",
        "студия разработки игр сотрудничество с блогерами",
        "Studio de développement de jeux",
    ),
    Query(
        "buyer.category.gaming_pc_shops",
        "buyers.categories",
        "интернет-магазин игровых компьютеров сотрудничество с блогерами",
        "интернет-магазин игровых компьютеров сотрудничество с блогерами",
        "Boutique de PC gaming",
    ),
    Query(
        "buyer.category.peripheral_makers",
        "buyers.categories",
        "производитель игровой периферии Россия",
        "производитель игровой периферии Россия",
        "Fabricant de périphériques gaming",
    ),
    Query(
        "buyer.category.lan_chain",
        "buyers.categories",
        "сеть компьютерных клубов франшиза",
        "сеть компьютерных клубов франшиза",
        "Réseau de clubs informatiques",
    ),
    Query(
        "buyer.category.bookmakers",
        "buyers.categories",
        "букмекер ЦУПИС партнёрство киберспорт",
        "букмекер ЦУПИС партнёрство киберспорт",
        "Bookmaker licencié (contrôle de licence requis)",
        betting=True,
    ),
    Query(
        "buyer.category.influence_agencies",
        "buyers.categories",
        "агентство инфлюенс-маркетинга игры стримеры",
        "агентство инфлюенс-маркетинга игры стримеры",
        "Agence d'influence gaming",
    ),
    Query(
        "buyer.category.case_studies",
        "buyers.categories",
        "кейс интеграции у игровых стримеров результаты бренд",
        "кейс интеграции у игровых стримеров результаты бренд",
        "Étude de cas d'intégration de marque",
    ),
)

BUYER_TIMING = (
    Query(
        "buyer.timing.blogger_manager",
        "buyers.timing",
        "вакансия менеджер по работе с блогерами игры",
        "вакансия менеджер по работе с блогерами игры (hh.ru)",
        "Recrutement — responsable influence",
        include_domains=("hh.ru",),
    ),
    Query(
        "buyer.timing.influence_marketer",
        "buyers.timing",
        "вакансия influence-маркетолог геймдев",
        "вакансия influence-маркетолог геймдев",
        "Recrutement — influence marketing",
    ),
    Query(
        "buyer.timing.game_release",
        "buyers.timing",
        "анонс релиза игры декабрь 2026",
        "анонс релиза игры декабрь 2026",
        "Annonce de sortie de jeu",
    ),
    Query(
        "buyer.timing.cs2_tournament",
        "buyers.timing",
        "регистрация на турнир по CS2 открыта призовой фонд ноябрь 2026",
        "регистрация на турнир по CS2 открыта призовой фонд ноябрь 2026",
        "Tournoi CS2 ouvert aux inscriptions",
    ),
    Query(
        "buyer.timing.closed_beta",
        "buyers.timing",
        "закрытое бета-тестирование набор тестеров 2026",
        "закрытое бета-тестирование набор тестеров 2026",
        "Bêta fermée — recrutement de testeurs",
    ),
    Query(
        "buyer.timing.hardware_launch",
        "buyers.timing",
        "презентация нового игрового устройства Россия 2026",
        "презентация нового игрового устройства Россия 2026",
        "Lancement d'un périphérique gaming",
    ),
)

CIS_KZ_STREAMERS = CreatorTemplate(
    "kz_streamers",
    "казахстанские стримеры {game}",
    "казахстанский русскоязычный стример по {game}",
    "Streamers Kazakhstan",
)

CIS_CREATOR_QUERIES = (
    Query(
        "cis.uz_gaming_bloggers",
        "cis.creators",
        "игровые блогеры Узбекистана на русском языке",
        "игровые блогеры Узбекистана на русском языке",
        "Créateurs gaming Ouzbékistan",
        include_domains=CREATOR_PLATFORM_DOMAINS,
        exclude_domains=CREATOR_EXCLUDED_DOMAINS,
        exclude_text=CREATOR_NEGATIVE_TERMS,
        market="UZ",
    ),
)

CIS_BUYER_QUERIES = (
    Query(
        "cis.kz_esports_partners",
        "cis.buyers",
        "киберспортивный турнир в Казахстане партнёры 2026",
        "киберспорт Казахстан партнёры турнир 2026",
        "Tournoi et sponsors Kazakhstan",
        exclude_domains=CREATOR_EXCLUDED_DOMAINS,
        market="KZ",
    ),
    Query(
        "cis.by_esports_partners",
        "cis.buyers",
        "киберспортивный турнир в Беларуси партнёры",
        "киберспорт Беларусь турнир партнёры",
        "Tournoi et sponsors Biélorussie (contrôle sanctions renforcé)",
        exclude_domains=CREATOR_EXCLUDED_DOMAINS,
        market="BY",
    ),
)

BETTING_QUERIES = tuple(
    query for query in BUYER_ADS + BUYER_CATEGORIES if query.betting
)


@dataclass(frozen=True)
class CompanyTemplate:
    key: str
    engine: str
    text: str
    target: str


COMPANY_TEMPLATES = (
    CompanyTemplate(
        "marketing_director",
        "{company} директор по маркетингу интервью",
        "{company} директор по маркетингу интервью",
        "Responsable marketing",
    ),
    CompanyTemplate(
        "blogger_manager",
        "{company} руководитель по работе с блогерами",
        "{company} руководитель по работе с блогерами",
        "Responsable influence",
    ),
    CompanyTemplate(
        "advertiser_contacts",
        "{company} для рекламодателей контакты",
        "{company} для рекламодателей контакты",
        "Contacts annonceurs",
    ),
    CompanyTemplate(
        "registry_ids",
        "{company} ИНН ОГРН",
        "{company} ИНН ОГРН",
        "Identifiants du registre public",
    ),
)


def all_creator_model_queries() -> tuple[Query, ...]:
    """Every game × template combination, before the weekly rotation."""
    return tuple(
        _creator_query(template, game)
        for template in CREATOR_TEMPLATES
        for game in GAMES
    )


def betting_compatible_games() -> tuple[Game, ...]:
    """Games that may be paired with a betting campaign.

    Minecraft, Brawl Stars and Roblox attract a young audience and are never
    allowed for betting, whatever the creator's size or score.
    """
    return tuple(game for game in GAMES if not game.young_audience)


def all_cis_queries() -> tuple[Query, ...]:
    """The CIS block: one streamer template per game plus the fixed queries."""
    streamers = tuple(
        _creator_query(
            CIS_KZ_STREAMERS,
            game,
            block="cis.creators",
            prefix="cis",
            market="KZ",
            include_domains=CREATOR_PLATFORM_DOMAINS,
        )
        for game in GAMES
    )
    return streamers + CIS_CREATOR_QUERIES + CIS_BUYER_QUERIES


def all_queries() -> tuple[Query, ...]:
    """The whole pool, without the per-company contact queries (B5)."""
    return (
        all_creator_model_queries()
        + GENERAL_CREATOR_QUERIES
        + BUYER_ADS
        + BUYER_SPONSORS
        + BUYER_CATEGORIES
        + BUYER_TIMING
        + all_cis_queries()
    )


def company_queries(company: str) -> tuple[Query, ...]:
    """B5: four professional-contact queries for one already-found buyer."""
    company = company.strip()
    if not company:
        raise ValueError("company must not be empty")
    digest = hashlib.sha1(
        company.encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:8]
    return tuple(
        Query(
            id=f"buyer.contacts.{template.key}.{digest}",
            block="buyers.contacts",
            text=template.text.format(company=company),
            engine_query=template.engine.format(company=company),
            target=f"{template.target} — {company}",
        )
        for template in COMPANY_TEMPLATES
    )


def creator_plan(week: int | None = None) -> tuple[Query, ...]:
    """The creator half of a week: 12 queries, or 6 on a CIS week."""
    week = _week(week)
    if week % 3 == 0:
        game = _rotate(GAMES, 1, week)[0]
        streamer = _creator_query(
            CIS_KZ_STREAMERS,
            game,
            block="cis.creators",
            prefix="cis",
            market="KZ",
            include_domains=CREATOR_PLATFORM_DOMAINS,
        )
        return (streamer,) + CIS_CREATOR_QUERIES + GENERAL_CREATOR_QUERIES

    games = _rotate(GAMES, 2, week)
    templates = _rotate(CREATOR_TEMPLATES, 4, week)
    models = tuple(
        _creator_query(template, game) for game in games for template in templates
    )
    return models + GENERAL_CREATOR_QUERIES


def buyer_plan(
    week: int | None = None,
    *,
    include_betting: bool = False,
) -> tuple[Query, ...]:
    """The buyer half of a week: 13 queries, or 15 on a CIS week.

    Betting queries are added on top only when ``include_betting`` is true;
    they never displace the core block, and they require a licence check.
    """
    week = _week(week)
    ads = _rotate(
        tuple(query for query in BUYER_ADS if not query.betting),
        5,
        week,
    )
    sponsors = _rotate(BUYER_SPONSORS, 3, week)
    categories = _rotate(
        tuple(query for query in BUYER_CATEGORIES if not query.betting),
        3,
        week,
    )
    timing = _rotate(BUYER_TIMING, 2, week)

    queries = ads + sponsors + categories + timing
    if week % 3 == 0:
        queries += CIS_BUYER_QUERIES
    if include_betting:
        queries += BETTING_QUERIES
    return queries


def week_plan(
    week: int | None = None,
    *,
    include_betting: bool = False,
) -> tuple[Query, ...]:
    """The full rotation: 25 queries, or 21 on a CIS week."""
    week = _week(week)
    return creator_plan(week) + buyer_plan(week, include_betting=include_betting)


def current_week() -> int:
    """The ISO week number, used when no week is given."""
    return date.today().isocalendar().week


def _creator_query(
    template: CreatorTemplate,
    game: Game,
    *,
    block: str = "creators.models",
    prefix: str = "creator",
    market: str = "RU",
    include_domains: tuple[str, ...] | None = None,
) -> Query:
    return Query(
        id=f"{prefix}.{template.key}.{game.key}",
        block=block,
        text=template.text.format(game=game.name),
        engine_query=template.engine.format(game=game.name),
        target=f"{template.target} — {game.name}",
        include_domains=(
            template.include_domains if include_domains is None else include_domains
        ),
        exclude_domains=CREATOR_EXCLUDED_DOMAINS,
        exclude_text=CREATOR_NEGATIVE_TERMS,
        market=market,
        young_audience=game.young_audience,
    )


def _rotate(items: Sequence[T], count: int, week: int) -> tuple[T, ...]:
    """Pick a different slice every week without repeating inside the slice."""
    if not items:
        return ()
    count = min(count, len(items))
    start = (week - 1) * count % len(items)
    return tuple(items[(start + offset) % len(items)] for offset in range(count))


def _week(week: int | None) -> int:
    if week is None:
        return current_week()
    if isinstance(week, bool) or not isinstance(week, int) or not 1 <= week <= 53:
        raise ValueError("week must be an ISO week number between 1 and 53")
    return week
