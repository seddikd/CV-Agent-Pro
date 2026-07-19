"""Cœur du scoring de correspondance offre↔candidat (logique pure, sans web).

Extrait ici pour être réutilisé SANS dépendance à FastAPI : le routeur
`mod_matching` (interface) ET le moteur d'alertes `alerts_engine` (appelé depuis
le pipeline / la CLI) l'importent tous les deux. 100 % déterministe, aucun LLM.
"""
import re
import unicodedata


# Mots vides / bruit ignorés dans le titre d'offre : sans valeur discriminante
# (articles, mentions H/F, niveaux de séniorité…). Normalisés (sans accents).
# On y range aussi les intitulés de métier trop génériques comme « ingénieur » :
# seuls ils matcheraient toutes les spécialités (ex. un ingénieur mécanique
# ressortirait sur une offre de génie civil). Le filtre doit porter sur la
# spécialité (« génie civil »), pas sur le mot « ingénieur ».
_MOTS_VIDES = {
    "de", "du", "des", "le", "la", "les", "un", "une", "et", "ou", "en",
    "au", "aux", "pour", "avec", "sur", "dans", "par", "chez", "sous",
    "hf", "fh", "junior", "senior", "confirme", "confirmee", "debutant",
    "stage", "stagiaire", "alternance", "cdd", "cdi", "poste",
    # Intitulés de métier génériques (à discriminer par la spécialité).
    "ingenieur", "ingenieure", "ingenieurs", "ingenieures",
    "technicien", "technicienne", "techniciens", "techniciennes",
    "agent", "agente", "agents", "agentes",
    "responsable", "responsables",
    "assistant", "assistante", "assistants", "assistantes",
}


def _normaliser(texte) -> str:
    """Minuscule + suppression des accents (comparaison souple, robuste)."""
    if not texte:
        return ""
    txt = unicodedata.normalize("NFKD", str(texte))
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return txt.lower()


def _tokens_titre(titre: str) -> list[str]:
    """Mots significatifs d'un titre d'offre.

    ≥ 3 caractères, hors mots vides et mentions de type « (H/F) ». Sert de base
    au test de pertinence : ce sont les mots que l'on recherche chez le candidat.
    """
    mots = re.findall(r"[a-z0-9]+", _normaliser(titre))
    return [m for m in mots if len(m) >= 3 and m not in _MOTS_VIDES]


def titre_pertinent(job: dict, cand: dict) -> bool:
    """Vrai si le titre de l'offre a un rapport réel avec le candidat.

    Le titre de l'offre doit apparaître :
      - **partiellement** (≥ 2 mots significatifs) dans le diplôme du candidat, OU
      - **totalement** (tous ses mots) dans l'expérience professionnelle, OU
      - **partiellement** (≥ 2 mots) dans le résumé du candidat.

    Le seuil de 2 mots évite les faux positifs d'un mot isolé et ambigu (ex.
    « civil » du titre qui matcherait « état civil » dans un résumé). Si le titre
    ne compte qu'un seul mot significatif, le seuil retombe à 1 (sinon aucune
    correspondance ne serait possible). Écarte les profils sans rapport avec
    l'offre ; un titre sans mot exploitable (vide, « (H/F) »…) n'applique aucun
    filtre (tous les candidats restent éligibles).
    """
    tokens = _tokens_titre(job.get("titre") or "")
    if not tokens:
        return True  # titre non discriminant -> pas de filtrage

    # Nombre de mots du titre exigés pour une correspondance « partielle » : 2,
    # ou moins si le titre est plus court (au minimum 1).
    seuil = min(2, len(tokens))

    diplome = _normaliser(cand.get("diplome_plus_eleve"))
    experience = _normaliser(
        " ".join(v for v in (cand.get("experiences_json"),
                             cand.get("entreprises")) if v)
    )
    resume = _normaliser(
        " ".join(v for v in (cand.get("resume"), cand.get("resume_ia"),
                             cand.get("poste_recherche"),
                             cand.get("specialite")) if v)
    )

    # Diplôme : correspondance partielle (≥ seuil mots distincts du titre).
    if sum(1 for tok in tokens if tok in diplome) >= seuil:
        return True
    # Expérience professionnelle : correspondance totale (tous les mots présents).
    if all(tok in experience for tok in tokens):
        return True
    # Résumé : correspondance partielle (≥ seuil mots distincts du titre).
    if sum(1 for tok in tokens if tok in resume) >= seuil:
        return True
    return False


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
