"""Rappels d'entretien par email : envoi automatique X heures avant l'échéance.

Appelé périodiquement par le planificateur (APScheduler, voir webapp). Idempotent
grâce à la colonne `entretiens.reminder_sent` : un rappel n'est envoyé qu'une
fois. Réutilise le SMTP configuré (`notifier`). Best effort : un échec réseau est
journalisé sans jamais faire planter le planificateur.
"""
import logging
from datetime import datetime, timedelta

from state_db import connect
import web_db
import notifier

log = logging.getLogger("cv_agent.reminders")


def _fmt_dt(iso: str) -> str:
    """Formatte « YYYY-MM-DDTHH:MM[:SS] » en « JJ/MM/AAAA à HHhMM » (best effort)."""
    s = (iso or "")[:16]
    if len(s) < 16 or s[10] != "T":
        return iso or ""
    date, heure = s[:10], s[11:16]
    return f"{date[8:10]}/{date[5:7]}/{date[:4]} à {heure.replace(':', 'h')}"


def envoyer_rappels_dus(force: bool = False) -> int:
    """Envoie les rappels des entretiens Planifiés dont l'échéance approche.

    Fenêtre : maintenant ≤ date_heure ≤ maintenant + N heures (N = réglage
    `entretiens.reminder_hours_before`). Marque `reminder_sent = 1` après envoi.
    Destinataires : le candidat (si email connu) + les destinataires RH configurés.
    Retourne le nombre de rappels effectivement envoyés.

    `force=True` (bouton « Envoyer maintenant ») ignore le réglage d'activation
    automatique : l'administrateur déclenche explicitement l'envoi. SMTP reste requis.
    """
    settings = web_db.get_all_settings()
    if not force and settings.get("entretiens.reminder_enabled", "true").lower() != "true":
        return 0
    try:
        heures = max(0, int(settings.get("entretiens.reminder_hours_before", "24")))
    except (ValueError, TypeError):
        heures = 24

    cfg = web_db.settings_to_config(settings)
    smtp_cfg = cfg["smtp"]
    if not smtp_cfg.get("host"):
        return 0  # SMTP non configuré : rien à envoyer
    rh_recipients = notifier.parse_recipients(cfg["notify"].get("recipients", ""))

    maintenant = datetime.now()
    debut = maintenant.isoformat(timespec="minutes")
    borne = (maintenant + timedelta(hours=heures)).isoformat(timespec="minutes")

    with connect() as conn:
        rows = conn.execute(
            "SELECT e.id AS id, e.date_heure AS date_heure, e.type AS type, "
            "e.lieu AS lieu, e.notes AS notes, "
            "c.nom AS nom, c.prenom AS prenom, c.email AS email, "
            "c.poste_recherche AS poste "
            "FROM entretiens e JOIN candidates c ON c.id = e.candidate_id "
            "WHERE e.statut = 'Planifié' AND e.reminder_sent = 0 "
            "AND e.date_heure >= ? AND e.date_heure <= ? "
            "ORDER BY e.date_heure ASC",
            (debut, borne),
        ).fetchall()
        dus = [dict(r) for r in rows]

    envoyes = 0
    for e in dus:
        destinataires = list(rh_recipients)
        if e.get("email"):
            destinataires.append((e["email"] or "").strip())
        # Déduplication en préservant l'ordre ; on ignore les valeurs vides.
        destinataires = list(dict.fromkeys(d for d in destinataires if d))
        if not destinataires:
            continue

        nom = f"{e.get('prenom') or ''} {e.get('nom') or ''}".strip() or "le candidat"
        quand = _fmt_dt(e["date_heure"])
        sujet = f"[CV Agent] Rappel d'entretien — {nom} — {quand}"
        lignes = [f"Rappel : un entretien est prévu {quand}.", "", f"Candidat : {nom}"]
        if e.get("poste"):
            lignes.append(f"Poste : {e['poste']}")
        if e.get("type"):
            lignes.append(f"Type : {e['type']}")
        if e.get("lieu"):
            lignes.append(f"Lieu / lien : {e['lieu']}")
        if e.get("notes"):
            lignes += ["", f"Notes : {e['notes']}"]
        lignes += ["", "— CV Agent"]

        ok, msg = notifier.send_email(smtp_cfg, destinataires, sujet, "\n".join(lignes))
        if ok:
            with connect() as conn:
                conn.execute(
                    "UPDATE entretiens SET reminder_sent = 1 WHERE id = ?", (e["id"],)
                )
            envoyes += 1
            log.info("Rappel entretien #%s envoyé (%s).", e["id"], msg)
        else:
            log.warning("Rappel entretien #%s NON envoyé : %s", e["id"], msg)

    return envoyes
