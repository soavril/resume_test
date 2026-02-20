import re
from pathlib import Path

# Shared emoji pattern for Google Docs / LLM output cleanup
EMOJI_PATTERN = (
    r"[\U0001f4e7\U0001f4de\U0001f4cd\U0001f4bc\U0001f4c5\U0001f393"
    r"\U0001f3e2\U0001f4dd\U0001f4c4\U0001f517\U0001f310\U0001f4f1"
    r"\u260e\u2709\u2706\u2702]\s*"
)


def parse_resume(file_path: str | Path) -> str:
    """Parse a resume file (PDF, DOCX, TXT, MD) and return clean plain text."""
    path = Path(file_path)
    if path.suffix.lower() == ".pdf":
        return _parse_pdf(path)
    elif path.suffix.lower() in (".docx", ".doc"):
        return _parse_docx(path)
    elif path.suffix.lower() in (".txt", ".md"):
        raw = path.read_text(encoding="utf-8")
        return clean_markdown(raw)
    else:
        raise ValueError(f"Unsupported file format: {path.suffix}")


def clean_markdown(text: str) -> str:
    """Clean Google Docs markdown export artifacts.

    Handles: unicode artifacts, emoji icons, excessive whitespace,
    inconsistent bullet styles, and trailing whitespace.
    """
    # 1. Remove unicode artifacts (BOM, zero-width spaces, soft hyphens)
    text = text.lstrip("\ufeff")
    text = re.sub(r"[\u200b\u200c\u200d\u00ad\u2060\ufeff]", "", text)

    # 2. Remove emoji icons commonly used in Google Docs resumes
    text = re.sub(EMOJI_PATTERN, "", text)

    # 3. Normalize bullet points (●, •, ◦, ◆, ■, ▪, ★, ○ → -)
    text = re.sub(r"^(\s*)[●•◦◆■▪★○]\s*", r"\1- ", text, flags=re.MULTILINE)
    # Normalize asterisk-heavy bullets (* followed by excessive spaces)
    text = re.sub(r"^(\s*)\*\s{2,}", r"\1- ", text, flags=re.MULTILINE)

    # 4. Collapse multiple spaces/tabs to single space (preserve leading indent)
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        # Normalize indent to consistent spaces
        indent = " " * (len(indent.replace("\t", "    ")))
        stripped = re.sub(r"[ \t]{2,}", " ", stripped).rstrip()
        cleaned_lines.append(f"{indent}{stripped}" if stripped else "")
    text = "\n".join(cleaned_lines)

    # 5. Remove excessive blank lines (3+ → 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _parse_pdf(path: Path) -> str:
    import fitz  # pymupdf

    doc = fitz.open(str(path))
    text = []
    for page in doc:
        text.append(page.get_text())
    doc.close()
    return "\n".join(text)


def _parse_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
