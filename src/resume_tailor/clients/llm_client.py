"""Claude API wrapper with async support and retry logic."""

from __future__ import annotations

from dataclasses import dataclass

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from resume_tailor.utils.json_parser import extract_json


@dataclass
class LLMResponse:
    """Response from the LLM including usage metadata."""

    text: str
    input_tokens: int
    output_tokens: int


class LLMClient:
    """Async Claude API client with exponential-backoff retries."""

    def __init__(self, api_key: str | None = None):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        reraise=True,
    )
    async def _call_api(
        self,
        prompt: str,
        system: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> anthropic.types.Message:
        """Make the actual API call with retry logic."""
        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        return await self.client.messages.create(**kwargs)

    async def generate(
        self,
        prompt: str,
        system: str = "",
        model: str = "claude-haiku-4-5-20251001",
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> LLMResponse:
        """Send a prompt to Claude and return the text response with usage."""
        message = await self._call_api(
            prompt=prompt,
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return LLMResponse(
            text=message.content[0].text,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )

    async def generate_json(
        self,
        prompt: str,
        system: str = "",
        model: str = "claude-haiku-4-5-20251001",
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> dict:
        """Send a prompt and parse JSON from response."""
        response = await self.generate(
            prompt=prompt,
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return extract_json(response.text)
