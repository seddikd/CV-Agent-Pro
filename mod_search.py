"""Module « Recherche avancée » : filtres multicritères. Routeur isolé."""
from fastapi import APIRouter, Request

from web_core import require_user, render, DB_PATH, connect

router = APIRouter()

# Champs texte : (nom du champ de formulaire, colonne SQL, libellé).
# Chacun est comparé via LIKE %valeur% (colonnes séparées par virgules incluses).
TEXT_FIELDS = [
    ("competences", "competences", "Compétences"),
    ("entreprise", "entreprises", "Entreprise"),
    ("diplome", "diplome_plus_eleve", "Diplôme"),
    ("langues", "langues", "Langues"),
    ("specialite", "specialite", "Spécialité"),
    ("disponibilite", "disponibilite", "Disponibilité"),
    ("certification", "certifications", "Certification"),
]

OPERATEURS = ["AND", "OR", "NOT"]


@router.get("/recherche")
def recherche(request: Request):
    user = require_user(request, DB_PATH)

    # Valeurs saisies (récupérées depuis la query string, sans dépendance externe).
    qp = request.query_params
    valeurs = {champ: (qp.get(champ) or "").strip() for champ, _, _ in TEXT_FIELDS}
    exp_min_raw = (qp.get("experience") or "").strip()
    operateur = (qp.get("operateur") or "AND").upper()
    if operateur not in OPERATEURS:
        operateur = "AND"

    # Expérience minimale : entier positif uniquement, sinon ignorée.
    exp_min = None
    if exp_min_raw:
        try:
            exp_min = int(exp_min_raw)
        except ValueError:
            exp_min = None

    # Construction paramétrée : on n'ajoute une clause QUE si le champ est rempli.
    conditions = []
    params = []
    for champ, colonne, _ in TEXT_FIELDS:
        val = valeurs[champ]
        if val:
            conditions.append(f"{colonne} LIKE ?")
            params.append(f"%{val}%")
    if exp_min is not None:
        conditions.append("annees_experience >= ?")
        params.append(exp_min)

    rows = []
    aucun_critere = not conditions

    if conditions:
        # Assemblage des clauses selon l'opérateur logique global.
        if operateur == "OR":
            where = " OR ".join(conditions)
        elif operateur == "NOT":
            # NOT exclut les candidats correspondant à l'un des critères.
            where = "NOT (" + " OR ".join(conditions) + ")"
        else:  # AND
            where = " AND ".join(conditions)

        sql = (
            "SELECT id, nom, prenom, email, poste_recherche, specialite, "
            "annees_experience, competences, statut "
            f"FROM candidates WHERE {where} "
            "ORDER BY id DESC LIMIT 500"
        )
        with connect(DB_PATH) as conn:
            rows = conn.execute(sql, params).fetchall()

    return render(request, "recherche.html", {
        "text_fields": TEXT_FIELDS,
        "valeurs": valeurs,
        "experience": exp_min_raw,
        "operateur": operateur,
        "operateurs": OPERATEURS,
        "rows": rows,
        "aucun_critere": aucun_critere,
        "nb_resultats": len(rows),
    })
