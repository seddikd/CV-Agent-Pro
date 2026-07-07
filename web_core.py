"""Socle partagé pour les routeurs de modules ATS.

Chaque module avancé (offres, recherche, comparaison…) vit dans son propre
fichier `mod_<nom>.py` exposant un `APIRouter`. Pour éviter tout import circulaire
avec `webapp.py`, ces routeurs importent d'ici (jamais `webapp`) :
  - `render()`    : rend un template en injectant l'utilisateur courant ;
  - `templates`   : instance Jinja partagée (mêmes dossier/réglages que webapp) ;
  - `llm_cfg()`   : config LLM prête pour `llm_provider.chat_json` ;
  - `connect()`   : connexion PostgreSQL (ré-export de state_db/db) ;
  - ré-exports d'auth (`require_user`, `require_admin`, `current_user`).

`webapp.py` se contente d'inclure chaque routeur (`app.include_router(...)`).
"""

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request

import app_paths
import web_auth
import web_db

# Ré-exports pratiques (les modules importent depuis web_core uniquement).
from web_auth import require_user, require_admin, current_user  # noqa: F401
from state_db import connect  # noqa: F401


HERE = app_paths.RESOURCE_DIR

templates = Jinja2Templates(directory=HERE / "templates")


def render(request: Request, template: str, ctx: dict | None = None) -> HTMLResponse:
    """Rend un template en injectant `user` + drapeaux de permission (comme webapp.render)."""
    user = web_auth.current_user(request)
    base = {
        "user": user,
        "can_write": web_auth.can_write(user),
        "can_run_cycle": web_auth.can_run_cycle(user),
    }
    if ctx:
        base.update(ctx)
    return templates.TemplateResponse(request, template, base)


def llm_cfg() -> dict:
    """Config LLM courante, prête pour `llm_provider.chat_json(llm_cfg(), ...)`."""
    settings = web_db.get_all_settings()
    return web_db.settings_to_config(settings)["llm"]
