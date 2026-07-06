import db
# `connect` est ré-exporté depuis db.py : selon CV_AGENT_DB_URL il ouvre une
# connexion SQLite (défaut, local) ou PostgreSQL. Les appelants (web_db, main…)
# continuent d'importer `from state_db import connect` sans changement.
from db import connect


# Schéma commun aux deux moteurs. « {PK} » = clé primaire auto-incrémentée
# (INTEGER…AUTOINCREMENT en SQLite, SERIAL en PostgreSQL — voir db.pk()).
# Les upserts sont écrits en ON CONFLICT portable (SQLite ≥ 3.24 et PostgreSQL).
SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_emails (
    uid TEXT NOT NULL,
    folder TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    is_cv INTEGER NOT NULL,
    candidate_id INTEGER,
    notes TEXT,
    PRIMARY KEY (uid, folder)
);

CREATE TABLE IF NOT EXISTS candidate_counter (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_id INTEGER NOT NULL
);
INSERT INTO candidate_counter (id, last_id) VALUES (1, 0) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS users (
    id {PK},
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'manager', 'rh', 'lecture')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL,
    expediteur TEXT,
    nom TEXT,
    prenom TEXT,
    email TEXT,
    telephone TEXT,
    poste_recherche TEXT,
    annees_experience INTEGER,
    diplome_plus_eleve TEXT,
    competences TEXT,
    langues TEXT,
    resume TEXT,
    pdf_filename TEXT,
    pdf_path TEXT,
    statut TEXT NOT NULL DEFAULT 'Nouveau',
    commentaires TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_candidates_statut ON candidates(statut);
CREATE INDEX IF NOT EXISTS idx_candidates_received_at ON candidates(received_at);
CREATE INDEX IF NOT EXISTS idx_candidates_poste ON candidates(poste_recherche);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id {PK},
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    triggered_by TEXT NOT NULL,
    emails_fetched INTEGER DEFAULT 0,
    cvs_detected INTEGER DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at DESC);

-- ─── Tables ATS (modules avancés) ────────────────────────────────────────────
-- Créées de façon centralisée ici pour que chaque module reste isolé (routeur
-- + templates) sans toucher au schéma. Portable SQLite/PostgreSQL.

-- Offres d'emploi (module « Gestion des offres »).
CREATE TABLE IF NOT EXISTS jobs (
    id {PK},
    titre TEXT NOT NULL,
    departement TEXT,
    lieu TEXT,
    description TEXT,
    competences_requises TEXT,
    experience_min INTEGER,
    niveau_etude TEXT,
    statut TEXT NOT NULL DEFAULT 'Brouillon',
    created_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_statut ON jobs(statut);

-- Notes internes RH attachées à un candidat (module « Notes internes »).
CREATE TABLE IF NOT EXISTS candidate_notes (
    id {PK},
    candidate_id INTEGER NOT NULL,
    author_id INTEGER,
    author_name TEXT,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_candidate ON candidate_notes(candidate_id);

-- Pièces jointes d'un candidat (module « Gestion documentaire »).
CREATE TABLE IF NOT EXISTS candidate_documents (
    id {PK},
    candidate_id INTEGER NOT NULL,
    doc_type TEXT,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    uploaded_by INTEGER,
    uploaded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_candidate ON candidate_documents(candidate_id);

-- Scores de correspondance offre↔candidat (module « Matching IA »).
CREATE TABLE IF NOT EXISTS matches (
    id {PK},
    job_id INTEGER NOT NULL,
    candidate_id INTEGER NOT NULL,
    score INTEGER,
    details_json TEXT,
    computed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_matches_job ON matches(job_id);
CREATE INDEX IF NOT EXISTS idx_matches_candidate ON matches(candidate_id);

-- Alertes : un candidat correspond fortement à une offre publiée (module « Alertes »).
-- UNIQUE(candidate_id, job_id) : une seule alerte par paire (dédup via ON CONFLICT).
CREATE TABLE IF NOT EXISTS alerts (
    id {PK},
    candidate_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    seen INTEGER NOT NULL DEFAULT 0,
    UNIQUE (candidate_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_alerts_seen ON alerts(seen);
"""


def init(db_path: str) -> None:
    db.init_dir(db_path)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA.replace("{PK}", db.pk()))
    migrate(db_path)


# ─── Migrations idempotentes ─────────────────────────────────────────────────
# Colonnes ajoutées après coup (parsing enrichi, ATS…). Non destructif : on ne
# fait qu'ajouter la colonne si elle manque. Portable SQLite/PostgreSQL.
# Pour ajouter un champ : ajouter une ligne (table, colonne, type SQL).
_MIGRATIONS: list[tuple[str, str, str]] = [
    # Parsing avancé (Module 1) — champs extraits du CV en plus des colonnes d'origine.
    ("candidates", "universite", "TEXT"),
    ("candidates", "entreprises", "TEXT"),
    ("candidates", "certifications", "TEXT"),
    ("candidates", "soft_skills", "TEXT"),
    ("candidates", "logiciels", "TEXT"),
    ("candidates", "permis", "TEXT"),
    ("candidates", "disponibilite", "TEXT"),
    ("candidates", "salaire_souhaite", "TEXT"),
    ("candidates", "specialite", "TEXT"),
    ("candidates", "wilaya", "TEXT"),
    ("candidates", "niveau_etude", "TEXT"),
    ("candidates", "experiences_json", "TEXT"),
    # Synthèse enrichie générée à la demande (module « Résumé IA ») — JSON.
    ("candidates", "resume_ia", "TEXT"),
    # Marque un candidat comme doublon d'un autre (module « Détection de doublons »).
    ("candidates", "duplicate_of", "INTEGER"),
    # Étape dans le pipeline de recrutement (module « Pipeline »). Défaut applicatif : « CV reçu ».
    ("candidates", "stage", "TEXT"),
]


def _column_exists(conn, table: str, column: str) -> bool:
    if db.is_postgres():
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = ? AND column_name = ?",
            (table, column),
        ).fetchone()
        return row is not None
    # SQLite : PRAGMA non paramétrable ; table est un littéral contrôlé (jamais
    # une entrée utilisateur), donc sûr.
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def migrate(db_path: str) -> int:
    """Applique les migrations manquantes. Idempotent. Retourne le nb de colonnes ajoutées."""
    added = 0
    with connect(db_path) as conn:
        for table, column, coltype in _MIGRATIONS:
            if not _column_exists(conn, table, column):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
                added += 1
    return added


def is_processed(db_path: str, uid: str, folder: str) -> bool:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_emails WHERE uid = ? AND folder = ?",
            (uid, folder),
        ).fetchone()
        return row is not None


def mark_processed(
    db_path: str,
    uid: str,
    folder: str,
    processed_at: str,
    is_cv: bool,
    candidate_id: int | None = None,
    notes: str | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO processed_emails
            (uid, folder, processed_at, is_cv, candidate_id, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid, folder) DO UPDATE SET
                processed_at = excluded.processed_at,
                is_cv = excluded.is_cv,
                candidate_id = excluded.candidate_id,
                notes = excluded.notes
            """,
            (uid, folder, processed_at, int(is_cv), candidate_id, notes),
        )


def next_candidate_id(db_path: str) -> int:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE candidate_counter SET last_id = last_id + 1 WHERE id = 1"
        )
        row = conn.execute(
            "SELECT last_id FROM candidate_counter WHERE id = 1"
        ).fetchone()
        return int(row["last_id"])
