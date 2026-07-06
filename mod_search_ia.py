"""Module « Recherche IA » : recherche en langage naturel. Routeur isolé.

L'utilisateur saisit une requête en français courant (ex. « ingénieur réseau
Cisco avec plus de 5 ans d'expérience parlant anglais »). Un LLM la traduit en
filtres structurés, à partir desquels on construit une requête SQL PARAMÉTRÉE
sur la table `candidates`. Aucun appel LLM sur un simple GET.
"""
import json

from fastapi import APIRouter, Request, Form

from web_core import require_user, render, DB_PATH, connect, llm_cfg
import llm_provider

router = APIRouter()

# Le prompt système impose une réponse STRICTEMENT JSON, sans texte autour, et
# décrit chaque champ attendu. « null / [] si non précisé » évite les filtres
# fantômes construits à partir de valeurs inventées.
SYSTEM_PROMPT = (
    "Tu es un assistant de recrutement. On te donne une requête de recherche de "
    "candidats en langage naturel (français). Tu dois la convertir en filtres "
    "structurés et répondre STRICTEMENT par un objet JSON valide, sans aucun "
    "texte avant ou après, respectant EXACTEMENT ce schéma :\n"
    "{\n"
    '  "competences": [string],       // compétences / technologies citées (ex. "Cisco", "Python")\n'
    '  "specialite": string|null,     // domaine de spécialité (ex. "réseau", "data science")\n'
    '  "poste": string|null,          // intitulé de poste recherché (ex. "ingénieur réseau")\n'
    '  "experience_min": number|null, // nombre minimal d\'années d\'expérience\n'
    '  "langues": [string],           // langues parlées exigées (ex. "anglais")\n'
    '  "niveau_etude": string|null,   // niveau d\'étude (ex. "master", "bac+5")\n'
    '  "certifications": [string]      // certifications citées (ex. "CCNA", "PMP")\n'
    "}\n"
    "Règle impérative : mets null pour les champs texte non précisés et [] pour "
    "les listes non précisées. N'invente jamais de valeur non présente dans la requête."
)


def _as_list(val):
    """Normalise une valeur en liste de chaînes non vides (tolère None / scalaire)."""
    if val is None:
        return []
    if not isinstance(val, list):
        val = [val]
    out = []
    for item in val:
        if item is None:
            continue
        s = str(item).strip()
        if s:
            out.append(s)
    return out


def _as_str(val):
    """Normalise une valeur en chaîne non vide ou None."""
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _as_num(val):
    """Normalise une valeur en nombre (int) positif ou None."""
    if val is None or val == "":
        return None
    try:
        n = float(val)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return int(n)


def _normaliser_filtres(data: dict) -> dict:
    """Filtres propres et typés à partir de la réponse (potentiellement bruitée) du LLM."""
    return {
        "competences": _as_list(data.get("competences")),
        "specialite": _as_str(data.get("specialite")),
        "poste": _as_str(data.get("poste")),
        "experience_min": _as_num(data.get("experience_min")),
        "langues": _as_list(data.get("langues")),
        "niveau_etude": _as_str(data.get("niveau_etude")),
        "certifications": _as_list(data.get("certifications")),
    }


def _construire_sql(filtres: dict):
    """(sql, params) paramétré à partir des filtres non vides. Renvoie (None, None) si aucun."""
    conditions = []
    params = []

    # Listes : chaque valeur → LIKE %valeur% sur la colonne (texte séparé par virgules).
    for cle, colonne in (
        ("competences", "competences"),
        ("langues", "langues"),
        ("certifications", "certifications"),
    ):
        for val in filtres[cle]:
            conditions.append(f"{colonne} LIKE ?")
            params.append(f"%{val}%")

    # Champs texte simples.
    for cle, colonne in (
        ("specialite", "specialite"),
        ("poste", "poste_recherche"),
        ("niveau_etude", "niveau_etude"),
    ):
        val = filtres[cle]
        if val:
            conditions.append(f"{colonne} LIKE ?")
            params.append(f"%{val}%")

    # Expérience minimale.
    if filtres["experience_min"] is not None:
        conditions.append("annees_experience >= ?")
        params.append(filtres["experience_min"])

    if not conditions:
        return None, None

    sql = (
        "SELECT id, nom, prenom, email, poste_recherche, specialite, "
        "annees_experience, competences, statut "
        "FROM candidates WHERE " + " AND ".join(conditions) + " "
        "ORDER BY id DESC LIMIT 500"
    )
    return sql, params


@router.get("/recherche-ia")
def recherche_ia(request: Request):
    user = require_user(request, DB_PATH)
    # GET simple : on rend uniquement le formulaire, sans appeler le LLM.
    return render(request, "recherche_ia.html", {
        "q": "",
        "filtres": None,
        "rows": None,
        "erreur": None,
        "nb_resultats": 0,
    })


@router.post("/recherche-ia")
def recherche_ia_post(request: Request, q: str = Form("")):
    user = require_user(request, DB_PATH)

    q = (q or "").strip()
    if not q:
        return render(request, "recherche_ia.html", {
            "q": "",
            "filtres": None,
            "rows": None,
            "erreur": "Saisissez une requête pour lancer la recherche.",
            "nb_resultats": 0,
        })

    # 1) Interprétation LLM : requête libre → filtres JSON structurés.
    try:
        raw, _ = llm_provider.chat_json(llm_cfg(), SYSTEM_PROMPT, q)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise json.JSONDecodeError("objet attendu", raw, 0)
    except llm_provider.LLMError as e:
        return render(request, "recherche_ia.html", {
            "q": q,
            "filtres": None,
            "rows": None,
            "erreur": f"Le service d'IA n'a pas pu interpréter la requête : {e}",
            "nb_resultats": 0,
        })
    except json.JSONDecodeError:
        return render(request, "recherche_ia.html", {
            "q": q,
            "filtres": None,
            "rows": None,
            "erreur": "La réponse de l'IA n'était pas exploitable. Reformulez votre requête.",
            "nb_resultats": 0,
        })

    # 2) Normalisation des filtres.
    filtres = _normaliser_filtres(data)

    # 3) Construction de la requête SQL paramétrée.
    sql, params = _construire_sql(filtres)

    rows = []
    if sql is not None:
        with connect(DB_PATH) as conn:
            rows = conn.execute(sql, params).fetchall()

    # 4) Rendu : filtres interprétés + résultats.
    return render(request, "recherche_ia.html", {
        "q": q,
        "filtres": filtres,
        "aucun_filtre": sql is None,
        "rows": rows,
        "erreur": None,
        "nb_resultats": len(rows),
    })
