"""Module « API REST » : endpoints JSON documentés (OpenAPI/Swagger).

Exposés sous /api, documentés automatiquement par FastAPI (voir /openapi.json et
/docs). Lecture seule en v1. Authentification : session de l'application (les
appels doivent porter le cookie de session ; 401 sinon) — cohérent avec le reste
de l'app, sans nouveau secret à gérer.

Réutilise les helpers existants (`web_db`, `matching_core`) plutôt que de
dupliquer la logique.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query

import web_db
import web_auth
from web_core import DB_PATH, connect
from matching_core import score_candidat


def _require_api_user(request: Request) -> dict:
    """Auth API : renvoie l'utilisateur courant ou 401 (pas de redirection HTML)."""
    user = web_auth.current_user(request, DB_PATH)
    if not user:
        raise HTTPException(status_code=401, detail="Authentification requise")
    return user


# Toutes les routes /api exigent une session valide.
router = APIRouter(prefix="/api", tags=["API REST"],
                   dependencies=[Depends(_require_api_user)])


@router.get("/candidates", summary="Lister les candidats",
            description="Liste filtrable des candidats (recherche plein texte, statut, poste).")
def api_candidates(
    search: str = Query("", description="Recherche nom/email/compétences"),
    statut: str = Query("", description="Filtre par statut exact"),
    poste: str = Query("", description="Filtre par poste recherché"),
    limit: int = Query(500, ge=1, le=2000, description="Nombre max de résultats"),
):
    return web_db.list_candidates(DB_PATH, search=search, statut=statut,
                                  poste=poste, limit=limit)


@router.get("/candidates/{cid}", summary="Détail d'un candidat")
def api_candidate(cid: int):
    c = web_db.get_candidate(DB_PATH, cid)
    if not c:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    return c


@router.get("/jobs", summary="Lister les offres d'emploi")
def api_jobs(statut: str = Query("", description="Filtre par statut d'offre")):
    with connect(DB_PATH) as conn:
        if statut:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE statut = ? ORDER BY updated_at DESC",
                (statut,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


@router.get("/jobs/{jid}", summary="Détail d'une offre")
def api_job(jid: int):
    with connect(DB_PATH) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    return dict(row)


@router.get("/stats", summary="Statistiques agrégées",
            description="Total des candidats et répartition par statut.")
def api_stats():
    return web_db.candidate_stats(DB_PATH)


@router.get("/matching/{jid}", summary="Classement des candidats pour une offre",
            description="Score de correspondance (déterministe) de chaque candidat vis-à-vis de l'offre, classé.")
def api_matching(jid: int):
    with connect(DB_PATH) as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Offre introuvable")
        job = dict(job)
        cands = [dict(r) for r in conn.execute("SELECT * FROM candidates").fetchall()]
    classement = []
    for c in cands:
        res = score_candidat(job, c)
        classement.append({
            "candidate_id": c["id"],
            "nom": c.get("nom"), "prenom": c.get("prenom"),
            "score": res["score"],
            "points_forts": res["points_forts"],
            "competences_manquantes": res["competences_manquantes"],
        })
    classement.sort(key=lambda x: x["score"], reverse=True)
    return {"job_id": jid, "titre": job.get("titre"), "classement": classement}


@router.get("/pipeline", summary="Candidats par étape du pipeline (workflow)")
def api_pipeline():
    import mod_pipeline
    with connect(DB_PATH) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, nom, prenom, poste_recherche, statut, stage FROM candidates"
        ).fetchall()]
    colonnes = {etape: [] for etape in mod_pipeline.ETAPES}
    for c in rows:
        stage = c.get("stage") or mod_pipeline.ETAPE_DEFAUT
        if stage not in colonnes:
            stage = mod_pipeline.ETAPE_DEFAUT
        colonnes[stage].append(c)
    return colonnes


@router.get("/alerts", summary="Lister les alertes candidat↔offre")
def api_alerts(seen: int | None = Query(None, description="1=lues, 0=non lues, absent=toutes")):
    sql = ("SELECT a.id, a.candidate_id, a.job_id, a.score, a.created_at, a.seen "
           "FROM alerts a")
    params = []
    if seen in (0, 1):
        sql += " WHERE a.seen = ?"
        params.append(seen)
    sql += " ORDER BY a.seen ASC, a.score DESC, a.id DESC"
    with connect(DB_PATH) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
