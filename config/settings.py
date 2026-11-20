"""Central project settings. Values come from .env, with safe defaults."""

from config.environment import optional

# Which AI to use. Change it in .env to switch model, without touching the code.
AI_PROVIDER = optional("AI_PROVIDER", "deepseek")

# Model name. Empty means "use the provider's default".
AI_MODEL = optional("AI_MODEL")

# DeepSeek credentials and model override. The key is required only when the
# DeepSeek provider is built, so tests and dry runs need no secret.
DEEPSEEK_API_KEY = optional("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = optional("DEEPSEEK_MODEL")

# Engagement sample: an Apify Actor run per creator. Empty means "no actor
# chosen": creators then go to review, as the engagement contract expects. The
# input is JSON text; {platform} and {url} are replaced per candidate.
ENGAGEMENT_ACTOR_ID = optional("ENGAGEMENT_ACTOR_ID")
ENGAGEMENT_ACTOR_INPUT = optional("ENGAGEMENT_ACTOR_INPUT")
ENGAGEMENT_ACTOR_MAX_ITEMS = optional("ENGAGEMENT_ACTOR_MAX_ITEMS")

# Telegram notifications. Empty means "not configured": the notifier then
# refuses with a clear message instead of failing at the network level.
TELEGRAM_BOT_TOKEN = optional("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = optional("TELEGRAM_CHAT_ID")

# Web search. Empty means "not configured": the integration refuses with a
# clear message instead of failing at the network level.
EXA_API_KEY = optional("EXA_API_KEY")
APIFY_API_KEY = optional("APIFY_API_KEY")
SERPAPI_API_KEY = optional("SERPAPI_API_KEY")

# Baserow. Les endpoints de schéma (tables, champs) attendent un JWT, pas un
# jeton de base. Le JWT s'obtient avec POST /api/user/token-auth/ et reste
# valide 60 minutes. Le jeton de base (Token) ne sert qu'aux endpoints de
# lignes. Empty values mean "not configured": the schema seeder stops.
BASEROW_URL = optional("BASEROW_URL")
BASEROW_TOKEN = optional("BASEROW_TOKEN")
BASEROW_DATABASE_ID = optional("BASEROW_DATABASE_ID")
BASEROW_AUTH_SCHEME = optional("BASEROW_AUTH_SCHEME", "JWT")

# Row access for the synchronization service. A schema JWT expires after an
# hour; a background service needs a database token that does not. Keep both
# credentials separate: the schema seeder stays on the JWT, the sync service
# uses BASEROW_ROW_TOKEN. When the row token is empty, the client falls back to
# BASEROW_TOKEN (useful for a short manual run, not for a long-lived worker).
BASEROW_ROW_TOKEN = optional("BASEROW_ROW_TOKEN")
BASEROW_ROW_AUTH_SCHEME = optional("BASEROW_ROW_AUTH_SCHEME", "Token")

# Table ids used by the synchronization service. A database token can read and
# write rows but may not list the schema, so the ids are configuration rather
# than a discovery step. They are visible in the Baserow URL:
# /database/{database_id}/table/{table_id}/. When all three are set, the sync
# service never asks Baserow for the schema.
BASEROW_TABLE_CREATORS = optional("BASEROW_TABLE_CREATORS")
BASEROW_TABLE_BUYERS = optional("BASEROW_TABLE_BUYERS")
BASEROW_TABLE_PLATFORMS = optional("BASEROW_TABLE_PLATFORMS")

# PostgreSQL: the critical data (facts, scores, eligibility). Empty means "not
# configured": the connection factory refuses with a clear message instead of
# failing at the network level.
DATABASE_URL = optional("DATABASE_URL")

# Roskomnadzor registry (creators). The registry is a public web form, not an
# API: the endpoint and the name of the field carrying the query are
# configuration, and an empty value means "not configured". The allowed domains
# are the official host names; a response from another host is a lookalike
# (V-09), never a registry answer.
RKN_SEARCH_URL = optional("RKN_SEARCH_URL")
RKN_QUERY_FIELD = optional("RKN_QUERY_FIELD")
RKN_ALLOWED_DOMAINS = optional("RKN_ALLOWED_DOMAINS")

# Sanctions lists. "SOURCE=url,SOURCE=url" (for example
# "OFAC_SDN=https://.../sdn.csv,EU=https://.../list.csv,UK=https://.../list.json").
# Each source is read independently: an unreadable list suspends the screening,
# it never clears it.
SANCTIONS_LIST_URLS = optional("SANCTIONS_LIST_URLS")

# Betting licence registries, one URL per country: "RU=https://...,KZ=https://...".
# A country without a URL is not mapped, which suspends the qualification instead
# of guessing (verification.md §5).
BETTING_LICENCE_URLS = optional("BETTING_LICENCE_URLS")
