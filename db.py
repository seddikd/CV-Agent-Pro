"""Accès base de données — PostgreSQL (unique moteur supporté).

La connexion est définie par la variable d'environnement CV_AGENT_DB_URL, par ex. :

    CV_AGENT_DB_URL="postgresql://cvagent:motdepasse@localhost:5432/cvagent"

Elle est **obligatoire** : sans elle, l'application refuse de démarrer (plus de
repli SQLite). Le déploiement se fait via Docker (image + service PostgreSQL) ou
en pointant la variable vers un serveur PostgreSQL existant.

Convention du projet : toutes les requêtes s'écrivent avec le placeholder « ? »,
traduit en « %s » pour psycopg. Le wrapper `_PgConn` expose l'API minimale
utilisée par state_db/web_db (`conn.execute(...)`, `row["colonne"]`, `commit()`,
`rollback()`, `close()`).
"""

import os
from contextlib import contextmanager


def db_url() -> str:
    """URL PostgreSQL configurée. Lève une erreur explicite si absente."""
    url = os.environ.get("CV_AGENT_DB_URL")
    if not url:
        raise RuntimeError(
            "CV_AGENT_DB_URL n'est pas définie : PostgreSQL est requis. "
            "Exemple : CV_AGENT_DB_URL=postgresql://cvagent:motdepasse@localhost:5432/cvagent"
        )
    return url


def pk() -> str:
    """Fragment DDL de clé primaire auto-incrémentée (PostgreSQL)."""
    return "SERIAL PRIMARY KEY"


# ─── Adaptateur PostgreSQL ───────────────────────────────────────────────────
# psycopg utilise le placeholder « %s » et non « ? » : on traduit la requête et on
# enveloppe la connexion pour offrir l'API minimale attendue par state_db/web_db.

def _translate(sql: str) -> str:
    # psycopg interprète « % » dans le TEXTE de la requête comme un marqueur de
    # format : on double d'abord les « % » littéraux, PUIS on convertit « ? » -> « %s ».
    return sql.replace("%", "%%").replace("?", "%s")


class _PgConn:
    """Enveloppe une connexion psycopg pour l'API sqlite-like utilisée ici."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        return self._raw.execute(_translate(sql), params)

    def executescript(self, script: str):
        # psycopg exécute une commande à la fois : on découpe le script DDL.
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
def connect():
    """Connexion transactionnelle à PostgreSQL (commit à la sortie, rollback sur erreur)."""
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


def insert_returning_id(conn, sql: str, params) -> int:
    """Exécute un INSERT et renvoie l'id généré (via RETURNING id)."""
    cur = conn.execute(sql + " RETURNING id", params)
    return int(cur.fetchone()["id"])
