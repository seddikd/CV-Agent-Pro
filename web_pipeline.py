"""Cœur du pipeline : relève des mails, classification, extraction, stockage SQLite.

Autonome (appelable depuis la CLI ou depuis le planificateur FastAPI)."""

import logging
import threading
from datetime import datetime

import state_db
import web_db
import mail_fetcher
import outlook_fetcher
import pdf_extractor
import llm_classifier
import llm_extractor
import notifier
import alerts_engine


log = logging.getLogger("cv_agent.pipeline")

# Drapeau d'annulation coopérative : posé par le bouton "Arrêter", vérifié entre
# chaque email (l'arrêt prend effet après l'email en cours de traitement).
_cancel_event = threading.Event()

# Posé UNIQUEMENT tant qu'un cycle tourne réellement dans ce process. Permet de
# distinguer un vrai cycle en cours d'une ligne 'running' orpheline (app fermée
# pendant un cycle) que le bouton Arrêter doit nettoyer directement.
_active_event = threading.Event()

# Verrou process : garantit l'invariant « un seul cycle à la fois ». APScheduler
# exécute le job planifié ET le job « Lancer maintenant » (ids distincts) dans le
# même pool de threads : max_instances=1 ne dédoublonne qu'un job vis-à-vis de
# lui-même, pas entre deux ids. Sans ce verrou, deux cycles pouvaient démarrer en
# parallèle (SQLite « database is locked », deux lignes 'running', drapeaux
# _active_event/_cancel_event corrompus).
_run_lock = threading.Lock()


def request_cancel() -> None:
    _cancel_event.set()


def is_active() -> bool:
    """True si un cycle s'exécute réellement dans ce process."""
    return _active_event.is_set()


def _process_email(email, cfg: dict, folder: str | None = None) -> bool:
    """Retourne un dict-résumé du candidat si c'est un CV stocké, sinon None.

    Un id candidat et le fichier PDF définitif ne sont créés QU'APRÈS confirmation
    que le document est bien un CV (classification OK) ET extraction réussie :
    sinon on ne consomme pas d'id et on ne laisse aucun fichier orphelin. Le
    fichier temporaire d'extraction est toujours supprimé (bloc finally).

    `folder` sert de clé de dédup (table `processed_emails`) : IMAP -> dossier IMAP ;
    import PST/OST -> étiquette propre au fichier (voir `outlook_fetcher.folder_label`).
    """
    uid = email.uid
    folder = folder or cfg["imap"]["folder"]
    now_iso = datetime.now().isoformat(timespec="seconds")
    # Conservé sur CHAQUE marquage, CV ou non : c'est la seule clé qui permettra de
    # retrouver ce mail dans la boîte Outlook vivante (« Ranger les traités »).
    msgid = getattr(email, "message_id", "") or None

    if not email.attachments:
        log.info("[%s] pas de pièce jointe exploitable", uid)
        state_db.mark_processed(uid, folder, now_iso, is_cv=False, notes="no_attachment",
                                message_id=msgid)
        return None

    primary_att = email.attachments[0]
    storage = cfg["paths"]["pdf_storage"]
    # Fichier temporaire (sans id) : sert uniquement à l'extraction de texte. Le
    # fichier définitif « idNNNN_… » n'est écrit que si c'est un CV confirmé.
    tmp_path = mail_fetcher.save_attachment(primary_att, storage, prefix="tmp")
    try:
        cv_text = pdf_extractor.extract_text(tmp_path, cfg["processing"]["pdf_max_chars"])
        if not cv_text:
            log.warning("[%s] aucun texte extractible", uid)
            state_db.mark_processed(
                uid, folder, now_iso, is_cv=False,
                notes="no_text_in_attachment", message_id=msgid,
            )
            return None

        llm_cfg = cfg["llm"]
        classification = llm_classifier.classify(
            llm_cfg,
            subject=email.subject,
            body_text=email.body_text,
            attachment_text=cv_text,
        )
        log.info(
            "[%s] classification: is_cv=%s confidence=%.2f",
            uid, classification.is_cv, classification.confidence,
        )

        threshold = cfg["processing"]["classification_confidence_threshold"]
        if not classification.is_cv or classification.confidence < threshold:
            state_db.mark_processed(
                uid, folder, now_iso, is_cv=False,
                notes=f"non_cv: {classification.reason[:100]}", message_id=msgid,
            )
            return None

        # Arrêt demandé pendant la classification : on saute l'extraction (2e appel
        # LLM, lent) et on ne marque PAS l'email traité -> repris au prochain cycle.
        if _cancel_event.is_set():
            log.info("[%s] arrêt demandé — extraction sautée (sera repris)", uid)
            return None

        extraction = llm_extractor.extract(
            llm_cfg,
            cv_text=cv_text,
            email_subject=email.subject,
        )

        # CV confirmé + extraction réussie : on alloue l'id et on écrit le fichier
        # définitif. En cas d'échec avant ce point, aucun id/fichier n'est consommé.
        candidate_id = state_db.next_candidate_id()
        saved_path = mail_fetcher.save_attachment(
            primary_att, storage, prefix=f"id{candidate_id:04d}"
        )
        log.info("[%s] pièce jointe enregistrée -> %s", uid, saved_path.name)

        expediteur = (
            f"{email.from_name} <{email.from_addr}>" if email.from_name else email.from_addr
        )
        web_db.insert_candidate(
            candidate_id=candidate_id,
            received_at=email.received_at,
            expediteur=expediteur,
            extraction=extraction,
            pdf_filename=saved_path.name,
            pdf_path=str(saved_path.resolve()),
        )
        state_db.mark_processed(
            uid, folder, now_iso, is_cv=True,
            candidate_id=candidate_id, notes="ok", message_id=msgid,
        )
        log.info("[%s] TERMINÉ candidate_id=%d", uid, candidate_id)
        return {
            "id": candidate_id,
            "nom": extraction.nom,
            "prenom": extraction.prenom,
            "poste_recherche": extraction.poste_recherche,
            "annees_experience": extraction.annees_experience,
        }
    finally:
        # Le fichier temporaire n'a servi qu'à l'extraction : toujours le supprimer.
        tmp_path.unlink(missing_ok=True)


def run_pipeline(triggered_by: str = "scheduler") -> dict:
    """Un cycle complet. Retourne un petit dict-résumé."""
    state_db.init()

    # Verrou non bloquant : si un cycle tourne déjà dans ce process, on abandonne
    # immédiatement (le job planifié et « Lancer maintenant » ne peuvent pas se
    # chevaucher). Le verrou est relâché dans le finally.
    if not _run_lock.acquire(blocking=False):
        log.warning("Cycle déjà en cours (verrou process) — ignoré")
        return {"skipped": True, "reason": "already_running"}
    try:
        return _run_pipeline_locked(triggered_by)
    finally:
        _run_lock.release()


def _run_pipeline_locked(triggered_by: str) -> dict:
    """Corps du cycle, exécuté sous _run_lock (un seul cycle à la fois)."""
    if web_db.running_run_exists():
        log.warning("Pipeline already running, skipping")
        return {"skipped": True, "reason": "already_running"}

    settings = web_db.get_all_settings()
    cfg = web_db.settings_to_config(settings)

    if not cfg["imap"]["user"] or not cfg["imap"]["password"]:
        log.error("Identifiants IMAP non configurés")
        return {"skipped": True, "reason": "no_imap_credentials"}

    run_id = web_db.create_run(triggered_by=triggered_by)
    log.info("=== Run %d started (triggered_by=%s) ===", run_id, triggered_by)
    _cancel_event.clear()  # repartir d'un état non-annulé
    _active_event.set()

    try:
        emails = mail_fetcher.fetch_new_emails(
            host=cfg["imap"]["host"],
            port=cfg["imap"]["port"],
            user=cfg["imap"]["user"],
            password=cfg["imap"]["password"],
            folder=cfg["imap"]["folder"],
            security=cfg["imap"]["security"],
            since_days=cfg["processing"]["fetch_since_days"],
            max_emails=cfg["processing"]["max_emails_per_run"],
            already_processed=lambda uid: state_db.is_processed(
                uid, cfg["imap"]["folder"]
            ),
        )
        web_db.update_run(run_id, emails_fetched=len(emails))
        log.info("Run %d: %d new emails to process", run_id, len(emails))

        cvs = 0
        new_candidates = []
        cancelled = False
        for email in emails:
            if _cancel_event.is_set():
                cancelled = True
                log.info("Run %d: arrêt demandé par l'utilisateur", run_id)
                break
            try:
                candidate = _process_email(email, cfg)
                if candidate:
                    cvs += 1
                    new_candidates.append(candidate)
            except Exception as e:
                # On marque l'email comme traité (en erreur) pour NE PAS le reprendre
                # à chaque cycle : sinon boucle infinie qui regaspille id/fichier/quota
                # LLM. Pour forcer une reprise : bouton « Recommencer à zéro ».
                log.exception("[%s] échec du traitement : %s", email.uid, e)
                try:
                    state_db.mark_processed(
                        email.uid, cfg["imap"]["folder"],
                        datetime.now().isoformat(timespec="seconds"),
                        is_cv=False, notes=f"erreur: {str(e)[:150]}",
                        message_id=getattr(email, "message_id", "") or None,
                    )
                except Exception as e2:
                    log.warning("[%s] marquage 'traité' impossible : %s", email.uid, e2)

        # Alertes : les nouveaux CV correspondent-ils à des offres publiées ? Calcul
        # groupé (une seule connexion, offres chargées une fois) après la boucle.
        new_alerts = []
        try:
            new_alerts = alerts_engine.generer_alertes_pour_candidats(
                [c["id"] for c in new_candidates]
            )
        except Exception as e:
            log.warning("Alertes : %s", e)

        # Notifications email (best effort — ne doivent jamais faire échouer le cycle).
        try:
            notifier.notify_new_candidates(cfg["notify"], cfg["smtp"], new_candidates)
        except Exception as e:
            log.warning("Notification échouée : %s", e)
        try:
            alerts_engine.notifier_alertes(cfg["notify"], cfg["smtp"], new_alerts)
        except Exception as e:
            log.warning("Notification alertes échouée : %s", e)

        web_db.update_run(
            run_id, status="cancelled" if cancelled else "success",
            cvs_detected=cvs, finished=True,
        )
        log.info(
            "=== Run %d %s (CVs detected=%d) ===",
            run_id, "annulé" if cancelled else "finished", cvs,
        )
        return {
            "run_id": run_id, "emails_fetched": len(emails),
            "cvs_detected": cvs, "cancelled": cancelled,
        }

    except Exception as e:
        log.exception("Run %d failed: %s", run_id, e)
        web_db.update_run(
            run_id, status="failed",
            error=str(e)[:500], finished=True,
        )
        return {"run_id": run_id, "error": str(e)}
    finally:
        _active_event.clear()


# ─── Import ponctuel depuis un fichier Outlook PST/OST ───────────────────────────

def run_outlook_import(path: str, backend: str | None = None,
                       triggered_by: str = "import_outlook") -> dict:
    """Importe les CV d'un fichier PST/OST en réutilisant tout le pipeline.

    Même invariant que le cycle IMAP : un seul traitement à la fois (verrou process),
    annulation coopérative, ligne `runs` pour le suivi. La dédup utilise une étiquette
    de dossier propre au fichier pour ne pas télescoper l'historique IMAP.
    """
    state_db.init()
    if not _run_lock.acquire(blocking=False):
        log.warning("Traitement déjà en cours (verrou process) — import ignoré")
        return {"skipped": True, "reason": "already_running"}
    try:
        return _run_outlook_import_locked(path, backend, triggered_by)
    finally:
        _run_lock.release()


def _run_outlook_import_locked(path: str, backend: str | None, triggered_by: str) -> dict:
    if web_db.running_run_exists():
        log.warning("Traitement déjà en cours, import ignoré")
        return {"skipped": True, "reason": "already_running"}

    settings = web_db.get_all_settings()
    cfg = web_db.settings_to_config(settings)
    label = outlook_fetcher.folder_label(path)

    run_id = web_db.create_run(triggered_by=triggered_by)
    log.info("=== Import %d démarré (%s) ===", run_id, path)
    _cancel_event.clear()
    _active_event.set()

    try:
        emails = outlook_fetcher.fetch_emails(
            path=path,
            max_emails=cfg["processing"]["max_emails_per_run"],
            already_processed=lambda uid: state_db.is_processed(uid, label),
            backend=backend or cfg["outlook"]["backend"],
        )
        web_db.update_run(run_id, emails_fetched=len(emails))
        log.info("Import %d : %d message(s) à traiter", run_id, len(emails))

        cvs = 0
        new_candidates = []
        cancelled = False
        for email in emails:
            if _cancel_event.is_set():
                cancelled = True
                log.info("Import %d : arrêt demandé par l'utilisateur", run_id)
                break
            try:
                candidate = _process_email(email, cfg, folder=label)
                if candidate:
                    cvs += 1
                    new_candidates.append(candidate)
            except Exception as e:
                log.exception("[%s] échec du traitement : %s", email.uid, e)
                try:
                    state_db.mark_processed(
                        email.uid, label,
                        datetime.now().isoformat(timespec="seconds"),
                        is_cv=False, notes=f"erreur: {str(e)[:150]}",
                        message_id=getattr(email, "message_id", "") or None,
                    )
                except Exception as e2:
                    log.warning("[%s] marquage 'traité' impossible : %s", email.uid, e2)

        new_alerts = []
        try:
            new_alerts = alerts_engine.generer_alertes_pour_candidats(
                [c["id"] for c in new_candidates]
            )
        except Exception as e:
            log.warning("Alertes : %s", e)

        try:
            notifier.notify_new_candidates(cfg["notify"], cfg["smtp"], new_candidates)
        except Exception as e:
            log.warning("Notification échouée : %s", e)
        try:
            alerts_engine.notifier_alertes(cfg["notify"], cfg["smtp"], new_alerts)
        except Exception as e:
            log.warning("Notification alertes échouée : %s", e)

        web_db.update_run(
            run_id, status="cancelled" if cancelled else "success",
            cvs_detected=cvs, finished=True,
        )
        log.info("=== Import %d %s (CVs détectés=%d) ===",
                 run_id, "annulé" if cancelled else "terminé", cvs)
        return {
            "run_id": run_id, "emails_fetched": len(emails),
            "cvs_detected": cvs, "cancelled": cancelled,
        }

    except Exception as e:
        log.exception("Import %d échoué : %s", run_id, e)
        web_db.update_run(run_id, status="failed", error=str(e)[:500], finished=True)
        return {"run_id": run_id, "error": str(e)}
    finally:
        _active_event.clear()
