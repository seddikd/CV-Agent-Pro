"""Bootstrap de premier lancement : init base, réglages, création du 1er admin.

Idempotent — relançable sans risque. Importe les réglages depuis config.yaml s'il
existe, sinon utilise les défauts ; demande les identifiants admin si aucun n'existe.
Nécessite PostgreSQL (variable CV_AGENT_DB_URL)."""

import getpass
import sys
from pathlib import Path

import app_runtime
app_runtime.force_utf8_streams()  # éviter un crash cp1252 sur ✓/→ pendant l'install

import yaml

import app_paths
import db
import state_db
import web_db
import web_auth


CONFIG_YAML = app_paths.resource("config.yaml")


def seed_from_yaml(yaml_path: Path) -> None:
    """Import IMAP/Ollama config from old config.yaml into DB."""
    if not yaml_path.exists():
        print(f"[i] {yaml_path.name} introuvable, defaults conservés.")
        return
    with yaml_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    items = {}
    imap = cfg.get("imap", {})
    ollama = cfg.get("ollama", {})
    llm = cfg.get("llm", {})
    openrouter = cfg.get("openrouter", {})
    smtp = cfg.get("smtp", {})
    notify = cfg.get("notify", {})
    proc = cfg.get("processing", {})
    paths = cfg.get("paths", {})

    mapping = {
        "imap.host": imap.get("host"),
        "imap.port": imap.get("port"),
        "imap.security": imap.get("security"),
        "imap.user": imap.get("user"),
        "imap.password": imap.get("password"),
        "imap.folder": imap.get("folder"),
        "imap.move_processed": imap.get("move_processed"),
        "imap.move_folder_cv": imap.get("move_folder_cv"),
        "imap.move_folder_non_cv": imap.get("move_folder_non_cv"),
        "llm.provider": llm.get("provider"),
        "ollama.model": ollama.get("model"),
        "ollama.host": ollama.get("host"),
        "ollama.timeout_seconds": ollama.get("timeout_seconds"),
        "openrouter.base_url": openrouter.get("base_url"),
        "openrouter.model": openrouter.get("model"),
        "openrouter.api_key": openrouter.get("api_key"),
        "openrouter.timeout_seconds": openrouter.get("timeout_seconds"),
        "smtp.host": smtp.get("host"),
        "smtp.port": smtp.get("port"),
        "smtp.security": smtp.get("security"),
        "smtp.user": smtp.get("user"),
        "smtp.password": smtp.get("password"),
        "smtp.from": smtp.get("from"),
        "notify.enabled": notify.get("enabled"),
        "notify.recipients": notify.get("recipients"),
        "paths.pdf_storage": paths.get("pdf_storage"),
        "paths.log_file": paths.get("log_file"),
        "processing.max_emails_per_run": proc.get("max_emails_per_run"),
        "processing.classification_confidence_threshold":
            proc.get("classification_confidence_threshold"),
        "processing.pdf_max_chars": proc.get("pdf_max_chars"),
        "processing.fetch_since_days": proc.get("fetch_since_days"),
    }

    for k, v in mapping.items():
        if v is None:
            continue
        # Don't overwrite placeholders
        if isinstance(v, str) and v.startswith("MOT_DE_PASSE"):
            continue
        if isinstance(v, str) and v.startswith("votre.email"):
            continue
        # Un booléen YAML donne True/False en Python ; les réglages booléens sont
        # comparés à la chaîne "true" (settings_to_config), d'où la minuscule —
        # sans quoi `move_processed: true` serait stocké "True" et resterait inactif.
        items[k] = str(v).lower() if isinstance(v, bool) else str(v)

    if items:
        web_db.set_settings(items)
        print(f"[✓] {len(items)} paramètres importés depuis config.yaml")
    else:
        print("[i] Rien à importer depuis config.yaml")


def create_initial_admin() -> None:
    if web_db.admin_count() > 0:
        print("[✓] Compte admin déjà existant.")
        return

    print()
    print("=== Création du compte administrateur initial ===")
    email = input("Email admin : ").strip().lower()
    name = input("Nom complet : ").strip() or email

    while True:
        pwd1 = getpass.getpass("Mot de passe (min 8 chars) : ")
        if len(pwd1) < 8:
            print("Trop court, recommence.")
            continue
        pwd2 = getpass.getpass("Confirmation         : ")
        if pwd1 != pwd2:
            print("Les mots de passe diffèrent, recommence.")
            continue
        break

    if web_db.get_user_by_email(email):
        print(f"[!] {email} existe déjà — abandon de la création.")
        return

    uid = web_db.create_user(
        email, name, web_auth.hash_password(pwd1), role="admin"
    )
    print(f"[✓] Admin créé (id={uid}, email={email})")


def main() -> None:
    print(">>> Bootstrap CV Agent")
    try:
        db.db_url()  # échoue tôt avec un message clair si CV_AGENT_DB_URL manque
    except RuntimeError as e:
        sys.exit(str(e))
    state_db.init()
    web_db.seed_default_settings()
    seed_from_yaml(CONFIG_YAML)
    create_initial_admin()
    print()
    print(">>> Bootstrap terminé.")
    print(">>> Lance ensuite : python -m uvicorn webapp:app --host 0.0.0.0 --port 6060")
    print(">>> Ou simplement : run_web.bat")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Interrompu")
        sys.exit(1)
