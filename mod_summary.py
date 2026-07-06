"""Module « Résumé IA » : fiche synthétique générée par LLM. Routeur isolé.

Deux routes, toutes deux renvoyant le fragment `_summary.html` (jamais base.html) :
  - `GET  /candidate/{cid}/resume-ia`          : affiche la fiche stockée ou un
    bouton de génération ;
  - `POST /candidate/{cid}/resume-ia/generate` : appelle le LLM, valide le JSON,
    le stocke dans `candidates.resume_ia`, puis renvoie le fragment à jour.

La colonne `candidates.resume_ia` (TEXT) stocke la chaîne JSON de la fiche.
"""
import json

from fastapi import APIRouter, Request

from web_core import require_user, render, DB_PATH, connect, llm_cfg
import llm_provider

router = APIRouter()


# Clés attendues dans la fiche produite par le LLM.
_CHAMPS_TEXTE = ("resume_pro", "experience_totale", "recommandations")
_CHAMPS_LISTE = ("competences_cles", "forces", "axes_amelioration")

# Colonnes du candidat utilisées pour construire le prompt (+ resume_ia : la fiche
# déjà enregistrée, à réafficher si une régénération échoue plutôt que de la masquer).
_COLONNES = [
    "id", "nom", "prenom", "poste_recherche", "specialite",
    "annees_experience", "diplome_plus_eleve", "niveau_etude", "universite",
    "competences", "logiciels", "soft_skills", "langues", "certifications",
    "entreprises", "experiences_json", "resume", "resume_ia",
]

SYSTEM_PROMPT = (
    "Tu es un assistant RH expert en analyse de CV. À partir des informations "
    "d'un candidat, tu produis une fiche de synthèse professionnelle, concise "
    "et utile pour un recruteur.\n"
    "Tu réponds STRICTEMENT par un objet JSON valide, en FRANÇAIS, sans aucun "
    "texte avant ou après, sans bloc de code Markdown.\n"
    "Le JSON doit contenir EXACTEMENT ces clés :\n"
    '  - "resume_pro" (string) : un paragraphe de synthèse du profil ;\n'
    '  - "experience_totale" (string) : estimation de l\'expérience globale ;\n'
    '  - "competences_cles" (tableau de strings) : compétences majeures ;\n'
    '  - "forces" (tableau de strings) : points forts du candidat ;\n'
    '  - "axes_amelioration" (tableau de strings) : axes de progression ;\n'
    '  - "recommandations" (string) : recommandation RH pour le recrutement.\n'
    "N'invente pas d'informations absentes ; reste factuel."
)


def _fmt(valeur) -> str:
    """Rend une valeur de champ lisible pour le prompt (listes JSON incluses)."""
    if valeur is None:
        return ""
    if isinstance(valeur, (list, dict)):
        return json.dumps(valeur, ensure_ascii=False)
    return str(valeur).strip()


def _construire_prompt(cand: dict) -> str:
    """Assemble le prompt utilisateur à partir des champs du candidat."""
    libelles = [
        ("Nom", "nom"),
        ("Prénom", "prenom"),
        ("Poste recherché", "poste_recherche"),
        ("Spécialité", "specialite"),
        ("Années d'expérience", "annees_experience"),
        ("Diplôme le plus élevé", "diplome_plus_eleve"),
        ("Niveau d'étude", "niveau_etude"),
        ("Université", "universite"),
        ("Compétences", "competences"),
        ("Logiciels", "logiciels"),
        ("Soft skills", "soft_skills"),
        ("Langues", "langues"),
        ("Certifications", "certifications"),
        ("Entreprises", "entreprises"),
        ("Parcours (JSON)", "experiences_json"),
        ("Résumé extrait", "resume"),
    ]
    lignes = []
    for libelle, cle in libelles:
        val = _fmt(cand.get(cle))
        if val:
            lignes.append(f"{libelle} : {val}")
    corps = "\n".join(lignes) if lignes else "Aucune information détaillée."
    return (
        "Voici les informations du candidat :\n\n"
        f"{corps}\n\n"
        "Génère la fiche de synthèse au format JSON demandé."
    )


def _normaliser_fiche(data: dict) -> dict:
    """Valide et normalise le JSON du LLM vers la structure attendue."""
    if not isinstance(data, dict):
        raise ValueError("réponse JSON inattendue (objet attendu)")
    fiche: dict = {}
    for cle in _CHAMPS_TEXTE:
        val = data.get(cle)
        fiche[cle] = _fmt(val) if val is not None else ""
    for cle in _CHAMPS_LISTE:
        val = data.get(cle)
        if isinstance(val, list):
            fiche[cle] = [str(x).strip() for x in val if str(x).strip()]
        elif val:
            fiche[cle] = [_fmt(val)]
        else:
            fiche[cle] = []
    return fiche


def _charger_fiche(brut: str | None) -> dict | None:
    """Décode la fiche JSON stockée, ou None si absente/illisible."""
    if not brut:
        return None
    try:
        return _normaliser_fiche(json.loads(brut))
    except (ValueError, TypeError):
        return None


@router.get("/candidate/{cid}/resume-ia")
def resume_ia(request: Request, cid: int):
    user = require_user(request, DB_PATH)

    with connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, resume_ia FROM candidates WHERE id=?", (cid,)
        ).fetchone()

    if row is None:
        return render(request, "_summary.html", {
            "cid": cid, "fiche": None, "erreur": "Candidat introuvable.",
        })

    fiche = _charger_fiche(row["resume_ia"])
    return render(request, "_summary.html", {"cid": cid, "fiche": fiche})


@router.post("/candidate/{cid}/resume-ia/generate")
def resume_ia_generate(request: Request, cid: int):
    user = require_user(request, DB_PATH)

    with connect(DB_PATH) as conn:
        row = conn.execute(
            f"SELECT {', '.join(_COLONNES)} FROM candidates WHERE id=?", (cid,)
        ).fetchone()

    if row is None:
        return render(request, "_summary.html", {
            "cid": cid, "fiche": None, "erreur": "Candidat introuvable.",
        })

    cand = dict(row)
    fiche_actuelle = _charger_fiche(cand.get("resume_ia"))

    try:
        raw, _ = llm_provider.chat_json(
            llm_cfg(), SYSTEM_PROMPT, _construire_prompt(cand)
        )
        fiche = _normaliser_fiche(json.loads(raw))
    except llm_provider.LLMError:
        return render(request, "_summary.html", {
            "cid": cid, "fiche": fiche_actuelle,
            "erreur": "Le modèle IA n'a pas pu générer la fiche. "
                      "Vérifiez la configuration LLM et réessayez.",
        })
    except (ValueError, TypeError):
        return render(request, "_summary.html", {
            "cid": cid, "fiche": fiche_actuelle,
            "erreur": "La réponse de l'IA n'était pas au format attendu. "
                      "Veuillez réessayer.",
        })

    json_str = json.dumps(fiche, ensure_ascii=False)
    with connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE candidates SET resume_ia=? WHERE id=?", (json_str, cid)
        )

    return render(request, "_summary.html", {"cid": cid, "fiche": fiche})
