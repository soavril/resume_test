"""Extract job description text from images and PDF files.

Uses Claude Vision API for OCR. PDF pages are converted to images
via PyMuPDF (fitz) before sending to the API.
"""

from __future__ import annotations

import logging

from resume_tailor.clients.llm_client import LLMClient

logger = logging.getLogger(__name__)

# Media type mapping
_EXT_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

PDF_DPI = 150


def pdf_to_images(pdf_bytes: bytes) -> list[tuple[bytes, str]]:
    """Convert PDF pages to PNG images using PyMuPDF.

    Args:
        pdf_bytes: Raw PDF file bytes.

    Returns:
        List of (image_bytes, media_type) tuples, one per page.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    try:
        for page in doc:
            mat = fitz.Matrix(PDF_DPI / 72, PDF_DPI / 72)
            pix = page.get_pixmap(matrix=mat)
            images.append((pix.tobytes("png"), "image/png"))
    finally:
        doc.close()
    return images


def _get_media_type(filename: str) -> str | None:
    """Get media type from filename extension."""
    lower = filename.lower()
    for ext, mt in _EXT_MEDIA_TYPES.items():
        if lower.endswith(ext):
            return mt
    return None


async def extract_jd_from_file(
    llm: LLMClient,
    file_bytes: bytes,
    filename: str,
) -> str:
    """Extract job description text from an image or PDF file.

    Args:
        llm: LLMClient instance with Vision support.
        file_bytes: Raw file bytes.
        filename: Original filename (used to detect file type).

    Returns:
        Extracted text from the job description.
    """
    lower = filename.lower()

    if lower.endswith(".pdf"):
        images = pdf_to_images(file_bytes)
        if not images:
            raise ValueError("PDF에 페이지가 없습니다.")

        parts = []
        for i, (img_bytes, media_type) in enumerate(images):
            logger.info("Extracting text from PDF page %d/%d", i + 1, len(images))
            text = await llm.extract_text_from_image(img_bytes, media_type)
            parts.append(text)

        return "\n\n".join(parts)

    media_type = _get_media_type(filename)
    if not media_type:
        raise ValueError(
            f"지원하지 않는 파일 형식입니다: {filename}. "
            f"PNG, JPG, JPEG, GIF, WEBP, PDF만 지원합니다."
        )

    return await llm.extract_text_from_image(file_bytes, media_type)
