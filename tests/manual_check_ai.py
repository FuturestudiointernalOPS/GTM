"""Manual check: send a fake creator to the AI layer and print the answer."""
from dotenv import load_dotenv

load_dotenv()

from ai.deepseek import DeepSeekProvider  # noqa: E402

provider = DeepSeekProvider()

fake_creator = {
    "name": "Test creator",
    "platform": "Twitch",
    "description": "Стримы по CS2 и Dota 2 каждый вечер",
    "followers": 12000,
}

result = provider.analyze_creator(fake_creator)
print("Result:", result)
print("Tokens:", provider.last_usage.total_tokens)
