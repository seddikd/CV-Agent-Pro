"""Aides d'authentification : bcrypt + session."""

import bcrypt
from fastapi import HTTPException, Request, status

import web_db


def _pw_bytes(plain: str) -> bytes:
    # bcrypt 5.x lève ValueError si > 72 octets ; on tronque (comportement bcrypt
    # historique) pour ne jamais planter sur une longue passphrase.
    return plain.encode("utf-8")[:72]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_pw_bytes(plain), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_pw_bytes(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def current_user(request: Request) -> dict | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    user = web_db.get_user_by_id(int(uid))
    # Un compte désactivé n'est plus « connecté » : évite la boucle /login <-> /.
    if not user or not user["active"]:
        return None
    return user


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user or not user["active"]:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin requis")
    return user


# ─── Permissions par rôle ─────────────────────────────────────────────────────
# Rôles autorisés à ÉCRIRE (créer/modifier/supprimer des données métier).
# « lecture » en est exclu : consultation seule.
WRITE_ROLES = frozenset({"admin", "manager", "rh"})
# Rôles autorisés à déclencher/arrêter un cycle de traitement.
CYCLE_ROLES = frozenset({"admin", "manager"})


def can_write(user: dict | None) -> bool:
    """True si l'utilisateur peut modifier des données (pas « lecture »)."""
    return bool(user) and user.get("role") in WRITE_ROLES


def can_run_cycle(user: dict | None) -> bool:
    """True si l'utilisateur peut lancer/arrêter un cycle (admin ou manager)."""
    return bool(user) and user.get("role") in CYCLE_ROLES


def require_write(request: Request) -> dict:
    """Exige un rôle en écriture ; bloque « lecture » (403)."""
    user = require_user(request)
    if user["role"] not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Action non autorisée (lecture seule)")
    return user


def require_cycle(request: Request) -> dict:
    """Exige le droit de lancer un cycle (admin ou manager)."""
    user = require_user(request)
    if user["role"] not in CYCLE_ROLES:
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs et managers")
    return user
