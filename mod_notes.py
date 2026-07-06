"""Module « Notes internes » : fil de notes/observations RH par candidat. Routeur isolé."""
from datetime import datetime

from fastapi import APIRouter, Request, Form

from web_core import require_user, render, DB_PATH, connect
import db

router = APIRouter()


def _list_notes(cid: int) -> list[dict]:
    """Renvoie les notes d'un candidat, les plus récentes d'abord."""
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT id, candidate_id, author_id, author_name, body, created_at
            FROM candidate_notes
            WHERE candidate_id = ?
            ORDER BY id DESC
            """,
            (cid,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/candidate/{cid}/notes")
def get_notes(request: Request, cid: int):
    """Fragment « Notes internes » : liste des notes + formulaire d'ajout."""
    user = require_user(request, DB_PATH)
    notes = _list_notes(cid)
    return render(request, "_notes.html", {"cid": cid, "notes": notes})


@router.post("/candidate/{cid}/notes")
def add_note(request: Request, cid: int, body: str = Form("")):
    """Ajoute une note (si non vide) puis renvoie le fragment à jour."""
    user = require_user(request, DB_PATH)
    texte = (body or "").strip()
    if texte:
        with connect(DB_PATH) as conn:
            db.insert_returning_id(
                conn,
                """
                INSERT INTO candidate_notes
                    (candidate_id, author_id, author_name, body, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    user["id"],
                    user["name"],
                    texte,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
    notes = _list_notes(cid)
    return render(request, "_notes.html", {"cid": cid, "notes": notes})
