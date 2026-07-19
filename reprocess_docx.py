"""Re-traite les candidats dont le CV est un Word (.docx / .doc).

Contexte : l'ancienne extraction .docx ne lisait que les paragraphes et perdait
le contenu des TABLEAUX et des en-têtes/pieds de page (voir pdf_extractor). Les
CV Word mis en page en tableaux étaient donc extraits presque vides. Ce script
ré-extrait le texte avec l'extracteur corrigé, relance l'extraction LLM et met à
jour la fiche candidat.

Sûr et idempotent :
  - passe par web_db.insert_candidate (upsert par id) qui PRÉSERVE le suivi RH
    (statut, commentaires) et created_at ;
  - si la ré-extraction LLM ne renvoie rien d'exploitable (échec LLM, texte
    illisible), la fiche n'est PAS écrasée (on saute) ;
  - le .doc binaire (Word 97-2003) n'est pas lisible par python-docx : il ressort
    vide et est simplement signalé, pas modifié.

À lancer DANS le conteneur (mêmes base, config et fichiers) :
    docker compose cp reprocess_docx.py app:/app/reprocess_docx.py
    docker compose exec app python /app/reprocess_docx.py --dry-run   # inventaire
    docker compose exec app python /app/reprocess_docx.py             # traitement
"""
import argparse
import logging
from datetime import datetime
from pathlib import Path

import web_db
import pdf_extractor
import llm_extractor

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("reprocess_docx")


def _candidats_word(conn) -> list[dict]:
    """Candidats dont le fichier CV est un .docx ou .doc, triés par id."""
    rows = conn.execute(
        "SELECT id, received_at, expediteur, pdf_filename, pdf_path, "
        "       nom, prenom, resume, duplicate_of "
        "FROM candidates "
        "WHERE LOWER(pdf_filename) LIKE '%.docx' "
        "   OR LOWER(pdf_filename) LIKE '%.doc' "
        "ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


def _a_du_contenu(ext) -> bool:
    """Vrai si l'extraction LLM a produit quelque chose d'exploitable.

    Garde-fou anti-écrasement : sur échec LLM / texte illisible, l'extraction est
    vide — on ne veut alors PAS remplacer les données existantes par du vide.
    """
    return bool(
        ext.nom or ext.prenom or ext.resume or ext.poste_recherche
        or ext.competences_principales or ext.experiences
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Liste les candidats concernés sans rien modifier.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Ne traiter que les N premiers (0 = tous).")
    parser.add_argument("--include-doublons", action="store_true",
                        help="Traiter aussi les fiches marquées comme doublons.")
    args = parser.parse_args()

    cfg = web_db.settings_to_config(web_db.get_all_settings())
    llm_cfg = cfg["llm"]
    max_chars = cfg["processing"]["pdf_max_chars"]

    with web_db.connect() as conn:
        candidats = _candidats_word(conn)

    if not args.include_doublons:
        candidats = [c for c in candidats if not c.get("duplicate_of")]
    if args.limit > 0:
        candidats = candidats[: args.limit]

    log.info("%d candidat(s) Word à examiner%s", len(candidats),
             " (mode simulation)" if args.dry_run else "")
    if args.dry_run:
        for c in candidats:
            log.info("  #%s %s %s -> %s (résumé actuel : %d car.)",
                     c["id"], c.get("prenom") or "", c.get("nom") or "",
                     c["pdf_filename"], len(c.get("resume") or ""))
        return

    maj, vides, absents, sautes, erreurs = 0, 0, 0, 0, 0
    for c in candidats:
        cid = c["id"]
        chemin = Path(c["pdf_path"]) if c.get("pdf_path") else None
        try:
            if not chemin or not chemin.exists():
                log.warning("#%s fichier introuvable (%s) — ignoré", cid, chemin)
                absents += 1
                continue

            texte = pdf_extractor.extract_text(chemin, max_chars)
            if not texte.strip():
                log.warning("#%s aucun texte extractible (%s) — ignoré",
                            cid, c["pdf_filename"])
                vides += 1
                continue

            extraction = llm_extractor.extract(llm_cfg, cv_text=texte, email_subject="")
            if not _a_du_contenu(extraction):
                log.warning("#%s extraction LLM vide — fiche NON modifiée", cid)
                sautes += 1
                continue

            # received_at est stocké en texte ISO ; insert_candidate attend un datetime.
            try:
                recu = datetime.fromisoformat(c["received_at"])
            except (TypeError, ValueError):
                recu = datetime.now()

            web_db.insert_candidate(
                candidate_id=cid,
                received_at=recu,
                expediteur=c.get("expediteur") or "",
                extraction=extraction,
                pdf_filename=c["pdf_filename"],
                pdf_path=c["pdf_path"],
            )
            maj += 1
            log.info("#%s mis à jour : %s %s | résumé %d car. | %d compétence(s)",
                     cid, extraction.prenom or "", extraction.nom or "",
                     len(extraction.resume or ""),
                     len(extraction.competences_principales))
        except Exception as e:
            erreurs += 1
            log.exception("#%s échec : %s", cid, e)

    log.info("Terminé : %d mis à jour, %d texte vide, %d fichier absent, "
             "%d extraction vide (non modifiés), %d erreur(s)",
             maj, vides, absents, sautes, erreurs)


if __name__ == "__main__":
    main()
