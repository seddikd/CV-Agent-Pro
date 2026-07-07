"""Point d'entrée CLI — exécute un seul cycle du pipeline (réglages lus en base).

La base est PostgreSQL, définie par CV_AGENT_DB_URL (obligatoire)."""

import sys

import app_runtime
app_runtime.force_utf8_streams()

import app_paths
import db
import web_db
import web_pipeline


def main() -> None:
    try:
        db.db_url()  # échoue tôt avec un message clair si CV_AGENT_DB_URL manque
    except RuntimeError as e:
        sys.exit(str(e))

    settings = web_db.get_all_settings()
    if not settings:
        sys.exit(
            "Aucune configuration trouvée en base. Lance d'abord : python bootstrap.py"
        )

    app_runtime.configure_logging(
        str(app_paths.data_path(settings.get("paths.log_file", "logs/agent.log")))
    )
    result = web_pipeline.run_pipeline(triggered_by="cli")
    print(result)


if __name__ == "__main__":
    main()
