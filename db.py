"""Abstraction du backend base de données : SQLite (défaut) ou PostgreSQL.

Le backend est choisi par la variable d'environnement CV_AGENT_DB_URL :

    CV_AGENT_DB_URL="postgresql://user:pw@host:5432/cvagent"  -> PostgreSQL
    (absente)                                                 -> SQLite local

But : autoriser une bascule vers PostgreSQL (déploiement centralisé, plusieurs
postes RH sur une même base) SANS régression pour le déploiement local
mono-machine en .exe, qui reste la configuration par défaut, testée et packagée.
On bascule en pointant simplement la variable d'env, sans toucher au code.

Convention du projet : toutes les requêtes s'écrivent avec le placeholder « ? »
(style SQLite). Pour PostgreSQL, l'adaptateur les traduit en « %s » à la volée,
et expose la même interface minimale que sqlite3 (`conn.execute(...)`,
`row["colonne"]`, `commit()`, `close()`) — les couches state_db/web_db restent
ainsi identiques quel que soit le backend.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


# Gabarit de clé primaire auto-incrémentée selon le dialecte. Les autres
# différences de DDL (types, index, contraintes) sont communes aux deux moteurs.
_PK = {
    "sqlite": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "postgres": "SERIAL PRIMARY KEY",
}


def db_url() -> str | None:
    """URL PostgreSQL configurée, ou None (=> SQLite)."""
    return os.environ.get("CV_AGENT_DB_URL") or None


def backend() -> str:
    """« postgres » si CV_AGENT_DB_URL est défini, sinon « sqlite »."""
    return "postgres" if db_url() else "sqlite"


def is_postgres() -> bool:
    return backend() == "postgres"


def pk() -> str:
    """Fragment DDL de clé primaire auto-incrémentée pour le backend courant."""
    return _PK[backend()]


# ─── Adaptateur PostgreSQL ───────────────────────────────────────────────────
# psycopg utilise le placeholder « %s » et non « ? » : on traduit la requête et
# on enveloppe la connexion pour offrir la même API que sqlite3.Connection.

def _translate(sql: str) -> str:
    # psycopg interprète « % » dans le TEXTE de la requête comme un marqueur de
    # format : tout « % » littéral doit être doublé en « %% », sinon erreur dès
    # qu'une requête en contient un (ex. LIKE 'a@%'). On double d'abord les « % »
    # existants, PUIS on convertit les placeholders « ? » en « %s ».
    return sql.replace("%", "%%").replace("?", "%s")


class _PgConn:
    """Enveloppe une connexion psycopg pour imiter l'API sqlite3 utilisée ici."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        return self._raw.execute(_translate(sql), params)

    def executescript(self, script: str):
        # psycopg (protocole étendu) exécute une commande à la fois : on découpe
        # le script DDL en instructions individuelles.
        with self._raw.cursor() as cur:
            for stmt in script.split(";"):
                if stmt.strip():
                    cur.execute(stmt)
        return self

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()


@contextmanager
def connect(db_path: str):
    """Connexion transactionnelle au backend courant.

    `db_path` n'est utilisé qu'en mode SQLite ; en mode PostgreSQL c'est
    CV_AGENT_DB_URL qui prime. La signature reste identique pour ne rien changer
    chez les appelants (state_db/web_db)."""
    if is_postgres():
        import psycopg
        from psycopg.rows import dict_row

        raw = psycopg.connect(db_url(), row_factory=dict_row)
        conn = _PgConn(raw)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def insert_returning_id(conn, sql: str, params) -> int:
    """Exécute un INSERT et renvoie l'id généré, quel que soit le backend.

    PostgreSQL n'a pas de `lastrowid` : on ajoute `RETURNING id`. SQLite
    conserve `lastrowid` (compatibilité avec les versions sans RETURNING)."""
    if is_postgres():
        cur = conn.execute(sql + " RETURNING id", params)
        return int(cur.fetchone()["id"])
    cur = conn.execute(sql, params)
    return int(cur.lastrowid)


def init_dir(db_path: str) -> None:
    """Crée le dossier parent du fichier SQLite (no-op en PostgreSQL)."""
    if not is_postgres():
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
