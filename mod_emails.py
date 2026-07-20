"""Module « Emails candidats » : envoi d'emails depuis la fiche candidat à partir
de modèles paramétrables, + CRUD administrateur des modèles. Routeur isolé.

Importe uniquement depuis `web_core` / `web_auth` (jamais `webapp`, pour éviter
tout import circulaire). `webapp` se contente d'inclure `router`.
"""
from datetime import datetime

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from web_core import require_user, require_admin, render, connect
from web_auth import require_write
import web_db
import email_service

router = APIRouter()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _fragment(request: Request, cid: int, selection: str = "",
              flash: str = "", flash_ok: bool = True):
    """Rend le fragment « Emails » d'un candidat (choix modèle + aperçu + historique)."""
    candidat = web_db.get_candidate(cid) or {}
    destinataire = (candidat.get("email") or "").strip()
    modeles = email_service.liste_modeles()
    if not selection and modeles:
        selection = modeles[0]["cle"]
    modele = email_service.get_modele(selection) if selection else None
    sujet_rendu, corps_rendu = ("", "")
    if modele:
        sujet_rendu, corps_rendu = email_service.rendre_modele(modele, candidat)
    return render(request, "_candidate_emails.html", {
        "cid": cid,
        "destinataire": destinataire,
        "modeles": modeles,
        "selection": selection,
        "sujet_rendu": sujet_rendu,
        "corps_rendu": corps_rendu,
        "historique": email_service.historique(cid),
        "smtp_ok": email_service.smtp_configure(),
        "flash": flash,
        "flash_ok": flash_ok,
    })


@router.get("/candidate/{cid}/emails")
def candidate_emails(request: Request, cid: int):
    """Fragment « Emails » : sélecteur de modèle, aperçu et historique des envois."""
    require_user(request)
    return _fragment(request, cid)


@router.get("/candidate/{cid}/emails/apercu")
def candidate_emails_apercu(request: Request, cid: int, template_cle: str = ""):
    """Aperçu (sujet + corps rendus) du modèle sélectionné, pour le candidat."""
    require_user(request)
    candidat = web_db.get_candidate(cid) or {}
    modele = email_service.get_modele(template_cle)
    sujet_rendu, corps_rendu = ("", "")
    if modele:
        sujet_rendu, corps_rendu = email_service.rendre_modele(modele, candidat)
    return render(request, "_email_apercu.html", {
        "sujet_rendu": sujet_rendu,
        "corps_rendu": corps_rendu,
    })


@router.post("/candidate/{cid}/emails/envoyer")
def candidate_emails_envoyer(request: Request, cid: int,
                             template_cle: str = Form("")):
    """Rend le modèle avec les champs du candidat, envoie, journalise, puis renvoie
    le fragment à jour (historique inclus)."""
    require_write(request)
    cle = (template_cle or "").strip()
    ok, msg = email_service.envoyer(cid, cle)
    return _fragment(request, cid, selection=cle, flash=msg, flash_ok=ok)


# ─── Administration des modèles ───────────────────────────────────────────────

@router.get("/admin/emails-modeles")
def admin_emails(request: Request, msg: str = ""):
    """Page d'administration : liste et édition des modèles d'email."""
    require_admin(request)
    return render(request, "emails_admin.html", {
        "modeles": email_service.liste_modeles(),
        "variables": email_service.VARIABLES,
        "msg": msg,
    })


@router.post("/admin/emails-modeles")
def admin_emails_save(request: Request,
                      action: str = Form("enregistrer"),
                      cle: str = Form(""),
                      libelle: str = Form(""),
                      sujet: str = Form(""),
                      corps: str = Form("")):
    """Crée/met à jour (upsert par `cle`) ou supprime un modèle d'email."""
    require_admin(request)
    cle = (cle or "").strip()
    if not cle:
        return RedirectResponse(
            "/admin/emails-modeles?msg=Clé+obligatoire", status_code=303
        )
    if action == "supprimer":
        with connect() as conn:
            conn.execute("DELETE FROM email_templates WHERE cle = ?", (cle,))
        return RedirectResponse(
            "/admin/emails-modeles?msg=Modèle+supprimé", status_code=303
        )
    with connect() as conn:
        conn.execute(
            "INSERT INTO email_templates (cle, libelle, sujet, corps, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(cle) DO UPDATE SET libelle = excluded.libelle, "
            "sujet = excluded.sujet, corps = excluded.corps, "
            "updated_at = excluded.updated_at",
            (cle, (libelle or "").strip(), sujet or "", corps or "", _now()),
        )
    return RedirectResponse(
        "/admin/emails-modeles?msg=Modèle+enregistré", status_code=303
    )
