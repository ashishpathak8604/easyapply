"""Google Gemini provider (free tier)."""

from __future__ import annotations

from typing import Any

from src.llm.base import LLMError, LLMProvider


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, *, api_key: str, model: str, **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)
        if not api_key:
            raise LLMError("Gemini API key is missing")
        self.api_key = api_key

    def generate(self, prompt: str, json_mode: bool = False) -> str:
        prompt = self._validate_prompt(prompt)
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        generation: dict[str, Any] = {}
        if json_mode:
            generation["responseMimeType"] = "application/json"

        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation,
        }
        data = self._post(
            url,
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json_body=body,
        )

        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise LLMError("Gemini returned no candidates (possibly blocked)")
        texts: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    texts.append(part["text"])
        if not texts:
            raise LLMError("Gemini returned no text")
        return "".join(texts)
