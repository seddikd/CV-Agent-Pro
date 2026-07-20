"""Module « Entretiens » : planification des entretiens candidats. Routeur isolé.

Un entretien lie un candidat à une date/heure, un type (présentiel / visio /
téléphonique), un lieu (ou lien) et un statut. La création peut être amorcée
depuis la fiche candidat (`/entretiens/nouveau?candidate_id=…`), le candidat
étant alors présélectionné dans le formulaire.
"""
from datetime import datetime

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse

from web_core import require_user, render, connect
import db
import web_db
import entretien_reminders
import activity

router = APIRouter()

# Types d'entretien et statuts autorisés (voir schéma `entretiens`).
TYPES = ["Présentiel", "Visioconférence", "Téléphonique"]
STATUTS = ["Planifié", "Terminé", "Annulé"]


def _now() -> str:
    """Horodatage courant (ISO, à la seconde)."""
    return datetime.now().isoformat(timespec="seconds")


def _liste_candidats(conn) -> list[dict]:
    """Candidats pour le menu déroulant (id + nom lisible), triés par nom.

    Exclut les candidats marqués comme doublons (duplicate_of) : on ne planifie
    pas d'entretien avec un profil en double, on garde son « original ».
    """
    rows = conn.execute(
        "SELECT id, nom, prenom, poste_recherche FROM candidates "
        "WHERE duplicate_of IS NULL "
        "ORDER BY nom ASC, prenom ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def _get_entretien(conn, eid: int) -> dict | None:
    """Récupère un entretien (joint au candidat) ou None si absent."""
    row = conn.execute(
        "SELECT e.*, c.nom AS cand_nom, c.prenom AS cand_prenom, "
        "c.poste_recherche AS cand_poste "
        "FROM entretiens e JOIN candidates c ON c.id = e.candidate_id "
        "WHERE e.id = ?",
        (eid,),
    ).fetchone()
    return dict(row) if row else None


@router.get("/entretiens")
def liste_entretiens(request: Request, statut: str = "", msg: str = ""):
    """Liste des entretiens (à venir d'abord), filtrable par statut."""
    user = require_user(request)
    with connect() as conn:
        base = (
            "SELECT e.id AS id, e.date_heure AS date_heure, e.type AS type, "
            "e.lieu AS lieu, e.statut AS statut, e.notes AS notes, "
            "e.reminder_sent AS reminder_sent, e.candidate_id AS candidate_id, "
            "c.nom AS cand_nom, c.prenom AS cand_prenom, "
            "c.poste_recherche AS cand_poste "
            "FROM entretiens e JOIN candidates c ON c.id = e.candidate_id "
        )
        if statut in STATUTS:
            rows = conn.execute(
                base + "WHERE e.statut = ? ORDER BY e.date_heure ASC",
                (statut,),
            ).fetchall()
        else:
            statut = ""
            rows = conn.execute(base + "ORDER BY e.date_heure ASC").fetchall()
        entretiens = [dict(r) for r in rows]

    maintenant = datetime.now().isoformat(timespec="minutes")
    a_venir = sum(
        1 for e in entretiens
        if e["statut"] == "Planifié" and (e["date_heure"] or "") >= maintenant
    )
    return render(request, "entretiens_list.html", {
        "entretiens": entretiens,
        "statut": statut,
        "statuts": STATUTS,
        "a_venir": a_venir,
        "maintenant": maintenant,
        "msg": msg,
    })


@router.post("/entretiens/envoyer-rappels")
def envoyer_rappels_maintenant(request: Request):
    """Déclenche manuellement l'envoi des rappels d'entretien dus (bouton UI)."""
    user = require_user(request)
    smtp = web_db.settings_to_config(web_db.get_all_settings())["smtp"]
    if not smtp.get("host"):
        return RedirectResponse(
            "/entretiens?msg=SMTP+non+configuré+—+renseignez-le+dans+Param.+Mail",
            status_code=303,
        )
    n = entretien_reminders.envoyer_rappels_dus(force=True)
    return RedirectResponse(
        f"/entretiens?msg={n}+rappel(s)+envoyé(s)", status_code=303
    )


@router.get("/entretiens/nouveau")
def formulaire_nouvel_entretien(request: Request, candidate_id: int = 0):
    """Formulaire de planification. `candidate_id` présélectionne un candidat."""
    user = require_user(request)
    with connect() as conn:
        candidats = _liste_candidats(conn)
    return render(request, "entretien_form.html", {
        "entretien": None,
        "candidats": candidats,
        "candidate_id": candidate_id,
        "types": TYPES,
        "statuts": STATUTS,
    })


@router.post("/entretiens")
def creer_entretien(
    request: Request,
    candidate_id: int = Form(...),
    date_heure: str = Form(...),
    type: str = Form(""),
    lieu: str = Form(""),
    statut: str = Form("Planifié"),
    notes: str = Form(""),
):
    """Crée un entretien puis redirige vers la liste."""
    user = require_user(request)
    if statut not in STATUTS:
        raise HTTPException(status_code=400, detail="Statut invalide")
    date_heure = date_heure.strip()
    if not date_heure:
        raise HTTPException(status_code=400, detail="La date est obligatoire")
    now = _now()
    with connect() as conn:
        if conn.execute(
            "SELECT 1 FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=400, detail="Candidat introuvable")
        db.insert_returning_id(
            conn,
            "INSERT INTO entretiens "
            "(candidate_id, date_heure, type, lieu, statut, notes, "
            " created_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                candidate_id, date_heure, type.strip(), lieu.strip(),
                statut, notes.strip(), user["id"], now, now,
            ),
        )
        activity.log(conn, candidate_id, activity.ENTRETIEN, "Entretien planifié",
                     f"{type.strip()} le {date_heure} — {lieu.strip()}".strip(" —"))
    return RedirectResponse("/entretiens", status_code=303)


@router.get("/entretiens/{eid}/modifier")
def formulaire_modifier_entretien(request: Request, eid: int):
    """Formulaire de modification d'un entretien existant."""
    user = require_user(request)
    with connect() as conn:
        entretien = _get_entretien(conn, eid)
        candidats = _liste_candidats(conn)
    if entretien is None:
        raise HTTPException(status_code=404, detail="Entretien introuvable")
    return render(request, "entretien_form.html", {
        "entretien": entretien,
        "candidats": candidats,
        "candidate_id": entretien["candidate_id"],
        "types": TYPES,
        "statuts": STATUTS,
    })


@router.post("/entretiens/{eid}/update")
def mettre_a_jour_entretien(
    request: Request,
    eid: int,
    candidate_id: int = Form(...),
    date_heure: str = Form(...),
    type: str = Form(""),
    lieu: str = Form(""),
    statut: str = Form("Planifié"),
    notes: str = Form(""),
):
    """Met à jour un entretien existant."""
    user = require_user(request)
    if statut not in STATUTS:
        raise HTTPException(status_code=400, detail="Statut invalide")
    date_heure = date_heure.strip()
    if not date_heure:
        raise HTTPException(status_code=400, detail="La date est obligatoire")
    with connect() as conn:
        if _get_entretien(conn, eid) is None:
            raise HTTPException(status_code=404, detail="Entretien introuvable")
        # reminder_sent remis à 0 : un entretien modifié (date potentiellement
        # changée) doit ré-armer son rappel email.
        conn.execute(
            "UPDATE entretiens SET candidate_id = ?, date_heure = ?, type = ?, "
            "lieu = ?, statut = ?, notes = ?, reminder_sent = 0, updated_at = ? "
            "WHERE id = ?",
            (
                candidate_id, date_heure, type.strip(), lieu.strip(),
                statut, notes.strip(), _now(), eid,
            ),
        )
    return RedirectResponse("/entretiens", status_code=303)


@router.post("/entretiens/{eid}/statut")
def changer_statut_entretien(request: Request, eid: int, statut: str = Form(...)):
    """Change le statut d'un entretien (Terminé / Annulé)."""
    user = require_user(request)
    if statut not in STATUTS:
        raise HTTPException(status_code=400, detail="Statut invalide")
    with connect() as conn:
        ent = _get_entretien(conn, eid)
        if ent is None:
            raise HTTPException(status_code=404, detail="Entretien introuvable")
        conn.execute(
            "UPDATE entretiens SET statut = ?, updated_at = ? WHERE id = ?",
            (statut, _now(), eid),
        )
        activity.log(conn, ent["candidate_id"], activity.ENTRETIEN, f"Entretien {statut}")
    return RedirectResponse("/entretiens", status_code=303)


@router.post("/entretiens/{eid}/delete")
def supprimer_entretien(request: Request, eid: int):
    """Supprime un entretien puis redirige vers la liste."""
    user = require_user(request)
    with connect() as conn:
        conn.execute("DELETE FROM entretiens WHERE id = ?", (eid,))
    return RedirectResponse("/entretiens", status_code=303)
