from pathlib import Path
import logging

from pypdf import PdfReader
from docx import Document


log = logging.getLogger(__name__)


def extract_text(file_path: Path, max_chars: int = 30000) -> str:
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        text = _extract_pdf(file_path)
    elif ext in (".docx", ".doc"):
        text = _extract_docx(file_path)
    else:
        log.warning("Unsupported extension: %s", ext)
        return ""

    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[...TRONQUÉ...]"
    return text


def _extract_pdf(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception as e:
        log.warning("PDF extract failed for %s: %s", path.name, e)
        return ""


def _extract_docx(path: Path) -> str:
    try:
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        log.warning("DOCX extract failed for %s: %s", path.name, e)
        return ""
