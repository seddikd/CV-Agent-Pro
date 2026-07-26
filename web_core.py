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

# Anti-cache des assets : on suffixe l'URL de style.css par la date de
# modification du fichier (?v=...). Le navigateur re-télécharge donc la feuille
# de style dès qu'elle change, sans jamais servir une version obsolète en cache.
import os

try:
    _css_mtime = int(os.path.getmtime(HERE / "static" / "style.css"))
except OSError:
    _css_mtime = 1
templates.env.globals["asset_v"] = str(_css_mtime)


# ─── Vue (coquille) de l'interface ────────────────────────────────────────────
# Deux interfaces cohabitent, choisies par utilisateur (en fait par navigateur)
# via le cookie `cvagent-vue` que pose /preferences/vue :
#   « onglets » → templates/_coquille_onglets.html  (bandeau + onglets, v2.0)
#   « lateral » → templates/_coquille_laterale.html (barre latérale, v1)
# Toutes les autres pages sont communes aux deux vues.
#
# VUE_DEFAUT s'applique au premier passage, avant tout choix explicite. C'est le
# SEUL réglage qui distingue les deux déploiements : ICI (prod) on reste sur
# « lateral », l'apparence historique, et les onglets sont la vue secondaire ;
# l'instance de développement fait l'inverse. Volontairement une constante et non
# un réglage en base : évite une lecture de `settings` à chaque rendu de page.
VUES = ("onglets", "lateral")
VUE_DEFAUT = "lateral"
COOKIE_VUE = "cvagent-vue"


def vue_courante(request: Request) -> str:
    """Vue demandée par le cookie, en refusant toute valeur inconnue."""
    vue = request.cookies.get(COOKIE_VUE)
    return vue if vue in VUES else VUE_DEFAUT


def render(request: Request, template: str, ctx: dict | None = None) -> HTMLResponse:
    """Rend un template en injectant `user` + drapeaux de permission + la vue."""
    user = web_auth.current_user(request)
    base = {
        "user": user,
        "can_write": web_auth.can_write(user),
        "can_run_cycle": web_auth.can_run_cycle(user),
        "vue": vue_courante(request),
    }
    if ctx:
        base.update(ctx)
    return templates.TemplateResponse(request, template, base)


def llm_cfg() -> dict:
    """Config LLM courante, prête pour `llm_provider.chat_json(llm_cfg(), ...)`."""
    settings = web_db.get_all_settings()
    return web_db.settings_to_config(settings)["llm"]
