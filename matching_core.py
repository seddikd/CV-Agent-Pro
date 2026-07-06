"""Cœur du scoring de correspondance offre↔candidat (logique pure, sans web).

Extrait ici pour être réutilisé SANS dépendance à FastAPI : le routeur
`mod_matching` (interface) ET le moteur d'alertes `alerts_engine` (appelé depuis
le pipeline / la CLI) l'importent tous les deux. 100 % déterministe, aucun LLM.
"""


def split_set(*valeurs) -> set:
    """Union de champs « séparés par virgules » en un set minuscule/strippé."""
    out = set()
    for valeur in valeurs:
        if not valeur:
            continue
        for morceau in str(valeur).split(","):
            morceau = morceau.strip().lower()
            if morceau:
                out.add(morceau)
    return out


def score_candidat(job: dict, cand: dict) -> dict:
    """Calcule le score de correspondance d'un candidat vis-à-vis d'une offre.

    Déterministe, sans LLM. Retourne un dict :
    {"score", "compatibilite", "points_forts", "competences_manquantes"}.
    """
    # Compétences requises par l'offre vs. compétences réelles du candidat.
    requises = split_set(job.get("competences_requises"))
    candidat_comp = split_set(
        cand.get("competences"),
        cand.get("logiciels"),
        cand.get("certifications"),
    )

    if requises:
        inter = requises & candidat_comp
        couverture = len(inter) / len(requises)
        points_forts = sorted(inter)
        competences_manquantes = sorted(requises - candidat_comp)
    else:
        couverture = 1.0
        points_forts = []
        competences_manquantes = []

    # Score expérience : plein si le candidat atteint le minimum requis.
    exp_min = job.get("experience_min")
    try:
        exp_min = int(exp_min) if exp_min not in (None, "") else 0
    except (TypeError, ValueError):
        exp_min = 0
    annees = cand.get("annees_experience")
    try:
        annees = int(annees) if annees not in (None, "") else 0
    except (TypeError, ValueError):
        annees = 0
    if exp_min <= 0 or annees >= exp_min:
        score_experience = 1.0
    else:
        score_experience = annees / exp_min

    # Score niveau d'étude : comparaison souple insensible à la casse.
    niveau_requis = (job.get("niveau_etude") or "").strip().lower()
    niveau_cand = (cand.get("niveau_etude") or "").strip().lower()
    if not niveau_requis:
        score_niveau = 1.0
    elif niveau_cand and niveau_cand == niveau_requis:
        score_niveau = 1.0
    elif niveau_cand:
        score_niveau = 0.5
    else:
        score_niveau = 0.0

    score = round(
        100 * (0.6 * couverture + 0.3 * score_experience + 0.1 * score_niveau)
    )
    return {
        "score": score,
        "compatibilite": score,
        "points_forts": points_forts,
        "competences_manquantes": competences_manquantes,
    }
