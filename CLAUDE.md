# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CV Agent: a **local, single-machine** HR tool that polls a Gmail inbox over IMAP, uses an LLM to detect and extract CVs from attachments, stores candidates in SQLite, and serves a French web dashboard (FastAPI + Jinja + HTMX) for the RH team. Ships as a Windows desktop `.exe` (uvicorn on loopback + system tray). 100% local — no data leaves the machine unless the `openrouter` cloud LLM provider is explicitly selected.

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

**SQLite (`state.db`) is the single source of truth.** `config.yaml` is only a first-run *seed* consumed by `bootstrap.py`; at runtime all configuration lives in the `settings` table and is edited via the admin UI, not files. `web_db.settings_to_config()` flattens the DB settings into the nested `cfg` dict every pipeline module consumes — when adding a config key, wire it in `DEFAULT_SETTINGS`, the `MAIL_FIELDS`/`LLM_FIELDS` form lists in `webapp.py`, and `settings_to_config()`.

**Pipeline flow** (`web_pipeline.run_pipeline` orchestrates one cycle):
`mail_fetcher` (IMAP) → `pdf_extractor` (PDF/DOCX → text) → `llm_classifier` (is this a CV?) → `llm_extractor` (structured fields) → `web_db.insert_candidate`. It is triggered three ways, all sharing the same function: the in-process **APScheduler** job, the "Run now" admin button, and `main.py`.

**Two DB layers, one connection helper.** `state_db.py` owns the schema, `connect()`, and the low-level idempotency machinery (`processed_emails` dedup by IMAP UID, `candidate_counter` for sequential `idNNNN` IDs). `web_db.py` builds on `state_db.connect()` for users / candidates / settings / runs. Both use parameterized SQL exclusively.

**Backend DB configurable (SQLite par défaut, PostgreSQL optionnel).** `db.py` abstrait le moteur : sans `CV_AGENT_DB_URL`, c'est SQLite (défaut local, packagé dans l'exe, testé) ; avec `CV_AGENT_DB_URL="postgresql://user:pw@host:5432/cvagent"`, c'est PostgreSQL (déploiement centralisé multi-postes). `state_db.connect` est ré-exporté depuis `db.connect`. **Règles pour rester portable** : (1) toujours écrire les requêtes avec le placeholder `?` (traduit en `%s` pour psycopg) ; (2) pour un id auto-incrémenté dans le schéma, utiliser le token `{PK}` (rendu `db.pk()`) ; (3) pour récupérer l'id d'un INSERT, passer par `db.insert_returning_id(conn, sql, params)` — jamais `cur.lastrowid` directement ; (4) pour un upsert, utiliser `ON CONFLICT(...) DO UPDATE/NOTHING` (portable), jamais `INSERT OR IGNORE/REPLACE` (SQLite-only). Pour un déploiement multi-postes sur base PostgreSQL partagée, fixer sur **chaque poste** le **même** `CV_AGENT_SECRET` : `secret_store` bascule alors sur le chiffrement portable `enc:v2:` (voir invariant « Secrets »), déchiffrable par tous les postes partageant ce secret.

**LLM provider is a config choice, not failover.** `llm_provider.chat_json()` dispatches to Ollama (local) or an OpenAI-compatible cloud endpoint (OpenRouter/Gemini/etc.) based solely on `llm.provider`. Classifier and extractor both go through this single function and expect a JSON object back (it raises `LLMError` otherwise).

**Path resolution is frozen-exe-aware.** `app_paths` splits `RESOURCE_DIR` (read-only bundled templates/static/config.yaml — `_MEIPASS` when frozen) from `DATA_DIR` (writable — `%LOCALAPPDATA%\CV-Agent` when frozen, project dir in dev). Any file the app writes (DB, logs, `cv_pdfs`, session secret) must go through `app_paths.data_path()`, never a bare relative path.

**Packaging.** `desktop.py` is the PyInstaller entry point (onedir). When you add a new top-level module, add it to `hiddenimports` in `cv-agent.spec` or it won't be bundled. The desktop app binds uvicorn to `127.0.0.1`; the autostart service (`install_autostart.ps1`, scheduled task under a user account) uses `0.0.0.0:6060` behind a LAN-only firewall rule.

## Invariants and gotchas

- **Single uvicorn worker only.** APScheduler and the SQLite writer assume one process — `start_web.bat` passes `--workers 1`. Do not scale to multiple workers.
- **Cooperative cancellation.** `web_pipeline` uses module-level `threading.Event`s (`_cancel_event`, `_active_event`) to stop a run between emails and to distinguish a live run from an orphaned `running` row (cleaned at startup by `clear_stale_runs`). Preserve this when touching run lifecycle.
- **Secrets are encrypted at rest.** `imap.password`, `smtp.password`, `openrouter.api_key` (the `SECRET_SETTING_KEYS` set in `web_db.py`) are encrypted via `secret_store.py` transparently inside `web_db.set_settings`/`get_all_settings` — callers always see plaintext in memory. Two stored forms: **`enc:v2:…`** = portable Fernet (AES-128-CBC + HMAC), key derived from `CV_AGENT_SECRET` via PBKDF2 — used when `CV_AGENT_SECRET` is set; decryptable on any machine sharing the same secret (the multi-poste / shared-PostgreSQL mode). **`enc:v1:…`** = Windows DPAPI, machine scope — the fallback when `CV_AGENT_SECRET` is unset (single-poste); a copied `state.db` cannot be decrypted elsewhere. Unprefixed values are legacy plaintext (auto-migrated at startup). A blob that can't be decrypted (wrong/absent `CV_AGENT_SECRET`, DPAPI blob on another machine) yields `""`, not a crash. **Never put real credentials in `config.yaml`** — it is bundled into the distributed exe.
- **Security conventions.** Jinja autoescaping is on (no `|safe`); any HTML built by hand from server/LLM/remote content must be `html.escape()`d (see `_test_result_html`). Login has a per-account throttle (5 failures → 30 s lockout) in `webapp.py`.
- **Admin-count guards.** User update/delete refuse to remove the last active admin or self — keep these checks intact.
