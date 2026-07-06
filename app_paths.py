"""Résolution centralisée des chemins — compatible exécution normale ET .exe figé.

Deux notions distinctes :
  - RESOURCE_DIR : ressources embarquées en LECTURE SEULE (templates, static,
    config.yaml). En mode figé (PyInstaller), c'est le dossier temporaire _MEIPASS.
  - DATA_DIR : données en ÉCRITURE (state.db, logs, cv_pdfs, output). En mode figé,
    c'est %LOCALAPPDATA%\\CV-Agent (le dossier d'install est en lecture seule).

En développement (non figé), les deux pointent vers le dossier du projet, donc
le comportement actuel est strictement inchangé.
"""

import os
import sys
from pathlib import Path

APP_NAME = "CV-Agent-Pro"


def is_frozen() -> bool:
    """True quand on tourne depuis un exécutable PyInstaller."""
    return bool(getattr(sys, "frozen", False))


if is_frozen():
    # Ressources dépaquetées par PyInstaller (onefile) ou à côté de l'exe (onedir).
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    _base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    DATA_DIR = Path(_base) / APP_NAME
else:
    RESOURCE_DIR = Path(__file__).resolve().parent
    DATA_DIR = Path(__file__).resolve().parent  # dev : dossier projet, inchangé

DATA_DIR.mkdir(parents=True, exist_ok=True)


def resource(*parts: str) -> Path:
    """Chemin d'une ressource embarquée (lecture seule)."""
    return RESOURCE_DIR.joinpath(*parts)


def data_path(rel) -> Path:
    """Résout un chemin de données : relatif -> sous DATA_DIR, absolu -> tel quel."""
    p = Path(rel)
    return p if p.is_absolute() else (DATA_DIR / p)


def db_path() -> Path:
    """Chemin de la base SQLite (toujours en zone d'écriture)."""
    return DATA_DIR / "state.db"
