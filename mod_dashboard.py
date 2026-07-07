"""Module « Dashboard RH » : tableau de bord statistique. Routeur isolé.

Toutes les agrégations (SQL + Python) vivent ici — rien n'est ajouté à web_db.
Les requêtes utilisent uniquement le placeholder portable `?`.
"""
from collections import Counter
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Request

from web_core import require_user, render, connect

router = APIRouter()

# Statuts connus (indicateurs de recrutement), dans l'ordre d'affichage.
STATUTS = ["Nouveau", "À contacter", "Entretien planifié",
           "Refusé", "Embauché", "Doublon"]

# Au-delà de ce nombre de catégories, on regroupe le reste dans « Autres ».
TOP_N = 10


def _count_by_column(conn, column: str) -> list[dict]:
    """Compte les candidats groupés par `column`, tri décroissant.

    Regroupe les catégories au-delà de TOP_N dans « Autres ». Les valeurs
    vides / NULL sont ignorées. `column` est une constante interne (jamais
    une entrée utilisateur), donc son interpolation dans le SQL est sûre.
    """
    sql = (
        f"SELECT {column} AS cat, COUNT(*) AS n FROM candidates "
        f"WHERE {column} IS NOT NULL AND TRIM({column}) <> '' "
        f"GROUP BY {column} ORDER BY n DESC, cat ASC"
    )
    rows = [dict(r) for r in conn.execute(sql).fetchall()]
    if len(rows) <= TOP_N:
        return rows
    tete = rows[:TOP_N]
    reste = sum(r["n"] for r in rows[TOP_N:])
    if reste:
        tete.append({"cat": "Autres", "n": reste})
    return tete


def _experience_buckets(conn) -> list[dict]:
    """Répartit les candidats par tranches d'années d'expérience."""
    tranches = [
        ("0", 0, 0),
        ("1-2", 1, 2),
        ("3-5", 3, 5),
        ("6-10", 6, 10),
        ("10+", 11, None),
    ]
    out = []
    for label, lo, hi in tranches:
        if hi is None:
            sql = "SELECT COUNT(*) AS n FROM candidates WHERE annees_experience >= ?"
            params = (lo,)
        else:
            sql = ("SELECT COUNT(*) AS n FROM candidates "
                   "WHERE annees_experience >= ? AND annees_experience <= ?")
            params = (lo, hi)
        n = conn.execute(sql, params).fetchone()["n"]
        out.append({"cat": label, "n": n})
    return out


def _top_competences(conn, limite: int = 15) -> list[dict]:
    """Agrège la colonne `competences` (séparée par virgules) → top N."""
    compteur: Counter = Counter()
    sql = ("SELECT competences FROM candidates "
           "WHERE competences IS NOT NULL AND TRIM(competences) <> ''")
    for r in conn.execute(sql).fetchall():
        for brut in (r["competences"] or "").split(","):
            comp = brut.strip().lower()
            if comp:
                compteur[comp] += 1
    return [{"cat": cat, "n": n} for cat, n in compteur.most_common(limite)]


def _add_pct(items: list[dict]) -> list[dict]:
    """Ajoute une largeur relative (%) à chaque barre, calée sur le max."""
    maxi = max((it["n"] for it in items), default=0)
    for it in items:
        it["pct"] = round(it["n"] * 100 / maxi) if maxi else 0
    return items


@router.get("/dashboard")
def dashboard(request: Request):
    user = require_user(request)

    cutoff = (date.today() - timedelta(days=7)).isoformat()

    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM candidates").fetchone()["n"]
        nouveaux_7j = conn.execute(
            "SELECT COUNT(*) AS n FROM candidates WHERE received_at >= ?",
            (cutoff,),
        ).fetchone()["n"]

        # Compte par statut (dans l'ordre métier, 0 si absent).
        brut_statut = {
            r["statut"]: r["n"]
            for r in conn.execute(
                "SELECT statut, COUNT(*) AS n FROM candidates "
                "WHERE statut IS NOT NULL AND TRIM(statut) <> '' GROUP BY statut"
            ).fetchall()
        }
        par_statut = [{"cat": s, "n": brut_statut.get(s, 0)} for s in STATUTS]

        charts = {
            "specialite": _add_pct(_count_by_column(conn, "specialite")),
            "poste": _add_pct(_count_by_column(conn, "poste_recherche")),
            "wilaya": _add_pct(_count_by_column(conn, "wilaya")),
            "niveau": _add_pct(_count_by_column(conn, "niveau_etude")),
            "experience": _add_pct(_experience_buckets(conn)),
        }
        competences = _add_pct(_top_competences(conn, 15))

        # Activité récente : derniers CV reçus (panneau agenda du tableau de bord).
        recents = [
            dict(r)
            for r in conn.execute(
                "SELECT id, nom, prenom, poste_recherche, statut, received_at "
                "FROM candidates ORDER BY received_at DESC LIMIT 7"
            ).fetchall()
        ]

        # Entretiens à venir : planifiés dont la date n'est pas encore passée.
        maintenant = datetime.now().isoformat(timespec="minutes")
        entretiens = [
            dict(r)
            for r in conn.execute(
                "SELECT e.id AS id, e.date_heure AS date_heure, e.type AS type, "
                "e.lieu AS lieu, e.candidate_id AS candidate_id, "
                "c.nom AS cand_nom, c.prenom AS cand_prenom "
                "FROM entretiens e JOIN candidates c ON c.id = e.candidate_id "
                "WHERE e.statut = 'Planifié' AND e.date_heure >= ? "
                "ORDER BY e.date_heure ASC LIMIT 7",
                (maintenant,),
            ).fetchall()
        ]

    return render(request, "dashboard_stats.html", {
        "total": total,
        "nouveaux_7j": nouveaux_7j,
        "par_statut": par_statut,
        "charts": charts,
        "competences": competences,
        "recents": recents,
        "entretiens": entretiens,
    })
