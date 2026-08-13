"""Parse uploaded files (PDF / TXT / Markdown) into raw text."""
import io

from pypdf import PdfReader

from app.observability import logger

SUPPORTED = {
    "application/pdf": "pdf",
    "text/plain": "text",
    "text/markdown": "markdown",
}


def parse_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def parse_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def parse_markdown(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def parse_file(filename: str, content_type: str, data: bytes) -> tuple[str, str]:
    """Return (kind, text). Falls back to extension detection.

    Raises ValueError when the file type is not supported.
    """
    ctype = content_type or ""
    if ctype not in SUPPORTED:
        lower = filename.lower()
        if lower.endswith(".pdf"):
            ctype = "application/pdf"
        elif lower.endswith(".md") or lower.endswith(".markdown"):
            ctype = "text/markdown"
        elif lower.endswith(".txt"):
            ctype = "text/plain"

    if ctype not in SUPPORTED:
        raise ValueError(f"Unsupported file type: {content_type or filename}")

    kind = SUPPORTED[ctype]
    text = {
        "pdf": parse_pdf,
        "text": parse_text,
        "markdown": parse_markdown,
    }[kind](data)

    logger.info("document_parsed", filename=filename, kind=kind, chars=len(text))
    return kind, text
