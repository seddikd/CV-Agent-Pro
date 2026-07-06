"""Module « Matching IA » : score de correspondance offre↔candidat.

Scoring 100 % LOCAL et déterministe (aucun appel LLM — fonctionne hors-ligne).
La table `matches` sert de cache des scores calculés. Routeur isolé.
"""
import json
import threading
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse

from web_core import require_user, render, DB_PATH, connect
from matching_core import score_candidat  # logique de scoring partagée (réutilisée par les alertes)

router = APIRouter()

# Sérialise le remplissage du cache `matches` : deux premières consultations
# simultanées d'une même offre (endpoints sync exécutés dans le pool de threads)
# calculaient et inséraient chacune un jeu complet -> lignes dupliquées (la table
# `matches` n'a pas de contrainte UNIQUE(job_id, candidate_id)). Le verrou garantit
# qu'un seul calcul a lieu ; le second voit alors le cache déjà rempli.
_matching_lock = threading.Lock()


def _now() -> str:
    """Horodatage courant (ISO, à la seconde)."""
    return datetime.now().isoformat(timespec="seconds")


def _get_job(conn, job_id: int) -> dict | None:
    """Récupère une offre par id (dict) ou None si absente."""
    row = conn.execute(
        "SELECT * FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    return dict(row) if row else None


def _compute_and_cache(conn, job: dict) -> None:
    """Calcule le score de chaque candidat et remplit le cache `matches`.

    Purge d'abord les lignes existantes de l'offre (idempotent : recalcul propre,
    pas de doublon même si appelé deux fois).
    """
    conn.execute("DELETE FROM matches WHERE job_id = ?", (job["id"],))
    cands = [
        dict(r)
        for r in conn.execute("SELECT * FROM candidates").fetchall()
    ]
    now = _now()
    for cand in cands:
        res = score_candidat(job, cand)
        details = json.dumps(
            {
                "points_forts": res["points_forts"],
                "competences_manquantes": res["competences_manquantes"],
            },
            ensure_ascii=False,
        )
        # Insertion simple : l'id généré n'est pas utilisé (pas de insert_returning_id).
        conn.execute(
            "INSERT INTO matches "
            "(job_id, candidate_id, score, details_json, computed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (job["id"], cand["id"], res["score"], details, now),
        )


def _lire_classement(conn, job_id: int) -> list:
    """Lit le cache `matches` joint aux candidats, classé par score décroissant."""
    rows = conn.execute(
        "SELECT m.score AS score, m.details_json AS details_json, "
        "m.computed_at AS computed_at, "
        "c.id AS candidate_id, c.nom AS nom, c.prenom AS prenom, "
        "c.poste_recherche AS poste_recherche "
        "FROM matches m "
        "JOIN candidates c ON c.id = m.candidate_id "
        "WHERE m.job_id = ? "
        "ORDER BY m.score DESC, c.nom ASC",
        (job_id,),
    ).fetchall()
    classement = []
    for i, r in enumerate(rows, start=1):
        d = dict(r)
        try:
            details = json.loads(d.get("details_json") or "{}")
        except (ValueError, TypeError):
            details = {}
        d["points_forts"] = details.get("points_forts", [])
        d["competences_manquantes"] = details.get("competences_manquantes", [])
        d["rang"] = i
        classement.append(d)
    return classement


@router.get("/matching")
def liste_matching(request: Request):
    """Liste des offres avec un lien vers le matching de chacune."""
    user = require_user(request, DB_PATH)
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, titre, statut FROM jobs ORDER BY updated_at DESC"
        ).fetchall()
        offres = [dict(r) for r in rows]
    return render(request, "matching_list.html", {"offres": offres})


@router.get("/matching/{job_id}")
def detail_matching(request: Request, job_id: int):
    """Matching d'une offre : lit le cache ou le calcule si absent. 404 si offre absente."""
    user = require_user(request, DB_PATH)
    # Verrou : la séquence « vérifier l'absence de cache puis le remplir » doit être
    # atomique vis-à-vis d'une consultation concurrente de la même offre (sinon
    # double calcul -> lignes dupliquées). Le verrou couvre la connexion entière,
    # donc le commit a lieu avant qu'un second appel ne relise le cache.
    with _matching_lock:
        with connect(DB_PATH) as conn:
            offre = _get_job(conn, job_id)
            if offre is None:
                raise HTTPException(status_code=404, detail="Offre introuvable")
            existe = conn.execute(
                "SELECT 1 FROM matches WHERE job_id = ? LIMIT 1", (job_id,)
            ).fetchone()
            if existe is None:
                _compute_and_cache(conn, offre)
            classement = _lire_classement(conn, job_id)
    return render(
        request,
        "matching_detail.html",
        {"offre": offre, "classement": classement},
    )


@router.post("/matching/{job_id}/recompute")
def recalculer_matching(request: Request, job_id: int):
    """Recalcule tout le matching de l'offre et met à jour le cache."""
    user = require_user(request, DB_PATH)
    with connect(DB_PATH) as conn:
        offre = _get_job(conn, job_id)
        if offre is None:
            raise HTTPException(status_code=404, detail="Offre introuvable")
        conn.execute("DELETE FROM matches WHERE job_id = ?", (job_id,))
        _compute_and_cache(conn, offre)
    return RedirectResponse(f"/matching/{job_id}", status_code=303)
