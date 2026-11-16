"""Central project settings. Values come from .env, with safe defaults."""
from config.environment import optional

# Which AI to use. Change it in .env to switch model, without touching the code.
AI_PROVIDER = optional("AI_PROVIDER", "deepseek")

# Model name. Empty means "use the provider's default".
AI_MODEL = optional("AI_MODEL")

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

# PostgreSQL: the critical data (facts, scores, eligibility). Empty means "not
# configured": the connection factory refuses with a clear message instead of
# failing at the network level.
DATABASE_URL = optional("DATABASE_URL")
