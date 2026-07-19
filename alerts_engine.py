"""Moteur d'alertes : détecte les candidats correspondant fortement à une offre.

Appelé depuis le pipeline (à chaque nouveau CV) et depuis la page /alertes
(recalcul global). Réutilise le scoring déterministe de `matching_core` et le
`notifier` SMTP existant. Aucune dépendance à FastAPI.
"""

import logging
from datetime import datetime

import db
from state_db import connect
from matching_core import score_candidat, titre_pertinent
import notifier


log = logging.getLogger("cv_agent.alerts")

# Score minimal (0-100) au-delà duquel une correspondance déclenche une alerte.
SEUIL_ALERTE = 60


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _offres_publiees(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM jobs WHERE statut = ? ORDER BY id", ("Publiée",)
    ).fetchall()
    return [dict(r) for r in rows]


def _inserer_alerte(conn, candidate_id: int, job_id: int, score: int) -> bool:
    """Insère une alerte (dédupliquée). Retourne True si une ligne a été créée."""
    cur = conn.execute(
        "INSERT INTO alerts (candidate_id, job_id, score, created_at, seen) "
        "VALUES (?, ?, ?, ?, 0) "
        "ON CONFLICT (candidate_id, job_id) DO NOTHING",
        (candidate_id, job_id, score, _now()),
    )
    return cur.rowcount > 0


def _generer_pour_candidat(conn, cand: dict, offres: list[dict]) -> list[dict]:
    """Score un candidat (déjà chargé) vs les offres fournies ; crée les alertes ≥ seuil.

    Cœur réutilisable : la connexion et la liste d'offres sont fournies par
    l'appelant, ce qui évite de rouvrir une connexion / re-requêter les offres à
    chaque candidat (cf. traitement par lot).
    """
    nouvelles = []
    for job in offres:
        # Même filtre de pertinence que le matching : pas d'alerte pour un
        # candidat sans rapport avec le titre de l'offre.
        if not titre_pertinent(job, cand):
            continue
        res = score_candidat(job, cand)
        if res["score"] >= SEUIL_ALERTE:
            if _inserer_alerte(conn, cand["id"], job["id"], res["score"]):
                nouvelles.append({
                    "candidate_id": cand["id"],
                    "candidate_nom": f"{cand.get('prenom') or ''} {cand.get('nom') or ''}".strip(),
                    "job_id": job["id"],
                    "job_titre": job.get("titre") or f"Offre #{job['id']}",
                    "score": res["score"],
                })
    return nouvelles


def generer_alertes_pour_candidat(candidate_id: int) -> list[dict]:
    """Score un candidat vs toutes les offres publiées ; crée les alertes ≥ seuil.

    Retourne la liste des alertes NOUVELLEMENT créées (pour la notification).
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            return []
        return _generer_pour_candidat(conn, dict(row), _offres_publiees(conn))


def generer_alertes_pour_candidats(candidate_ids: list[int]) -> list[dict]:
    """Version par lot : une seule connexion, offres publiées chargées une fois.

    Utilisée par le pipeline pour les nouveaux CV d'un cycle (évite N connexions
    et N requêtes d'offres). Retourne les alertes nouvellement créées.
    """
    if not candidate_ids:
        return []
    nouvelles = []
    with connect() as conn:
        offres = _offres_publiees(conn)
        if not offres:
            return []
        for cid in candidate_ids:
            row = conn.execute(
                "SELECT * FROM candidates WHERE id = ?", (cid,)
            ).fetchone()
            if row is not None:
                nouvelles += _generer_pour_candidat(conn, dict(row), offres)
    return nouvelles


def recalculer_toutes_alertes() -> int:
    """Recalcule les alertes pour TOUS les candidats vs toutes les offres publiées.

    Utile après création d'offres postérieures aux CV. Idempotent (dédup UNIQUE).
    Une seule connexion, offres et candidats chargés une fois (pas de N+1).
    Retourne le nombre d'alertes nouvellement créées.
    """
    total = 0
    with connect() as conn:
        offres = _offres_publiees(conn)
        if not offres:
            return 0
        # Exclut les doublons : ils ne doivent pas générer d'alertes (cohérent
        # avec le matching, qui les écarte également).
        cands = [dict(r) for r in conn.execute(
            "SELECT * FROM candidates WHERE duplicate_of IS NULL ORDER BY id"
        ).fetchall()]
        for cand in cands:
            total += len(_generer_pour_candidat(conn, cand, offres))
    return total


def notifier_alertes(notify_cfg: dict, smtp_cfg: dict, alertes: list[dict]) -> None:
    """Envoie un email récapitulatif des nouvelles correspondances (best effort)."""
    if not notify_cfg.get("enabled") or not alertes:
        return
    recipients = notifier.parse_recipients(notify_cfg.get("recipients", ""))
    if not recipients:
        return
    n = len(alertes)
    subject = f"[CV Agent] {n} correspondance{'s' if n > 1 else ''} candidat↔offre"
    lines = [f"{n} nouvelle(s) correspondance(s) détectée(s) :", ""]
    for a in alertes:
        lines.append(
            f"• {a['candidate_nom']} → « {a['job_titre']} » (score {a['score']}/100)"
        )
    lines += ["", "— CV Agent"]
    ok, msg = notifier.send_email(smtp_cfg, recipients, subject, "\n".join(lines))
    log.info("Notification alertes : %s", msg)
