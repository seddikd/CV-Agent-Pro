"""Module « Statistiques RH » : indicateurs de recrutement. Routeur isolé.

Toutes les agrégations (SQL + Python) vivent ici — rien n'est ajouté à web_db.
Les requêtes utilisent uniquement le placeholder portable `?`. Les regroupements
par mois se font en Python (découpe de la chaîne ISO `received_at`) pour rester
portable SQLite/PostgreSQL.
"""
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Request

from web_core import require_user, render, connect

router = APIRouter()

# Statuts connus, dans l'ordre d'affichage métier.
STATUTS = ["Nouveau", "À contacter", "Entretien planifié",
           "Refusé", "Embauché", "Doublon"]

# Regroupements « top N ».
TOP_POSTES = 10
TOP_COMPETENCES = 15
# Nombre de mois affichés dans l'évolution mensuelle.
MOIS_FENETRE = 12


def _add_pct(items: list[dict]) -> list[dict]:
    """Ajoute une largeur relative (%) à chaque barre, calée sur le max."""
    maxi = max((it["n"] for it in items), default=0)
    for it in items:
        it["pct"] = round(it["n"] * 100 / maxi) if maxi else 0
    return items


def _compte_par_statut(conn) -> dict[str, int]:
    """Compte les candidats par statut (dict statut → nombre)."""
    return {
        r["statut"]: r["n"]
        for r in conn.execute(
            "SELECT statut, COUNT(*) AS n FROM candidates "
            "WHERE statut IS NOT NULL AND TRIM(statut) <> '' GROUP BY statut"
        ).fetchall()
    }


def temps_moyen_recrutement(conn) -> float | None:
    """Durée moyenne (jours) entre `created_at` et `updated_at` des embauchés.

    Parse les dates ISO en Python ; ignore les valeurs illisibles ou négatives.
    Renvoie `None` si aucun embauché exploitable.
    """
    rows = conn.execute(
        "SELECT created_at, updated_at FROM candidates WHERE statut = ?",
        ("Embauché",),
    ).fetchall()
    durees: list[float] = []
    for r in rows:
        debut, fin = r["created_at"], r["updated_at"]
        if not debut or not fin:
            continue
        try:
            d = datetime.fromisoformat(debut)
            f = datetime.fromisoformat(fin)
        except (ValueError, TypeError):
            continue
        jours = (f - d).total_seconds() / 86400
        if jours >= 0:
            durees.append(jours)
    if not durees:
        return None
    return sum(durees) / len(durees)


def candidats_par_metier(conn, limite: int = TOP_POSTES) -> list[dict]:
    """Compte les candidats par `poste_recherche` : top N + « Autres »."""
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT poste_recherche AS cat, COUNT(*) AS n FROM candidates "
            "WHERE poste_recherche IS NOT NULL AND TRIM(poste_recherche) <> '' "
            "GROUP BY poste_recherche ORDER BY n DESC, cat ASC"
        ).fetchall()
    ]
    if len(rows) <= limite:
        return rows
    tete = rows[:limite]
    reste = sum(r["n"] for r in rows[limite:])
    if reste:
        tete.append({"cat": "Autres", "n": reste})
    return tete


def _mois_precedent(annee: int, mois: int) -> tuple[int, int]:
    """Renvoie (année, mois) du mois précédant (annee, mois)."""
    if mois == 1:
        return annee - 1, 12
    return annee, mois - 1


def evolution_mensuelle(conn, fenetre: int = MOIS_FENETRE) -> list[dict]:
    """Compte les candidatures par mois (« YYYY-MM » de `received_at`).

    Construit une fenêtre continue des `fenetre` derniers mois se terminant au
    mois le plus récent présent dans les données (mois manquants comblés à 0).
    Renvoie une liste vide si aucune date exploitable.
    """
    compteur: Counter = Counter()
    for r in conn.execute(
        "SELECT received_at FROM candidates "
        "WHERE received_at IS NOT NULL AND TRIM(received_at) <> ''"
    ).fetchall():
        cle = (r["received_at"] or "")[:7]  # « YYYY-MM »
        # Validation légère : « AAAA-MM » avec un tiret en position 5.
        if len(cle) == 7 and cle[4] == "-":
            compteur[cle] += 1
    if not compteur:
        return []

    fin = max(compteur)  # mois le plus récent, ordre lexicographique = chrono
    try:
        annee, mois = int(fin[:4]), int(fin[5:7])
    except ValueError:
        return []

    # Génère les `fenetre` mois consécutifs se terminant à (annee, mois).
    labels: list[str] = []
    a, m = annee, mois
    for _ in range(fenetre):
        labels.append(f"{a:04d}-{m:02d}")
        a, m = _mois_precedent(a, m)
    labels.reverse()
    return [{"cat": lab, "n": compteur.get(lab, 0)} for lab in labels]


def competences_recherchees(conn, limite: int = TOP_COMPETENCES) -> list[dict]:
    """Agrège `competences_requises` des offres (séparées par virgules) → top N."""
    compteur: Counter = Counter()
    for r in conn.execute(
        "SELECT competences_requises FROM jobs "
        "WHERE competences_requises IS NOT NULL AND TRIM(competences_requises) <> ''"
    ).fetchall():
        for brut in (r["competences_requises"] or "").split(","):
            comp = brut.strip().lower()
            if comp:
                compteur[comp] += 1
    return [{"cat": cat, "n": n} for cat, n in compteur.most_common(limite)]


@router.get("/statistiques")
def statistiques(request: Request):
    user = require_user(request)

    with connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM candidates"
        ).fetchone()["n"]

        par_statut_brut = _compte_par_statut(conn)
        n_embauche = par_statut_brut.get("Embauché", 0)
        n_refuse = par_statut_brut.get("Refusé", 0)

        temps_moyen = temps_moyen_recrutement(conn)
        par_metier = _add_pct(candidats_par_metier(conn))
        evolution = _add_pct(evolution_mensuelle(conn))
        competences = _add_pct(competences_recherchees(conn))

    par_statut = [{"cat": s, "n": par_statut_brut.get(s, 0)} for s in STATUTS]
    taux_recrutement = round(n_embauche * 100 / total, 1) if total else 0
    taux_refus = round(n_refuse * 100 / total, 1) if total else 0
    temps_moyen_txt = f"{temps_moyen:.1f}" if temps_moyen is not None else "N/A"

    return render(request, "statistiques.html", {
        "total": total,
        "par_statut": par_statut,
        "n_embauche": n_embauche,
        "n_refuse": n_refuse,
        "taux_recrutement": taux_recrutement,
        "taux_refus": taux_refus,
        "temps_moyen_txt": temps_moyen_txt,
        "par_metier": par_metier,
        "evolution": evolution,
        "competences": competences,
    })
