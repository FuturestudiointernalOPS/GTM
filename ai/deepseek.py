"""DeepSeek implementation of AIProvider."""

from openai import OpenAI

from ai.provider import AIProvider
from config import settings

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-v4-flash"


class DeepSeekProvider(AIProvider):
    """Talks to DeepSeek through its OpenAI-compatible API."""

    def __init__(self, model=None, api_key=None, base_url=DEFAULT_BASE_URL):
        # Model and key come from the environment (.env), never from the code.
        self.model = (
            model or settings.AI_MODEL or settings.DEEPSEEK_MODEL or DEFAULT_MODEL
        )
        key = api_key or settings.DEEPSEEK_API_KEY
        if not key:
            raise RuntimeError(
                "Missing setting: DEEPSEEK_API_KEY (add it to the .env file)"
            )
        self.client = OpenAI(api_key=key, base_url=base_url)
        self.last_usage = None  # tokens of the last call, for cost tracking

    def chat(self, system: str, user: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        self.last_usage = response.usage
        return response.choices[0].message.content
