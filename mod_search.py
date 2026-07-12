"""Module « Recherche avancée » : filtres multicritères. Routeur isolé."""
from fastapi import APIRouter, Request

from web_core import require_user, render, connect
from algeria_geo import WILAYAS, COMMUNES_BY_WILAYA

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

# Situations familiales proposées (liste déroulante ; valeurs normalisées à l'extraction).
SITUATIONS = ["Célibataire", "Marié(e)", "Divorcé(e)", "Veuf(ve)"]

# Tranches d'âge : (libellé, borne min incluse, borne max incluse ou None pour « et plus »).
TRANCHES_AGE = [
    ("18-24", 18, 24),
    ("25-30", 25, 30),
    ("31-35", 31, 35),
    ("36-40", 36, 40),
    ("41-50", 41, 50),
    ("51+", 51, None),
]


@router.get("/recherche")
def recherche(request: Request):
    user = require_user(request)

    # Valeurs saisies (récupérées depuis la query string, sans dépendance externe).
    qp = request.query_params
    valeurs = {champ: (qp.get(champ) or "").strip() for champ, _, _ in TEXT_FIELDS}
    exp_min_raw = (qp.get("experience") or "").strip()
    wilaya = (qp.get("wilaya") or "").strip()
    commune = (qp.get("commune") or "").strip()
    situation = (qp.get("situation_familiale") or "").strip()
    tranche_age = (qp.get("tranche_age") or "").strip()
    operateur = (qp.get("operateur") or "AND").upper()
    if operateur not in OPERATEURS:
        operateur = "AND"

    # Options de wilaya : référentiel officiel des 58 wilayas d'Algérie (algeria_geo),
    # et non plus les valeurs libres présentes en base. Le menu « Commune » est
    # dépendant : il est peuplé côté client (JS) selon la wilaya choisie.
    wilayas = WILAYAS
    # Commune retenue seulement si elle appartient bien à la wilaya sélectionnée.
    if commune and commune not in COMMUNES_BY_WILAYA.get(wilaya, []):
        commune = ""

    # Bornes de la tranche d'âge choisie (None si aucune / invalide).
    age_min = age_max = None
    for libelle, bmin, bmax in TRANCHES_AGE:
        if tranche_age == libelle:
            age_min, age_max = bmin, bmax
            break

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
    if wilaya:
        conditions.append("wilaya LIKE ?")
        params.append(f"%{wilaya}%")
    if situation in SITUATIONS:
        conditions.append("situation_familiale LIKE ?")
        params.append(f"%{situation}%")
    if age_min is not None:
        # Unité parenthésée : reste cohérente sous l'opérateur global (AND/OR/NOT).
        if age_max is not None:
            conditions.append("(age >= ? AND age <= ?)")
            params.extend([age_min, age_max])
        else:
            conditions.append("age >= ?")
            params.append(age_min)

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
            "wilaya, situation_familiale, age, "
            "annees_experience, competences, statut "
            f"FROM candidates WHERE {where} "
            "ORDER BY id DESC LIMIT 500"
        )
        with connect() as conn:
            rows = conn.execute(sql, params).fetchall()

    return render(request, "recherche.html", {
        "text_fields": TEXT_FIELDS,
        "valeurs": valeurs,
        "experience": exp_min_raw,
        "wilaya": wilaya,
        "wilayas": wilayas,
        "commune": commune,
        # Mapping wilaya -> communes, sérialisé côté template pour le menu dépendant.
        "communes_by_wilaya": COMMUNES_BY_WILAYA,
        "situation_familiale": situation,
        "situations": SITUATIONS,
        "tranche_age": tranche_age,
        "tranches_age": [t[0] for t in TRANCHES_AGE],
        "operateur": operateur,
        "operateurs": OPERATEURS,
        "rows": rows,
        "aucun_critere": aucun_critere,
        "nb_resultats": len(rows),
    })
