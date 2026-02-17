"""Claude API wrapper with async support and retry logic."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from resume_tailor.utils.json_parser import extract_json

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from the LLM including usage metadata."""

    text: str
    input_tokens: int
    output_tokens: int


class LLMClient:
    """Async Claude API client with exponential-backoff retries."""

    def __init__(self, api_key: str | None = None, timeout: float | None = None):
        kwargs: dict = {}
        if api_key is not None:
            kwargs["api_key"] = api_key
        if timeout is not None:
            kwargs["timeout"] = timeout
        self.client = anthropic.AsyncAnthropic(**kwargs)
        self._token_log: list[tuple[str, int, int]] = []  # (model, input_tokens, output_tokens)

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
        logger.debug("LLM call: model=%s", model)
        try:
            message = await self._call_api(
                prompt=prompt,
                system=system,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception:
            logger.error("LLM call failed", exc_info=True)
            raise
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        logger.debug("LLM response: %d input, %d output tokens", input_tokens, output_tokens)
        self._token_log.append((model, input_tokens, output_tokens))
        return LLMResponse(
            text=message.content[0].text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        reraise=True,
    )
    async def extract_text_from_image(
        self,
        image_bytes: bytes,
        image_media_type: str,
        model: str = "claude-haiku-4-5-20251001",
    ) -> str:
        """Extract text from an image using Claude Vision.

        Args:
            image_bytes: Raw image bytes (PNG, JPEG, etc.)
            image_media_type: MIME type (e.g. "image/png", "image/jpeg")
            model: Claude model to use (Haiku for cost efficiency)

        Returns:
            Extracted text preserving structure and formatting.
        """
        b64_data = base64.b64encode(image_bytes).decode("utf-8")

        message = await self.client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image_media_type,
                            "data": b64_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "이 채용공고 이미지의 모든 텍스트를 정확히 추출하세요. "
                            "원본의 구조와 포맷(제목, 목록, 표 등)을 최대한 유지하세요. "
                            "추출된 텍스트만 출력하고, 설명이나 코멘트는 추가하지 마세요."
                        ),
                    },
                ],
            }],
        )
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        self._token_log.append((model, input_tokens, output_tokens))
        return message.content[0].text

    def get_token_summary(self) -> dict:
        """Return accumulated token usage and reset the log."""
        summary = {
            "input": sum(t[1] for t in self._token_log),
            "output": sum(t[2] for t in self._token_log),
            "calls": list(self._token_log),
        }
        self._token_log.clear()
        return summary
