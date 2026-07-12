"""Application FastAPI : interface web de CV Agent."""

import html
import json
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

import app_runtime
import app_paths
import state_db
import web_db
import web_auth
import web_pipeline
import excel_export
import llm_provider
import mail_fetcher
import outlook_fetcher
import notifier

# Modules ATS avancés : chacun expose un `router` (APIRouter) dans son fichier
# `mod_<nom>.py`. Ajoutés ici uniquement ; le code de chaque module reste isolé.
import mod_dashboard
import mod_search
import mod_jobs
import mod_compare
import mod_notes
import mod_duplicates
import mod_summary
import mod_documents
import mod_matching
import mod_search_ia
import mod_pipeline
import mod_stats
import mod_alerts
import mod_api
import mod_entretiens
import entretien_reminders

# render() vit dans web_core (socle partagé des routeurs mod_*) : on le réutilise
# ici plutôt que d'en maintenir une copie identique (contexte de base commun).
from web_core import render


app_runtime.force_utf8_streams()


HERE = app_paths.RESOURCE_DIR          # templates / static (lecture seule)


def _load_session_secret() -> str:
    """Secret de session PERSISTANT : sinon chaque relance déconnecte tout le monde."""
    env = os.environ.get("CV_AGENT_SECRET")
    if env:
        return env
    p = app_paths.data_path("session.secret")
    try:
        if p.exists():
            existing = p.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        generated = secrets.token_hex(32)
        p.write_text(generated, encoding="utf-8")
        return generated
    except OSError:
        return secrets.token_hex(32)  # dernier recours (sessions non persistantes)


SESSION_SECRET = _load_session_secret()

log = logging.getLogger("cv_agent.web")

scheduler = BackgroundScheduler(daemon=True)


def setup_logging() -> None:
    settings = web_db.get_all_settings()
    log_file = str(app_paths.data_path(settings.get("paths.log_file", "logs/agent.log")))
    app_runtime.configure_logging(log_file)


def _scheduled_run() -> None:
    try:
        web_pipeline.run_pipeline(triggered_by="scheduler")
    except Exception as e:
        log.exception("Scheduled run failed: %s", e)


def _scheduled_reminders() -> None:
    try:
        n = entretien_reminders.envoyer_rappels_dus()
        if n:
            log.info("%d rappel(s) d'entretien envoyé(s)", n)
    except Exception as e:
        log.exception("Reminder job failed: %s", e)


def reschedule_from_settings() -> None:
    settings = web_db.get_all_settings()
    enabled = settings.get("scheduler.enabled", "true").lower() == "true"
    interval = max(1, int(settings.get("scheduler.interval_minutes", "60")))

    if scheduler.get_job("pipeline"):
        scheduler.remove_job("pipeline")

    if enabled:
        scheduler.add_job(
            _scheduled_run,
            trigger=IntervalTrigger(minutes=interval),
            id="pipeline",
            next_run_time=datetime.now(),
            max_instances=1,
            coalesce=True,
        )
        log.info("Scheduler armed (every %d min)", interval)
    else:
        log.info("Scheduler disabled by settings")

    # Job de rappels d'entretien, indépendant du planificateur de pipeline
    # (vérifie toutes les 15 min les entretiens dont l'échéance approche).
    if scheduler.get_job("entretien_reminders"):
        scheduler.remove_job("entretien_reminders")
    if settings.get("entretiens.reminder_enabled", "true").lower() == "true":
        scheduler.add_job(
            _scheduled_reminders,
            trigger=IntervalTrigger(minutes=15),
            id="entretien_reminders",
            next_run_time=datetime.now(),
            max_instances=1,
            coalesce=True,
        )
        log.info("Rappels d'entretien armés (toutes les 15 min)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    state_db.init()
    web_db.seed_default_settings()
    setup_logging()

    # Chiffre au repos les secrets encore en clair (bases antérieures au chiffrement).
    migrated = web_db.migrate_encrypt_secrets()
    if migrated:
        log.info("%d secret(s) chiffré(s) au repos (migration DPAPI)", migrated)

    # Au démarrage, aucun cycle ne peut être réellement en cours : nettoyer les
    # cycles 'running' orphelins (app fermée pendant un cycle) qui bloqueraient l'UI.
    stale = web_db.clear_stale_runs()
    if stale:
        log.warning("%d cycle(s) orphelin(s) nettoyé(s) au démarrage", stale)

    if web_db.admin_count() == 0:
        log.warning(
            "Aucun compte admin — la page /setup permet d'en créer un au premier accès."
        )

    scheduler.start()
    reschedule_from_settings()
    log.info("Web app started")
    yield
    scheduler.shutdown(wait=False)
    log.info("Web app stopped")


class WriteGuardMiddleware(BaseHTTPMiddleware):
    """Applique le rôle « lecture seule » : tout POST/PUT/PATCH/DELETE émis par
    un utilisateur de rôle « lecture » est refusé (403). Centralisé ici pour
    couvrir en un seul point toutes les routes mutantes, actuelles et futures."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            uid = request.session.get("user_id")
            if uid:
                u = web_db.get_user_by_id(int(uid))
                if u and u.get("role") == "lecture":
                    return JSONResponse(
                        {"detail": "Lecture seule : action non autorisée."},
                        status_code=403,
                    )
        return await call_next(request)


app = FastAPI(lifespan=lifespan)
# Le middleware ajouté en DERNIER est le plus externe. SessionMiddleware doit
# envelopper WriteGuardMiddleware pour que `request.session` soit déjà chargé.
app.add_middleware(WriteGuardMiddleware)
# https_only pose le drapeau Secure sur le cookie de session (à activer derrière un
# reverse-proxy HTTPS via CV_AGENT_HTTPS_ONLY=1). Désactivé par défaut : le mode LAN
# documenté sert en HTTP clair, où un cookie Secure ne serait jamais renvoyé. En
# loopback (bureau) la boucle locale est de confiance. same_site='lax' explicite :
# atténue le CSRF sur les POST mutants (soumissions cross-site non accompagnées du cookie).
_https_only = os.environ.get("CV_AGENT_HTTPS_ONLY", "").lower() in ("1", "true", "yes")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=8 * 3600,
    same_site="lax",
    https_only=_https_only,
)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

# Enregistrement des routeurs de modules ATS (routes définies dans mod_*.py).
for _mod in (mod_dashboard, mod_search, mod_jobs, mod_compare,
             mod_notes, mod_duplicates, mod_summary, mod_documents,
             mod_matching, mod_search_ia, mod_pipeline, mod_stats,
             mod_alerts, mod_api, mod_entretiens):
    app.include_router(_mod.router)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    ico = HERE / "static" / "app.ico"
    if ico.exists():
        return FileResponse(ico, media_type="image/x-icon")
    raise HTTPException(404)


# ─── Anti-brute-force login ───────────────────────────────────────────────────
# Limitation par compte : après 5 échecs consécutifs, le compte est bloqué 30 s.
# État en mémoire (process unique, loopback) protégé par un verrou.
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_LOCKOUT_SECONDS = 30
_login_attempts: dict[str, dict] = {}   # email -> {"count": int, "locked_until": float}
_login_lock = threading.Lock()


def _login_lock_remaining(email: str) -> int:
    """Secondes restantes de blocage pour cet email (0 si non bloqué)."""
    with _login_lock:
        rec = _login_attempts.get(email)
        if not rec:
            return 0
        remaining = rec["locked_until"] - time.monotonic()
        return int(remaining) + 1 if remaining > 0 else 0


def _register_login_failure(email: str) -> None:
    with _login_lock:
        rec = _login_attempts.setdefault(email, {"count": 0, "locked_until": 0.0})
        rec["count"] += 1
        if rec["count"] >= _LOGIN_MAX_ATTEMPTS:
            rec["locked_until"] = time.monotonic() + _LOGIN_LOCKOUT_SECONDS
            rec["count"] = 0  # fenêtre de blocage armée ; on repart de zéro après


def _reset_login_attempts(email: str) -> None:
    with _login_lock:
        _login_attempts.pop(email, None)


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, err: str = ""):
    # Premier lancement (aucun admin) : formulaire de création. Sinon → login.
    if web_db.admin_count() > 0:
        return RedirectResponse("/login", status_code=303)
    return render(request, "setup.html", {"err": err})


@app.post("/setup")
def setup_submit(
    request: Request,
    email: str = Form(...),
    name: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    if web_db.admin_count() > 0:
        return RedirectResponse("/login", status_code=303)
    email = email.strip().lower()
    if len(password) < 8:
        return RedirectResponse(
            "/setup?err=Mot+de+passe+trop+court+(min+8)", status_code=303
        )
    if password != password2:
        return RedirectResponse(
            "/setup?err=Les+mots+de+passe+ne+correspondent+pas", status_code=303
        )
    uid = web_db.create_user(
        email, name.strip() or email,
        web_auth.hash_password(password), role="admin",
    )
    request.session["user_id"] = uid
    log.info("Premier admin créé via /setup : %s", email)
    return RedirectResponse("/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, err: str = ""):
    # Pas encore d'admin → forcer la page de premier lancement.
    if web_db.admin_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    if web_auth.current_user(request):
        return RedirectResponse("/", status_code=302)
    return render(request, "login.html", {"err": err})


@app.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    email_norm = email.strip().lower()

    wait = _login_lock_remaining(email_norm)
    if wait > 0:
        return RedirectResponse(
            f"/login?err=Trop+d'essais.+Réessayez+dans+{wait}+s", status_code=303
        )

    user = web_db.get_user_by_email(email)
    if not user or not web_auth.verify_password(password, user["password_hash"]):
        _register_login_failure(email_norm)
        return RedirectResponse("/login?err=Identifiants+invalides", status_code=303)

    _reset_login_attempts(email_norm)
    request.session["user_id"] = user["id"]
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, search: str = "", statut: str = "", poste: str = ""):
    user = web_auth.require_user(request)
    rows = web_db.list_candidates(search=search, statut=statut, poste=poste)
    stats = web_db.candidate_stats()
    last = web_db.last_successful_run()
    return render(
        request, "dashboard.html",
        {
            "rows": rows,
            "stats": stats,
            "statuts": web_db.STATUTS,
            "search": search, "statut": statut, "poste": poste,
            "last_run": last,
        },
    )


@app.get("/candidate/{cid}", response_class=HTMLResponse)
def candidate_page(request: Request, cid: int):
    user = web_auth.require_user(request)
    c = web_db.get_candidate(cid)
    if not c:
        raise HTTPException(404, "Candidat introuvable")
    # Les expériences détaillées sont stockées en JSON : on les décode pour le rendu.
    experiences = []
    if c.get("experiences_json"):
        try:
            experiences = json.loads(c["experiences_json"]) or []
        except (json.JSONDecodeError, TypeError):
            experiences = []
    return render(
        request, "candidate.html",
        {"c": c, "statuts": web_db.STATUTS, "experiences": experiences},
    )


@app.post("/candidate/{cid}/update", response_class=HTMLResponse)
def candidate_update(
    request: Request, cid: int,
    statut: str | None = Form(None),
    commentaires: str | None = Form(None),
):
    user = web_auth.require_user(request)
    c = web_db.get_candidate(cid)
    if not c:
        raise HTTPException(404)
    if statut is not None and statut not in web_db.STATUTS:
        raise HTTPException(400, "Statut invalide")
    web_db.update_candidate_status(
        cid, statut=statut, commentaires=commentaires
    )
    if request.headers.get("HX-Request"):
        c = web_db.get_candidate(cid)
        return render(request, "_status_cell.html",
                      {"c": c, "statuts": web_db.STATUTS})
    return RedirectResponse(f"/candidate/{cid}", status_code=303)


@app.get("/candidate/{cid}/pdf")
def candidate_pdf(request: Request, cid: int):
    web_auth.require_user(request)
    c = web_db.get_candidate(cid)
    if not c or not c["pdf_path"]:
        raise HTTPException(404)
    path = Path(c["pdf_path"])
    if not path.exists():
        # Base migrée (ex. dev -> exe installé) : le chemin absolu stocké pointe
        # ailleurs. On retente dans le dossier de stockage actuel via le nom de fichier.
        if c["pdf_filename"]:
            alt = app_paths.data_path("cv_pdfs") / c["pdf_filename"]
            if alt.exists():
                path = alt
        if not path.exists():
            raise HTTPException(404, "PDF introuvable")
    return FileResponse(
        path, media_type="application/pdf",
        filename=c["pdf_filename"] or path.name,
        # inline : s'affiche dans l'iframe et l'onglet au lieu d'être téléchargé.
        content_disposition_type="inline",
    )


# ─── Excel export ─────────────────────────────────────────────────────────────

@app.get("/export.xlsx")
def export_xlsx(request: Request):
    web_auth.require_user(request)
    data = excel_export.export_to_bytes()
    fname = f"candidats_{datetime.now():%Y%m%d_%H%M}.xlsx"

    def iter_bytes():
        yield data

    return StreamingResponse(
        iter_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ─── Manual run ───────────────────────────────────────────────────────────────

@app.post("/run-now")
def run_now(request: Request, reset_all: str = Form("")):
    web_auth.require_cycle(request)
    if web_db.running_run_exists():
        return RedirectResponse(
            "/admin/runs?msg=Un+cycle+est+déjà+en+cours", status_code=303
        )
    if reset_all:
        # "Recommencer à zéro" : on efface la mémoire de traitement + les candidats.
        web_db.reset_processing_state()
    scheduler.add_job(
        web_pipeline.run_pipeline,
        args=["manual"],
        id=f"manual_{datetime.now().timestamp()}",
        misfire_grace_time=None,
    )
    msg = "Cycle+déclenché+(re-scan+complet)" if reset_all else "Cycle+déclenché"
    return RedirectResponse(f"/admin/runs?msg={msg}", status_code=303)


@app.post("/admin/runs/clear")
def admin_runs_clear(request: Request):
    web_auth.require_admin(request)
    if web_pipeline.is_active():
        return RedirectResponse(
            "/admin/runs?msg=Impossible+:+un+cycle+est+en+cours", status_code=303
        )
    r = web_db.wipe_processing_data()
    return RedirectResponse(
        f"/admin/runs?msg=Vidé+:+{r['runs']}+cycle(s)+et+{r['candidates']}+candidat(s)",
        status_code=303,
    )


@app.post("/admin/runs/stop")
def admin_runs_stop(request: Request):
    web_auth.require_cycle(request)
    web_pipeline.request_cancel()
    if web_pipeline.is_active():
        # Un vrai cycle tourne : annulation coopérative (effet après l'email en cours).
        msg = "Arrêt+demandé+(l'email+en+cours+se+termine)"
    else:
        # Aucun cycle actif mais une ligne 'running' subsiste -> orphelin : on nettoie.
        n = web_db.clear_stale_runs()
        msg = "Cycle+bloqué+nettoyé" if n else "Aucun+cycle+en+cours"
    return RedirectResponse(f"/admin/runs?msg={msg}", status_code=303)


# ─── Import Outlook (PST/OST) ───────────────────────────────────────────────────

def _import_dir() -> Path:
    cfg = web_db.settings_to_config(web_db.get_all_settings())
    d = Path(cfg["outlook"]["import_dir"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_import_target(filename: str, server_path: str) -> Path:
    """Résout la cible d'import : chemin serveur libre, sinon fichier du dossier d'import.

    Un `filename` issu de la liste est réduit à son basename (anti-traversée) ; un
    `server_path` explicite (fichier déposé ailleurs, ex. volume monté) est accepté tel quel.
    """
    if server_path.strip():
        return Path(server_path.strip()).expanduser().resolve()
    return (_import_dir() / Path(filename).name).resolve()


@app.get("/admin/import", response_class=HTMLResponse)
def admin_import(request: Request, msg: str = ""):
    web_auth.require_cycle(request)
    d = _import_dir()
    files = []
    for p in sorted(d.glob("*")):
        if p.suffix.lower() in (".pst", ".ost") and p.is_file():
            files.append({"name": p.name, "size_mb": round(p.stat().st_size / (1024 * 1024), 1)})
    return render(
        request, "admin_import.html",
        {
            "msg": msg,
            "files": files,
            "import_dir": str(d),
            "backends": outlook_fetcher.available_backends(),
            "can_move": outlook_fetcher.can_move_messages(),
            "running": web_db.running_run_exists(),
        },
    )


@app.post("/admin/import/upload")
async def admin_import_upload(request: Request, file: UploadFile = File(...)):
    web_auth.require_cycle(request)
    name = Path(file.filename or "").name
    if Path(name).suffix.lower() not in (".pst", ".ost"):
        return RedirectResponse("/admin/import?msg=Fichier+refusé+:+.pst+ou+.ost+attendu",
                                status_code=303)
    dest = _import_dir() / name
    # Écriture en flux (par blocs) : les PST peuvent peser plusieurs Go.
    with open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
    return RedirectResponse(f"/admin/import?msg=Fichier+déposé+:+{name}", status_code=303)


@app.post("/admin/import/test")
def admin_import_test(request: Request, filename: str = Form(""), server_path: str = Form("")):
    web_auth.require_cycle(request)
    target = _resolve_import_target(filename, server_path)
    ok, message = outlook_fetcher.check_file(str(target))
    from urllib.parse import quote
    return RedirectResponse(f"/admin/import?msg={quote(message)}", status_code=303)


@app.post("/admin/import/run")
def admin_import_run(request: Request, filename: str = Form(""), server_path: str = Form("")):
    web_auth.require_cycle(request)
    if web_db.running_run_exists():
        return RedirectResponse("/admin/import?msg=Un+traitement+est+déjà+en+cours",
                                status_code=303)
    target = _resolve_import_target(filename, server_path)
    if not target.exists():
        return RedirectResponse("/admin/import?msg=Fichier+introuvable", status_code=303)
    if target.suffix.lower() not in (".pst", ".ost"):
        return RedirectResponse("/admin/import?msg=Extension+attendue+:+.pst+ou+.ost",
                                status_code=303)
    scheduler.add_job(
        web_pipeline.run_outlook_import,
        args=[str(target)],
        id=f"import_{datetime.now().timestamp()}",
        misfire_grace_time=None,
    )
    return RedirectResponse(
        f"/admin/import?msg=Import+lancé+:+{target.name}+(suivi+dans+Cycles)",
        status_code=303,
    )


@app.post("/admin/import/move")
def admin_import_move(request: Request, filename: str = Form(""),
                      server_path: str = Form(""), target_folder: str = Form("Traités")):
    """Range les mails porteurs d'un CV dans un dossier du PST (win32com/Outlook).

    Opération synchrone (comme « Tester ») : nécessite Outlook installé. On refuse
    si un traitement tourne déjà pour éviter de monter deux fois le même store.
    """
    web_auth.require_cycle(request)
    from urllib.parse import quote
    if web_db.running_run_exists():
        return RedirectResponse(
            "/admin/import?msg=" + quote("Un traitement est en cours — réessayez après."),
            status_code=303,
        )
    target = _resolve_import_target(filename, server_path)
    if not target.exists():
        return RedirectResponse("/admin/import?msg=Fichier+introuvable", status_code=303)
    try:
        _moved, message = outlook_fetcher.move_cv_messages(
            str(target), target_folder=target_folder
        )
    except Exception as e:
        message = f"Déplacement échoué : {e}"
    return RedirectResponse(f"/admin/import?msg={quote(message)}", status_code=303)


# ─── Admin: users ─────────────────────────────────────────────────────────────

@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, msg: str = ""):
    web_auth.require_admin(request)
    users = web_db.list_users()
    return render(request, "admin_users.html", {"users": users, "msg": msg})


@app.post("/admin/users/create")
def admin_users_create(
    request: Request,
    email: str = Form(...),
    name: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    web_auth.require_admin(request)
    if role not in web_db.ROLES:
        raise HTTPException(400, "Rôle invalide")
    # Inclut les comptes désactivés : UNIQUE(email) s'y applique aussi (sinon
    # recréer l'email d'un compte désactivé lèverait une IntegrityError -> 500).
    if web_db.email_exists(email):
        return RedirectResponse(
            "/admin/users?msg=Email+déjà+utilisé", status_code=303
        )
    web_db.create_user(
        email, name, web_auth.hash_password(password), role
    )
    return RedirectResponse("/admin/users?msg=Utilisateur+créé", status_code=303)


@app.post("/admin/users/{uid}/update")
def admin_users_update(
    request: Request, uid: int,
    name: str = Form(...),
    role: str = Form(...),
    active: str = Form("0"),
    password: str = Form(""),
):
    admin = web_auth.require_admin(request)
    if role not in web_db.ROLES:
        raise HTTPException(400)

    target = web_db.get_user_by_id(uid)
    if not target:
        raise HTTPException(404)

    new_active = active == "1"
    if (target["role"] == "admin" and (role != "admin" or not new_active)):
        if web_db.admin_count() <= 1:
            return RedirectResponse(
                "/admin/users?msg=Impossible+:+il+doit+rester+1+admin+actif",
                status_code=303,
            )

    pwd_hash = web_auth.hash_password(password) if password else None
    web_db.update_user(
        uid, name=name, role=role, active=new_active,
        password_hash=pwd_hash,
    )
    return RedirectResponse("/admin/users?msg=Utilisateur+mis+à+jour", status_code=303)


@app.post("/admin/users/{uid}/delete")
def admin_users_delete(request: Request, uid: int):
    admin = web_auth.require_admin(request)
    target = web_db.get_user_by_id(uid)
    if not target:
        raise HTTPException(404)
    if target["id"] == admin["id"]:
        return RedirectResponse(
            "/admin/users?msg=Impossible+de+supprimer+votre+propre+compte",
            status_code=303,
        )
    if target["role"] == "admin" and web_db.admin_count() <= 1:
        return RedirectResponse(
            "/admin/users?msg=Impossible+:+il+doit+rester+1+admin",
            status_code=303,
        )
    web_db.delete_user(uid)
    return RedirectResponse("/admin/users?msg=Utilisateur+supprimé", status_code=303)


@app.post("/admin/users/bulk-delete")
def admin_users_bulk_delete(request: Request, ids: list[int] = Form(default=[])):
    """Suppression en masse. Mêmes garde-fous que la suppression unitaire :
    jamais son propre compte, et il doit toujours rester au moins un admin actif.
    Les comptes protégés sont ignorés (pas d'échec global) et signalés."""
    admin = web_auth.require_admin(request)

    # Cibles réelles (dédupliquées, existantes), en excluant son propre compte.
    demandes = set(ids)
    self_selectionne = admin["id"] in demandes
    demandes.discard(admin["id"])
    cibles = [t for t in (web_db.get_user_by_id(i) for i in demandes) if t]

    # Préserver au moins un admin actif : on ne supprime pas plus d'admins actifs
    # que « total - 1 ». Les admins actifs en trop sont retirés de la sélection.
    admins_actifs_cibles = [t for t in cibles if t["role"] == "admin" and t["active"]]
    supprimables_admin = max(0, web_db.admin_count() - 1)
    ids_proteges: set[int] = set()
    if len(admins_actifs_cibles) > supprimables_admin:
        ids_proteges = {t["id"] for t in admins_actifs_cibles}

    a_supprimer = [t["id"] for t in cibles if t["id"] not in ids_proteges]
    n = web_db.delete_users(a_supprimer)

    parts = [f"{n} utilisateur(s) supprimé(s)"]
    if self_selectionne:
        parts.append("votre compte a été ignoré")
    if ids_proteges:
        parts.append("au moins un admin actif doit rester")
    from urllib.parse import quote
    return RedirectResponse(
        "/admin/users?msg=" + quote(" — ".join(parts)), status_code=303
    )


# ─── Admin: settings ──────────────────────────────────────────────────────────

# --- Onglet « Paramètres Mail » : réception (IMAP), planification, notifications (SMTP)
MAIL_FIELDS = [
    ("imap.host", "Serveur IMAP", "text"),
    ("imap.port", "Port IMAP", "number"),
    ("imap.security", "Sécurité IMAP", "select"),
    ("imap.user", "Utilisateur (email)", "text"),
    ("imap.password", "Mot de passe (ou d'application selon le fournisseur)", "password"),
    ("imap.folder", "Dossier IMAP", "text"),
    ("processing.fetch_since_days", "Profondeur historique (jours)", "number"),
    ("processing.max_emails_per_run", "Max emails / cycle", "number"),
    ("scheduler.interval_minutes", "Intervalle planificateur (min)", "number"),
    ("scheduler.enabled", "Planificateur activé (true/false)", "text"),
    ("notify.enabled", "Notifications email (true/false)", "text"),
    ("notify.recipients", "Destinataires (emails séparés par virgule)", "text"),
    ("entretiens.reminder_enabled", "Rappels d'entretien par email (true/false)", "text"),
    ("entretiens.reminder_hours_before", "Rappel entretien : heures avant", "number"),
    ("smtp.host", "Serveur SMTP", "text"),
    ("smtp.port", "Port SMTP", "number"),
    ("smtp.security", "Sécurité SMTP", "select"),
    ("smtp.user", "Utilisateur SMTP", "text"),
    ("smtp.password", "Mot de passe SMTP", "password"),
    ("smtp.from", "Expéditeur (adresse From)", "text"),
    ("outlook.import_dir", "Import Outlook : dossier serveur (relatif aux données)", "text"),
    ("outlook.backend", "Import Outlook : lecteur (auto / pypff / win32com)", "text"),
]

# --- Onglet « Paramètres LLM » : moteur, modèles, extraction
LLM_FIELDS = [
    ("llm.provider", "Moteur LLM", "select"),
    ("ollama.model", "Modèle Ollama", "text"),
    ("ollama.host", "URL Ollama", "text"),
    ("ollama.timeout_seconds", "Timeout LLM (s)", "number"),
    ("openrouter.base_url", "URL de base API cloud (compatible OpenAI)", "text"),
    ("openrouter.model", "Modèle cloud", "text"),
    ("openrouter.api_key", "Clé API cloud", "password"),
    ("openrouter.timeout_seconds", "Timeout cloud (s)", "number"),
    ("processing.classification_confidence_threshold",
     "Seuil de confiance CV (0-1)", "text"),
    ("processing.pdf_max_chars", "Max chars PDF envoyés au LLM", "number"),
]

_SETTINGS_SECRETS = web_db.SECRET_SETTING_KEYS  # chiffrés au repos (voir secret_store)


def _render_settings(request, fields, section, title, action, msg):
    values = web_db.get_all_settings()
    return render(request, "admin_settings.html", {
        "fields": fields, "values": values, "msg": msg,
        "section": section, "title": title, "action": action,
    })


async def _save_settings(request, fields, redirect_to):
    web_auth.require_admin(request)
    form = await request.form()
    items = {}
    for key, _, _ in fields:
        if key in form:
            items[key] = str(form[key]).strip()
    for secret in _SETTINGS_SECRETS:  # ne pas écraser un secret laissé vide
        if secret in items and items[secret] == "":
            items.pop(secret)
    web_db.set_settings(items)
    reschedule_from_settings()
    return RedirectResponse(f"{redirect_to}?msg=Paramètres+enregistrés", status_code=303)


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings(request: Request):
    web_auth.require_admin(request)
    return RedirectResponse("/admin/settings/mail", status_code=303)


@app.get("/admin/settings/mail", response_class=HTMLResponse)
def admin_settings_mail(request: Request, msg: str = ""):
    web_auth.require_admin(request)
    return _render_settings(request, MAIL_FIELDS, "mail", "Paramètres Mail", "/admin/settings/mail", msg)


@app.get("/admin/settings/llm", response_class=HTMLResponse)
def admin_settings_llm(request: Request, msg: str = ""):
    web_auth.require_admin(request)
    return _render_settings(request, LLM_FIELDS, "llm", "Paramètres LLM", "/admin/settings/llm", msg)


@app.post("/admin/settings/mail")
async def admin_settings_mail_save(request: Request):
    return await _save_settings(request, MAIL_FIELDS, "/admin/settings/mail")


@app.post("/admin/settings/llm")
async def admin_settings_llm_save(request: Request):
    return await _save_settings(request, LLM_FIELDS, "/admin/settings/llm")


@app.post("/admin/settings/test-openrouter", response_class=HTMLResponse)
def admin_test_openrouter(
    request: Request,
    model: str = Form(""),
    api_key: str = Form(""),
):
    web_auth.require_admin(request)
    # Config OpenRouter courante (clé env/base), surchargée par les valeurs du
    # formulaire si elles sont renseignées — permet de tester AVANT d'enregistrer.
    cfg = web_db.settings_to_config(web_db.get_all_settings())
    orc = dict(cfg["llm"]["openrouter"])
    if model.strip():
        orc["model"] = model.strip()
    if api_key.strip():
        orc["api_key"] = api_key.strip()

    ok, message = llm_provider.check_openrouter(orc)
    return _test_result_html(ok, message)


@app.get("/admin/settings/openrouter-models")
def admin_openrouter_models(request: Request):
    """Liste JSON des modèles cloud OpenRouter (pour enrichir la datalist)."""
    web_auth.require_admin(request)
    try:
        modeles = llm_provider.list_cloud_models()
    except Exception as e:  # noqa: BLE001 - réseau indisponible → l'UI garde sa liste figée
        return JSONResponse({"error": str(e)}, status_code=502)
    return JSONResponse({"models": modeles})


@app.post("/admin/settings/test-ollama", response_class=HTMLResponse)
def admin_test_ollama(
    request: Request,
    model: str = Form(""),
    host: str = Form(""),
):
    web_auth.require_admin(request)
    cfg = web_db.settings_to_config(web_db.get_all_settings())
    oc = dict(cfg["llm"]["ollama"])
    if model.strip():
        oc["model"] = model.strip()
    if host.strip():
        oc["host"] = host.strip()
    ok, message = llm_provider.check_ollama(oc)
    return _test_result_html(ok, message)


@app.post("/admin/settings/test-imap", response_class=HTMLResponse)
def admin_test_imap(
    request: Request,
    host: str = Form(""),
    port: str = Form(""),
    security: str = Form(""),
    user: str = Form(""),
    password: str = Form(""),
    folder: str = Form(""),
):
    web_auth.require_admin(request)
    s = web_db.get_all_settings()
    h = host.strip() or s.get("imap.host", "")
    u = user.strip() or s.get("imap.user", "")
    # Champ mot de passe vide (non re-saisi) -> on utilise celui enregistré.
    pw = password.strip() or s.get("imap.password", "")
    f = folder.strip() or s.get("imap.folder", "INBOX")
    sec = security.strip() or s.get("imap.security", "SSL")
    try:
        p = int(port.strip()) if port.strip() else int(s.get("imap.port", "993"))
    except ValueError:
        p = 993
    ok, message = mail_fetcher.check_connection(h, p, u, pw, f, security=sec)
    return _test_result_html(ok, message)


@app.post("/admin/settings/test-smtp", response_class=HTMLResponse)
async def admin_test_smtp(request: Request):
    web_auth.require_admin(request)
    form = await request.form()
    s = web_db.get_all_settings()

    def val(field, default=""):
        # Valeur du formulaire (nom pointé) sinon celle enregistrée.
        v = str(form.get(field, "")).strip()
        return v or s.get(field, default)

    sc = {
        "host": val("smtp.host"),
        "security": val("smtp.security", "TLS"),
        "user": val("smtp.user"),
        "password": val("smtp.password"),
        "from": val("smtp.from"),
    }
    try:
        sc["port"] = int(val("smtp.port", "587"))
    except ValueError:
        sc["port"] = 587

    # Si des destinataires sont saisis, on envoie un vrai email de test ; sinon
    # on teste juste la connexion + l'authentification.
    dest = notifier.parse_recipients(val("notify.recipients"))
    if dest:
        ok, message = notifier.send_email(
            sc, dest, "[CV Agent] Email de test",
            "Ceci est un email de test de CV Agent. Si vous le recevez, la configuration SMTP fonctionne.",
        )
        if ok:
            message = f"Email de test envoyé à {len(dest)} destinataire(s)."
    else:
        ok, message = notifier.check_smtp(sc)
    return _test_result_html(ok, message)


def _test_result_html(ok: bool, message: str) -> HTMLResponse:
    color = "#1a7f37" if ok else "#c1121f"
    icon = "✓" if ok else "✗"
    # message peut contenir du contenu renvoyé par un serveur distant (modèles
    # Ollama, corps d'erreur d'une API) : l'échapper pour éviter une injection HTML.
    safe_message = html.escape(message)
    return HTMLResponse(
        f'<span style="color:{color};font-weight:600">{icon} {safe_message}</span>'
    )


# ─── Admin: runs ──────────────────────────────────────────────────────────────

@app.get("/admin/runs", response_class=HTMLResponse)
def admin_runs(request: Request, msg: str = ""):
    web_auth.require_user(request)
    runs = web_db.list_runs(limit=50)
    last = web_db.last_successful_run()
    running = web_db.running_run_exists()
    return render(
        request, "admin_runs.html",
        {"runs": runs, "last": last, "running": running, "msg": msg},
    )


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    last = web_db.last_successful_run()
    return {
        "status": "ok",
        "last_success": last["finished_at"] if last else None,
        "scheduler_jobs": [j.id for j in scheduler.get_jobs()],
    }
