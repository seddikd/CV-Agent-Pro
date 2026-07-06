"""CLI entry point — runs one pipeline cycle reading settings from SQLite."""

import argparse
import sys

import app_runtime
app_runtime.force_utf8_streams()

import app_paths
import web_db
import web_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single CV pipeline cycle")
    parser.add_argument("--db", default=str(app_paths.db_path()))
    args = parser.parse_args()

    settings = web_db.get_all_settings(args.db)
    if not settings:
        sys.exit(
            "Aucune configuration trouvée en base. Lance d'abord : python bootstrap.py"
        )

    app_runtime.configure_logging(
        str(app_paths.data_path(settings.get("paths.log_file", "logs/agent.log")))
    )
    result = web_pipeline.run_pipeline(args.db, triggered_by="cli")
    print(result)


if __name__ == "__main__":
    main()
