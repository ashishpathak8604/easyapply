"""Resume PDF text extraction with pdfplumber and a PyMuPDF fallback."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class ResumeExtractionError(RuntimeError):
    """The resume PDF is missing, unreadable, or contains no usable text."""


@dataclass(slots=True)
class ExtractionResult:
    text: str
    method: str
    page_count: int | None = None
    warnings: list[str] = field(default_factory=list)


def _extract_with_pdfplumber(path: Path) -> tuple[str, int]:
    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
        page_count = len(pdf.pages)
    return "\n".join(pages), page_count


def _extract_with_pymupdf(path: Path) -> tuple[str, int]:
    try:
        import pymupdf
    except ImportError:  # older PyMuPDF releases expose the fitz name
        import fitz as pymupdf  # type: ignore[no-redef]

    pages: list[str] = []
    with pymupdf.open(path) as document:
        page_count = document.page_count
        for page in document:
            pages.append(page.get_text("text") or "")
    return "\n".join(pages), page_count


def extract_resume_text(path: str | Path) -> ExtractionResult:
    """Extract text from a resume PDF.

    pdfplumber is tried first; PyMuPDF is used if pdfplumber fails or returns no
    usable text. Raises :class:`ResumeExtractionError` when neither works.
    """

    resume_path = Path(path).expanduser()
    if not resume_path.exists():
        raise ResumeExtractionError(
            f"resume PDF not found: {resume_path}. Place your resume there or "
            "pass --resume <path>."
        )
    if not resume_path.is_file():
        raise ResumeExtractionError(f"resume path is not a file: {resume_path}")

    warnings: list[str] = []
    errors: list[str] = []

    try:
        text, pages = _extract_with_pdfplumber(resume_path)
        if text.strip():
            return ExtractionResult(
                text=text, method="pdfplumber", page_count=pages, warnings=warnings
            )
        warnings.append("pdfplumber returned no text; trying PyMuPDF")
    except Exception as exc:  # noqa: BLE001 - third-party parsers raise various errors
        errors.append(f"pdfplumber: {type(exc).__name__}")
        warnings.append("pdfplumber failed; trying PyMuPDF")

    try:
        text, pages = _extract_with_pymupdf(resume_path)
        if text.strip():
            return ExtractionResult(
                text=text, method="pymupdf", page_count=pages, warnings=warnings
            )
        errors.append("pymupdf: no text")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pymupdf: {type(exc).__name__}")

    detail = ", ".join(errors) if errors else "no extractable text"
    raise ResumeExtractionError(
        f"could not read usable text from {resume_path.name} ({detail}). "
        "If it is a scanned image PDF, export a text-based PDF or add a "
        "plain-text copy."
    )
