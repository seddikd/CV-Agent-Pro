"""Notifications email par SMTP.

Gère les 3 modes de connexion : SSL (implicite), TLS (STARTTLS), None (clair).
Utilisé pour prévenir des destinataires quand de nouveaux candidats sont détectés.
"""

import logging
import re
import smtplib
import ssl
from email.message import EmailMessage


log = logging.getLogger("cv_agent.notify")


def parse_recipients(raw: str) -> list[str]:
    """Liste d'emails depuis une saisie séparée par virgule / point-virgule / retour."""
    return [r.strip() for r in re.split(r"[,;\n]", raw or "") if r.strip()]


def _connect(sc: dict) -> smtplib.SMTP:
    host = sc.get("host") or ""
    port = int(sc.get("port") or 0)
    security = (sc.get("security") or "none").lower()
    timeout = 20

    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)
        if security == "tls":
            server.starttls(context=ssl.create_default_context())
    if sc.get("user") and sc.get("password"):
        server.login(sc["user"], sc["password"])
    return server


def check_smtp(sc: dict) -> tuple[bool, str]:
    """Test de connexion (+ auth) SMTP. Retourne (ok, message)."""
    if not sc.get("host"):
        return False, "Serveur SMTP requis."
    try:
        server = _connect(sc)
        try:
            server.noop()
        finally:
            server.quit()
        return True, f"Connexion réussie ({sc.get('security', 'none').upper()})."
    except smtplib.SMTPAuthenticationError:
        return False, "Authentification refusée (utilisateur / mot de passe)."
    except (smtplib.SMTPException, OSError) as e:
        return False, f"Échec de connexion : {e}"


def send_email(sc: dict, recipients: list[str], subject: str, body_text: str) -> tuple[bool, str]:
    if not recipients:
        return False, "Aucun destinataire."
    if not sc.get("host"):
        return False, "Serveur SMTP non configuré."
    sender = sc.get("from") or sc.get("user") or "cv-agent@localhost"
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body_text)
    try:
        server = _connect(sc)
        try:
            server.send_message(msg)
        finally:
            server.quit()
        return True, f"Envoyé à {len(recipients)} destinataire(s)."
    except Exception as e:  # noqa: BLE001 - on veut ne jamais faire planter le pipeline
        log.warning("Envoi SMTP échoué : %s", e)
        return False, f"Échec envoi : {e}"


def notify_new_candidates(notify_cfg: dict, smtp_cfg: dict, candidates: list[dict]) -> None:
    """Envoie un email récapitulatif si des candidats ont été détectés."""
    if not notify_cfg.get("enabled") or not candidates:
        return
    recipients = parse_recipients(notify_cfg.get("recipients", ""))
    if not recipients:
        return
    n = len(candidates)
    subject = f"[CV Agent] {n} nouveau{'x' if n > 1 else ''} candidat{'s' if n > 1 else ''}"
    lines = [f"{n} nouveau(x) candidat(s) détecté(s) :", ""]
    for c in candidates:
        prenom = c.get("prenom") or ""
        nom = c.get("nom") or ""
        poste = c.get("poste_recherche") or "poste non précisé"
        exp = c.get("annees_experience")
        exp_txt = f"{exp} ans d'exp." if exp is not None else "exp. n/c"
        lines.append(f"• {prenom} {nom} — {poste} ({exp_txt})")
    lines += ["", "— CV Agent"]
    ok, msg = send_email(smtp_cfg, recipients, subject, "\n".join(lines))
    log.info("Notification candidats : %s", msg)
