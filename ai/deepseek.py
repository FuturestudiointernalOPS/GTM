"""DeepSeek implementation of AIProvider."""
import os

from openai import OpenAI

from ai.provider import AIProvider


class DeepSeekProvider(AIProvider):
    """Talks to DeepSeek through its OpenAI-compatible API."""

    def __init__(self, model=None, api_key=None, base_url="https://api.deepseek.com/v1"):
        # Model and key come from the environment (.env), never from the code.
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self.client = OpenAI(
            api_key=api_key or os.environ["DEEPSEEK_API_KEY"],
            base_url=base_url,
        )
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
