"""Module « Détection de doublons » : regroupe les candidats en double. Routeur isolé."""
import re
from datetime import datetime

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse

from web_core import require_user, render, connect

router = APIRouter()


def _norm_email(valeur) -> str:
    """Normalise un email : minuscule + strip. Retourne '' si vide."""
    return (valeur or "").strip().lower()


def _norm_tel(valeur) -> str:
    """Normalise un téléphone : ne garde que les chiffres.

    Retourne '' si moins de 6 chiffres (numéro trop court pour être fiable).
    """
    chiffres = re.sub(r"\D", "", valeur or "")
    return chiffres if len(chiffres) >= 6 else ""


def _norm_nom(prenom, nom) -> str:
    """Normalise (nom + prénom) : minuscule, espaces réduits. '' si les deux vides."""
    brut = f"{(prenom or '').strip()} {(nom or '').strip()}".strip().lower()
    brut = re.sub(r"\s+", " ", brut)
    return brut


# Critères de rapprochement : (clé interne, libellé, fonction de normalisation).
CRITERES = [
    ("email", "Même email", lambda c: _norm_email(c["email"])),
    ("telephone", "Même téléphone", lambda c: _norm_tel(c["telephone"])),
    ("nom", "Même nom et prénom", lambda c: _norm_nom(c["prenom"], c["nom"])),
]


@router.get("/doublons")
def doublons(request: Request):
    user = require_user(request)

    with connect() as conn:
        rows = conn.execute(
            "SELECT id, nom, prenom, email, telephone, poste_recherche, "
            "statut, duplicate_of "
            "FROM candidates ORDER BY id ASC"
        ).fetchall()

    # Regroupement en Python : pour chaque critère, on indexe par valeur normalisée.
    groupes = []
    for cle, libelle, fonction in CRITERES:
        index = {}
        for c in rows:
            valeur = fonction(c)
            if not valeur:
                continue
            index.setdefault(valeur, []).append(c)
        for valeur, membres in index.items():
            if len(membres) < 2:
                continue
            # Le plus ancien (plus petit id) est considéré comme l'original.
            membres = sorted(membres, key=lambda c: c["id"])
            original = membres[0]
            groupes.append({
                "critere": libelle,
                "valeur": valeur,
                "original_id": original["id"],
                "membres": membres,
            })

    # Affichage stable : par critère puis par id de l'original.
    ordre = {cle: i for i, (cle, _, _) in enumerate(CRITERES)}
    libelle_vers_cle = {lib: cle for cle, lib, _ in CRITERES}
    groupes.sort(key=lambda g: (ordre[libelle_vers_cle[g["critere"]]], g["original_id"]))

    return render(request, "duplicates.html", {
        "groupes": groupes,
        "nb_groupes": len(groupes),
    })


@router.post("/doublons/{cid}/mark")
def marquer_doublon(cid: int, request: Request, original_id: int = Form(...)):
    user = require_user(request)

    if original_id == cid:
        raise HTTPException(status_code=400, detail="Un candidat ne peut pas être son propre doublon.")

    with connect() as conn:
        # L'original doit exister.
        orig = conn.execute(
            "SELECT id FROM candidates WHERE id = ?", (original_id,)
        ).fetchone()
        if orig is None:
            raise HTTPException(status_code=400, detail="Candidat original introuvable.")

        # Le candidat marqué doit exister aussi.
        cible = conn.execute(
            "SELECT id FROM candidates WHERE id = ?", (cid,)
        ).fetchone()
        if cible is None:
            raise HTTPException(status_code=400, detail="Candidat introuvable.")

        conn.execute(
            "UPDATE candidates SET duplicate_of = ?, statut = ? WHERE id = ?",
            (original_id, "Doublon", cid),
        )
        conn.commit()

    return RedirectResponse("/doublons", status_code=303)
