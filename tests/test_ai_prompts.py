"""Every prompt the provider can ask for must exist and be reachable.

The defect these tests guard against is a method that names a prompt file which
was never written: the failure only appears the first time the method is called.
"""
from ai.provider import PROMPTS_DIR, AIProvider

PROMPTS = (
    "analyze_creator",
    "analyze_buyer",
    "extract_creator",
    "extract_buyer",
    "generate_outreach",
)


class EmptyAnswer(AIProvider):
    def chat(self, system: str, user: str) -> str:
        return "{}"


class ClaimsAnswer(AIProvider):
    def chat(self, system: str, user: str) -> str:
        return '{"claims": {}}'


def test_every_prompt_file_exists_and_is_not_empty():
    missing = [
        name for name in PROMPTS if not (PROMPTS_DIR / f"{name}.md").exists()
    ]
    empty = [
        name
        for name in PROMPTS
        if (PROMPTS_DIR / f"{name}.md").exists()
        and not (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
    ]

    assert missing == []
    assert empty == []


def test_every_provider_method_can_read_its_prompt():
    assert EmptyAnswer().analyze_creator({}) == {}
    assert EmptyAnswer().analyze_buyer({}) == {}
    assert EmptyAnswer().generate_outreach({}) == {}
    assert ClaimsAnswer().extract_creator({}).claims.followers is None
    assert ClaimsAnswer().extract_buyer({}).claims.creators_paid is None
