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
def doublons(request: Request, msg: str = ""):
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
            # Candidats encore « à ranger » : ni l'original, ni déjà marqués.
            nb_markables = sum(
                1 for c in membres
                if c["id"] != original["id"] and not c["duplicate_of"]
            )
            groupes.append({
                "cle": cle,
                "critere": libelle,
                "valeur": valeur,
                "original_id": original["id"],
                "membres": membres,
                "nb_membres": len(membres),
                "nb_markables": nb_markables,
            })

    # Affichage stable : par critère puis par id de l'original.
    ordre = {cle: i for i, (cle, _, _) in enumerate(CRITERES)}
    groupes.sort(key=lambda g: (ordre[g["cle"]], g["original_id"]))

    # Candidats concernés (uniques, un même candidat pouvant apparaître dans
    # plusieurs groupes) et candidats déjà marqués comme doublon.
    concernes = {c["id"] for g in groupes for c in g["membres"]}
    nb_marques = sum(1 for c in rows if c["duplicate_of"])

    # Nombre de candidats encore « à ranger » sur toute la page (pour l'entête).
    # On compte les candidats DISTINCTS : un même candidat peut être « à ranger »
    # dans plusieurs groupes (même email ET même téléphone) — le sommer par groupe
    # le compterait deux fois (et le marquage en lot, lui, dédoublonne par cid).
    nb_a_ranger = len({
        c["id"]
        for g in groupes
        for c in g["membres"]
        if c["id"] != g["original_id"] and not c["duplicate_of"]
    })

    # Onglets de filtre par critère (clé, libellé, nom d'icône, nb de groupes).
    # Les valeurs sont des noms du jeu d'icônes (templates/_icones.html) : le
    # gabarit les passe à `ui.ic`, qui produit le SVG.
    icone = {"email": "enveloppe", "telephone": "telephone", "nom": "carte"}
    filtres = [
        {
            "cle": cle,
            "libelle": libelle,
            "icone": icone.get(cle, "recherche"),
            "nb": sum(1 for g in groupes if g["cle"] == cle),
        }
        for cle, libelle, _ in CRITERES
    ]

    return render(request, "duplicates.html", {
        "groupes": groupes,
        "nb_groupes": len(groupes),
        "nb_concernes": len(concernes),
        "nb_marques": nb_marques,
        "nb_a_ranger": nb_a_ranger,
        "filtres": filtres,
        "msg": msg,
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


@router.post("/doublons/mark-bulk")
def marquer_doublons_bulk(request: Request, pairs: str = Form(default="")):
    """Marque en lot plusieurs candidats comme doublons.

    `pairs` est une liste de couples « cid:original_id » séparés par des virgules
    (ou espaces) — le candidat `cid` devient doublon de `original_id`. On envoie
    un champ unique (et non un champ par case) pour éviter la limite Starlette de
    1000 champs quand on sélectionne tout. On ignore silencieusement les couples
    invalides, auto-référents ou pointant vers un candidat inexistant, puis on
    applique tous les marquages valides en une seule transaction.
    """
    user = require_user(request)

    from urllib.parse import quote

    # Parse + validation des couples (dédup sur le candidat marqué : un cid ne peut
    # être marqué qu'une fois, même s'il apparaît dans plusieurs groupes cochés).
    a_marquer: dict[int, int] = {}
    for pair in re.split(r"[,\s]+", pairs.strip()):
        if not pair:
            continue
        try:
            cid_s, orig_s = pair.split(":", 1)
            cid, original_id = int(cid_s), int(orig_s)
        except (ValueError, AttributeError):
            continue
        if cid == original_id or cid in a_marquer:
            continue
        a_marquer[cid] = original_id

    n = 0
    if a_marquer:
        with connect() as conn:
            existants = {
                r["id"] for r in conn.execute("SELECT id FROM candidates").fetchall()
            }
            for cid, original_id in a_marquer.items():
                if cid not in existants or original_id not in existants:
                    continue
                conn.execute(
                    "UPDATE candidates SET duplicate_of = ?, statut = ? WHERE id = ?",
                    (original_id, "Doublon", cid),
                )
                n += 1
            conn.commit()

    msg = (f"{n} candidat(s) marqué(s) comme doublon."
           if n else "Aucun candidat sélectionné.")
    return RedirectResponse(f"/doublons?msg={quote(msg)}", status_code=303)
