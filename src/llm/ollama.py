"""Local Ollama provider (no cloud data transfer)."""

from __future__ import annotations

from typing import Any

from src.llm.base import LLMError, LLMProvider


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, *, host: str, model: str, **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)
        self.host = (host or "http://127.0.0.1:11434").rstrip("/")

    def generate(self, prompt: str, json_mode: bool = False) -> str:
        prompt = self._validate_prompt(prompt)
        body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if json_mode:
            body["format"] = "json"

        data = self._post(
            f"{self.host}/api/generate",
            headers={"Content-Type": "application/json"},
            json_body=body,
        )
        text = data.get("response")
        if not isinstance(text, str) or not text.strip():
            raise LLMError("Ollama returned no text")
        return text
