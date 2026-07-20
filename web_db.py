"""DB helpers for the web app: users, candidates, settings, runs."""

import json
import os
from datetime import datetime
from typing import Any

import app_paths
import db
import secret_store
from state_db import connect


# Réglages contenant un secret : chiffrés au repos (DPAPI). Source unique de
# vérité, importée aussi par webapp pour la logique « ne pas écraser si vide ».
SECRET_SETTING_KEYS = ("imap.password", "openrouter.api_key", "smtp.password")

# Rôles applicatifs (voir la contrainte CHECK sur users.role dans state_db.py).
# admin   : accès total (utilisateurs + réglages système inclus) ;
# manager : tout sauf gestion des utilisateurs et réglages ;
# rh      : gestion des candidats/offres/notes/documents/pipeline ;
# lecture : consultation seule, aucune écriture.
ROLES = ("admin", "manager", "rh", "lecture")


DEFAULT_SETTINGS = {
    "imap.host": "imap.gmail.com",  # exemple ; tout serveur IMAP est accepté
    "imap.port": "993",
    "imap.security": "SSL",  # SSL (993) | STARTTLS (143) | None (143)
    "imap.user": "",
    "imap.password": "",
    "imap.folder": "INBOX",
    "llm.provider": "ollama",  # "ollama" (local) ou "openrouter" (cloud)
    "ollama.model": "qwen2.5:14b",
    "ollama.host": "http://localhost:11434",
    "ollama.timeout_seconds": "600",
    "openrouter.base_url": "https://openrouter.ai/api/v1",
    "openrouter.model": "meta-llama/llama-3.3-70b-instruct:free",
    "openrouter.api_key": "",
    "openrouter.timeout_seconds": "120",
    "smtp.host": "",
    "smtp.port": "587",
    "smtp.security": "TLS",  # SSL | TLS | None
    "smtp.user": "",
    "smtp.password": "",
    "smtp.from": "",
    "notify.enabled": "false",
    "notify.recipients": "",
    "paths.pdf_storage": "cv_pdfs",
    "paths.log_file": "logs/agent.log",
    "processing.max_emails_per_run": "100",
    "processing.classification_confidence_threshold": "0.6",
    "processing.pdf_max_chars": "30000",
    "processing.fetch_since_days": "30",
    "scheduler.interval_minutes": "60",
    "scheduler.enabled": "true",
    # Rappels d'entretien : email automatique X heures avant l'entretien.
    "entretiens.reminder_enabled": "true",
    "entretiens.reminder_hours_before": "24",
    # Import de fichiers Outlook (PST/OST). `import_dir` : dossier serveur où déposer
    # les fichiers (relatif à DATA_DIR ; ex. /data/import en Docker). `backend` :
    # auto | pypff (libpff, multiplateforme) | win32com (Outlook, Windows).
    "outlook.import_dir": "import",
    "outlook.backend": "auto",
    # RGPD : rétention (mois, 0 = désactivé) + purge automatique quotidienne.
    "rgpd.retention_mois": "0",
    "rgpd.purge_auto_active": "false",
    # Reporting : rapport hebdomadaire par email (jour paramétrable).
    "reporting.hebdo_active": "false",
    "reporting.hebdo_jour": "lundi",
}


STATUTS = [
    "Nouveau",
    "À contacter",
    "Entretien planifié",
    "Refusé",
    "Embauché",
    "Doublon",
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def seed_default_settings() -> None:
    with connect() as conn:
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO NOTHING",
                (k, v, _now()),
            )


def get_all_settings() -> dict[str, str]:
    """Renvoie les réglages en clair : les secrets sont déchiffrés à la volée."""
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        out: dict[str, str] = {}
        for r in rows:
            v = r["value"]
            if r["key"] in SECRET_SETTING_KEYS:
                v = secret_store.decrypt(v)
            out[r["key"]] = v
        return out


def set_settings(items: dict[str, str]) -> None:
    now = _now()
    with connect() as conn:
        for k, v in items.items():
            if k in SECRET_SETTING_KEYS:
                v = secret_store.encrypt(v)  # chiffré au repos (no-op si vide)
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (k, v, now),
            )


def migrate_encrypt_secrets() -> int:
    """Chiffre en place les secrets encore stockés en clair (bases créées avant
    l'ajout du chiffrement). Idempotent. Retourne le nombre de secrets migrés."""
    n = 0
    now = _now()
    with connect() as conn:
        for key in SECRET_SETTING_KEYS:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            if not row:
                continue
            raw = row["value"]
            if not raw or secret_store.is_encrypted(raw):
                continue
            enc = secret_store.encrypt(raw)
            if enc != raw:  # chiffrement réellement appliqué (DPAPI disponible)
                conn.execute(
                    "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?",
                    (enc, now, key),
                )
                n += 1
    return n


def _int(settings: dict, key: str, default) -> int:
    """int() tolérant : valeur vide/invalide (champ effacé dans l'UI) -> défaut."""
    try:
        return int(str(settings.get(key, default)).strip())
    except (ValueError, TypeError):
        return int(default)


def _float(settings: dict, key: str, default) -> float:
    try:
        return float(str(settings.get(key, default)).strip())
    except (ValueError, TypeError):
        return float(default)


def settings_to_config(settings: dict[str, str]) -> dict:
    """Reconstruit le dict de config imbriqué (consommé par le pipeline) à plat.

    Accès tolérant via .get(...) avec les valeurs par défaut de DEFAULT_SETTINGS :
    une base à laquelle il manque une clé (base antérieure à l'ajout d'un réglage,
    lancée par `python main.py` qui ne re-sème pas) ne doit pas lever de KeyError.
    """
    return {
        "imap": {
            "host": settings.get("imap.host", DEFAULT_SETTINGS["imap.host"]),
            "port": _int(settings, "imap.port", 993),
            "security": settings.get("imap.security", "SSL"),
            "user": settings.get("imap.user", ""),
            "password": settings.get("imap.password", ""),
            "folder": settings.get("imap.folder", DEFAULT_SETTINGS["imap.folder"]),
        },
        "llm": {
            # Fournisseur choisi selon la machine : local vs cloud.
            "provider": settings.get("llm.provider", "ollama"),
            "ollama": {
                "model": settings.get("ollama.model", DEFAULT_SETTINGS["ollama.model"]),
                "host": settings.get("ollama.host", DEFAULT_SETTINGS["ollama.host"]),
                "timeout": _int(settings, "ollama.timeout_seconds", 600),
            },
            "openrouter": {
                # URL de base compatible OpenAI (OpenRouter par défaut ; Gemini/OpenAI/… possible).
                "base_url": settings.get("openrouter.base_url", "https://openrouter.ai/api/v1"),
                "model": settings.get(
                    "openrouter.model", "meta-llama/llama-3.3-70b-instruct:free"
                ),
                # La variable d'env prime sur la valeur stockée en base.
                "api_key": os.environ.get("OPENROUTER_API_KEY")
                or settings.get("openrouter.api_key", ""),
                "timeout": _int(settings, "openrouter.timeout_seconds", 120),
            },
        },
        "smtp": {
            "host": settings.get("smtp.host", ""),
            "port": _int(settings, "smtp.port", 587),
            "security": settings.get("smtp.security", "TLS"),
            "user": settings.get("smtp.user", ""),
            "password": settings.get("smtp.password", ""),
            "from": settings.get("smtp.from", ""),
        },
        "notify": {
            "enabled": settings.get("notify.enabled", "false") == "true",
            "recipients": settings.get("notify.recipients", ""),
        },
        "paths": {
            # Résolus en zone d'écriture (DATA_DIR) pour rester valides une fois figé en .exe.
            "pdf_storage": str(app_paths.data_path(
                settings.get("paths.pdf_storage", DEFAULT_SETTINGS["paths.pdf_storage"]))),
            "log_file": str(app_paths.data_path(
                settings.get("paths.log_file", DEFAULT_SETTINGS["paths.log_file"]))),
        },
        "processing": {
            "max_emails_per_run": _int(settings, "processing.max_emails_per_run", 100),
            "classification_confidence_threshold": _float(
                settings, "processing.classification_confidence_threshold", 0.6
            ),
            "pdf_max_chars": _int(settings, "processing.pdf_max_chars", 30000),
            "fetch_since_days": _int(settings, "processing.fetch_since_days", 30),
        },
        "outlook": {
            # Dossier serveur des fichiers PST/OST, résolu en zone d'écriture (DATA_DIR)
            # pour rester valide une fois figé en .exe (comme paths.pdf_storage).
            "import_dir": str(app_paths.data_path(
                settings.get("outlook.import_dir", DEFAULT_SETTINGS["outlook.import_dir"]))),
            "backend": settings.get("outlook.backend", DEFAULT_SETTINGS["outlook.backend"]),
        },
    }


def list_users() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, email, name, role, active, created_at FROM users ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]


def get_user_by_email(email: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? AND active = 1", (email.lower(),)
        ).fetchone()
        return dict(row) if row else None


def email_exists(email: str) -> bool:
    """True si un compte (même désactivé) utilise déjà cet email.

    Distinct de get_user_by_email (qui filtre active=1, pour le login) : la
    contrainte UNIQUE(email) s'applique aussi aux comptes désactivés, donc la
    vérification anti-doublon à la création doit les inclure.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE email = ?", (email.lower(),)
        ).fetchone()
        return row is not None


def get_user_by_id(user_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, email, name, role, active FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def create_user(
    email: str, name: str, password_hash: str, role: str
) -> int:
    if role not in ROLES:
        raise ValueError(f"Rôle invalide : {role!r}")
    with connect() as conn:
        return db.insert_returning_id(
            conn,
            """
            INSERT INTO users (email, name, password_hash, role, active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (email.lower(), name, password_hash, role, _now()),
        )


def update_user(
    user_id: int,
    name: str | None = None,
    role: str | None = None,
    active: bool | None = None,
    password_hash: str | None = None,
) -> None:
    fields = []
    values: list[Any] = []
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"Rôle invalide : {role!r}")
        fields.append("role = ?")
        values.append(role)
    if active is not None:
        fields.append("active = ?")
        values.append(int(active))
    if password_hash is not None:
        fields.append("password_hash = ?")
        values.append(password_hash)
    if not fields:
        return
    values.append(user_id)
    with connect() as conn:
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)


def delete_user(user_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def delete_users(user_ids: list[int]) -> int:
    """Supprime plusieurs comptes en une seule connexion. Retourne le nb supprimé.

    Les garde-fous (ne pas supprimer son propre compte, préserver au moins un
    admin actif) sont appliqués EN AMONT par l'appelant (voir la route
    /admin/users/bulk-delete) : cette fonction se contente d'exécuter."""
    if not user_ids:
        return 0
    with connect() as conn:
        for uid in user_ids:
            conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    return len(user_ids)


def admin_count() -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND active = 1"
        ).fetchone()
        return int(row["c"])


def insert_candidate(
    candidate_id: int,
    received_at: datetime,
    expediteur: str,
    extraction,
    pdf_filename: str,
    pdf_path: str,
) -> None:
    now = _now()
    with connect() as conn:
        # Upsert portable (SQLite/PostgreSQL) : en cas de ré-insertion d'un même
        # id, on rafraîchit les champs extraits mais on PRÉSERVE le suivi RH
        # (statut, commentaires) et created_at — ceux-ci ne figurent pas dans le
        # DO UPDATE, ils gardent donc leur valeur d'origine.
        conn.execute(
            """
            INSERT INTO candidates
            (id, received_at, expediteur, nom, prenom, email, telephone,
             poste_recherche, annees_experience, diplome_plus_eleve,
             competences, langues, resume, pdf_filename, pdf_path,
             specialite, wilaya, situation_familiale, date_naissance, age,
             niveau_etude, universite,
             soft_skills, logiciels, entreprises, certifications,
             permis, disponibilite, salaire_souhaite, experiences_json,
             statut, commentaires, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'Nouveau', '', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                received_at = excluded.received_at,
                expediteur = excluded.expediteur,
                nom = excluded.nom,
                prenom = excluded.prenom,
                email = excluded.email,
                telephone = excluded.telephone,
                poste_recherche = excluded.poste_recherche,
                annees_experience = excluded.annees_experience,
                diplome_plus_eleve = excluded.diplome_plus_eleve,
                competences = excluded.competences,
                langues = excluded.langues,
                resume = excluded.resume,
                pdf_filename = excluded.pdf_filename,
                pdf_path = excluded.pdf_path,
                specialite = excluded.specialite,
                wilaya = excluded.wilaya,
                situation_familiale = excluded.situation_familiale,
                date_naissance = excluded.date_naissance,
                age = excluded.age,
                niveau_etude = excluded.niveau_etude,
                universite = excluded.universite,
                soft_skills = excluded.soft_skills,
                logiciels = excluded.logiciels,
                entreprises = excluded.entreprises,
                certifications = excluded.certifications,
                permis = excluded.permis,
                disponibilite = excluded.disponibilite,
                salaire_souhaite = excluded.salaire_souhaite,
                experiences_json = excluded.experiences_json,
                updated_at = excluded.updated_at
            """,
            (
                candidate_id,
                received_at.isoformat(timespec="seconds"),
                expediteur,
                extraction.nom,
                extraction.prenom,
                extraction.email,
                extraction.telephone,
                extraction.poste_recherche,
                extraction.annees_experience,
                extraction.diplome_plus_eleve,
                ", ".join(extraction.competences_principales),
                ", ".join(extraction.langues),
                extraction.resume,
                pdf_filename,
                pdf_path,
                extraction.specialite,
                extraction.wilaya,
                extraction.situation_familiale,
                extraction.date_naissance,
                extraction.age,
                extraction.niveau_etude,
                extraction.universite,
                ", ".join(extraction.soft_skills),
                ", ".join(extraction.logiciels),
                ", ".join(extraction.entreprises),
                ", ".join(extraction.certifications),
                extraction.permis,
                extraction.disponibilite,
                extraction.salaire_souhaite,
                json.dumps(extraction.experiences, ensure_ascii=False)
                if extraction.experiences else None,
                now,
                now,
            ),
        )


# Options de tri autorisées pour la liste des candidats. Clé = valeur du
# paramètre `sort` (exposée dans l'URL), valeur = clause ORDER BY appliquée.
# Whitelist stricte : jamais de fragment SQL construit depuis l'entrée utilisateur.
SORT_OPTIONS: dict[str, str] = {
    "recu_desc": "received_at DESC, id DESC",
    "recu_asc": "received_at ASC, id ASC",
    "id_desc": "id DESC",
    "id_asc": "id ASC",
}
DEFAULT_SORT = "recu_desc"

# Tailles de page proposées pour la pagination de la liste des candidats.
PER_PAGE_OPTIONS: list[int] = [50, 100, 250, 500]
DEFAULT_PER_PAGE = 50


def _candidates_filter(
    search: str, statut: str, poste: str
) -> tuple[str, list[Any]]:
    """Construit la clause WHERE paramétrée commune à la liste et au comptage.

    Les candidats marqués comme doublons (duplicate_of) sont exclus : une fois
    fusionné dans l'onglet Doublons, un profil ne réapparaît ni dans la liste ni
    dans la recherche (il reste géré depuis l'onglet Doublons).
    """
    clause = " WHERE duplicate_of IS NULL"
    params: list[Any] = []
    if search:
        clause += " AND (nom LIKE ? OR prenom LIKE ? OR email LIKE ? OR competences LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like, like])
    if statut:
        clause += " AND statut = ?"
        params.append(statut)
    if poste:
        clause += " AND poste_recherche LIKE ?"
        params.append(f"%{poste}%")
    return clause, params


def count_candidates(search: str = "", statut: str = "", poste: str = "") -> int:
    """Nombre total de candidats correspondant aux filtres (sans pagination)."""
    clause, params = _candidates_filter(search, statut, poste)
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM candidates" + clause, params).fetchone()
        return int(row["n"])


def list_candidates(
    search: str = "",
    statut: str = "",
    poste: str = "",
    sort: str = DEFAULT_SORT,
    limit: int = 500,
    offset: int = 0,
) -> list[dict]:
    clause, params = _candidates_filter(search, statut, poste)
    order_by = SORT_OPTIONS.get(sort, SORT_OPTIONS[DEFAULT_SORT])
    sql = "SELECT * FROM candidates" + clause + f" ORDER BY {order_by} LIMIT ? OFFSET ?"
    params.append(limit)
    params.append(max(0, offset))
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_candidate(candidate_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        return dict(row) if row else None


def update_candidate_status(
    candidate_id: int, statut: str | None = None,
    commentaires: str | None = None,
) -> None:
    fields = []
    values: list[Any] = []
    if statut is not None:
        fields.append("statut = ?")
        values.append(statut)
    if commentaires is not None:
        fields.append("commentaires = ?")
        values.append(commentaires)
    if not fields:
        return
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(candidate_id)
    with connect() as conn:
        conn.execute(
            f"UPDATE candidates SET {', '.join(fields)} WHERE id = ?", values
        )


def candidate_stats() -> dict:
    # Cohérent avec la liste : les doublons (duplicate_of) ne sont pas comptés.
    with connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM candidates WHERE duplicate_of IS NULL"
        ).fetchone()["c"]
        by_statut = conn.execute(
            "SELECT statut, COUNT(*) AS c FROM candidates "
            "WHERE duplicate_of IS NULL GROUP BY statut"
        ).fetchall()
        return {
            "total": int(total),
            "by_statut": {r["statut"]: int(r["c"]) for r in by_statut},
        }


def reset_processing_state() -> dict:
    """Efface la mémoire de traitement pour re-vérifier tous les emails à zéro.

    Supprime les emails déjà vus ET les candidats (sinon un re-scan créerait des
    doublons), et remet le compteur d'ID à zéro."""
    with connect() as conn:
        emails = conn.execute("DELETE FROM processed_emails").rowcount
        cands = conn.execute("DELETE FROM candidates").rowcount
        conn.execute("UPDATE candidate_counter SET last_id = 0 WHERE id = 1")
    return {"emails_cleared": emails, "candidates_cleared": cands}


def create_run(triggered_by: str) -> int:
    with connect() as conn:
        return db.insert_returning_id(
            conn,
            "INSERT INTO runs (started_at, status, triggered_by) VALUES (?, 'running', ?)",
            (_now(), triggered_by),
        )


def update_run(
    run_id: int,
    status: str | None = None,
    emails_fetched: int | None = None,
    cvs_detected: int | None = None,
    error: str | None = None,
    finished: bool = False,
) -> None:
    fields = []
    values: list[Any] = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if emails_fetched is not None:
        fields.append("emails_fetched = ?")
        values.append(emails_fetched)
    if cvs_detected is not None:
        fields.append("cvs_detected = ?")
        values.append(cvs_detected)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if finished:
        fields.append("finished_at = ?")
        values.append(_now())
    if not fields:
        return
    values.append(run_id)
    with connect() as conn:
        conn.execute(f"UPDATE runs SET {', '.join(fields)} WHERE id = ?", values)


def list_runs(limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def last_successful_run() -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE status = 'success' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def running_run_exists() -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM runs WHERE status = 'running' LIMIT 1"
        ).fetchone()
        return row is not None


def wipe_processing_data() -> dict:
    """Vide l'historique des cycles + candidats + mémoire des emails vus (remet à zéro).
    Ne touche pas aux réglages ni aux utilisateurs."""
    with connect() as conn:
        runs = conn.execute("DELETE FROM runs").rowcount
        cands = conn.execute("DELETE FROM candidates").rowcount
        emails = conn.execute("DELETE FROM processed_emails").rowcount
        conn.execute("UPDATE candidate_counter SET last_id = 0 WHERE id = 1")
    return {"runs": runs, "candidates": cands, "emails": emails}


def clear_stale_runs() -> int:
    """Marque comme échoués les cycles restés 'running' (orphelins d'un process
    fermé pendant un cycle). Retourne le nombre de lignes nettoyées."""
    with connect() as conn:
        cur = conn.execute(
            "UPDATE runs SET status='failed', "
            "error='interrompu (application fermée pendant le cycle)', "
            "finished_at=? WHERE status='running'",
            (_now(),),
        )
        return cur.rowcount
