"""Module « Gestion des offres d'emploi » : CRUD offres. Routeur isolé."""
from datetime import datetime

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse

from web_core import require_user, render, connect
import db

router = APIRouter()

# Statuts autorisés pour une offre (voir schéma `jobs`).
STATUTS = ["Brouillon", "Publiée", "Archivée"]


def _now() -> str:
    """Horodatage courant (ISO, à la seconde)."""
    return datetime.now().isoformat(timespec="seconds")


def _get_job(conn, job_id: int) -> dict | None:
    """Récupère une offre par id (dict) ou None si absente."""
    row = conn.execute(
        "SELECT * FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    return dict(row) if row else None


@router.get("/offres")
def liste_offres(request: Request, statut: str = ""):
    """Liste des offres, filtrable par statut."""
    user = require_user(request)
    with connect() as conn:
        if statut in STATUTS:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE statut = ? "
                "ORDER BY updated_at DESC",
                (statut,),
            ).fetchall()
        else:
            statut = ""
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC"
            ).fetchall()
        offres = [dict(r) for r in rows]

        # Compteurs par statut (toujours sur l'ensemble, indépendamment du filtre).
        stats_offres = {
            r["statut"]: r["n"]
            for r in conn.execute(
                "SELECT statut, COUNT(*) AS n FROM jobs GROUP BY statut"
            ).fetchall()
        }
    total_offres = sum(stats_offres.values())
    return render(
        request,
        "jobs_list.html",
        {
            "offres": offres, "statut": statut, "statuts": STATUTS,
            "stats_offres": stats_offres, "total_offres": total_offres,
        },
    )


@router.get("/offres/nouveau")
def formulaire_nouvelle_offre(request: Request):
    """Formulaire de création d'une offre."""
    user = require_user(request)
    return render(
        request,
        "job_form.html",
        {"offre": None, "statuts": STATUTS},
    )


@router.post("/offres")
def creer_offre(
    request: Request,
    titre: str = Form(...),
    departement: str = Form(""),
    lieu: str = Form(""),
    description: str = Form(""),
    competences_requises: str = Form(""),
    experience_min: str = Form(""),
    niveau_etude: str = Form(""),
    statut: str = Form("Brouillon"),
):
    """Crée une offre puis redirige vers son détail."""
    user = require_user(request)
    if statut not in STATUTS:
        raise HTTPException(status_code=400, detail="Statut invalide")
    titre = titre.strip()
    if not titre:
        raise HTTPException(status_code=400, detail="Le titre est obligatoire")
    exp = int(experience_min) if experience_min.strip().isdigit() else None
    now = _now()
    with connect() as conn:
        new_id = db.insert_returning_id(
            conn,
            "INSERT INTO jobs "
            "(titre, departement, lieu, description, competences_requises, "
            " experience_min, niveau_etude, statut, created_by, created_at, "
            " updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                titre,
                departement.strip(),
                lieu.strip(),
                description.strip(),
                competences_requises.strip(),
                exp,
                niveau_etude.strip(),
                statut,
                user["id"],
                now,
                now,
            ),
        )
    return RedirectResponse(f"/offres/{new_id}", status_code=303)


@router.get("/offres/{job_id}")
def detail_offre(request: Request, job_id: int):
    """Détail d'une offre. 404 si absente."""
    user = require_user(request)
    with connect() as conn:
        offre = _get_job(conn, job_id)
    if offre is None:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    return render(
        request,
        "job_detail.html",
        {"offre": offre, "statuts": STATUTS},
    )


@router.get("/offres/{job_id}/modifier")
def formulaire_modifier_offre(request: Request, job_id: int):
    """Formulaire de modification (réutilise job_form.html préremplit)."""
    user = require_user(request)
    with connect() as conn:
        offre = _get_job(conn, job_id)
    if offre is None:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    return render(
        request,
        "job_form.html",
        {"offre": offre, "statuts": STATUTS},
    )


@router.post("/offres/{job_id}/update")
def mettre_a_jour_offre(
    request: Request,
    job_id: int,
    titre: str = Form(...),
    departement: str = Form(""),
    lieu: str = Form(""),
    description: str = Form(""),
    competences_requises: str = Form(""),
    experience_min: str = Form(""),
    niveau_etude: str = Form(""),
    statut: str = Form("Brouillon"),
):
    """Met à jour les champs d'une offre existante."""
    user = require_user(request)
    if statut not in STATUTS:
        raise HTTPException(status_code=400, detail="Statut invalide")
    titre = titre.strip()
    if not titre:
        raise HTTPException(status_code=400, detail="Le titre est obligatoire")
    exp = int(experience_min) if experience_min.strip().isdigit() else None
    with connect() as conn:
        if _get_job(conn, job_id) is None:
            raise HTTPException(status_code=404, detail="Offre introuvable")
        conn.execute(
            "UPDATE jobs SET titre = ?, departement = ?, lieu = ?, "
            "description = ?, competences_requises = ?, experience_min = ?, "
            "niveau_etude = ?, statut = ?, updated_at = ? WHERE id = ?",
            (
                titre,
                departement.strip(),
                lieu.strip(),
                description.strip(),
                competences_requises.strip(),
                exp,
                niveau_etude.strip(),
                statut,
                _now(),
                job_id,
            ),
        )
    return RedirectResponse(f"/offres/{job_id}", status_code=303)


@router.post("/offres/{job_id}/statut")
def changer_statut_offre(
    request: Request,
    job_id: int,
    statut: str = Form(...),
):
    """Change le statut d'une offre (publication / archivage)."""
    user = require_user(request)
    if statut not in STATUTS:
        raise HTTPException(status_code=400, detail="Statut invalide")
    with connect() as conn:
        if _get_job(conn, job_id) is None:
            raise HTTPException(status_code=404, detail="Offre introuvable")
        conn.execute(
            "UPDATE jobs SET statut = ?, updated_at = ? WHERE id = ?",
            (statut, _now(), job_id),
        )
    return RedirectResponse(f"/offres/{job_id}", status_code=303)


@router.post("/offres/{job_id}/delete")
def supprimer_offre(request: Request, job_id: int):
    """Supprime une offre puis redirige vers la liste."""
    user = require_user(request)
    with connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return RedirectResponse("/offres", status_code=303)
