"""Module « RGPD » : export (portabilité), suppression (effacement) et purge.

Routeur isolé (importé par webapp via `include_router`). Trois usages :

  - page d'administration `/admin/rgpd` : rétention, compteur d'éligibles, purge ;
  - export JSON d'un candidat `/candidate/{cid}/rgpd/export` (portabilité) ;
  - suppression définitive d'un candidat `/candidate/{cid}/rgpd/supprimer`.

La suppression et la purge sont DESTRUCTRICES et réservées aux administrateurs.
"""
import json

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, Response

from web_core import require_user, require_admin, render
import web_db
import rgpd

router = APIRouter()


def _retention_mois() -> int:
    """Durée de rétention configurée (en mois) ; 0 = désactivée / valeur invalide."""
    try:
        return int(web_db.get_all_settings().get("rgpd.retention_mois", "0"))
    except (ValueError, TypeError):
        return 0


def _purge_auto_active() -> bool:
    return web_db.get_all_settings().get("rgpd.purge_auto_active", "false").lower() == "true"


@router.get("/admin/rgpd")
def page_rgpd(request: Request, msg: str = ""):
    """Page d'administration RGPD : réglages, compteur d'éligibles, purge manuelle."""
    require_admin(request)
    mois = _retention_mois()
    eligibles = rgpd.compter_eligibles(mois) if mois > 0 else 0
    return render(request, "rgpd_admin.html", {
        "retention_mois": mois,
        "purge_auto_active": _purge_auto_active(),
        "eligibles": eligibles,
        "msg": msg,
    })


@router.post("/admin/rgpd/purge")
def lancer_purge(request: Request):
    """Lance la purge manuelle des candidats dépassant la rétention configurée."""
    require_admin(request)
    from urllib.parse import quote
    mois = _retention_mois()
    if mois <= 0:
        return RedirectResponse(
            "/admin/rgpd?msg=" + quote(
                "Rétention désactivée (0 mois) — définissez-la dans Param. Mail avant de purger."
            ),
            status_code=303,
        )
    n = rgpd.purger_anciens(mois)
    return RedirectResponse(
        "/admin/rgpd?msg=" + quote(f"Purge effectuée : {n} candidat(s) supprimé(s)."),
        status_code=303,
    )


@router.get("/candidate/{cid}/rgpd/export")
def exporter_candidat(request: Request, cid: int):
    """Télécharge toutes les données d'un candidat en JSON (droit à la portabilité)."""
    require_user(request)
    data = rgpd.export_candidat(cid)
    if data is None:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    # default=str : sérialise sans planter d'éventuels types non-JSON (dates, Decimal…).
    contenu = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    return Response(
        content=contenu,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="candidat_{cid}_rgpd.json"'
        },
    )


@router.post("/candidate/{cid}/rgpd/supprimer")
def supprimer_candidat(request: Request, cid: int):
    """Suppression DÉFINITIVE d'un candidat et de toutes ses données (réservé admin)."""
    require_admin(request)
    from urllib.parse import quote
    if not rgpd.supprimer_candidat(cid):
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    return RedirectResponse(
        "/?msg=" + quote(f"Candidat #{cid} supprimé définitivement (RGPD)."),
        status_code=303,
    )
