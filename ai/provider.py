"""Common AI interface.

Workflows only talk to AIProvider, never to a specific model.
Prompts live in ai/prompts/ so they can change without touching the code.
"""
import json
from abc import ABC, abstractmethod
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


class AIProvider(ABC):
    """Contract that every AI provider must follow."""

    @abstractmethod
    def chat(self, system: str, user: str) -> str:
        """Send one request to the model and return its text answer."""

    # --- Shared logic, written once for every provider ---

    def _ask_json(self, prompt_name: str, data: dict) -> dict:
        """Load a prompt file, send the data, and return the answer as a dict."""
        system = (PROMPTS_DIR / f"{prompt_name}.md").read_text(encoding="utf-8")
        answer = self.chat(system, json.dumps(data, ensure_ascii=False))
        return json.loads(_strip_code_fences(answer))

    def analyze_creator(self, data: dict) -> dict:
        return self._ask_json("analyze_creator", data)

    def analyze_buyer(self, data: dict) -> dict:
        return self._ask_json("analyze_buyer", data)

    def generate_outreach(self, data: dict) -> dict:
        return self._ask_json("generate_outreach", data)


def _strip_code_fences(text: str) -> str:
    """Models sometimes wrap JSON in ```json ... ```: remove that wrapper."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()
