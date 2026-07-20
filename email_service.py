"""Service d'envoi d'emails aux candidats à partir de modèles paramétrables.

Rend un modèle (substitution des variables {prenom}/{nom}/{poste}), envoie via le
SMTP déjà configuré (réutilise `notifier.send_email` — même API que les rappels
d'entretien) et journalise chaque tentative dans `email_log`. L'envoi exige que le
SMTP soit configuré : sinon un message clair est renvoyé, jamais de crash.

Les emails sont envoyés en texte brut (`notifier` pose `set_content`), la
substitution n'introduit donc pas de HTML ; l'aperçu affiché dans l'UI est rendu
par Jinja (autoescaping actif), aucune donnée n'est injectée en HTML à la main.
"""
import logging
from datetime import datetime

from state_db import connect
import db
import web_db
import notifier

log = logging.getLogger("cv_agent.emails")

# Variables reconnues dans le sujet et le corps d'un modèle.
VARIABLES = ("{prenom}", "{nom}", "{poste}")


# Modèles installés au premier démarrage (idempotent via seed_default_templates).
DEFAULT_TEMPLATES = [
    {
        "cle": "accuse_reception",
        "libelle": "Accusé de réception",
        "sujet": "Bonne réception de votre candidature",
        "corps": (
            "Bonjour {prenom} {nom},\n\n"
            "Nous accusons réception de votre candidature au poste de {poste} et "
            "vous remercions de l'intérêt que vous portez à notre entreprise.\n\n"
            "Votre profil va être étudié avec attention par notre équipe. Nous "
            "reviendrons vers vous dans les meilleurs délais.\n\n"
            "Cordialement,\nLe service des Ressources Humaines"
        ),
    },
    {
        "cle": "relance",
        "libelle": "Relance / demande d'informations",
        "sujet": "Votre candidature au poste de {poste}",
        "corps": (
            "Bonjour {prenom} {nom},\n\n"
            "Nous revenons vers vous concernant votre candidature au poste de "
            "{poste}. Afin de poursuivre l'étude de votre dossier, pourriez-vous "
            "nous faire parvenir les éléments complémentaires nécessaires ?\n\n"
            "Nous restons à votre disposition pour tout renseignement.\n\n"
            "Cordialement,\nLe service des Ressources Humaines"
        ),
    },
    {
        "cle": "convocation",
        "libelle": "Convocation à un entretien",
        "sujet": "Invitation à un entretien — poste de {poste}",
        "corps": (
            "Bonjour {prenom} {nom},\n\n"
            "Suite à l'étude de votre candidature au poste de {poste}, nous avons "
            "le plaisir de vous convier à un entretien.\n\n"
            "Merci de nous confirmer vos disponibilités afin que nous convenions "
            "ensemble d'une date et d'une heure.\n\n"
            "Dans l'attente de votre retour, nous vous prions d'agréer nos "
            "salutations distinguées.\n\n"
            "Le service des Ressources Humaines"
        ),
    },
    {
        "cle": "refus",
        "libelle": "Réponse négative",
        "sujet": "Suite donnée à votre candidature",
        "corps": (
            "Bonjour {prenom} {nom},\n\n"
            "Nous vous remercions de l'intérêt que vous avez porté à notre "
            "entreprise en postulant au poste de {poste}.\n\n"
            "Après une étude attentive de votre dossier, nous ne sommes pas en "
            "mesure de donner une suite favorable à votre candidature. Nous "
            "conservons néanmoins votre profil et ne manquerons pas de vous "
            "recontacter si une opportunité correspondait à votre parcours.\n\n"
            "Nous vous souhaitons une pleine réussite dans vos recherches.\n\n"
            "Cordialement,\nLe service des Ressources Humaines"
        ),
    },
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def seed_default_templates() -> None:
    """Installe les 4 modèles par défaut s'ils n'existent pas. Idempotent.

    À appeler au démarrage (comme `web_db.seed_default_settings`)."""
    now = _now()
    with connect() as conn:
        for t in DEFAULT_TEMPLATES:
            conn.execute(
                "INSERT INTO email_templates (cle, libelle, sujet, corps, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(cle) DO NOTHING",
                (t["cle"], t["libelle"], t["sujet"], t["corps"], now),
            )


def liste_modeles() -> list[dict]:
    """Tous les modèles, triés par libellé."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, cle, libelle, sujet, corps, updated_at "
            "FROM email_templates ORDER BY libelle ASC, cle ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_modele(cle: str) -> dict | None:
    """Un modèle par sa clé, ou None."""
    if not cle:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT id, cle, libelle, sujet, corps, updated_at "
            "FROM email_templates WHERE cle = ?",
            (cle,),
        ).fetchone()
    return dict(row) if row else None


def rendre_modele(modele: dict, candidat: dict) -> tuple[str, str]:
    """Substitue {prenom}/{nom}/{poste} dans (sujet, corps). Renvoie du texte brut.

    Substitution littérale (str.replace) : aucun risque de KeyError si le corps
    contient d'autres accolades, contrairement à str.format.
    """
    mapping = {
        "{prenom}": (candidat.get("prenom") or "").strip(),
        "{nom}": (candidat.get("nom") or "").strip(),
        "{poste}": (candidat.get("poste_recherche") or "").strip(),
    }
    sujet = modele.get("sujet") or ""
    corps = modele.get("corps") or ""
    for var, val in mapping.items():
        sujet = sujet.replace(var, val)
        corps = corps.replace(var, val)
    return sujet, corps


def smtp_configure() -> bool:
    """True si un serveur SMTP est renseigné (condition minimale pour envoyer)."""
    cfg = web_db.settings_to_config(web_db.get_all_settings())
    return bool(cfg["smtp"].get("host"))


def historique(candidate_id: int) -> list[dict]:
    """Journal des emails d'un candidat, les plus récents d'abord."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, candidate_id, template_cle, destinataire, sujet, sent_at, statut "
            "FROM email_log WHERE candidate_id = ? ORDER BY id DESC",
            (candidate_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _journaliser_log(candidate_id, template_cle, destinataire, sujet, statut) -> None:
    """Trace une tentative d'envoi dans email_log."""
    with connect() as conn:
        db.insert_returning_id(
            conn,
            "INSERT INTO email_log "
            "(candidate_id, template_cle, destinataire, sujet, sent_at, statut) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (candidate_id, template_cle, destinataire, sujet, _now(), statut),
        )


def _journaliser_activite(candidate_id, modele, destinataire, ok) -> None:
    """Journalise l'envoi dans la timeline d'activité si un module `activity`
    est présent. Best effort : jamais bloquant si le module/API diffère."""
    try:
        import activity  # module optionnel (timeline candidat)
    except Exception:
        return
    try:
        libelle = modele.get("libelle") or modele.get("cle") or "email"
        etat = "envoyé" if ok else "en échec"
        # log_now : hors transaction, connexion propre, ne lève jamais.
        activity.log_now(
            candidate_id, activity.EMAIL,
            f"Email « {libelle} » {etat}", destinataire,
        )
    except Exception:
        log.debug("Journalisation activité (email) ignorée", exc_info=True)


def envoyer(candidate_id: int, template_cle: str) -> tuple[bool, str]:
    """Rend le modèle avec les champs du candidat, envoie à `candidate.email`,
    journalise dans email_log. Retourne (ok, message).

    Ne lève jamais : toute condition manquante (candidat, email, modèle, SMTP)
    renvoie (False, message clair)."""
    candidat = web_db.get_candidate(candidate_id)
    if not candidat:
        return False, "Candidat introuvable."
    destinataire = (candidat.get("email") or "").strip()
    if not destinataire:
        return False, "Ce candidat n'a pas d'adresse email : envoi impossible."
    modele = get_modele(template_cle)
    if not modele:
        return False, "Modèle d'email introuvable."

    cfg = web_db.settings_to_config(web_db.get_all_settings())
    smtp_cfg = cfg["smtp"]
    if not smtp_cfg.get("host"):
        return False, "SMTP non configuré — renseignez-le dans « Param. Mail »."

    sujet, corps = rendre_modele(modele, candidat)
    ok, msg = notifier.send_email(smtp_cfg, [destinataire], sujet, corps)
    statut = "Envoyé" if ok else "Échec"
    _journaliser_log(candidate_id, template_cle, destinataire, sujet, statut)
    _journaliser_activite(candidate_id, modele, destinataire, ok)
    if ok:
        return True, f"Email « {modele.get('libelle') or template_cle} » envoyé à {destinataire}."
    return False, msg
