"""Complète les Message-ID manquants dans `processed_emails` pour un PST/OST importé.

À quoi ça sert : le rangement des mails traités (« Ranger les traités », onglet Import
Outlook) retrouve les mails dans la boîte Outlook vivante par leur **Message-ID**. Les
imports antérieurs à cette fonctionnalité n'ont enregistré qu'un `uid` — un identifiant
de nœud pypff, propre au fichier lu, qu'Outlook ne peut pas reconnaître. Ce script
relit le fichier d'origine, rétablit la correspondance `uid -> Message-ID` et complète
les lignes existantes.

Ne relance AUCUN traitement : ni LLM, ni extraction, ni insertion de candidat. Il ne
fait qu'écrire la colonne `message_id` là où elle est vide. Réexécutable sans risque.

Nécessite le backend **pypff**, donc à lancer dans le conteneur (le venv Windows n'a
généralement que win32com) :

    docker compose run --rm --no-deps app python backfill_message_ids.py /data/import/boite.ost

Options :
    --dry-run   affiche ce qui serait écrit, sans rien modifier
"""

from __future__ import annotations

import argparse
import logging
import sys

import db
import outlook_fetcher
from outlook_fetcher import (
    _PR_INTERNET_MESSAGE_ID,
    _pff_iter_folder,
    _pff_record_string,
)
from mail_fetcher import normalize_message_id

log = logging.getLogger("backfill")


def iter_uid_message_id(path: str):
    """Génère (uid, message_id) pour chaque message du fichier.

    Volontairement plus léger que `_pff_iter_emails` : on ne lit ni le corps ni les
    pièces jointes (plusieurs Go inutilement décodés), seulement les deux valeurs
    nécessaires au rapprochement.
    """
    import pypff

    pff = pypff.file()
    pff.open(path)
    try:
        for _nom, msg in _pff_iter_folder(pff.get_root_folder()):
            try:
                ident = msg.get_identifier()
            except Exception:
                continue
            mid = normalize_message_id(_pff_record_string(msg, _PR_INTERNET_MESSAGE_ID))
            if mid:
                yield f"outlook:{ident}", mid
    finally:
        pff.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", help="chemin du .pst/.ost tel qu'importé")
    ap.add_argument("--dry-run", action="store_true", help="ne rien écrire")
    args = ap.parse_args()

    label = outlook_fetcher.folder_label(args.path)
    log.info("Fichier : %s", args.path)
    log.info("Étiquette de dédup (folder) : %s", label)

    # Agrégats nommés : les curseurs renvoient des dict (row_factory=dict_row).
    with db.connect() as conn:
        total = conn.execute(
            "SELECT count(*) AS n FROM processed_emails WHERE folder = ?", (label,)
        ).fetchone()["n"]
        manquants = conn.execute(
            "SELECT count(*) AS n FROM processed_emails "
            "WHERE folder = ? AND (message_id IS NULL OR message_id = '')",
            (label,),
        ).fetchone()["n"]

    if not total:
        log.error("Aucune ligne pour « %s » : ce fichier n'a pas été importé sous ce nom.",
                  label)
        return 1
    log.info("%d ligne(s) traitée(s), dont %d sans Message-ID.", total, manquants)
    if not manquants:
        log.info("Rien à compléter.")
        return 0

    lus = ecrits = 0
    with db.connect() as conn:
        for uid, mid in iter_uid_message_id(args.path):
            lus += 1
            if args.dry_run:
                row = conn.execute(
                    "SELECT 1 FROM processed_emails WHERE uid = ? AND folder = ? "
                    "AND (message_id IS NULL OR message_id = '')",
                    (uid, label),
                ).fetchone()
                if row:
                    ecrits += 1
                continue
            # Ne touche que les lignes vides : un Message-ID déjà enregistré vient de
            # l'import lui-même et fait autorité.
            cur = conn.execute(
                "UPDATE processed_emails SET message_id = ? "
                "WHERE uid = ? AND folder = ? AND (message_id IS NULL OR message_id = '')",
                (mid, uid, label),
            )
            ecrits += cur.rowcount or 0
            if lus % 500 == 0:
                log.info("  %d messages lus, %d ligne(s) complétée(s)…", lus, ecrits)

    verbe = "seraient complétées" if args.dry_run else "complétées"
    log.info("Terminé : %d message(s) lu(s) dans le fichier, %d ligne(s) %s.",
             lus, ecrits, verbe)
    if ecrits < manquants:
        log.warning("%d ligne(s) restent sans Message-ID : messages absents du fichier "
                    "ou dépourvus d'en-tête Internet. Ils ne seront pas rangés.",
                    manquants - ecrits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
