# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CV Agent: a **local** HR tool that polls **any IMAP inbox** (Gmail, Outlook/Office 365, internal server…) over IMAP, uses an LLM to detect and extract CVs from attachments, stores candidates in **PostgreSQL**, and serves a French web dashboard (FastAPI + Jinja + HTMX) for the RH team. Deployed via **Docker** (recommended) or a Windows desktop `.exe` (uvicorn on loopback + system tray). 100% local — no data leaves the network unless the `openrouter` cloud LLM provider is explicitly selected. **PostgreSQL is required** (`CV_AGENT_DB_URL`); there is no SQLite fallback.

**All user-facing text and code comments are in French.** Match that when editing.

## Commands

```powershell
# First-time setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python bootstrap.py           # init DB, seed settings, create first admin (interactive)

# Run the web app (dev, LAN-exposed on :6060)
.\run_web.bat                 # == python -m uvicorn webapp:app --host 0.0.0.0 --port 6060

# Run as desktop app (loopback + systray, mirrors the shipped .exe)
python desktop.py

# Run ONE pipeline cycle from the CLI (debug a single fetch/classify/extract pass)
python main.py

# Build the Windows executable (onedir -> dist\CV-Agent\)
pyinstaller cv-agent.spec --noconfirm     # or: .\build_exe.ps1

# Build the installer (Inno Setup, installer.iss) and regenerate the manual PDF
.\build_installer.ps1
python build_pdf.py           # regenerate MANUEL_UTILISATION.pdf after editing the .md
```

There is **no automated test suite**. Verify changes by running a real pipeline cycle (`python main.py`) against the configured mailbox, or by importing a module and exercising it directly with the `.venv` interpreter. Check `logs\agent.log` for pipeline output.

## Architecture — the big picture

**PostgreSQL is the single source of truth.** `config.yaml` is only a first-run *seed* consumed by `bootstrap.py`; at runtime all configuration lives in the `settings` table and is edited via the admin UI, not files. `web_db.settings_to_config()` flattens the DB settings into the nested `cfg` dict every pipeline module consumes — when adding a config key, wire it in `DEFAULT_SETTINGS`, the `MAIL_FIELDS`/`LLM_FIELDS` form lists in `webapp.py`, and `settings_to_config()` (e.g. `imap.security` = SSL/STARTTLS/None, wired in all four places).

**Pipeline flow** (`web_pipeline.run_pipeline` orchestrates one cycle):
`mail_fetcher` (IMAP) → `pdf_extractor` (PDF/DOCX → text) → `llm_classifier` (is this a CV?) → `llm_extractor` (structured fields) → `web_db.insert_candidate`. It is triggered three ways, all sharing the same function: the in-process **APScheduler** job, the "Run now" admin button, and `main.py`.

**Two DB layers, one connection helper.** `state_db.py` owns the schema, `connect()`, and the low-level idempotency machinery (`processed_emails` dedup by IMAP UID, `candidate_counter` for sequential `idNNNN` IDs). `web_db.py` builds on `state_db.connect()` for users / candidates / settings / runs. Both use parameterized SQL exclusively. **`connect()` prend zéro argument** (plus de `db_path` nulle part dans l'API) et lit la connexion depuis `CV_AGENT_DB_URL`.

**Moteur DB : PostgreSQL uniquement (obligatoire).** `db.py` n'est plus qu'un adaptateur PostgreSQL : `CV_AGENT_DB_URL` est **requis** — s'il manque, `db.db_url()` lève une `RuntimeError` explicite et l'app refuse de démarrer (plus aucun repli SQLite ; plus de fichier `state.db`). `state_db.connect` est ré-exporté depuis `db.connect`. **Conventions SQL** : (1) toujours écrire les requêtes avec le placeholder `?` (traduit en `%s` pour psycopg) ; (2) pour un id auto-incrémenté, utiliser le token `{PK}` (rendu `db.pk()` = `SERIAL PRIMARY KEY`) ; (3) pour récupérer l'id d'un INSERT, passer par `db.insert_returning_id(conn, sql, params)` (ajoute `RETURNING id`) ; (4) pour un upsert, utiliser `ON CONFLICT(...) DO UPDATE/NOTHING`. Pour plusieurs instances serveur sur la même base, fixer le **même** `CV_AGENT_SECRET` partout : `secret_store` utilise alors le chiffrement portable `enc:v2:` (voir invariant « Secrets »), déchiffrable par toutes les instances partageant ce secret. **Sous Linux/conteneur, `CV_AGENT_SECRET` est obligatoire** (pas de DPAPI).

**LLM provider is a config choice, not failover.** `llm_provider.chat_json()` dispatches to Ollama (local) or an OpenAI-compatible cloud endpoint (OpenRouter/Gemini/etc.) based solely on `llm.provider`. Classifier and extractor both go through this single function and expect a JSON object back (it raises `LLMError` otherwise).

**Path resolution is frozen-exe-aware.** `app_paths` splits `RESOURCE_DIR` (read-only bundled templates/static/config.yaml — `_MEIPASS` when frozen) from `DATA_DIR` (writable — `%LOCALAPPDATA%\CV-Agent-Pro` when frozen, project dir in dev, or `CV_AGENT_DATA_DIR` when set — e.g. `/data` in Docker). Any **file** the app writes (logs, `cv_pdfs`, session secret) must go through `app_paths.data_path()`, never a bare relative path. The database is PostgreSQL — no file on disk, and `app_paths.db_path()` no longer exists.

**Packaging.** `desktop.py` is the PyInstaller entry point (onedir). When you add a new top-level module, add it to `hiddenimports` in `cv-agent.spec` or it won't be bundled. The desktop app binds uvicorn to `127.0.0.1`; the autostart service (`install_autostart.ps1`, scheduled task under a user account) uses `0.0.0.0:6060` behind a LAN-only firewall rule.

## Invariants and gotchas

- **Single uvicorn worker only.** APScheduler and the `candidate_counter` sequence assume one process per instance — `start_web.bat` passes `--workers 1`. Do not scale to multiple workers, and do not run several instances that poll the same mailbox.
- **Cooperative cancellation.** `web_pipeline` uses module-level `threading.Event`s (`_cancel_event`, `_active_event`) to stop a run between emails and to distinguish a live run from an orphaned `running` row (cleaned at startup by `clear_stale_runs`). Preserve this when touching run lifecycle.
- **Secrets are encrypted at rest.** `imap.password`, `smtp.password`, `openrouter.api_key` (the `SECRET_SETTING_KEYS` set in `web_db.py`) are encrypted via `secret_store.py` transparently inside `web_db.set_settings`/`get_all_settings` — callers always see plaintext in memory. Two stored forms: **`enc:v2:…`** = portable Fernet (AES-128-CBC + HMAC), key derived from `CV_AGENT_SECRET` via PBKDF2 — used when `CV_AGENT_SECRET` is set; decryptable on any machine sharing the same secret (the multi-poste / shared-PostgreSQL mode). **`enc:v1:…`** = Windows DPAPI, machine scope — the fallback when `CV_AGENT_SECRET` is unset (Windows single-machine only); these blobs cannot be decrypted on another machine, so a shared PostgreSQL deployment must set `CV_AGENT_SECRET` (→ `enc:v2:`). Unprefixed values are legacy plaintext (auto-migrated at startup). A blob that can't be decrypted (wrong/absent `CV_AGENT_SECRET`, DPAPI blob on another machine) yields `""`, not a crash. **Never put real credentials in `config.yaml`** — it is bundled into the distributed exe.
- **Security conventions.** Jinja autoescaping is on (no `|safe`); any HTML built by hand from server/LLM/remote content must be `html.escape()`d (see `_test_result_html`). Login has a per-account throttle (5 failures → 30 s lockout) in `webapp.py`.
- **Admin-count guards.** User update/delete refuse to remove the last active admin or self — keep these checks intact.
