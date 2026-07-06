"""Utilitaires runtime partagés : encodage console UTF-8 + configuration logging.

Factorise du code jusque-là dupliqué dans main.py, webapp.py et bootstrap.py.
(desktop.py garde sa propre logique : en exe fenêtré, stdout/stderr valent None
et sont redirigés vers un fichier — cas non couvert ici.)
"""

import logging
import sys
from pathlib import Path


def force_utf8_streams() -> None:
    """Force stdout/stderr en UTF-8 (la console Windows est souvent en cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def configure_logging(log_file: str) -> None:
    """Configure le logging fichier + console (idempotent)."""
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
