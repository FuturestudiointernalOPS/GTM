"""Central project settings. Values come from .env, with safe defaults."""
from config.environment import optional

# Which AI to use. Change it in .env to switch model, without touching the code.
AI_PROVIDER = optional("AI_PROVIDER", "deepseek")

# Model name. Empty means "use the provider's default".
AI_MODEL = optional("AI_MODEL")
