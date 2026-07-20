import db
# `connect` est ré-exporté depuis db.py (PostgreSQL). Les appelants continuent
# d'importer `from state_db import connect` sans changement de nom.
from db import connect


# Schéma PostgreSQL. « {PK} » = clé primaire auto-incrémentée (SERIAL), rendue par
# db.pk(). Les upserts sont écrits en ON CONFLICT (portable).
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

-- Offres d'emploi (module « Gestion des offres »).
CREATE TABLE IF NOT EXISTS jobs (
    id {PK},
    titre TEXT NOT NULL,
    departement TEXT,
    lieu TEXT,
    wilaya TEXT,
    commune TEXT,
    type_contrat TEXT,
    nombre_postes INTEGER,
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

-- Entretiens planifiés pour un candidat (module « Entretiens »).
CREATE TABLE IF NOT EXISTS entretiens (
    id {PK},
    candidate_id INTEGER NOT NULL,
    date_heure TEXT NOT NULL,
    type TEXT,
    lieu TEXT,
    statut TEXT NOT NULL DEFAULT 'Planifié',
    notes TEXT,
    reminder_sent INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entretiens_candidate ON entretiens(candidate_id);
CREATE INDEX IF NOT EXISTS idx_entretiens_date ON entretiens(date_heure);

-- Journal d'activité chronologique par candidat (module « Timeline »).
CREATE TABLE IF NOT EXISTS candidate_events (
    id {PK},
    candidate_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    titre TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_candidate ON candidate_events(candidate_id, created_at);

-- Modèles d'emails candidats paramétrables (module « Emails candidats »).
CREATE TABLE IF NOT EXISTS email_templates (
    id {PK},
    cle TEXT UNIQUE NOT NULL,
    libelle TEXT,
    sujet TEXT,
    corps TEXT,
    updated_at TEXT
);

-- Journal des emails envoyés aux candidats (module « Emails candidats »).
CREATE TABLE IF NOT EXISTS email_log (
    id {PK},
    candidate_id INTEGER,
    template_cle TEXT,
    destinataire TEXT,
    sujet TEXT,
    sent_at TEXT,
    statut TEXT
);
CREATE INDEX IF NOT EXISTS idx_email_log_candidate ON email_log(candidate_id);
"""


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA.replace("{PK}", db.pk()))
    migrate()


# ─── Migrations idempotentes ─────────────────────────────────────────────────
# Colonnes ajoutées après coup. Non destructif : on n'ajoute la colonne que si
# elle manque. Pour ajouter un champ : ajouter une ligne (table, colonne, type SQL).
_MIGRATIONS: list[tuple[str, str, str]] = [
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
    # Situation familiale normalisée (Célibataire / Marié(e) / Divorcé(e) / Veuf(ve)).
    ("candidates", "situation_familiale", "TEXT"),
    # Date de naissance (texte brut du CV) + âge en années (entier) pour filtrer par tranche.
    ("candidates", "date_naissance", "TEXT"),
    ("candidates", "age", "INTEGER"),
    ("candidates", "niveau_etude", "TEXT"),
    ("candidates", "experiences_json", "TEXT"),
    # Synthèse enrichie générée à la demande (module « Résumé IA ») — JSON.
    ("candidates", "resume_ia", "TEXT"),
    # Marque un candidat comme doublon d'un autre (module « Détection de doublons »).
    ("candidates", "duplicate_of", "INTEGER"),
    # Étape dans le pipeline de recrutement (module « Pipeline »).
    ("candidates", "stage", "TEXT"),
    # Rappel email envoyé pour un entretien (module « Entretiens ») — idempotence.
    ("entretiens", "reminder_sent", "INTEGER DEFAULT 0"),
    # Message-ID RFC 5322 du mail d'origine. `uid` n'identifie un mail que DANS le
    # contexte qui l'a lu (UID IMAP, identifiant de nœud pypff, EntryID MAPI) : deux
    # backends ne se reconnaissent pas l'un l'autre, et un identifiant pypff ne vaut
    # que pour LE fichier lu. Le Message-ID, lui, voyage avec le mail — il permet de
    # retrouver dans la boîte Outlook vivante un mail traité depuis une copie OST
    # (« Ranger les traités »). Peut être vide : rien ne garantit sa présence.
    ("processed_emails", "message_id", "TEXT"),
    # Localisation (référentiel Algérie) + type de contrat + nb de postes (module « Offres »).
    ("jobs", "wilaya", "TEXT"),
    ("jobs", "commune", "TEXT"),
    ("jobs", "type_contrat", "TEXT"),
    ("jobs", "nombre_postes", "INTEGER"),
]


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = ? AND column_name = ?",
        (table, column),
    ).fetchone()
    return row is not None


def migrate() -> int:
    """Applique les migrations manquantes. Idempotent. Retourne le nb de colonnes ajoutées."""
    added = 0
    with connect() as conn:
        for table, column, coltype in _MIGRATIONS:
            if not _column_exists(conn, table, column):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
                added += 1
    return added


def is_processed(uid: str, folder: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_emails WHERE uid = ? AND folder = ?",
            (uid, folder),
        ).fetchone()
        return row is not None


def mark_processed(
    uid: str,
    folder: str,
    processed_at: str,
    is_cv: bool,
    candidate_id: int | None = None,
    notes: str | None = None,
    message_id: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO processed_emails
            (uid, folder, processed_at, is_cv, candidate_id, notes, message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid, folder) DO UPDATE SET
                processed_at = excluded.processed_at,
                is_cv = excluded.is_cv,
                candidate_id = excluded.candidate_id,
                notes = excluded.notes,
                message_id = COALESCE(excluded.message_id, processed_emails.message_id)
            """,
            (uid, folder, processed_at, int(is_cv), candidate_id, notes,
             (message_id or None)),
        )


def processed_message_ids(folder: str) -> dict[str, int]:
    """Message-ID des mails traités de `folder` -> is_cv (1 = CV, 0 = analysé, pas un CV).

    Sert au rangement des mails traités : on ne déplace que ce que la solution a
    réellement analysé, et on sépare les CV du reste. Les lignes sans Message-ID
    (traitées avant l'ajout de la colonne, ou mail sans en-tête) sont ignorées :
    faute de clé portable, on ne sait pas les retrouver dans la boîte, et deviner
    reviendrait à déplacer un mail au hasard.

    Un même Message-ID peut porter plusieurs lignes (le mail existe dans deux dossiers
    du fichier, d'où deux `uid`). `MAX(is_cv)` tranche explicitement : si UNE analyse a
    reconnu un CV, on le range comme CV. Sans ce regroupement, deux lignes en désaccord
    — la classification LLM n'étant pas déterministe d'un import à l'autre — feraient
    dépendre la destination de l'ordre de lecture, et un vrai CV pourrait finir dans le
    dossier des non-CV.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT message_id, MAX(is_cv) AS is_cv FROM processed_emails "
            "WHERE folder = ? AND message_id IS NOT NULL AND message_id <> '' "
            "GROUP BY message_id",
            (folder,),
        ).fetchall()
    return {r["message_id"]: int(r["is_cv"]) for r in rows}


def next_candidate_id() -> int:
    with connect() as conn:
        conn.execute(
            "UPDATE candidate_counter SET last_id = last_id + 1 WHERE id = 1"
        )
        row = conn.execute(
            "SELECT last_id FROM candidate_counter WHERE id = 1"
        ).fetchone()
        return int(row["last_id"])
