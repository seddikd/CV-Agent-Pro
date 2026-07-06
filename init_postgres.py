r"""Provisionne la base PostgreSQL pour un déploiement multi-postes.

À lancer UNE fois, sur le serveur (ou depuis un poste joignant le serveur), après
avoir posé les variables d'environnement :

    $env:CV_AGENT_DB_URL = "postgresql://user:pw@HOTE:5432/cvagent"
    $env:CV_AGENT_SECRET = "<secret partagé, identique sur tous les postes>"
    .\.venv\Scripts\python.exe init_postgres.py

Étapes : crée la base cible si absente -> crée le schéma (tables SERIAL) -> sème
les réglages par défaut. Idempotent : relançable sans risque (ne supprime rien).
L'admin se crée ensuite via la page /setup au premier démarrage de l'application.
"""

from urllib.parse import urlsplit, urlunsplit

import db
import state_db
import web_db


def _create_database_if_missing(url: str) -> str:
    """Crée la base nommée dans l'URL si elle n'existe pas. Retourne son nom."""
    import psycopg

    parts = urlsplit(url)
    dbname = parts.path.lstrip("/")
    if not dbname:
        raise SystemExit("CV_AGENT_DB_URL doit inclure un nom de base (ex. …/cvagent).")

    # On se connecte à la base de maintenance « postgres » pour pouvoir créer la
    # base cible (on ne peut pas créer une base depuis une connexion à elle-même).
    admin_url = urlunsplit(parts._replace(path="/postgres"))
    conn = psycopg.connect(admin_url, autocommit=True)
    try:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
        ).fetchone()
        if exists:
            print(f"Base « {dbname} » déjà présente — conservée.")
        else:
            # dbname provient de l'URL fournie par l'exploitant (identifiant
            # contrôlé, pas une entrée utilisateur) ; on le met entre guillemets.
            conn.execute(f'CREATE DATABASE "{dbname}"')
            print(f"Base « {dbname} » créée.")
    finally:
        conn.close()
    return dbname


def main() -> None:
    if not db.is_postgres():
        raise SystemExit(
            "CV_AGENT_DB_URL non définie : ce script cible PostgreSQL. "
            "Posez-la avant de relancer."
        )

    dbname = _create_database_if_missing(db.db_url())

    # En mode PostgreSQL, le chemin passé à connect()/init() est ignoré (l'URL prime).
    state_db.init("")
    web_db.seed_default_settings("")
    n = len(web_db.get_all_settings(""))

    print(f"Schéma créé + {n} réglages par défaut dans « {dbname} ».")
    print("Prochaine étape : démarrer l'application et créer l'admin via /setup.")


if __name__ == "__main__":
    main()
