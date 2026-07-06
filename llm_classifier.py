import json
import logging
from dataclasses import dataclass

import llm_provider


log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es un assistant RH qui détermine si un email reçu contient un CV / une candidature.

Tu reçois : le sujet de l'email, le corps de l'email, et le texte d'une pièce jointe (si présente).

Critères pour répondre is_cv = true :
- Le contenu présente une personne (formation, expériences professionnelles, compétences)
- ET/OU l'email est explicitement une candidature à un poste

Critères pour is_cv = false :
- Newsletter, facture, publicité, message administratif, conversation personnelle
- Pièce jointe technique (devis, fiche produit, rapport non lié à un candidat)
- Email sans pièce jointe pertinente ET sans contenu de candidature dans le corps

Tu réponds STRICTEMENT en JSON avec ces clés :
{
  "is_cv": true | false,
  "confidence": 0.0 à 1.0,
  "reason": "explication courte en français"
}
Aucun texte hors du JSON. Réponds en français ou en anglais selon la langue du contenu."""


@dataclass
class ClassificationResult:
    is_cv: bool
    confidence: float
    reason: str


def classify(
    llm_cfg: dict,
    subject: str,
    body_text: str,
    attachment_text: str,
) -> ClassificationResult:
    user_prompt = (
        f"SUJET DE L'EMAIL :\n{subject}\n\n"
        f"CORPS DE L'EMAIL :\n{body_text[:3000]}\n\n"
        f"PIÈCE JOINTE EXTRAITE :\n{attachment_text[:8000] if attachment_text else '[aucune]'}"
    )

    try:
        raw, _provider = llm_provider.chat_json(llm_cfg, SYSTEM_PROMPT, user_prompt)
    except llm_provider.LLMError as e:
        log.warning("Classifier LLM failed: %s", e)
        return ClassificationResult(False, 0.0, f"llm_error: {e}")

    try:
        data = json.loads(raw)
        return ClassificationResult(
            is_cv=bool(data.get("is_cv", False)),
            confidence=float(data.get("confidence", 0.0)),
            reason=str(data.get("reason", "")),
        )
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        log.warning("Classifier JSON parse failed: %s | raw=%r", e, raw[:300])
        return ClassificationResult(False, 0.0, f"parse_error: {e}")
