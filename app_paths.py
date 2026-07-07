"""Résolution centralisée des chemins — compatible exécution normale ET .exe figé.

Deux notions distinctes :
  - RESOURCE_DIR : ressources embarquées en LECTURE SEULE (templates, static,
    config.yaml). En mode figé (PyInstaller), c'est le dossier temporaire _MEIPASS.
  - DATA_DIR : fichiers en ÉCRITURE (logs, cv_pdfs, session.secret). Les données
    métier vivent en PostgreSQL, pas sur disque. En mode figé, DATA_DIR vaut
    %LOCALAPPDATA%\\CV-Agent-Pro (le dossier d'install est en lecture seule).

La variable d'environnement CV_AGENT_DATA_DIR force le DATA_DIR quel que soit le
mode : indispensable en conteneur Docker pour pointer vers un volume monté
(ex. CV_AGENT_DATA_DIR=/data). En développement (non figé) et sans cette variable,
les deux pointent vers le dossier du projet — comportement inchangé.
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
    _default_data = Path(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")) / APP_NAME
else:
    RESOURCE_DIR = Path(__file__).resolve().parent
    _default_data = Path(__file__).resolve().parent  # dev : dossier projet, inchangé

# CV_AGENT_DATA_DIR (ex. /data en conteneur) prime sur le défaut de chaque mode.
_env_data = os.environ.get("CV_AGENT_DATA_DIR")
DATA_DIR = Path(_env_data) if _env_data else _default_data

DATA_DIR.mkdir(parents=True, exist_ok=True)


def resource(*parts: str) -> Path:
    """Chemin d'une ressource embarquée (lecture seule)."""
    return RESOURCE_DIR.joinpath(*parts)


def data_path(rel) -> Path:
    """Résout un chemin de données : relatif -> sous DATA_DIR, absolu -> tel quel."""
    p = Path(rel)
    return p if p.is_absolute() else (DATA_DIR / p)
