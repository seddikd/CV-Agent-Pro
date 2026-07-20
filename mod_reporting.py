"""Module « Reporting » : funnel de conversion + KPI + temps par étape. Routeur isolé.

Page unique (`GET /reporting`) qui agrège les indicateurs de recrutement via les
fonctions pures de `reporting_core`. Aucune écriture : consultation seule.
Le rapport hebdomadaire par email vit dans `reporting_email` (job planifié).
"""
from fastapi import APIRouter, Request

from web_core import require_user, render, connect
import reporting_core

router = APIRouter()


@router.get("/reporting")
def page_reporting(request: Request):
    """Page complète : KPI, funnel de conversion (barres CSS), temps par étape."""
    user = require_user(request)
    # Une seule connexion partagée pour les trois agrégations (moins d'aller-retour).
    with connect() as conn:
        kpis = reporting_core.kpis(conn)
        funnel = reporting_core.funnel(conn)
        temps = reporting_core.temps_par_etape(conn)

    return render(request, "reporting.html", {
        "kpis": kpis,
        "funnel": funnel,
        "temps": temps,
    })
