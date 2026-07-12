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
)

log = logging.getLogger(__name__)

# Tags de propriétés MAPI utiles (pypff n'expose pas le nom de fichier d'une pièce
# jointe directement : il faut le lire dans les « record sets »).
_PR_ATTACH_LONG_FILENAME = 0x3707  # nom de fichier long (préféré)
_PR_ATTACH_FILENAME = 0x3704       # nom court 8.3 (repli)
_PR_DISPLAY_NAME = 0x3001          # à défaut, nom d'affichage de la pièce jointe

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
            )
        except Exception as e:
            log.warning("win32com : message illisible : %s", e)
    for sub in list(folder.Folders):
        yield from _w32_walk(sub, tmpdir)


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
# On ne peut pas s'appuyer sur la table `processed_emails` : le backend par défaut
# (pypff) y stocke des identifiants internes pypff, incompatibles avec les EntryID
# MAPI de win32com. On déplace donc, de façon indépendante du backend d'import,
# **tous les mails porteurs d'un CV (PDF/DOCX)** — c.-à-d. exactement ceux que
# l'import prend en charge.

def _w32_find_or_create_subfolder(root, name: str):
    """Retourne le sous-dossier `name` sous `root`, en le créant s'il manque."""
    target = name.strip().lower()
    for f in list(root.Folders):
        try:
            if (f.Name or "").strip().lower() == target:
                return f
        except Exception:
            continue
    return root.Folders.Add(name)


def _w32_has_cv_attachment(item) -> bool:
    for att in list(getattr(item, "Attachments", [])):
        try:
            if Path(att.FileName or "").suffix.lower() in ALLOWED_ATTACHMENT_EXTS:
                return True
        except Exception:
            continue
    return False


def _w32_collect_cv_messages(folder, skip_entryid: str, out: list) -> None:
    """Collecte récursivement les mails porteurs d'une PJ CV, hors dossier cible.

    On collecte AVANT de déplacer : déplacer un item pendant l'itération de la
    collection `Items` fait sauter des éléments (comportement MAPI connu).
    """
    try:
        if skip_entryid and folder.EntryID == skip_entryid:
            return  # ne pas re-parcourir le dossier cible (déplacements précédents)
    except Exception:
        pass
    try:
        for item in list(folder.Items):
            try:
                if getattr(item, "Class", None) != 43:  # 43 = olMail
                    continue
                if _w32_has_cv_attachment(item):
                    out.append(item)
            except Exception as e:
                log.warning("win32com : message ignoré au déplacement : %s", e)
    except Exception as e:
        log.warning("win32com : dossier illisible au déplacement : %s", e)
    try:
        for sub in list(folder.Folders):
            _w32_collect_cv_messages(sub, skip_entryid, out)
    except Exception as e:
        log.warning("win32com : sous-dossiers illisibles au déplacement : %s", e)


def can_move_messages(backend: str | None = None) -> bool:
    """True si le déplacement de messages est possible (backend win32com dispo)."""
    return _has_win32com()


def move_cv_messages(path: str, target_folder: str = "Traités",
                     backend: str | None = None) -> tuple[int, str]:
    """Déplace les mails porteurs d'un CV (PDF/DOCX) vers `target_folder` DANS le PST.

    Écriture dans le fichier : nécessite le backend **win32com** (Outlook installé,
    Windows). pypff est en lecture seule. Idempotent : les mails déjà rangés dans le
    dossier cible ne sont pas re-déplacés. Retourne (nb_déplacés, message).
    """
    p = Path(path)
    if not p.exists():
        return 0, f"Fichier introuvable : {path}"
    if p.suffix.lower() != ".pst":
        # AddStore ne monte de façon fiable que le PST ; l'OST n'est pas déplaçable ici.
        return 0, "Déplacement possible uniquement sur un fichier .pst (via Outlook)."
    if not _has_win32com():
        return 0, ("Déplacement indisponible : nécessite Outlook installé "
                   "(pywin32/win32com). pypff est en lecture seule.")
    target_folder = (target_folder or "Traités").strip() or "Traités"

    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    abspath = str(p.resolve())
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
        return 0, "Outlook n'a pas pu monter le fichier PST."

    root = store.GetRootFolder()
    try:
        target = _w32_find_or_create_subfolder(root, target_folder)
        try:
            target_eid = target.EntryID
        except Exception:
            target_eid = ""
        to_move: list = []
        _w32_collect_cv_messages(root, target_eid, to_move)
        moved = 0
        for item in to_move:
            try:
                item.Move(target)
                moved += 1
            except Exception as e:
                log.warning("win32com : déplacement d'un message échoué : %s", e)
        log.info("Déplacement : %d/%d mail(s) CV rangé(s) dans « %s » (%s)",
                 moved, len(to_move), target_folder, p.name)
        return moved, (f"{moved} mail(s) porteur(s) de CV déplacé(s) vers "
                       f"« {target_folder} ».")
    finally:
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
