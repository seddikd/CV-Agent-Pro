"""Fonctions pures de calcul du reporting RH (funnel, temps par étape, KPI).

Aucune route ici : ce module ne fait que des agrégations, réutilisables aussi
bien par la page web (`mod_reporting`) que par l'email hebdomadaire
(`reporting_email`). Toutes les requêtes utilisent le placeholder portable `?`.

Les doublons (`duplicate_of` non nul) sont exclus PARTOUT : un profil fusionné
ne doit jamais gonfler les indicateurs.

Dépendance DOUCE à `candidate_events` (fonctionnalité Timeline) : `temps_par_etape`
n'exige pas cette table. Si elle n'existe pas encore, la fonction dégrade
proprement (renvoie une liste vide + un indicateur « données insuffisantes »)
au lieu de lever une erreur.
"""
from datetime import datetime

from state_db import connect
# On réutilise la liste canonique des étapes du pipeline (source unique de vérité).
from mod_pipeline import ETAPES

# Étape finale « embauché » du pipeline (repère pour les KPI et le funnel).
ETAPE_EMBAUCHE = "Embauché"


def _parse_iso(valeur: str):
    """Parse une date ISO en `datetime`, ou None si illisible/vide."""
    if not valeur:
        return None
    try:
        return datetime.fromisoformat(valeur)
    except (ValueError, TypeError):
        return None


def _table_existe(conn, table: str) -> bool:
    """True si la table existe (introspection `information_schema`, portable PG)."""
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
        (table,),
    ).fetchone()
    return row is not None


# ─── Funnel de conversion ────────────────────────────────────────────────────

def funnel(conn=None) -> dict:
    """Funnel du pipeline : nombre de candidats par étape + taux de conversion.

    Pour chaque étape de `mod_pipeline.ETAPES`, compte les candidats actuellement
    positionnés sur cette étape (`stage`), doublons exclus. Ajoute, entre deux
    étapes consécutives, le taux de conversion = effectif de l'étape / effectif
    de l'étape précédente (en %). La première étape n'a pas de taux (`None`).

    Renvoie un dict prêt pour le rendu :
      {
        "steps": [ {"etape", "count", "taux", "pct"} , ... ],
        "total": <somme des effectifs de toutes les étapes>,
        "max_count": <effectif le plus élevé, pour la largeur des barres>,
      }
    `pct` = largeur relative de la barre (effectif / max_count), pour un rendu CSS.
    """
    if conn is None:
        with connect() as c:
            return funnel(c)

    # Comptage groupé en une requête, puis projection sur l'ordre des étapes.
    bruts = {
        r["stage"]: int(r["n"])
        for r in conn.execute(
            "SELECT stage, COUNT(*) AS n FROM candidates "
            "WHERE duplicate_of IS NULL AND stage IS NOT NULL "
            "GROUP BY stage"
        ).fetchall()
    }

    counts = [bruts.get(etape, 0) for etape in ETAPES]
    max_count = max(counts) if counts else 0

    steps = []
    for i, etape in enumerate(ETAPES):
        count = counts[i]
        if i == 0:
            taux = None
        else:
            precedent = counts[i - 1]
            taux = round(count * 100 / precedent, 1) if precedent else None
        pct = round(count * 100 / max_count) if max_count else 0
        steps.append({"etape": etape, "count": count, "taux": taux, "pct": pct})

    return {"steps": steps, "total": sum(counts), "max_count": max_count}


# ─── Temps moyen passé par étape (dépend de candidate_events) ─────────────────

def temps_par_etape(conn=None) -> dict:
    """Durée moyenne passée par étape, calculée depuis l'historique `candidate_events`.

    Contrat (fonctionnalité Timeline) : la table `candidate_events` porte, pour
    chaque changement d'étape, une ligne de `type = 'ETAPE'` avec :
      - `candidate_id` : le candidat concerné,
      - `valeur`       : le NOM de l'étape prise à cet instant,
      - `created_at`   : l'horodatage ISO de l'événement.
    La durée passée sur une étape = intervalle entre l'événement qui l'a prise et
    l'événement d'étape SUIVANT du même candidat ; on la rattache à l'étape de
    départ. On moyenne ensuite par étape.

    Dégradation propre : si la table n'existe pas encore (Timeline non déployée)
    ou en cas d'anomalie de schéma, renvoie `disponible = False` + une liste vide
    et un message, sans jamais lever d'erreur.

    Renvoie :
      {
        "disponible": bool,
        "message": str,          # explication si indisponible
        "lignes": [ {"etape", "n", "duree_jours", "duree_txt", "pct"} , ... ],
      }
    """
    if conn is None:
        with connect() as c:
            return temps_par_etape(c)

    indispo = {
        "disponible": False,
        "lignes": [],
        "message": (
            "Données insuffisantes : l'historique des étapes (Timeline / table "
            "candidate_events) n'est pas encore disponible."
        ),
    }

    try:
        if not _table_existe(conn, "candidate_events"):
            return indispo

        # La Timeline stocke le nom brut de l'étape dans la colonne `detail`
        # (cf. mod_pipeline.changer_etape : activity.log(..., ETAPE, titre, detail=stage)).
        rows = conn.execute(
            "SELECT candidate_id, detail AS valeur, created_at FROM candidate_events "
            "WHERE type = ? ORDER BY candidate_id ASC, created_at ASC",
            ("ETAPE",),
        ).fetchall()
    except Exception:  # noqa: BLE001 - schéma différent / table absente : on dégrade
        return indispo

    # Cumul des durées par étape de départ.
    total_sec: dict[str, float] = {e: 0.0 for e in ETAPES}
    nb: dict[str, int] = {e: 0 for e in ETAPES}

    evenements: dict[int, list[tuple]] = {}
    for r in rows:
        cid = r["candidate_id"]
        t = _parse_iso(r["created_at"])
        if t is None:
            continue
        evenements.setdefault(cid, []).append((t, r["valeur"]))

    for suite in evenements.values():
        # Déjà triés par la requête, mais on re-trie par sécurité (robustesse).
        suite.sort(key=lambda x: x[0])
        for i in range(len(suite) - 1):
            t_debut, etape = suite[i]
            t_fin, _ = suite[i + 1]
            if etape not in total_sec:
                continue  # étape hors référentiel courant : ignorée
            duree = (t_fin - t_debut).total_seconds()
            if duree < 0:
                continue
            total_sec[etape] += duree
            nb[etape] += 1

    lignes = []
    for etape in ETAPES:
        if nb[etape] == 0:
            continue
        moyenne_sec = total_sec[etape] / nb[etape]
        jours = moyenne_sec / 86400
        if jours >= 1:
            duree_txt = f"{jours:.1f} j"
        else:
            duree_txt = f"{moyenne_sec / 3600:.1f} h"
        lignes.append({
            "etape": etape,
            "n": nb[etape],
            "duree_jours": round(jours, 2),
            "duree_txt": duree_txt,
        })

    if not lignes:
        return {
            "disponible": False,
            "lignes": [],
            "message": (
                "Aucune transition d'étape enregistrée pour l'instant : le temps "
                "moyen par étape apparaîtra après quelques mouvements dans le pipeline."
            ),
        }

    # Largeur relative des barres, calée sur la durée la plus longue.
    maxi = max(l["duree_jours"] for l in lignes)
    for l in lignes:
        l["pct"] = round(l["duree_jours"] * 100 / maxi) if maxi else 0

    return {"disponible": True, "lignes": lignes, "message": ""}


# ─── KPI globaux ─────────────────────────────────────────────────────────────

def kpis(conn=None) -> dict:
    """Indicateurs clés : total candidats, embauchés, time-to-hire moyen.

    - `total`   : candidats hors doublons (`duplicate_of IS NULL`).
    - `embauches` : candidats hors doublons considérés embauchés, c.-à-d. étape
      pipeline `stage = 'Embauché'` OU statut RH `statut = 'Embauché'` (les deux
      circuits de suivi sont pris en compte).
    - `time_to_hire_jours` : durée moyenne (jours) entre `received_at` (réception
      du CV) et `updated_at` (dernière mise à jour ≈ décision) des embauchés ;
      `None` si aucun embauché exploitable.
    - `taux_embauche` : embauches / total (en %).

    Renvoie :
      {"total", "embauches", "time_to_hire_jours", "time_to_hire_txt", "taux_embauche"}
    """
    if conn is None:
        with connect() as c:
            return kpis(c)

    total = int(conn.execute(
        "SELECT COUNT(*) AS n FROM candidates WHERE duplicate_of IS NULL"
    ).fetchone()["n"])

    embauches = int(conn.execute(
        "SELECT COUNT(*) AS n FROM candidates "
        "WHERE duplicate_of IS NULL AND (stage = ? OR statut = ?)",
        (ETAPE_EMBAUCHE, "Embauché"),
    ).fetchone()["n"])

    # Time-to-hire : moyenne (received_at -> updated_at) des embauchés exploitables.
    rows = conn.execute(
        "SELECT received_at, updated_at FROM candidates "
        "WHERE duplicate_of IS NULL AND (stage = ? OR statut = ?)",
        (ETAPE_EMBAUCHE, "Embauché"),
    ).fetchall()
    durees: list[float] = []
    for r in rows:
        debut, fin = _parse_iso(r["received_at"]), _parse_iso(r["updated_at"])
        if debut is None or fin is None:
            continue
        jours = (fin - debut).total_seconds() / 86400
        if jours >= 0:
            durees.append(jours)
    time_to_hire = sum(durees) / len(durees) if durees else None

    return {
        "total": total,
        "embauches": embauches,
        "time_to_hire_jours": round(time_to_hire, 1) if time_to_hire is not None else None,
        "time_to_hire_txt": f"{time_to_hire:.1f}" if time_to_hire is not None else "N/A",
        "taux_embauche": round(embauches * 100 / total, 1) if total else 0,
    }
