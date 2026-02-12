import re
from pathlib import Path


def parse_jd(text: str) -> str:
    """Clean and normalize job description text."""
    # Remove excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    # Strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.splitlines()]
    return '\n'.join(lines).strip()


def load_jd_file(file_path: str) -> str:
    """Load JD from a text file."""
    return parse_jd(Path(file_path).read_text(encoding="utf-8"))
