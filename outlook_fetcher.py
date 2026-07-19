"""Lecture des emails depuis un fichier Outlook **PST ou OST**.

Complément « import ponctuel » du `mail_fetcher` (IMAP) : un PST/OST est un
instantané, pas une boîte qu'on interroge en boucle. On parcourt les messages du
fichier, on construit des objets `FetchedEmail` IDENTIQUES à ceux de l'IMAP, puis
le pipeline habituel (`web_pipeline._process_email`) prend le relais (classification,
extraction, dédup, insertion). On réutilise donc `Attachment`, `FetchedEmail`,
le filtre d'extensions et l'enregistrement des pièces jointes de `mail_fetcher`.

Deux backends, sélectionnés automatiquement :
  - **pypff** (libpff) : multiplateforme (Linux/Docker ET Windows), lit PST comme
    OST directement depuis le fichier. Backend principal.
  - **win32com** (Outlook MAPI) : Windows uniquement, requiert Outlook installé.
    Repli quand pypff n'est pas disponible (ex. exe sans binding compilé). Lit
    surtout le PST (via AddStore) ; l'OST reste géré au mieux par pypff.

L'identifiant de dédup (`uid`) est déterministe : `outlook:<identifiant interne>`,
associé à un « dossier » = nom du fichier importé. Réimporter le MÊME fichier ne
recrée donc pas de doublons ; deux fichiers distincts ne se télescopent pas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging

# On réutilise strictement les structures et helpers de l'IMAP : un FetchedEmail
# issu d'un PST est indiscernable d'un FetchedEmail IMAP pour le pipeline.
from mail_fetcher import (
    Attachment,
    FetchedEmail,
    ALLOWED_ATTACHMENT_EXTS,
    _safe_filename,
    normalize_message_id,
)

log = logging.getLogger(__name__)

# Tags de propriétés MAPI utiles (pypff n'expose pas le nom de fichier d'une pièce
# jointe directement : il faut le lire dans les « record sets »).
_PR_ATTACH_LONG_FILENAME = 0x3707  # nom de fichier long (préféré)
_PR_ATTACH_FILENAME = 0x3704       # nom court 8.3 (repli)
_PR_DISPLAY_NAME = 0x3001          # à défaut, nom d'affichage de la pièce jointe
_PR_INTERNET_MESSAGE_ID = 0x1035   # Message-ID RFC 5322 (clé de rapprochement)

# Même propriété côté MAPI/win32com, en notation DASL (PT_UNICODE).
_DASL_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"

# Nombre max de caractères de corps conservés (aligné sur le comportement IMAP).
_BODY_MAX = 5000


# ─── Détection des backends disponibles ─────────────────────────────────────────

def _has_pypff() -> bool:
    try:
        import pypff  # noqa: F401
        return True
    except Exception:
        return False


def _has_win32com() -> bool:
    try:
        import win32com.client  # noqa: F401
        return True
    except Exception:
        return False


def available_backends() -> list[str]:
    """Backends utilisables sur cette machine, par ordre de préférence."""
    backends = []
    if _has_pypff():
        backends.append("pypff")
    if _has_win32com():
        backends.append("win32com")
    return backends


def _resolve_backend(backend: str | None) -> str:
    """Choisit le backend effectif ('auto' -> premier disponible)."""
    avail = available_backends()
    if not avail:
        raise RuntimeError(
            "Aucun lecteur Outlook disponible : installez « libpff-python » (pypff) "
            "ou, sous Windows, « pywin32 » avec Outlook installé."
        )
    if backend and backend not in ("auto", ""):
        if backend not in avail:
            raise RuntimeError(
                f"Backend « {backend} » indisponible (disponibles : {', '.join(avail)})."
            )
        return backend
    return avail[0]


def folder_label(path: str) -> str:
    """Étiquette de « dossier » servant de clé de dédup pour ce fichier."""
    return f"outlook:{Path(path).name}"


# ─── Backend pypff (libpff) ─────────────────────────────────────────────────────

def _pff_record_string(message_or_att, entry_type: int) -> str | None:
    """Lit une propriété MAPI chaîne dans les record sets d'un item pypff."""
    try:
        for i in range(message_or_att.number_of_record_sets):
            rs = message_or_att.get_record_set(i)
            for j in range(rs.number_of_entries):
                e = rs.get_entry(j)
                if e.entry_type != entry_type:
                    continue
                try:
                    val = e.get_data_as_string()
                except Exception:
                    data = e.get_data()
                    if not data:
                        return None
                    # PT_UNICODE -> UTF-16-LE ; sinon on tente latin-1 tolérant.
                    val = data.decode("utf-16-le", "ignore").rstrip("\x00") or \
                        data.decode("latin-1", "ignore").rstrip("\x00")
                if val:
                    return val
    except Exception:
        return None
    return None


def _pff_attachment_name(att) -> str | None:
    for tag in (_PR_ATTACH_LONG_FILENAME, _PR_ATTACH_FILENAME, _PR_DISPLAY_NAME):
        name = _pff_record_string(att, tag)
        if name:
            return name
    return None


def _pff_message_datetime(msg) -> datetime:
    for getter in ("get_delivery_time", "get_client_submit_time", "get_creation_time"):
        try:
            dt = getattr(msg, getter)()
            if dt:
                return dt
        except Exception:
            continue
    return datetime.now()


def _pff_doc_attachments(msg) -> list[Attachment]:
    out: list[Attachment] = []
    try:
        n = msg.number_of_attachments
    except Exception:
        return out
    for i in range(n):
        try:
            att = msg.get_attachment(i)
            name = _pff_attachment_name(att)
            if not name:
                continue
            ext = Path(name).suffix.lower()
            if ext not in ALLOWED_ATTACHMENT_EXTS:
                continue
            size = att.get_size()
            if not size:
                continue
            content = att.read_buffer(size)
            out.append(Attachment(filename=_safe_filename(name), content=content, ext=ext))
        except Exception as e:
            log.warning("pypff : pièce jointe #%d illisible : %s", i, e)
    return out


def _pff_iter_folder(folder, path_prefix: str = ""):
    """Génère récursivement (dossier_nom, message) pour tout l'arbre."""
    try:
        name = folder.get_name() or path_prefix or "(racine)"
    except Exception:
        name = path_prefix or "(racine)"
    try:
        for i in range(folder.number_of_sub_messages):
            yield name, folder.get_sub_message(i)
    except Exception as e:
        log.warning("pypff : messages du dossier « %s » illisibles : %s", name, e)
    try:
        for i in range(folder.number_of_sub_folders):
            sub = folder.get_sub_folder(i)
            yield from _pff_iter_folder(sub, f"{name}/")
    except Exception as e:
        log.warning("pypff : sous-dossiers de « %s » illisibles : %s", name, e)


def _pff_iter_emails(path: str):
    """Génère des FetchedEmail depuis un PST/OST via pypff."""
    import pypff

    pff = pypff.file()
    pff.open(path)
    try:
        root = pff.get_root_folder()
        for _folder_name, msg in _pff_iter_folder(root):
            try:
                ident = msg.get_identifier()
            except Exception:
                continue
            uid = f"outlook:{ident}"

            attachments = _pff_doc_attachments(msg)
            if not attachments:
                # Pas de PJ exploitable : inutile de faire remonter le message
                # (le pipeline le rejetterait de toute façon). On l'ignore.
                continue

            try:
                body = msg.get_plain_text_body() or msg.get_html_body() or b""
            except Exception:
                body = b""
            if isinstance(body, bytes):
                body = body.decode("utf-8", "ignore")

            yield FetchedEmail(
                uid=uid,
                subject=(_safe_get(msg, "get_subject") or ""),
                from_addr=(_safe_get(msg, "get_sender_name") or ""),
                from_name=(_safe_get(msg, "get_sender_name") or ""),
                received_at=_pff_message_datetime(msg),
                body_text=body[:_BODY_MAX],
                attachments=attachments,
                message_id=normalize_message_id(
                    _pff_record_string(msg, _PR_INTERNET_MESSAGE_ID)),
            )
    finally:
        pff.close()


def _safe_get(obj, method: str):
    try:
        return getattr(obj, method)()
    except Exception:
        return None


# ─── Backend win32com (Outlook MAPI, Windows) ───────────────────────────────────

def _w32_iter_emails(path: str):
    """Génère des FetchedEmail depuis un PST via Outlook (AddStore/RemoveStore).

    Requiert Outlook installé. L'OST n'est pas ajoutable comme store : il est géré
    au mieux par pypff ; ici on cible surtout le PST.
    """
    import tempfile
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    abspath = str(Path(path).resolve())
    outlook.AddStore(abspath)
    store = None
    for st in outlook.Stores:
        try:
            if st.FilePath and Path(st.FilePath).resolve() == Path(abspath).resolve():
                store = st
                break
        except Exception:
            continue
    if store is None:
        raise RuntimeError("Outlook n'a pas pu monter le fichier PST.")

    tmpdir = Path(tempfile.mkdtemp(prefix="cvagent_ost_"))
    try:
        root = store.GetRootFolder()
        yield from _w32_walk(root, tmpdir)
    finally:
        try:
            outlook.RemoveStore(store.GetRootFolder())
        except Exception:
            pass


def _w32_walk(folder, tmpdir: Path):
    for item in list(folder.Items):
        try:
            if getattr(item, "Class", None) != 43:  # 43 = olMail
                continue
            atts = _w32_attachments(item, tmpdir)
            if not atts:
                continue
            uid = f"outlook:{getattr(item, 'EntryID', '') or id(item)}"
            received = getattr(item, "ReceivedTime", None)
            try:
                received = datetime(received.year, received.month, received.day,
                                    received.hour, received.minute, received.second)
            except Exception:
                received = datetime.now()
            yield FetchedEmail(
                uid=uid,
                subject=getattr(item, "Subject", "") or "",
                from_addr=getattr(item, "SenderEmailAddress", "") or "",
                from_name=getattr(item, "SenderName", "") or "",
                received_at=received,
                body_text=(getattr(item, "Body", "") or "")[:_BODY_MAX],
                attachments=atts,
                message_id=_w32_message_id(item),
            )
        except Exception as e:
            log.warning("win32com : message illisible : %s", e)
    for sub in list(folder.Folders):
        yield from _w32_walk(sub, tmpdir)


def _w32_message_id(item) -> str:
    """Message-ID d'un item MAPI, normalisé. Vide si la propriété est absente."""
    try:
        return normalize_message_id(
            item.PropertyAccessor.GetProperty(_DASL_INTERNET_MESSAGE_ID))
    except Exception:
        return ""  # mails internes/brouillons : pas d'en-tête Internet


def _w32_attachments(item, tmpdir: Path) -> list[Attachment]:
    out: list[Attachment] = []
    for att in list(getattr(item, "Attachments", [])):
        try:
            name = att.FileName or ""
            ext = Path(name).suffix.lower()
            if ext not in ALLOWED_ATTACHMENT_EXTS:
                continue
            tmp = tmpdir / _safe_filename(name)
            att.SaveAsFile(str(tmp))
            content = tmp.read_bytes()
            tmp.unlink(missing_ok=True)
            out.append(Attachment(filename=_safe_filename(name), content=content, ext=ext))
        except Exception as e:
            log.warning("win32com : pièce jointe illisible : %s", e)
    return out


# ─── Déplacement des mails traités dans le PST (win32com uniquement) ─────────────
#
# Un import PST/OST ne modifie pas le fichier ; la RH veut parfois « ranger » à la
# main les mails déjà traités dans un dossier dédié du PST (ex. « Traités ») pour
# garder l'inbox propre. C'est une **écriture** dans le fichier : seul le backend
# win32com (Outlook installé, Windows) sait le faire — pypff est en lecture seule.
#
# On range EXACTEMENT ce que la solution a traité, en recroisant la table
# `processed_emails` par **Message-ID**. La colonne `uid` ne peut pas servir de clé :
# chaque backend y écrit un identifiant propre à son contexte de lecture (UID IMAP,
# identifiant de nœud pypff, EntryID MAPI), et un identifiant pypff ne vaut que pour
# LE fichier lu — donc jamais pour la boîte vivante. Le Message-ID, lui, voyage avec
# le mail : c'est le seul pont entre une copie OST analysée et la boîte réelle.
#
# Deux destinations, car « traité » ne veut pas dire « CV » : les mails ayant produit
# un candidat (is_cv=1) vont dans le dossier principal, ceux analysés mais écartés
# (is_cv=0 : une PJ PDF/DOCX qui n'est pas une candidature) dans un dossier séparé.
# Un mail absent de la table n'est PAS déplacé : jamais traité (arrivé après
# l'instantané, par exemple), donc on n'y touche pas.

def _w32_existing_subfolder(root, name: str):
    """Retourne le sous-dossier `name` sous `root`, ou None. Ne crée rien (dry-run)."""
    target = name.strip().lower()
    for f in list(root.Folders):
        try:
            if (f.Name or "").strip().lower() == target:
                return f
        except Exception:
            continue
    return None


def _w32_find_or_create_subfolder(root, name: str):
    """Retourne le sous-dossier `name` sous `root`, en le créant s'il manque."""
    existing = _w32_existing_subfolder(root, name)
    return existing if existing is not None else root.Folders.Add(name)


def _w32_collect_processed(folder, skip_entryids: set, processed: dict, out: list) -> None:
    """Collecte récursivement les (item, is_cv) des mails traités, hors dossiers exclus.

    `processed` associe un Message-ID normalisé à son is_cv (1 = CV, 0 = analysé mais
    écarté). Un mail dont le Message-ID est absent de ce dictionnaire n'a jamais été
    traité par la solution : on l'ignore.

    On collecte AVANT de déplacer : déplacer un item pendant l'itération de la
    collection `Items` fait sauter des éléments (comportement MAPI connu). Les
    dossiers de `skip_entryids` (cibles + dossiers système) sont ignorés, eux et
    leur sous-arbre.
    """
    try:
        if folder.EntryID in skip_entryids:
            return  # dossier cible ou dossier système (Envoyés, Supprimés…)
    except Exception:
        pass
    try:
        for item in list(folder.Items):
            try:
                if getattr(item, "Class", None) != 43:  # 43 = olMail
                    continue
                mid = _w32_message_id(item)
                if not mid:
                    continue  # sans Message-ID, aucun rapprochement fiable possible
                is_cv = processed.get(mid)
                if is_cv is None:
                    continue  # jamais traité par la solution -> on n'y touche pas
                out.append((item, int(is_cv)))
            except Exception as e:
                log.warning("win32com : message ignoré au déplacement : %s", e)
    except Exception as e:
        log.warning("win32com : dossier illisible au déplacement : %s", e)
    try:
        for sub in list(folder.Folders):
            _w32_collect_processed(sub, skip_entryids, processed, out)
    except Exception as e:
        log.warning("win32com : sous-dossiers illisibles au déplacement : %s", e)


# Dossiers système à ne jamais balayer (olDefaultFolders) : Supprimés, Boîte d'envoi,
# Éléments envoyés, Brouillons, Courrier indésirable. Repérés par EntryID (robuste à
# la langue de l'interface). Certains n'existent pas dans un PST simple → on ignore.
_W32_SYSTEM_FOLDER_TYPES = (3, 4, 5, 16, 23)


def _w32_system_folder_eids(store) -> set:
    """EntryID des dossiers système du store (ceux qui existent)."""
    eids: set = set()
    for ftype in _W32_SYSTEM_FOLDER_TYPES:
        try:
            f = store.GetDefaultFolder(ftype)
            if f is not None:
                eids.add(f.EntryID)
        except Exception:
            continue  # dossier absent pour ce store (ex. PST autonome)
    return eids


def can_move_messages(backend: str | None = None) -> bool:
    """True si le déplacement de messages est possible (backend win32com dispo)."""
    return _has_win32com()


def _w32_find_store_by_path(outlook, abspath: str):
    """Retrouve le store Outlook (déjà chargé) dont le fichier == `abspath`."""
    ref = Path(abspath).resolve()
    for st in outlook.Stores:
        try:
            if st.FilePath and Path(st.FilePath).resolve() == ref:
                return st
        except Exception:
            continue
    return None


def _w32_find_store_by_account(outlook, account: str):
    """Retrouve le store du compte nommé `account` (repli quand `FilePath` est vide).

    Outlook ne renseigne pas `Store.FilePath` pour les comptes Exchange/Microsoft 365
    (`ExchangeStoreType` 3) : la propriété reste vide même store entièrement chargé, et
    `PR_STORE_FILE_PATH` est absente. Le repérage par chemin échoue donc pour tout OST
    sur ces profils. Un OST étant nommé d'après le compte (« recrutement@rayanox.co.ost »),
    on retombe sur le nom du store.

    La correspondance doit être **exacte et unique** : le déplacement écrit dans une boîte
    réelle qui se resynchronise vers le serveur, donc un rapprochement approximatif ou
    ambigu rangerait des mails dans le mauvais compte. En cas de doute on ne devine pas.

    Retourne (store, erreur) : l'un des deux est toujours None.
    """
    ref = (account or "").strip().casefold()
    if not ref:
        return None, "Nom de compte vide : impossible d'identifier la boîte."
    noms, matches = [], []
    for st in outlook.Stores:
        try:
            nom = (st.DisplayName or "").strip()
        except Exception:
            continue
        noms.append(nom)
        if nom.casefold() == ref:
            matches.append(st)
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, (f"Plusieurs comptes nommés « {account} » sont ouverts dans Outlook : "
                      "impossible de choisir sans risque. Fermez le doublon et réessayez.")
    dispo = ", ".join(f"« {n} »" for n in noms if n) or "aucun"
    return None, (f"Aucun compte « {account} » dans l'Outlook de ce poste. Un .ost ne peut pas "
                  f"être monté comme fichier indépendant : le compte doit y être configuré, et "
                  f"le fichier porter son nom. Comptes ouverts : {dispo}.")


def move_cv_messages(path: str, target_folder: str = "Traités",
                     non_cv_folder: str = "", backend: str | None = None,
                     dry_run: bool = False) -> tuple[int, str]:
    """Range les mails TRAITÉS par la solution, CV et non-CV séparés.

    Ne déplace que les mails effectivement analysés, retrouvés par **Message-ID** dans
    `processed_emails` (voir le commentaire de section) :

    - is_cv=1 (a produit un candidat)  -> `target_folder`
    - is_cv=0 (analysé, pas une candidature) -> `non_cv_folder`, s'il est fourni ;
      sinon ces mails sont laissés en place.

    Un mail absent de la table n'est jamais touché : il n'a pas été traité (arrivé
    après l'instantané importé, par exemple).

    Nécessite **win32com** (Outlook installé, Windows) ; pypff est en lecture seule.
    Deux cas selon le type de fichier :

    - **.pst** : fichier autonome. On le monte (`AddStore`), on déplace, puis on le
      démonte (`RemoveStore`). Le déplacement reste local au fichier.
    - **.ost** : cache d'un compte Exchange/Microsoft 365 — un OST NE peut PAS être
      monté comme fichier indépendant. On opère donc sur le store **déjà chargé** du
      compte correspondant. Le déplacement s'applique alors à la **boîte réelle** et
      se synchronise vers le serveur. Le compte doit être configuré dans l'Outlook de
      ce poste, sinon on renvoie une erreur explicite (on ne démonte évidemment jamais
      un compte vivant).

    `dry_run=True` compte ce qui serait déplacé sans rien modifier ni créer de dossier.

    Idempotent : les mails déjà dans un dossier cible ne sont pas re-balayés.
    Retourne (nb_déplacés, message).
    """
    p = Path(path)
    if not p.exists():
        return 0, f"Fichier introuvable : {path}"
    suffix = p.suffix.lower()
    if suffix not in (".pst", ".ost"):
        return 0, "Déplacement possible uniquement sur un fichier .pst ou .ost."
    if not _has_win32com():
        return 0, ("Déplacement indisponible : nécessite Outlook installé "
                   "(pywin32/win32com). pypff est en lecture seule.")
    target_folder = (target_folder or "Traités").strip() or "Traités"
    non_cv_folder = (non_cv_folder or "").strip()
    if non_cv_folder and non_cv_folder.casefold() == target_folder.casefold():
        return 0, ("Les deux dossiers cibles sont identiques : les CV et les non-CV "
                   "seraient mélangés. Choisissez deux noms distincts.")

    # Ce que la solution a réellement traité pour CE fichier. Sans cet index, aucun
    # rapprochement : on préfère ne rien déplacer plutôt que de deviner.
    import state_db
    processed = state_db.processed_message_ids(folder_label(path))
    if not processed:
        return 0, (f"Aucun mail traité avec Message-ID connu pour « {p.name} ». "
                   "Importez d'abord ce fichier ; si l'import est antérieur à cette "
                   "fonctionnalité, complétez les Message-ID en rejouant "
                   "backfill_message_ids.py.")

    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    abspath = str(p.resolve())

    # On réutilise un store déjà chargé s'il existe (cas OST vivant, ou PST déjà monté
    # par une session précédente) : on ne le démontera pas.
    store = _w32_find_store_by_path(outlook, abspath)
    added = False
    if store is None and suffix == ".pst":
        outlook.AddStore(abspath)          # un OST ne peut pas être monté ainsi
        added = True
        store = _w32_find_store_by_path(outlook, abspath)
    if store is None and suffix == ".ost":
        # `FilePath` est vide sur les profils Exchange/M365, et le fichier déposé dans le
        # dossier d'import n'est de toute façon qu'une copie : son chemin ne correspondra
        # jamais à celui du store vivant. On identifie le compte par son nom.
        store, err = _w32_find_store_by_account(outlook, p.stem)
        if store is None:
            return 0, err
    if store is None:
        return 0, "Outlook n'a pas pu monter le fichier PST."

    root = store.GetRootFolder()
    try:
        # En dry-run on ne crée aucun dossier : on se contente de le retrouver s'il existe.
        if dry_run:
            target = _w32_existing_subfolder(root, target_folder)
            non_cv_target = (_w32_existing_subfolder(root, non_cv_folder)
                             if non_cv_folder else None)
        else:
            target = _w32_find_or_create_subfolder(root, target_folder)
            non_cv_target = (_w32_find_or_create_subfolder(root, non_cv_folder)
                             if non_cv_folder else None)

        skip = _w32_system_folder_eids(store)   # Envoyés, Supprimés, Brouillons…
        for f in (target, non_cv_target):      # ne pas re-balayer les dossiers cibles
            try:
                if f is not None:
                    skip.add(f.EntryID)
            except Exception:
                pass

        to_move: list = []
        _w32_collect_processed(root, skip, processed, to_move)
        nb_cv = sum(1 for _, is_cv in to_move if is_cv)
        nb_non_cv = len(to_move) - nb_cv
        portee = "boîte du compte (synchronisé)" if suffix == ".ost" else p.name

        if dry_run:
            log.info("Dry-run : %d CV + %d non-CV rapprochés sur %d traités connus (%s)",
                     nb_cv, nb_non_cv, len(processed), portee)
            return len(to_move), (
                f"Simulation : {nb_cv} CV iraient vers « {target_folder} »"
                + (f", {nb_non_cv} non-CV vers « {non_cv_folder} »" if non_cv_folder
                   else f" ; {nb_non_cv} non-CV resteraient en place")
                + f". {len(processed)} mail(s) traité(s) connu(s) pour ce fichier."
            )

        moved = moved_non_cv = 0
        for item, is_cv in to_move:
            dest = target if is_cv else non_cv_target
            if dest is None:
                continue        # non-CV sans dossier dédié : on les laisse en place
            try:
                item.Move(dest)
                if is_cv:
                    moved += 1
                else:
                    moved_non_cv += 1
            except Exception as e:
                log.warning("win32com : déplacement d'un message échoué : %s", e)

        total = moved + moved_non_cv
        log.info("Rangement : %d CV -> « %s », %d non-CV -> « %s » (%s)",
                 moved, target_folder, moved_non_cv, non_cv_folder or "(laissés)", portee)
        note = ("" if suffix == ".pst"
                else " (boîte du compte — synchronisé vers le serveur)")
        detail = (f"{moved} CV rangé(s) dans « {target_folder} »"
                  + (f" et {moved_non_cv} non-CV dans « {non_cv_folder} »"
                     if non_cv_folder else "")
                  + note + ".")
        return total, detail
    finally:
        # NE JAMAIS démonter un store qu'on n'a pas monté (surtout un compte OST vivant).
        if added:
            try:
                outlook.RemoveStore(root)
            except Exception:
                pass


# ─── API publique ───────────────────────────────────────────────────────────────

def check_file(path: str, backend: str | None = None) -> tuple[bool, str]:
    """Vérifie qu'un fichier PST/OST est lisible ; compte messages/PJ (échantillon)."""
    p = Path(path)
    if not p.exists():
        return False, f"Fichier introuvable : {path}"
    if p.suffix.lower() not in (".pst", ".ost"):
        return False, "Extension attendue : .pst ou .ost"
    try:
        eff = _resolve_backend(backend)
    except RuntimeError as e:
        return False, str(e)
    try:
        gen = _iter_by_backend(path, eff)
        with_att = 0
        for _ in gen:
            with_att += 1
            if with_att >= 500:  # échantillon : on ne parcourt pas tout pour un test
                break
        suffix = "+" if with_att >= 500 else ""
        return True, (f"Fichier lisible ({eff}) — {with_att}{suffix} message(s) "
                      "avec pièce jointe exploitable détecté(s).")
    except Exception as e:
        return False, f"Lecture impossible ({eff}) : {e}"


def _iter_by_backend(path: str, backend: str):
    if backend == "pypff":
        return _pff_iter_emails(path)
    if backend == "win32com":
        return _w32_iter_emails(path)
    raise RuntimeError(f"Backend inconnu : {backend}")


def fetch_emails(
    path: str,
    max_emails: int,
    already_processed,
    backend: str | None = None,
) -> list[FetchedEmail]:
    """Renvoie jusqu'à max_emails FetchedEmail non encore traités du fichier.

    `already_processed(uid)` -> bool : même contrat que l'IMAP (dédup via la table
    `processed_emails`, clé = uid + `folder_label(path)`).
    """
    eff = _resolve_backend(backend)
    fetched: list[FetchedEmail] = []
    for email in _iter_by_backend(path, eff):
        if len(fetched) >= max_emails:
            break
        if already_processed(email.uid):
            continue
        fetched.append(email)
    log.info("%d message(s) exploitable(s) relevé(s) dans %s (%s)",
             len(fetched), Path(path).name, eff)
    return fetched
