"""Pick the AI provider named in the settings."""
from config import settings


def get_ai_provider():
    """Return the AI provider chosen in .env (AI_PROVIDER)."""
    if settings.AI_PROVIDER == "deepseek":
        from ai.deepseek import DeepSeekProvider
        return DeepSeekProvider(model=settings.AI_MODEL)

    raise ValueError(
        f"Unknown AI_PROVIDER: {settings.AI_PROVIDER!r} (supported: deepseek)"
    )
