"""Accès LLM unifié avec choix du fournisseur.

Le fournisseur est choisi par configuration (`llm.provider`), selon la machine :
  - "ollama"     : modèle local (PC performant, gratuit, données en local)
  - "openrouter" : API cloud COMPATIBLE OPENAI. L'URL de base est configurable, donc
    fonctionne avec OpenRouter, Google Gemini, OpenAI, Groq, Together, vLLM local…

`chat_json()` renvoie une chaîne JSON valide (ou lève LLMError)."""

import json
import logging

import ollama
import requests


log = logging.getLogger("cv_agent.llm")

DEFAULT_CLOUD_BASE = "https://openrouter.ai/api/v1"

# Endpoint public (sans clé) listant tous les modèles cloud OpenRouter.
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def list_cloud_models(timeout: int = 15) -> list[str]:
    """Récupère les identifiants de TOUS les modèles cloud d'OpenRouter (tri alpha).

    OpenRouter agrège les modèles cloud de nombreux fournisseurs (OpenAI, Google,
    Anthropic, Mistral, Meta…). L'appel ne nécessite pas de clé API. Lève
    `requests.RequestException` si le réseau échoue (l'appelant retombe alors sur
    la liste figée intégrée à l'UI).
    """
    r = requests.get(OPENROUTER_MODELS_URL, timeout=timeout)
    r.raise_for_status()
    modeles = [m.get("id") for m in r.json().get("data", []) if m.get("id")]
    return sorted(set(modeles))


def _cloud_url(orc: dict) -> str:
    """URL /chat/completions à partir de l'URL de base configurée."""
    base = (orc.get("base_url") or DEFAULT_CLOUD_BASE).rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


class LLMError(Exception):
    """Le fournisseur LLM n'a pas produit de JSON valide."""


def _ollama_chat(oc: dict, system: str, user: str) -> str:
    client = ollama.Client(host=oc["host"], timeout=oc["timeout"])
    resp = client.chat(
        model=oc["model"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        format="json",
        options={"temperature": 0.1},
    )
    return resp["message"]["content"]


def _openrouter_chat(orc: dict, system: str, user: str) -> str:
    if not orc.get("api_key"):
        raise LLMError("openrouter: clé API manquante (llm.provider=openrouter)")
    headers = {
        "Authorization": f"Bearer {orc['api_key']}",
        "Content-Type": "application/json",
        # En-têtes de classement OpenRouter (optionnels, sans impact fonctionnel).
        "HTTP-Referer": "https://localhost",
        "X-Title": "cv-agent",
    }
    payload = {
        "model": orc["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    # Beaucoup de modèles :free ne supportent pas response_format=json_object et
    # renvoient une erreur. On réessaie alors SANS (le prompt système impose déjà
    # du JSON), pour éviter un échec silencieux sur tous les emails.
    url = _cloud_url(orc)
    for attempt in (payload, {k: v for k, v in payload.items() if k != "response_format"}):
        r = requests.post(
            url, headers=headers, json=attempt, timeout=orc["timeout"]
        )
        if r.status_code in (400, 404, 422) and "response_format" in attempt:
            continue  # modèle sans support JSON structuré -> retry sans
        r.raise_for_status()
        content = r.json()["choices"][0]["message"].get("content")
        if content is None:
            raise LLMError("openrouter: réponse sans contenu (refus / tool-call ?)")
        return content
    raise LLMError("openrouter: échec (response_format non supporté)")


def check_ollama(oc: dict) -> tuple[bool, str]:
    """Test Ollama : serveur joignable ET modèle configuré installé. (ok, message)."""
    host = (oc.get("host") or "").rstrip("/")
    model = oc.get("model") or ""
    if not host:
        return False, "URL Ollama manquante."
    timeout = min(int(oc.get("timeout", 10) or 10), 10)
    try:
        r = requests.get(host + "/api/tags", timeout=timeout)
    except requests.RequestException as e:
        return False, f"Serveur injoignable ({e}). Ollama est-il démarré / l'URL correcte ?"
    if not r.ok:
        return False, f"Le serveur a répondu HTTP {r.status_code}."
    try:
        installed = [m.get("name", "") for m in r.json().get("models", [])]
    except ValueError:
        return False, "Réponse non-JSON du serveur Ollama."
    if model in installed:
        return True, f"OK — modèle « {model} » disponible."
    liste = ", ".join(installed) if installed else "aucun"
    return False, f"Serveur OK, mais modèle « {model} » absent. Installés : {liste}."


def check_openrouter(orc: dict) -> tuple[bool, str]:
    """Test rapide de l'API OpenRouter. Retourne (ok, message lisible)."""
    if not orc.get("api_key"):
        return False, "Clé API manquante (renseigne-la puis réessaie)."
    model = orc.get("model") or "meta-llama/llama-3.3-70b-instruct:free"
    headers = {
        "Authorization": f"Bearer {orc['api_key']}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://localhost",
        "X-Title": "cv-agent",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    timeout = min(int(orc.get("timeout", 30) or 30), 30)
    try:
        r = requests.post(_cloud_url(orc), headers=headers, json=payload, timeout=timeout)
    except requests.Timeout:
        return False, "Délai dépassé — serveur injoignable ?"
    except requests.RequestException as e:
        return False, f"Erreur réseau : {e}"

    if r.status_code == 401:
        return False, "Clé API invalide (401)."
    if r.status_code == 402:
        return False, "Crédits insuffisants (402)."
    if r.status_code == 429:
        return False, "Limite de débit atteinte (429) — clé OK mais quota temporaire dépassé."
    if r.status_code == 404:
        return False, f"Modèle introuvable : {model} (404)."
    if not r.ok:
        detail = ""
        try:
            err = r.json().get("error")
            detail = err.get("message") if isinstance(err, dict) else str(err or "")
        except (ValueError, AttributeError):
            pass
        return False, f"Erreur HTTP {r.status_code}" + (f" : {detail[:140]}" if detail else ".")
    try:
        data = r.json()
    except ValueError:
        apercu = (r.text or "").strip().replace("\n", " ")[:120]
        url = _cloud_url(orc)
        return (
            False,
            "Réponse non-JSON du serveur. Vérifiez l'URL de base API "
            f"(appel testé : {url}). Pour AgentRouter, utilisez "
            "https://agentrouter.org/v1 ou https://co.agentrouter.org/v1. "
            + (f"Aperçu : {apercu}" if apercu else ""),
        )
    if data.get("choices"):
        return True, f"OK — modèle « {model} » accessible."
    if data.get("error"):
        return False, f"Erreur : {data['error'].get('message', data['error'])}"
    return False, "Réponse inattendue du serveur."


def chat_json(llm_cfg: dict, system: str, user: str) -> tuple[str, str]:
    """Interroge le fournisseur configuré. Retourne (json_brut, fournisseur).

    Lève LLMError si le fournisseur échoue ou renvoie du JSON invalide."""
    provider = llm_cfg.get("provider", "ollama")

    try:
        if provider == "openrouter":
            raw = _openrouter_chat(llm_cfg["openrouter"], system, user)
        else:
            raw = _ollama_chat(llm_cfg["ollama"], system, user)
    except LLMError:
        raise
    except Exception as e:
        raise LLMError(f"{provider}: échec de l'appel ({e})") from e

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        raise LLMError(f"{provider}: JSON invalide ({e})") from e
    # Le contrat attend un OBJET JSON : un tableau/scalaire ferait planter
    # data.get(...) chez l'appelant. On le transforme en LLMError géré.
    if not isinstance(parsed, dict):
        raise LLMError(f"{provider}: JSON n'est pas un objet ({type(parsed).__name__})")

    return raw, provider
