"""Utility to extract JSON from LLM responses."""

from __future__ import annotations

import json
import re


def extract_json(text: str) -> dict | list:
    """Extract JSON from LLM response, handling ```json blocks.

    Tries in order:
    1. Direct json.loads on the full text
    2. Strip fenced code block markers and parse
    3. Find first '{' to last '}' and parse
    4. Find first '[' to last ']' and parse (JSON array)
    5. Try to repair truncated JSON (missing closing braces)
    """
    text = text.strip()

    # 1) Direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # 2) Strip fenced code block markers
    stripped = _strip_code_fences(text)
    if stripped != text:
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
        # Also try { to } extraction on stripped text
        result = _extract_braces(stripped)
        if result is not None:
            return result

    # 3) First '{' to last '}' on original
    result = _extract_braces(text)
    if result is not None:
        return result

    # 4) First '[' to last ']' (JSON array)
    result = _extract_brackets(text)
    if result is not None:
        return result

    # 5) Try to repair truncated JSON (add missing closing braces)
    result = _try_repair_truncated(stripped if stripped != text else text)
    if result is not None:
        return result

    raise ValueError(f"Could not extract JSON from text: {text[:200]}...")


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fence markers from text."""
    lines = text.split("\n")

    # Remove opening fence (```json, ```, etc.)
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]

    # Remove closing fence
    while lines and lines[-1].strip() in ("```", ""):
        lines = lines[:-1]

    return "\n".join(lines).strip()


def _extract_braces(text: str) -> dict | None:
    """Try to extract JSON object from first '{' to last '}'."""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _extract_brackets(text: str) -> list | None:
    """Try to extract JSON array from first '[' to last ']'."""
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _try_repair_truncated(text: str) -> dict | None:
    """Try to repair truncated JSON by closing open braces/brackets."""
    start = text.find("{")
    if start == -1:
        return None

    candidate = text[start:]
    # Count open/close braces
    open_braces = candidate.count("{") - candidate.count("}")
    open_brackets = candidate.count("[") - candidate.count("]")

    if open_braces <= 0 and open_brackets <= 0:
        return None

    # Try progressively truncating from the end and closing
    # Find the last complete value (ends with ", or ], or }, or true/false/null/number)
    # Then close all open structures
    repaired = candidate.rstrip()
    # Remove trailing comma if present
    if repaired.endswith(","):
        repaired = repaired[:-1]

    # Close open brackets then braces
    repaired += "]" * open_brackets + "}" * open_braces

    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # More aggressive: find last complete string value and truncate there
    last_quote = candidate.rfind('"')
    if last_quote > 0:
        # Find the matching start quote
        truncated = candidate[: last_quote + 1]
        # Recount
        ob = truncated.count("{") - truncated.count("}")
        ol = truncated.count("[") - truncated.count("]")
        if ob > 0 or ol > 0:
            repaired = truncated.rstrip().rstrip(",")
            repaired += "]" * max(0, ol) + "}" * max(0, ob)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

    return None
