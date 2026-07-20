"""Module « Timeline d'activité » : historique chronologique par candidat. Routeur isolé.

Un seul endpoint, un fragment HTMX chargé à la demande dans la fiche candidat :
    GET /candidate/{cid}/activite  ->  frise verticale des événements (récents d'abord).

Les événements proviennent de la table `candidate_events`, alimentée par le helper
`activity.log(...)` depuis les actions métier (changement de statut/étape, entretien,
note, email…). Au rendu, si aucun événement « RECU » n'existe encore pour le candidat,
on dérive un premier événement « CV reçu » depuis `candidates.received_at`, afin que la
frise ne soit jamais vide pour un candidat déjà présent (rétro-compatibilité).
"""
from fastapi import APIRouter, Request

from web_core import require_user, render, connect
import activity

router = APIRouter()


def _list_events(conn, cid: int) -> list[dict]:
    """Événements d'un candidat, les plus récents d'abord."""
    rows = conn.execute(
        "SELECT id, candidate_id, type, titre, detail, created_at "
        "FROM candidate_events WHERE candidate_id = ? "
        "ORDER BY created_at DESC, id DESC",
        (cid,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/candidate/{cid}/activite")
def get_activite(request: Request, cid: int):
    """Fragment « Activité » : frise verticale des événements du candidat."""
    require_user(request)
    with connect() as conn:
        events = _list_events(conn, cid)
        # Dérive un premier événement « CV reçu » si aucun RECU n'a été journalisé.
        if not any(e["type"] == activity.RECU for e in events):
            row = conn.execute(
                "SELECT received_at FROM candidates WHERE id = ?", (cid,)
            ).fetchone()
            recu_at = row["received_at"] if row else None
            if recu_at:
                events.append({
                    "id": 0,
                    "candidate_id": cid,
                    "type": activity.RECU,
                    "titre": "CV reçu",
                    "detail": "",
                    "created_at": recu_at,
                    "derive": True,
                })
                # Garde l'ordre « plus récent d'abord » après ajout du dérivé.
                events.sort(key=lambda e: (e.get("created_at") or ""), reverse=True)

    # Injecte l'icône de chaque type pour le rendu (fallback neutre).
    for e in events:
        e["icone"] = activity.ICONES.get(e["type"], "•")

    return render(request, "_candidate_timeline.html", {"cid": cid, "events": events})
