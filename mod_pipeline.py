"""Module « Pipeline de recrutement » : tableau kanban glisser-déposer. Routeur isolé."""
from datetime import datetime

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import Response

from web_core import require_user, render, DB_PATH, connect

router = APIRouter()

# Étapes du pipeline, dans l'ordre d'avancement (une colonne kanban chacune).
ETAPES = [
    "CV reçu",
    "Analyse",
    "Présélection",
    "Entretien RH",
    "Entretien Technique",
    "Test",
    "Offre",
    "Embauché",
    "Refusé",
]

# Étape par défaut quand `candidates.stage` est NULL / vide.
ETAPE_DEFAUT = "CV reçu"


def _now() -> str:
    """Horodatage courant (ISO, à la seconde)."""
    return datetime.now().isoformat(timespec="seconds")


@router.get("/pipeline")
def tableau_pipeline(request: Request):
    """Tableau kanban : une colonne par étape, les candidats regroupés par `stage`."""
    user = require_user(request, DB_PATH)
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, nom, prenom, poste_recherche, statut, stage "
            "FROM candidates ORDER BY updated_at DESC"
        ).fetchall()

    # Regroupement en Python : une liste de candidats par étape.
    colonnes = {etape: [] for etape in ETAPES}
    for row in rows:
        cand = dict(row)
        stage = cand.get("stage") or ETAPE_DEFAUT
        # Une étape inconnue (donnée héritée) retombe sur l'étape par défaut.
        if stage not in colonnes:
            stage = ETAPE_DEFAUT
        colonnes[stage].append(cand)

    return render(
        request,
        "pipeline.html",
        {"etapes": ETAPES, "colonnes": colonnes},
    )


@router.post("/pipeline/{cid}/stage")
def changer_etape(request: Request, cid: int, stage: str = Form(...)):
    """Déplace un candidat vers une nouvelle étape (appel AJAX du glisser-déposer)."""
    user = require_user(request, DB_PATH)
    if stage not in ETAPES:
        raise HTTPException(status_code=400, detail="Étape invalide")
    with connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE candidates SET stage = ?, updated_at = ? WHERE id = ?",
            (stage, _now(), cid),
        )
    # Réponse légère : le JS n'a besoin que du succès HTTP.
    return Response(status_code=204)
