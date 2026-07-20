"""Journal d'activité par candidat (« Timeline »).

Helper réutilisable pour enregistrer un événement dans la table `candidate_events`
et l'afficher ensuite en frise chronologique sur la fiche candidat.

Deux façons d'appeler :

  * ``log(conn, cid, TYPE, titre, detail)`` — écrit l'événement **dans la
    transaction de l'appelant** (connexion déjà ouverte). À utiliser juste après
    l'action métier (UPDATE de statut, création d'entretien…) pour que l'événement
    soit validé/annulé en même temps qu'elle.

  * ``log_now(cid, TYPE, titre, detail)`` — ouvre **sa propre** connexion et
    valide immédiatement. À utiliser quand il n'y a pas de transaction en cours
    (ex. après un envoi d'email réussi, hors de tout ``with connect()``).

Robustesse : les deux variantes **n'échouent jamais** l'action métier. Une erreur
de journalisation est capturée et tracée dans les logs, mais n'est jamais propagée
à l'appelant. Le simple fait d'écrire un événement ne doit pas empêcher un
changement de statut, la création d'un entretien ou l'envoi d'un email.

Note PostgreSQL : la variante ``log`` partage la transaction de l'appelant. Si son
INSERT échoue, la transaction courante est marquée en erreur côté serveur ; c'est
pourquoi ``log`` isole son écriture dans un SAVEPOINT (bloc ``conn.transaction()``)
quand c'est possible, de sorte qu'un échec de journalisation soit annulé
proprement sans invalider l'action métier déjà exécutée.
"""
from datetime import datetime
import logging

from state_db import connect

log_ = logging.getLogger("cv-agent.activity")

# ─── Constantes de type d'événement ──────────────────────────────────────────
# Réutilisées par les points d'appel (intégrateur) pour garantir des types stables.
RECU = "RECU"            # CV reçu / candidature entrée dans la solution
STATUT = "STATUT"        # Changement de statut candidat (Nouveau, Retenu, Rejeté…)
ETAPE = "ETAPE"          # Changement d'étape du pipeline de recrutement (kanban)
ENTRETIEN = "ENTRETIEN"  # Entretien planifié / mis à jour / statut changé
EMAIL = "EMAIL"          # Email envoyé au candidat
NOTE = "NOTE"            # Note interne RH ajoutée
DOC = "DOC"              # Document / pièce jointe ajouté

# Icône associée à chaque type (utilisée par le template de frise).
ICONES = {
    RECU: "📥",
    STATUT: "🏷️",
    ETAPE: "📊",
    ENTRETIEN: "📅",
    EMAIL: "✉️",
    NOTE: "📝",
    DOC: "📎",
}


def _now() -> str:
    """Horodatage courant (ISO, à la seconde)."""
    return datetime.now().isoformat(timespec="seconds")


def _insert(conn, candidate_id: int, type: str, titre: str, detail: str) -> None:
    """INSERT bas niveau de l'événement (sur la connexion fournie)."""
    conn.execute(
        "INSERT INTO candidate_events "
        "(candidate_id, type, titre, detail, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (candidate_id, (type or "").strip(), (titre or "").strip(),
         (detail or "").strip(), _now()),
    )


def log(conn, candidate_id: int, type: str, titre: str, detail: str = "") -> None:
    """Journalise un événement dans la transaction de l'appelant.

    `conn` est une connexion déjà ouverte (dans un ``with connect() as conn:``).
    L'événement est validé/annulé avec la transaction courante.

    Ne lève jamais : toute erreur est capturée et tracée. Sous PostgreSQL, l'INSERT
    est isolé dans un SAVEPOINT quand la connexion l'expose, afin qu'un échec de
    journalisation n'invalide pas la transaction métier déjà en cours.
    """
    try:
        # Isolation par SAVEPOINT si la connexion sous-jacente l'expose (psycopg).
        # Sinon, insertion directe (l'exception éventuelle reste capturée en aval).
        raw = getattr(conn, "_raw", None)
        tx = getattr(raw, "transaction", None)
        if callable(tx):
            with raw.transaction():
                _insert(conn, candidate_id, type, titre, detail)
        else:
            _insert(conn, candidate_id, type, titre, detail)
    except Exception:  # noqa: BLE001 — la journalisation ne doit jamais casser l'action métier.
        log_.warning(
            "Échec de journalisation d'activité (candidat %s, type %s)",
            candidate_id, type, exc_info=True,
        )


def log_now(candidate_id: int, type: str, titre: str, detail: str = "") -> None:
    """Journalise un événement sur sa propre connexion (commit immédiat).

    À utiliser hors de toute transaction métier. Ne lève jamais.
    """
    try:
        with connect() as conn:
            _insert(conn, candidate_id, type, titre, detail)
    except Exception:  # noqa: BLE001 — la journalisation ne doit jamais casser l'action métier.
        log_.warning(
            "Échec de journalisation d'activité (candidat %s, type %s)",
            candidate_id, type, exc_info=True,
        )
