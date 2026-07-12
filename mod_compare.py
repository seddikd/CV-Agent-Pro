"""Module « Comparaison de candidats ». Routeur isolé.

Route `GET /comparer` : compare 2 à 5 candidats côte à côte (une colonne
par candidat, une ligne par critère). Sans sélection valide, affiche un
formulaire de choix des candidats (soumis en GET vers `/comparer`).
"""
from fastapi import APIRouter, Request

from web_core import require_user, render, connect

router = APIRouter()

# Nombre de candidats comparables simultanément.
MIN_CANDIDATS = 2
MAX_CANDIDATS = 5

# Critères comparés, regroupés par section (libellé de section, [(libellé, clé)]).
# Le « Nom » n'est plus une ligne : il est porté par l'en-tête de colonne.
CRITERES_GROUPES = [
    ("Profil", [
        ("Poste recherché", "poste_recherche"),
        ("Spécialité", "specialite"),
        ("Wilaya", "wilaya"),
        ("Statut", "statut"),
    ]),
    ("Formation & expérience", [
        ("Niveau d'étude", "niveau_etude"),
        ("Diplôme", "diplome_plus_eleve"),
        ("Années d'expérience", "annees_experience"),
    ]),
    ("Compétences & atouts", [
        ("Compétences", "competences"),
        ("Langues", "langues"),
        ("Soft skills", "soft_skills"),
        ("Certifications", "certifications"),
    ]),
    ("Conditions", [
        ("Disponibilité", "disponibilite"),
        ("Salaire souhaité", "salaire_souhaite"),
    ]),
]

# Champs rendus sous forme de « puces » (valeurs séparées par virgule / point-virgule).
CHIP_FIELDS = ["competences", "langues", "soft_skills", "certifications"]


def _tokens(valeur) -> list[str]:
    """Découpe un champ liste en éléments nettoyés (virgule ou point-virgule)."""
    brut = (valeur or "").replace(";", ",")
    return [t.strip() for t in brut.split(",") if t.strip()]

# Colonnes lues en base (celles des critères + identité/clés techniques).
_COLONNES = [
    "id", "nom", "prenom", "poste_recherche", "specialite", "wilaya",
    "niveau_etude", "diplome_plus_eleve", "annees_experience", "competences",
    "langues", "soft_skills", "certifications", "disponibilite",
    "salaire_souhaite", "statut",
]


def _parse_ids(request: Request) -> list[int]:
    """Extrait les ids depuis la query string.

    Accepte `?ids=1,2,3` comme `?ids=1&ids=2`. Ignore les valeurs invalides
    et les doublons, en préservant l'ordre d'apparition.
    """
    ids: list[int] = []
    seen: set[int] = set()
    for brut in request.query_params.getlist("ids"):
        for morceau in brut.split(","):
            morceau = morceau.strip()
            if not morceau:
                continue
            try:
                cid = int(morceau)
            except ValueError:
                continue
            if cid not in seen:
                seen.add(cid)
                ids.append(cid)
    return ids


@router.get("/comparer")
def comparer(request: Request):
    user = require_user(request)

    ids = _parse_ids(request)[:MAX_CANDIDATS]
    # `?edit=1` force l'écran de sélection même avec une sélection valide, en la
    # pré-cochant → « Modifier la sélection » sans repartir de zéro.
    edit = request.query_params.get("edit") in ("1", "true", "oui")

    with connect() as conn:
        # NB : on passe par conn.execute(...) (jamais conn.cursor(), non exposé par
        # l'adaptateur PostgreSQL de db.py) pour rester portable SQLite/PostgreSQL.
        candidats: list[dict] = []
        if len(ids) >= MIN_CANDIDATS:
            placeholders = ", ".join("?" for _ in ids)
            rows = conn.execute(
                f"SELECT {', '.join(_COLONNES)} FROM candidates "
                f"WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
            par_id = {row["id"]: dict(row) for row in rows}
            # Respecte l'ordre demandé et ignore les ids absents en base.
            for cid in ids:
                if cid in par_id:
                    candidats.append(par_id[cid])

        if len(candidats) >= MIN_CANDIDATS and not edit:
            # Champ dérivé « Prénom Nom » pour la ligne « Nom ».
            for c in candidats:
                nom_complet = " ".join(
                    p for p in ((c.get("prenom") or "").strip(),
                                (c.get("nom") or "").strip()) if p
                )
                c["nom_complet"] = nom_complet or None

            # Meilleure valeur d'expérience (max) → surlignage.
            vals = {
                c["id"]: c["annees_experience"]
                for c in candidats
                if isinstance(c.get("annees_experience"), int)
            }
            best_exp_ids: list[int] = []
            if vals:
                maxi = max(vals.values())
                best_exp_ids = [cid for cid, v in vals.items() if v == maxi]

            # Éléments COMMUNS à tous les candidats, par champ « puces » (intersection
            # normalisée en minuscules) → mis en valeur dans le tableau. On stocke les
            # formes normalisées ; le gabarit compare chaque puce en minuscules.
            communs: dict[str, list[str]] = {}
            for champ in CHIP_FIELDS:
                ensembles = [{t.lower() for t in _tokens(c.get(champ))} for c in candidats]
                inter = set.intersection(*ensembles) if ensembles else set()
                communs[champ] = sorted(inter)

            return render(request, "compare.html", {
                "candidats": candidats,
                "criteres_groupes": CRITERES_GROUPES,
                "chip_fields": CHIP_FIELDS,
                "communs": communs,
                "best_exp_ids": best_exp_ids,
                "min_candidats": MIN_CANDIDATS,
                "max_candidats": MAX_CANDIDATS,
            })

        # Pas assez de candidats valides → formulaire de sélection.
        rows = conn.execute(
            "SELECT id, nom, prenom, poste_recherche FROM candidates "
            "ORDER BY LOWER(nom), LOWER(prenom)"
        ).fetchall()
        tous = [dict(row) for row in rows]

    return render(request, "compare.html", {
        "candidats": None,
        "tous": tous,
        "selection": ids,
        "min_candidats": MIN_CANDIDATS,
        "max_candidats": MAX_CANDIDATS,
    })
