"""Groq provider (free tier, OpenAI-compatible endpoint)."""

from __future__ import annotations

from typing import Any

from src.llm.base import LLMError, LLMProvider

API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, *, api_key: str, model: str, **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)
        if not api_key:
            raise LLMError("Groq API key is missing")
        self.api_key = api_key

    def generate(self, prompt: str, json_mode: bool = False) -> str:
        prompt = self._validate_prompt(prompt)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        data = self._post(
            API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json_body=body,
        )

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMError("Groq returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LLMError("Groq returned no text")
        return content
