from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import logging
import re
import socket

from imap_tools import MailBox, MailBoxStartTls, MailBoxUnencrypted, AND
from imap_tools.errors import MailboxLoginError, MailboxFolderSelectError


log = logging.getLogger(__name__)


def _open_mailbox(host: str, port: int, security: str = "SSL", timeout=None):
    """Instancie la bonne classe imap_tools selon le mode de sécurité choisi.

    Générique (tout fournisseur IMAP, pas seulement Gmail) :
      - SSL       -> MailBox (IMAPS, port 993 typique) ;
      - STARTTLS  -> MailBoxStartTls (port 143 typique) ;
      - None      -> MailBoxUnencrypted (clair, port 143 — à éviter).
    """
    sec = (security or "SSL").strip().upper()
    kwargs = {"port": port}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if sec in ("STARTTLS", "TLS"):
        return MailBoxStartTls(host, **kwargs)
    if sec in ("NONE", "AUCUNE", "PLAIN", ""):
        return MailBoxUnencrypted(host, **kwargs)
    return MailBox(host, **kwargs)  # SSL par défaut


def check_connection(
    host: str, port: int, user: str, password: str, folder: str,
    security: str = "SSL",
) -> tuple[bool, str]:
    """Test de connexion IMAP : login + sélection du dossier. Retourne (ok, message)."""
    if not (host and user and password):
        return False, "Serveur, utilisateur et mot de passe requis."
    try:
        with _open_mailbox(host, port, security, timeout=15).login(
            user, password, initial_folder=folder
        ):
            return True, f"Connexion réussie — dossier « {folder} » accessible."
    except MailboxLoginError:
        return False, ("Authentification refusée. Vérifiez identifiants et sécurité ; "
                       "certains fournisseurs (Gmail, Outlook…) exigent un mot de passe d'application.")
    except MailboxFolderSelectError:
        return False, f"Connecté, mais dossier « {folder} » introuvable."
    except (socket.gaierror, socket.timeout, ConnectionError, OSError) as e:
        return False, f"Serveur injoignable ({e})."
    except Exception as e:
        return False, f"Échec de connexion : {e}"

ALLOWED_ATTACHMENT_EXTS = {".pdf", ".docx", ".doc"}


@dataclass
class Attachment:
    filename: str
    content: bytes
    ext: str


@dataclass
class FetchedEmail:
    uid: str
    subject: str
    from_addr: str
    from_name: str
    received_at: datetime
    body_text: str
    attachments: list[Attachment]
    # Message-ID RFC 5322 : identifiant porté par le mail lui-même, contrairement à
    # `uid` qui ne vaut que pour le contexte de lecture (UID IMAP, nœud pypff, EntryID
    # MAPI). Seule clé permettant de recroiser un mail entre une copie OST et la boîte
    # Outlook vivante. Vide si l'en-tête est absent ou illisible.
    message_id: str = ""


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^\w\-. ]+", "_", name).strip()
    return name or "unnamed"


def normalize_message_id(raw: str | None) -> str:
    """Met un Message-ID sous une forme comparable : sans chevrons ni espaces.

    Les sources ne s'accordent pas sur la présentation (« <a@b> », « a@b », avec des
    espaces ou un repli de ligne) alors qu'il s'agit du même identifiant. On compare
    donc des valeurs nettoyées.

    Volontairement SANS passage en minuscules : d'après la RFC 5322 seule la partie
    domaine est insensible à la casse, pas la partie locale. Deux mails distincts
    pourraient donc ne différer que par la casse. Ici un faux négatif ne coûte qu'un
    mail non rangé, là où un faux positif déplacerait le mauvais mail dans une boîte
    réelle : en cas de doute, on ne rapproche pas.
    """
    if not raw:
        return ""
    return raw.strip().strip("<>").strip()


def _imap_message_id(msg) -> str:
    """Message-ID d'un message imap_tools, lu dans les en-têtes bruts."""
    try:
        vals = msg.headers.get("message-id") or ()
        return vals[0] if vals else ""
    except Exception:
        return ""


def _extract_doc_attachments(msg) -> list[Attachment]:
    out: list[Attachment] = []
    for att in msg.attachments:
        if not att.filename:
            continue
        ext = Path(att.filename).suffix.lower()
        if ext not in ALLOWED_ATTACHMENT_EXTS:
            continue
        out.append(
            Attachment(
                filename=_safe_filename(att.filename),
                content=att.payload,
                ext=ext,
            )
        )
    return out


def fetch_new_emails(
    host: str,
    port: int,
    user: str,
    password: str,
    folder: str,
    since_days: int,
    max_emails: int,
    already_processed: callable,
    security: str = "SSL",
) -> list[FetchedEmail]:
    """Se connecte en IMAP et renvoie les emails non traités reçus depuis since_days jours."""
    since_date = (datetime.now() - timedelta(days=since_days)).date()
    fetched: list[FetchedEmail] = []

    with _open_mailbox(host, port, security).login(user, password, initial_folder=folder) as mailbox:
        criteria = AND(date_gte=since_date)
        # reverse=True : les emails les plus RÉCENTS d'abord. Essentiel : avec un
        # plafond max_emails, les candidatures récentes doivent être traitées en
        # priorité (sinon, boîte chargée = CV récents jamais atteints).
        for msg in mailbox.fetch(criteria, mark_seen=False, bulk=False, reverse=True):
            if len(fetched) >= max_emails:
                break
            uid = msg.uid
            if uid is None:
                continue
            if already_processed(uid):
                continue

            from_name = (msg.from_values.name if msg.from_values else "") or ""
            from_addr = msg.from_ or ""

            fetched.append(
                FetchedEmail(
                    uid=uid,
                    subject=msg.subject or "",
                    from_addr=from_addr,
                    from_name=from_name,
                    received_at=msg.date,
                    body_text=(msg.text or msg.html or "")[:5000],
                    attachments=_extract_doc_attachments(msg),
                    message_id=normalize_message_id(_imap_message_id(msg)),
                )
            )

    log.info("%d nouveaux emails relevés depuis %s", len(fetched), folder)
    return fetched


def save_attachment(att: Attachment, storage_dir: str, prefix: str) -> Path:
    """Enregistre la pièce jointe sur disque et renvoie son chemin complet."""
    storage = Path(storage_dir)
    storage.mkdir(parents=True, exist_ok=True)
    final_name = f"{prefix}_{att.filename}"
    out_path = storage / final_name
    counter = 1
    while out_path.exists():
        stem = Path(final_name).stem
        suffix = Path(final_name).suffix
        out_path = storage / f"{stem}_{counter}{suffix}"
        counter += 1
    out_path.write_bytes(att.content)
    return out_path
