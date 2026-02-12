"""Tests for JSON extraction utility."""

import pytest

from resume_tailor.utils.json_parser import extract_json


class TestExtractJson:
    def test_direct_json(self):
        result = extract_json('{"name": "test"}')
        assert result == {"name": "test"}

    def test_fenced_code_block(self):
        text = 'Here is the result:\n```json\n{"name": "test"}\n```\nDone.'
        result = extract_json(text)
        assert result == {"name": "test"}

    def test_fenced_without_json_tag(self):
        text = '```\n{"key": "value"}\n```'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_embedded_json(self):
        text = 'The analysis is: {"score": 90, "pass": true} as shown above.'
        result = extract_json(text)
        assert result == {"score": 90, "pass": True}

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = extract_json(text)
        assert result["outer"]["inner"] == [1, 2, 3]

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Could not extract JSON"):
            extract_json("no json here at all")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            extract_json("")

    def test_multiline_fenced(self):
        text = """Here's the output:
```json
{
  "name": "홍길동",
  "skills": ["Python", "Java"]
}
```"""
        result = extract_json(text)
        assert result["name"] == "홍길동"
        assert len(result["skills"]) == 2
