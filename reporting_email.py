"""Rapport hebdomadaire de recrutement par email.

Construit un récapitulatif (nouveaux CV sur 7 jours, entretiens à venir,
embauchés, funnel résumé) et l'envoie aux destinataires RH configurés
(`notify.recipients`), via le SMTP configuré (`notifier`). Même modèle que
`entretien_reminders` : best effort, idempotent, ne fait jamais planter le
planificateur.

Réglages consommés :
  - `reporting.hebdo_active` ('true'/'false', défaut 'false') : active l'envoi auto ;
  - `reporting.hebdo_jour`  ('lundi'…'dimanche', défaut 'lundi') : jour d'envoi.

Le job planifié `job_rapport_hebdo()` est armé par le planificateur (voir
`webapp.reschedule_from_settings`) sur un déclencheur hebdomadaire dont le jour
est dérivé de `reporting.hebdo_jour` via `jour_to_cron()`.
"""
import logging
from datetime import datetime, timedelta

from state_db import connect
import web_db
import notifier
import reporting_core

log = logging.getLogger("cv_agent.reporting")

# Correspondance jour français -> jeton `day_of_week` d'APScheduler (CronTrigger).
JOURS_CRON = {
    "lundi": "mon",
    "mardi": "tue",
    "mercredi": "wed",
    "jeudi": "thu",
    "vendredi": "fri",
    "samedi": "sat",
    "dimanche": "sun",
}

# Clé de réglage interne (hors formulaire admin) : mémorise la semaine ISO déjà
# envoyée, pour garantir l'idempotence si le job se déclenche deux fois.
_LAST_SENT_KEY = "reporting.hebdo_last_iso_week"


def jour_to_cron(jour: str) -> str:
    """Convertit un jour français en jeton `day_of_week` (défaut 'mon' si inconnu)."""
    return JOURS_CRON.get((jour or "").strip().lower(), "mon")


def _fmt_date(iso: str) -> str:
    """« YYYY-MM-DD… » -> « JJ/MM/AAAA » (best effort)."""
    s = (iso or "")[:10]
    if len(s) < 10 or s[4] != "-":
        return iso or ""
    return f"{s[8:10]}/{s[5:7]}/{s[:4]}"


def _fmt_dt(iso: str) -> str:
    """« YYYY-MM-DDTHH:MM… » -> « JJ/MM/AAAA à HHhMM » (best effort)."""
    s = (iso or "")[:16]
    if len(s) < 16 or s[10] != "T":
        return _fmt_date(iso)
    return f"{_fmt_date(s)} à {s[11:16].replace(':', 'h')}"


def _iso_semaine(dt: datetime) -> str:
    """Identifiant de semaine ISO « AAAA-Www » (ex. 2026-W30)."""
    y, w, _ = dt.isocalendar()
    return f"{y:04d}-W{w:02d}"


def construire_rapport(conn) -> dict:
    """Assemble les données du rapport hebdo. Fonction pure (lecture seule).

    Renvoie un dict : nouveaux CV 7j, entretiens à venir (7j), KPI, funnel.
    """
    maintenant = datetime.now()
    seuil_7j = (maintenant - timedelta(days=7)).isoformat(timespec="seconds")
    borne_7j = (maintenant + timedelta(days=7)).isoformat(timespec="minutes")
    now_min = maintenant.isoformat(timespec="minutes")

    # Nouveaux CV reçus sur les 7 derniers jours (doublons exclus).
    nouveaux = int(conn.execute(
        "SELECT COUNT(*) AS n FROM candidates "
        "WHERE duplicate_of IS NULL AND received_at >= ?",
        (seuil_7j,),
    ).fetchone()["n"])

    # Entretiens planifiés à venir dans les 7 prochains jours.
    entretiens_rows = conn.execute(
        "SELECT e.date_heure AS date_heure, e.type AS type, "
        "c.nom AS nom, c.prenom AS prenom, c.poste_recherche AS poste "
        "FROM entretiens e JOIN candidates c ON c.id = e.candidate_id "
        "WHERE e.statut = 'Planifié' AND e.date_heure >= ? AND e.date_heure <= ? "
        "ORDER BY e.date_heure ASC",
        (now_min, borne_7j),
    ).fetchall()
    entretiens = [dict(r) for r in entretiens_rows]

    return {
        "date": maintenant,
        "nouveaux_7j": nouveaux,
        "entretiens": entretiens,
        "kpis": reporting_core.kpis(conn),
        "funnel": reporting_core.funnel(conn),
    }


def _corps_texte(rapport: dict) -> tuple[str, str]:
    """Construit (sujet, corps texte) de l'email hebdomadaire."""
    d = rapport["date"]
    sujet = f"[CV Agent] Rapport hebdomadaire — semaine du {d:%d/%m/%Y}"

    kpis = rapport["kpis"]
    lignes = [
        f"Rapport hebdomadaire de recrutement — {d:%d/%m/%Y}",
        "",
        "── Vue d'ensemble ──",
        f"• Nouveaux CV (7 derniers jours) : {rapport['nouveaux_7j']}",
        f"• Candidats au total : {kpis['total']}",
        f"• Embauchés : {kpis['embauches']} ({kpis['taux_embauche']} %)",
        f"• Time-to-hire moyen : "
        + (f"{kpis['time_to_hire_txt']} jours" if kpis["time_to_hire_txt"] != "N/A" else "N/A"),
        "",
        "── Funnel de conversion ──",
    ]
    for s in rapport["funnel"]["steps"]:
        taux = f" (conv. {s['taux']} %)" if s["taux"] is not None else ""
        lignes.append(f"• {s['etape']} : {s['count']}{taux}")

    lignes += ["", "── Entretiens à venir (7 jours) ──"]
    if rapport["entretiens"]:
        for e in rapport["entretiens"]:
            nom = f"{e.get('prenom') or ''} {e.get('nom') or ''}".strip() or "candidat"
            poste = f" — {e['poste']}" if e.get("poste") else ""
            lignes.append(f"• {_fmt_dt(e['date_heure'])} : {nom}{poste}")
    else:
        lignes.append("• Aucun entretien planifié dans les 7 prochains jours.")

    lignes += ["", "— CV Agent"]
    return sujet, "\n".join(lignes)


def job_rapport_hebdo(force: bool = False) -> int:
    """Envoie le rapport hebdomadaire aux destinataires RH. Retourne 1 si envoyé, 0 sinon.

    Best effort : toute anomalie (SMTP absent, aucun destinataire, envoi échoué)
    renvoie 0 sans lever d'erreur. `force=True` ignore le réglage d'activation et
    le garde-fou d'idempotence (déclenchement manuel explicite).
    """
    settings = web_db.get_all_settings()

    if not force and settings.get("reporting.hebdo_active", "false").lower() != "true":
        return 0

    # Garde-fou d'idempotence : une seule fois par semaine ISO (sauf force).
    semaine = _iso_semaine(datetime.now())
    if not force and settings.get(_LAST_SENT_KEY, "") == semaine:
        return 0

    cfg = web_db.settings_to_config(settings)
    smtp_cfg = cfg["smtp"]
    if not smtp_cfg.get("host"):
        return 0  # SMTP non configuré : rien à envoyer
    destinataires = notifier.parse_recipients(cfg["notify"].get("recipients", ""))
    if not destinataires:
        log.info("Rapport hebdo : aucun destinataire RH configuré (notify.recipients).")
        return 0

    with connect() as conn:
        rapport = construire_rapport(conn)

    sujet, corps = _corps_texte(rapport)
    ok, msg = notifier.send_email(smtp_cfg, destinataires, sujet, corps)
    if ok:
        # Mémorise la semaine envoyée (idempotence). Non bloquant en cas d'échec.
        try:
            web_db.set_settings({_LAST_SENT_KEY: semaine})
        except Exception as e:  # noqa: BLE001
            log.warning("Rapport hebdo : mémorisation de la semaine échouée : %s", e)
        log.info("Rapport hebdo envoyé à %d destinataire(s) (%s).", len(destinataires), msg)
        return 1

    log.warning("Rapport hebdo NON envoyé : %s", msg)
    return 0
