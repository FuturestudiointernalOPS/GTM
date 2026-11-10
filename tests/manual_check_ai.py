"""Manual check: send a fake creator to the configured AI and print the answer."""
from ai import get_ai_provider

provider = get_ai_provider()  # DeepSeek today; chosen by AI_PROVIDER in .env

fake_creator = {
    "name": "Test creator",
    "platform": "Twitch",
    "description": "Стримы по CS2 и Dota 2 каждый вечер",
    "followers": 12000,
}

result = provider.analyze_creator(fake_creator)
print("Provider:", type(provider).__name__, "| model:", provider.model)
print("Result:", result)
print("Tokens:", provider.last_usage.total_tokens)
