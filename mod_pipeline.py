"""Module « Pipeline de recrutement » : tableau kanban glisser-déposer. Routeur isolé."""
from datetime import datetime

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import Response, JSONResponse

from web_core import require_user, render, connect
import activity

router = APIRouter()

# Étapes du pipeline, dans l'ordre d'avancement (une colonne kanban chacune).
# « CV reçu » n'est plus une colonne : les candidats non encore engagés dans le
# pipeline (stage NULL, « CV reçu » ou inconnu) constituent le vivier accessible
# via la barre de recherche, et entrent dans le tableau à l'étape « Présélection ».
ETAPES = [
    "Présélection",
    "Entretien RH",
    "Entretien Technique",
    "Embauché",
    "Refusé",
]

# Étape d'entrée dans le pipeline (premier clic depuis la recherche).
ETAPE_ENTREE = "Présélection"


def _now() -> str:
    """Horodatage courant (ISO, à la seconde)."""
    return datetime.now().isoformat(timespec="seconds")


@router.get("/pipeline")
def tableau_pipeline(request: Request):
    """Tableau kanban : une colonne par étape, les candidats regroupés par `stage`."""
    user = require_user(request)
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, nom, prenom, poste_recherche, statut, stage "
            "FROM candidates ORDER BY updated_at DESC"
        ).fetchall()

    # Regroupement en Python : une liste de candidats par étape.
    # Les candidats hors pipeline (stage NULL / « CV reçu » / inconnu) ne sont
    # PAS affichés — ils restent dans le vivier interrogeable par la recherche.
    colonnes = {etape: [] for etape in ETAPES}
    for row in rows:
        cand = dict(row)
        stage = cand.get("stage")
        if stage in colonnes:
            colonnes[stage].append(cand)

    return render(
        request,
        "pipeline.html",
        {"etapes": ETAPES, "colonnes": colonnes},
    )


@router.get("/pipeline/search")
def rechercher_vivier(request: Request, q: str = ""):
    """Recherche dans le vivier hors pipeline par nom, prénom, diplôme ou spécialité.

    Retourne du JSON pour la barre de recherche du kanban. On exclut les
    candidats déjà placés dans une colonne (stage ∈ ETAPES) afin de ne pas créer
    de doublon de carte lors de l'ajout en « Analyse ».
    """
    user = require_user(request)
    q = (q or "").strip()
    if len(q) < 2:
        return JSONResponse([])

    motif = f"%{q.lower()}%"
    # Un placeholder par étape pour la clause d'exclusion NOT IN (...).
    marques = ",".join(["?"] * len(ETAPES))
    sql = (
        "SELECT id, nom, prenom, poste_recherche, diplome_plus_eleve, specialite "
        "FROM candidates "
        # Exclut les candidats marqués comme doublons (duplicate_of) : on ne
        # propose que les profils originaux dans le vivier.
        "WHERE duplicate_of IS NULL "
        f"AND (stage IS NULL OR stage NOT IN ({marques})) "
        "AND (LOWER(COALESCE(nom, '')) LIKE ? "
        "OR LOWER(COALESCE(prenom, '')) LIKE ? "
        "OR LOWER(COALESCE(diplome_plus_eleve, '')) LIKE ? "
        "OR LOWER(COALESCE(specialite, '')) LIKE ?) "
        "ORDER BY updated_at DESC LIMIT 20"
    )
    params = list(ETAPES) + [motif, motif, motif, motif]
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return JSONResponse([dict(r) for r in rows])


@router.post("/pipeline/{cid}/stage")
def changer_etape(
    request: Request, cid: int, stage: str = Form(...), motif_refus: str = Form("")
):
    """Déplace un candidat vers une nouvelle étape (appel AJAX du glisser-déposer)."""
    user = require_user(request)
    if stage not in ETAPES:
        raise HTTPException(status_code=400, detail="Étape invalide")
    motif_refus = motif_refus.strip()
    if stage == "Refusé" and not motif_refus:
        raise HTTPException(status_code=400, detail="Le motif de refus est obligatoire")
    with connect() as conn:
        if stage == "Refusé":
            conn.execute(
                "UPDATE candidates SET stage = ?, statut = 'Refusé', motif_refus = ?, "
                "updated_at = ? WHERE id = ?",
                (stage, motif_refus, _now(), cid),
            )
        else:
            conn.execute(
                "UPDATE candidates SET stage = ?, updated_at = ? WHERE id = ?",
                (stage, _now(), cid),
            )
        # Journal d'activité (timeline) + base du « temps par étape » du reporting :
        # le nom brut de l'étape est stocké dans `detail`.
        detail = motif_refus if stage == "Refusé" else stage
        activity.log(conn, cid, activity.ETAPE, f"Étape → {stage}", detail)
    # Réponse légère : le JS n'a besoin que du succès HTTP.
    return Response(status_code=204)


@router.post("/pipeline/{cid}/retirer")
def retirer_du_pipeline(request: Request, cid: int):
    """Retire un candidat du pipeline : `stage` repasse à NULL.

    Le candidat n'est pas supprimé — il quitte simplement le tableau et
    redevient disponible dans le vivier (barre de recherche).
    """
    user = require_user(request)
    with connect() as conn:
        conn.execute(
            "UPDATE candidates SET stage = NULL, updated_at = ? WHERE id = ?",
            (_now(), cid),
        )
    return Response(status_code=204)
