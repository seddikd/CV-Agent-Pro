"""Module « Alertes » : correspondances candidat↔offre publiée. Routeur isolé.

La détection se fait automatiquement dans le pipeline (à chaque nouveau CV) via
`alerts_engine`. Cette page les affiche et permet un recalcul global manuel.
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse

from web_core import require_user, render, DB_PATH, connect
import alerts_engine

router = APIRouter()


@router.get("/alertes")
def liste_alertes(request: Request, msg: str = ""):
    user = require_user(request, DB_PATH)
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT a.id AS id, a.score AS score, a.created_at AS created_at, "
            "a.seen AS seen, "
            "c.id AS candidate_id, c.nom AS nom, c.prenom AS prenom, "
            "j.id AS job_id, j.titre AS job_titre "
            "FROM alerts a "
            "JOIN candidates c ON c.id = a.candidate_id "
            "JOIN jobs j ON j.id = a.job_id "
            "ORDER BY a.seen ASC, a.score DESC, a.id DESC"
        ).fetchall()
        alertes = [dict(r) for r in rows]
    non_lues = sum(1 for a in alertes if not a["seen"])
    return render(request, "alertes.html", {
        "alertes": alertes,
        "non_lues": non_lues,
        "seuil": alerts_engine.SEUIL_ALERTE,
        "msg": msg,
    })


@router.post("/alertes/{aid}/seen")
def marquer_lue(request: Request, aid: int):
    require_user(request, DB_PATH)
    with connect(DB_PATH) as conn:
        conn.execute("UPDATE alerts SET seen = 1 WHERE id = ?", (aid,))
    return RedirectResponse("/alertes", status_code=303)


@router.post("/alertes/seen-all")
def marquer_toutes_lues(request: Request):
    require_user(request, DB_PATH)
    with connect(DB_PATH) as conn:
        conn.execute("UPDATE alerts SET seen = 1 WHERE seen = 0")
    return RedirectResponse("/alertes", status_code=303)


@router.post("/alertes/rebuild")
def recalculer(request: Request):
    require_user(request, DB_PATH)
    n = alerts_engine.recalculer_toutes_alertes(DB_PATH)
    return RedirectResponse(
        f"/alertes?msg={n}+nouvelle(s)+alerte(s)+détectée(s)", status_code=303
    )
