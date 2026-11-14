"""
Thin wrapper around a local Ollama model. Deterministic by default
(temperature=0, fixed seed) so pipeline runs and evaluations are
reproducible. Model name is config, never hard-coded into callers.
"""

import os

import ollama

DEFAULT_MODEL = os.environ.get("NOVATEL_LLM_MODEL", "qwen2.5:7b-instruct")
DEFAULT_SEED = 42


class OllamaClient:
    """Wraps ollama.chat() with deterministic defaults."""

    def __init__(self, model: str = DEFAULT_MODEL, temperature: float = 0.0, seed: int = DEFAULT_SEED):
        self.model = model
        self.temperature = temperature
        self.seed = seed

    def chat(self, system: str, user: str) -> str:
        """Single-turn chat completion. Returns the assistant's text content."""
        response = ollama.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            options={
                "temperature": self.temperature,
                "seed": self.seed,
            },
        )
        return response["message"]["content"]

    def ping(self) -> str:
        """One-line smoke test used after model install/pull."""
        return self.chat(
            system="Reply with exactly one short sentence.",
            user="Say hello and name yourself.",
        )
