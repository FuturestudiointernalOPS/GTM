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
