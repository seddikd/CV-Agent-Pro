"""Conformité RGPD : export (portabilité), suppression (effacement) et purge.

Ce module regroupe la logique métier des droits RGPD, indépendamment de l'UI :

  - `export_candidat(cid)`   : dict complet des données d'un candidat (portabilité) ;
  - `supprimer_candidat(cid)`: efface le candidat ET toutes ses lignes liées ;
  - `purger_anciens(mois)`   : efface les candidats trop anciens (rétention) ;
  - `job_purge_rgpd()`       : point d'entrée du job planifié quotidien.

Défensif par construction : certaines tables liées (candidate_events, email_log…)
peuvent ne pas exister selon la version de la base. On teste donc leur présence
via `information_schema` avant d'y toucher, plutôt que de présumer du schéma.
"""
import calendar
import logging
from datetime import datetime
from pathlib import Path

from state_db import connect
import web_db

log = logging.getLogger("cv_agent.rgpd")


# Tables liées à un candidat, purgées lors d'une suppression (table, colonne FK).
# L'ordre place les dépendances AVANT la ligne candidate finale. Chaque table est
# vérifiée à l'exécution : une table absente est simplement ignorée (défensif).
_TABLES_LIEES: list[tuple[str, str]] = [
    ("candidate_notes", "candidate_id"),
    ("candidate_documents", "candidate_id"),
    ("entretiens", "candidate_id"),
    ("matches", "candidate_id"),
    ("alerts", "candidate_id"),
    ("candidate_events", "candidate_id"),
    ("email_log", "candidate_id"),
]


def _table_existe(conn, table: str) -> bool:
    """True si la table existe dans le schéma courant (défense contre un schéma partiel)."""
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _lignes(conn, table: str, cid: int) -> list[dict]:
    """Renvoie toutes les lignes d'une table liée à `cid` (liste vide si table absente)."""
    if not _table_existe(conn, table):
        return []
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE candidate_id = ? ORDER BY id",
        (cid,),
    ).fetchall()
    return [dict(r) for r in rows]


# ─── Export (droit à la portabilité) ─────────────────────────────────────────

def export_candidat(cid: int) -> dict | None:
    """Assemble toutes les données d'un candidat en un dict sérialisable JSON.

    Regroupe la ligne `candidates` et l'ensemble de ses lignes liées connues
    (notes, documents, entretiens, correspondances, alertes, et — si présentes —
    events et journal d'emails). Renvoie None si le candidat n'existe pas.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM candidates WHERE id = ?", (cid,)
        ).fetchone()
        if row is None:
            return None
        candidat = dict(row)

        export = {
            "exporte_le": datetime.now().isoformat(timespec="seconds"),
            "candidate": candidat,
            "notes": _lignes(conn, "candidate_notes", cid),
            "documents": _lignes(conn, "candidate_documents", cid),
            "entretiens": _lignes(conn, "entretiens", cid),
            "matches": _lignes(conn, "matches", cid),
            "alerts": _lignes(conn, "alerts", cid),
            "candidate_events": _lignes(conn, "candidate_events", cid),
            "email_log": _lignes(conn, "email_log", cid),
        }
    return export


# ─── Suppression (droit à l'effacement) ───────────────────────────────────────

def _fichiers_a_effacer(conn, cid: int) -> list[str]:
    """Chemins disque à supprimer pour ce candidat (CV + pièces jointes).

    On collecte les chemins AVANT de supprimer les lignes, puis on efface les
    fichiers seulement après le commit (voir `supprimer_candidat`)."""
    chemins: list[str] = []
    row = conn.execute(
        "SELECT pdf_path FROM candidates WHERE id = ?", (cid,)
    ).fetchone()
    if row and row["pdf_path"]:
        chemins.append(row["pdf_path"])
    if _table_existe(conn, "candidate_documents"):
        docs = conn.execute(
            "SELECT stored_path FROM candidate_documents WHERE candidate_id = ?",
            (cid,),
        ).fetchall()
        chemins += [d["stored_path"] for d in docs if d["stored_path"]]
    return chemins


def _effacer_en_base(conn, cid: int) -> None:
    """Supprime les lignes liées puis la ligne candidate (dans la transaction ouverte)."""
    for table, col in _TABLES_LIEES:
        if _table_existe(conn, table):
            conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (cid,))
    conn.execute("DELETE FROM candidates WHERE id = ?", (cid,))


def _effacer_fichiers(chemins: list[str]) -> None:
    """Efface les fichiers disque (best effort : ignore les absents / erreurs)."""
    for p in chemins:
        try:
            Path(p).unlink()
        except (FileNotFoundError, OSError):
            pass


def supprimer_candidat(cid: int) -> bool:
    """Efface définitivement un candidat ET toutes ses données liées.

    Tout se fait dans une seule transaction (commit à la sortie du `with`, rollback
    sur erreur). Les fichiers disque associés ne sont supprimés qu'après le commit,
    pour ne pas perdre un fichier si la transaction échoue. Renvoie False si le
    candidat n'existe pas, True après suppression.
    """
    with connect() as conn:
        if conn.execute(
            "SELECT 1 FROM candidates WHERE id = ?", (cid,)
        ).fetchone() is None:
            return False
        chemins = _fichiers_a_effacer(conn, cid)
        _effacer_en_base(conn, cid)
    # Hors transaction : la base est déjà cohérente, on nettoie le disque.
    _effacer_fichiers(chemins)
    log.info("Candidat #%s supprimé (RGPD) — %d fichier(s) associé(s).", cid, len(chemins))
    return True


# ─── Purge par rétention (effacement automatique des anciens) ─────────────────

def _cutoff_iso(mois: int) -> str:
    """Horodatage ISO correspondant à « il y a `mois` mois » (borne de rétention).

    Un candidat reçu/créé AVANT cette borne dépasse la durée de conservation.
    Soustraction de mois calendaires exacte (jour ramené au dernier jour du mois
    cible si nécessaire, ex. 31 mars − 1 mois → 28/29 février)."""
    now = datetime.now()
    total = (now.year * 12 + (now.month - 1)) - mois
    annee, mois_idx = divmod(total, 12)
    m = mois_idx + 1
    jour = min(now.day, calendar.monthrange(annee, m)[1])
    return now.replace(year=annee, month=m, day=jour).isoformat(timespec="seconds")


def _ids_eligibles(conn, mois: int) -> list[int]:
    """Ids des candidats dont received_at/created_at dépasse `mois` mois."""
    cutoff = _cutoff_iso(mois)
    rows = conn.execute(
        "SELECT id FROM candidates "
        "WHERE COALESCE(received_at, created_at) < ? "
        "ORDER BY id",
        (cutoff,),
    ).fetchall()
    return [int(r["id"]) for r in rows]


def compter_eligibles(mois: int) -> int:
    """Nombre de candidats actuellement éligibles à la purge (0 si `mois` <= 0)."""
    if mois <= 0:
        return 0
    with connect() as conn:
        return len(_ids_eligibles(conn, mois))


def purger_anciens(mois: int) -> int:
    """Supprime tous les candidats dépassant `mois` mois de rétention.

    Renvoie le nombre de candidats supprimés. `mois <= 0` désactive la purge
    (aucune suppression, renvoie 0). Chaque candidat éligible est effacé avec ses
    lignes liées et ses fichiers, dans une transaction, puis on nettoie le disque.
    """
    if mois <= 0:
        return 0
    with connect() as conn:
        ids = _ids_eligibles(conn, mois)
        chemins: list[str] = []
        for cid in ids:
            chemins += _fichiers_a_effacer(conn, cid)
            _effacer_en_base(conn, cid)
    _effacer_fichiers(chemins)
    if ids:
        log.info("Purge RGPD : %d candidat(s) supprimé(s) (rétention %d mois).", len(ids), mois)
    return len(ids)


# ─── Job planifié (armé par reschedule_from_settings côté webapp) ─────────────

def job_purge_rgpd() -> None:
    """Job quotidien : si la purge auto est active et une rétention est définie,
    supprime les candidats trop anciens. Best effort : toute erreur est journalisée
    sans jamais faire planter le planificateur."""
    try:
        settings = web_db.get_all_settings()
        if settings.get("rgpd.purge_auto_active", "false").lower() != "true":
            return
        try:
            mois = int(settings.get("rgpd.retention_mois", "0"))
        except (ValueError, TypeError):
            mois = 0
        if mois <= 0:
            return
        n = purger_anciens(mois)
        if n:
            log.info("Job purge RGPD : %d candidat(s) purgé(s).", n)
    except Exception as e:  # noqa: BLE001 - le planificateur ne doit jamais tomber
        log.exception("Job purge RGPD échoué : %s", e)
