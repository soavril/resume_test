from pathlib import Path


def parse_resume(file_path: str | Path) -> str:
    """Parse a resume file (PDF or DOCX) and return plain text."""
    path = Path(file_path)
    if path.suffix.lower() == ".pdf":
        return _parse_pdf(path)
    elif path.suffix.lower() in (".docx", ".doc"):
        return _parse_docx(path)
    elif path.suffix.lower() in (".txt", ".md"):
        return path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"Unsupported file format: {path.suffix}")


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
