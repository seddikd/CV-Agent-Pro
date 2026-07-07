import json
import logging
from dataclasses import dataclass, field

import llm_provider


log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es un assistant RH expert. Tu extrais des informations structurées depuis un CV.

RÈGLES IMPORTANTES :
- Si une information n'est pas trouvable dans le CV, mets null (jamais une valeur inventée).
- Pour les listes, mets une liste vide [] si rien trouvé.
- annees_experience : nombre entier (estime si nécessaire à partir des dates d'expériences ; 0 si étudiant sans expérience).
- specialite : domaine/filière du candidat (ex. « Réseaux & Télécoms », « Développement web », « Comptabilité »).
- niveau_etude : niveau le plus élevé de façon normalisée (ex. « Bac », « Bac+2 », « Licence », « Master », « Doctorat », « Ingénieur »).
- wilaya : wilaya / ville de résidence en Algérie si mentionnée (ex. « Alger », « Oran »), sinon la ville trouvée, sinon null.
- situation_familiale : normalise STRICTEMENT en l'une de ces valeurs si mentionnée : « Célibataire », « Marié(e) », « Divorcé(e) », « Veuf(ve) ». Sinon null.
- date_naissance : date de naissance telle qu'écrite dans le CV (ex. « 12/05/1994 »), sinon null.
- age : âge du candidat en années (entier). Si l'âge n'est pas indiqué mais la date/année de naissance l'est, calcule-le. Sinon null.
- competences_principales : compétences TECHNIQUES (technologies, méthodes métier).
- soft_skills : qualités humaines/comportementales (ex. « travail en équipe », « rigueur »).
- logiciels : outils/logiciels maîtrisés (ex. « AutoCAD », « SAP », « Excel »).
- entreprises : noms des employeurs/entreprises où le candidat a travaillé.
- certifications : certifications/attestations professionnelles obtenues.
- permis : permis de conduire mentionné (ex. « B », « Poids lourd »), sinon null.
- disponibilite : disponibilité déclarée (ex. « Immédiate », « Sous 1 mois »), sinon null.
- salaire_souhaite : prétention salariale si mentionnée (texte brut), sinon null.
- experiences : liste des expériences professionnelles, chacune {"poste","entreprise","duree","description"} (champs manquants = null).
- resume : 2-3 phrases en français présentant le candidat (parcours, profil, atouts).
- Tu réponds STRICTEMENT en JSON valide, sans texte hors JSON.

Schéma JSON exact :
{
  "nom": string | null,
  "prenom": string | null,
  "email": string | null,
  "telephone": string | null,
  "poste_recherche": string | null,
  "specialite": string | null,
  "wilaya": string | null,
  "situation_familiale": string | null,
  "date_naissance": string | null,
  "age": number | null,
  "annees_experience": number | null,
  "diplome_plus_eleve": string | null,
  "niveau_etude": string | null,
  "universite": string | null,
  "competences_principales": [string],
  "soft_skills": [string],
  "logiciels": [string],
  "langues": [string],
  "entreprises": [string],
  "certifications": [string],
  "permis": string | null,
  "disponibilite": string | null,
  "salaire_souhaite": string | null,
  "experiences": [{"poste": string | null, "entreprise": string | null, "duree": string | null, "description": string | null}],
  "resume": string | null
}"""


@dataclass
class ExtractionResult:
    nom: str | None = None
    prenom: str | None = None
    email: str | None = None
    telephone: str | None = None
    poste_recherche: str | None = None
    specialite: str | None = None
    wilaya: str | None = None
    situation_familiale: str | None = None
    date_naissance: str | None = None
    age: int | None = None
    annees_experience: int | None = None
    diplome_plus_eleve: str | None = None
    niveau_etude: str | None = None
    universite: str | None = None
    competences_principales: list[str] = field(default_factory=list)
    soft_skills: list[str] = field(default_factory=list)
    logiciels: list[str] = field(default_factory=list)
    langues: list[str] = field(default_factory=list)
    entreprises: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    permis: str | None = None
    disponibilite: str | None = None
    salaire_souhaite: str | None = None
    experiences: list[dict] = field(default_factory=list)
    resume: str | None = None


def _coerce_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _coerce_list(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if x]
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    return []


def _coerce_experiences(v) -> list[dict]:
    """Normalise la liste d'expériences en dicts {poste,entreprise,duree,description}."""
    if not isinstance(v, list):
        return []
    out = []
    for item in v:
        if isinstance(item, dict):
            out.append({
                "poste": item.get("poste"),
                "entreprise": item.get("entreprise"),
                "duree": item.get("duree"),
                "description": item.get("description"),
            })
        elif item:
            out.append({"poste": None, "entreprise": None, "duree": None,
                        "description": str(item)})
    return out


def extract(
    llm_cfg: dict,
    cv_text: str,
    email_subject: str,
) -> ExtractionResult:
    user_prompt = (
        f"SUJET DE L'EMAIL (peut indiquer le poste visé) :\n{email_subject}\n\n"
        f"TEXTE DU CV :\n{cv_text}"
    )

    try:
        raw, _provider = llm_provider.chat_json(llm_cfg, SYSTEM_PROMPT, user_prompt)
    except llm_provider.LLMError as e:
        log.warning("Extractor LLM failed: %s", e)
        return ExtractionResult()

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        log.warning("Extractor JSON parse failed: %s | raw=%r", e, raw[:300])
        return ExtractionResult()

    return ExtractionResult(
        nom=data.get("nom"),
        prenom=data.get("prenom"),
        email=data.get("email"),
        telephone=data.get("telephone"),
        poste_recherche=data.get("poste_recherche"),
        specialite=data.get("specialite"),
        wilaya=data.get("wilaya"),
        situation_familiale=data.get("situation_familiale"),
        date_naissance=data.get("date_naissance"),
        age=_coerce_int(data.get("age")),
        annees_experience=_coerce_int(data.get("annees_experience")),
        diplome_plus_eleve=data.get("diplome_plus_eleve"),
        niveau_etude=data.get("niveau_etude"),
        universite=data.get("universite"),
        competences_principales=_coerce_list(data.get("competences_principales")),
        soft_skills=_coerce_list(data.get("soft_skills")),
        logiciels=_coerce_list(data.get("logiciels")),
        langues=_coerce_list(data.get("langues")),
        entreprises=_coerce_list(data.get("entreprises")),
        certifications=_coerce_list(data.get("certifications")),
        permis=data.get("permis"),
        disponibilite=data.get("disponibilite"),
        salaire_souhaite=data.get("salaire_souhaite"),
        experiences=_coerce_experiences(data.get("experiences")),
        resume=data.get("resume"),
    )
