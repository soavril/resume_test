"""Tests for LLMClient (Claude API wrapper)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from resume_tailor.clients.llm_client import LLMClient, LLMResponse


def _make_api_message(text: str, input_tokens: int = 100, output_tokens: int = 50) -> MagicMock:
    """Build a mock anthropic Message-like object."""
    message = MagicMock()
    message.usage.input_tokens = input_tokens
    message.usage.output_tokens = output_tokens
    message.content = [MagicMock(text=text)]
    return message


class TestLLMClientInit:
    def test_init_default_creates_client_with_no_kwargs(self):
        """Creates AsyncAnthropic with no extra kwargs when no args supplied."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic") as mock_cls:
            LLMClient()
            mock_cls.assert_called_once_with()

    def test_init_with_api_key_passes_key(self):
        """Passes api_key kwarg when provided."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic") as mock_cls:
            LLMClient(api_key="test-key")
            mock_cls.assert_called_once_with(api_key="test-key")

    def test_init_with_timeout_passes_timeout(self):
        """Passes timeout kwarg when provided."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic") as mock_cls:
            LLMClient(timeout=30.0)
            mock_cls.assert_called_once_with(timeout=30.0)

    def test_init_with_both_params_passes_both(self):
        """Passes both api_key and timeout when both are supplied."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic") as mock_cls:
            LLMClient(api_key="test-key", timeout=30.0)
            mock_cls.assert_called_once_with(api_key="test-key", timeout=30.0)


class TestLLMClientGenerate:
    async def test_generate_returns_llm_response(self):
        """generate() wraps API response fields into an LLMResponse dataclass."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                return_value=_make_api_message("hello world", input_tokens=100, output_tokens=50)
            )
            mock_cls.return_value = mock_client

            llm = LLMClient()
            result = await llm.generate("say hello")

        assert isinstance(result, LLMResponse)
        assert result.text == "hello world"
        assert result.input_tokens == 100
        assert result.output_tokens == 50

    async def test_token_log_accumulates_across_calls(self):
        """Each generate() call appends one entry to _token_log."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                return_value=_make_api_message("response", input_tokens=10, output_tokens=5)
            )
            mock_cls.return_value = mock_client

            llm = LLMClient()
            await llm.generate("prompt one")
            await llm.generate("prompt two")

        assert len(llm._token_log) == 2

    async def test_token_log_stores_model_and_counts(self):
        """_token_log entries are (model, input_tokens, output_tokens) tuples."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                return_value=_make_api_message("resp", input_tokens=20, output_tokens=8)
            )
            mock_cls.return_value = mock_client

            llm = LLMClient()
            await llm.generate("prompt", model="claude-haiku-4-5-20251001")

        model, inp, out = llm._token_log[0]
        assert model == "claude-haiku-4-5-20251001"
        assert inp == 20
        assert out == 8


class TestLLMClientGenerateJson:
    async def test_generate_json_parses_valid_json_text(self):
        """generate_json() returns a dict when the response text contains valid JSON."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                return_value=_make_api_message('{"key": "value", "count": 3}')
            )
            mock_cls.return_value = mock_client

            llm = LLMClient()
            result = await llm.generate_json("give me json")

        assert result == {"key": "value", "count": 3}

    async def test_generate_json_raises_on_non_json_response(self):
        """generate_json() raises ValueError when the response cannot be parsed as JSON."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                return_value=_make_api_message("this is plain text, not json")
            )
            mock_cls.return_value = mock_client

            llm = LLMClient()
            with pytest.raises(ValueError):
                await llm.generate_json("give me json")


class TestLLMClientTokenSummary:
    def test_get_token_summary_returns_correct_totals(self):
        """get_token_summary() sums input and output tokens across all log entries."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic"):
            llm = LLMClient()
            llm._token_log = [
                ("claude-haiku-4-5-20251001", 100, 50),
                ("claude-haiku-4-5-20251001", 200, 80),
            ]

        summary = llm.get_token_summary()

        assert summary["input"] == 300
        assert summary["output"] == 130
        assert len(summary["calls"]) == 2

    def test_get_token_summary_clears_log_after_return(self):
        """get_token_summary() empties _token_log so subsequent calls return zeros."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic"):
            llm = LLMClient()
            llm._token_log = [("claude-haiku-4-5-20251001", 50, 25)]

        llm.get_token_summary()
        second_summary = llm.get_token_summary()

        assert second_summary["input"] == 0
        assert second_summary["output"] == 0
        assert second_summary["calls"] == []


class TestLLMClientExtractTextFromImage:
    async def test_extract_text_from_image_returns_text_content(self):
        """extract_text_from_image() returns the text from the API response content."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                return_value=_make_api_message("extracted text from image")
            )
            mock_cls.return_value = mock_client

            llm = LLMClient()
            result = await llm.extract_text_from_image(
                image_bytes=b"fake-image-bytes",
                image_media_type="image/png",
            )

        assert result == "extracted text from image"

    async def test_extract_text_from_image_logs_tokens(self):
        """extract_text_from_image() appends a token log entry after a successful call."""
        with patch("resume_tailor.clients.llm_client.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(
                return_value=_make_api_message("text", input_tokens=200, output_tokens=40)
            )
            mock_cls.return_value = mock_client

            llm = LLMClient()
            await llm.extract_text_from_image(b"bytes", "image/jpeg")

        assert len(llm._token_log) == 1
        _, inp, out = llm._token_log[0]
        assert inp == 200
        assert out == 40
