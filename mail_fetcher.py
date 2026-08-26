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
    """Se connecte en IMAP et renvoie les emails non traités reçus depuis since_days jours.

    Important : on lit explicitement ALL (lus + non lus). Le filtre "déjà traité"
    reste géré par la table processed_emails, pas par le statut lu/non lu IMAP.
    """
    since_date = (datetime.now() - timedelta(days=since_days)).date()
    fetched: list[FetchedEmail] = []

    with _open_mailbox(host, port, security).login(user, password, initial_folder=folder) as mailbox:
        criteria = AND(all=True, date_gte=since_date)
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

    log.info("%d emails non traités relevés depuis %s", len(fetched), folder)
    return fetched


def move_processed_messages(
    host: str,
    port: int,
    user: str,
    password: str,
    folder: str,
    processed: dict[str, int],
    target_folder: str = "Traités",
    non_cv_folder: str = "",
    security: str = "SSL",
) -> tuple[int, int, str]:
    """Range les mails DÉJÀ traités du dossier IMAP dans des dossiers de la boîte.

    `processed` : uid -> is_cv, issu de `state_db.processed_uids(folder)`. Seuls les
    mails présents dans ce dict bougent — un mail jamais analysé (arrivé après le
    dernier cycle, ou hors profondeur d'historique) n'est PAS touché. Les CV vont
    dans `target_folder` ; les non-CV dans `non_cv_folder` si renseigné (sinon
    laissés en place). Les dossiers cibles sont créés s'ils n'existent pas.

    Le rapprochement par UID est sans ambiguïté ICI (même dossier que celui qui a
    produit les UID), contrairement au rangement PST/OST qui doit passer par le
    Message-ID. Après déplacement, l'UID disparaît du dossier relevé : la dédup par
    `processed_emails` n'est pas affectée (le mail n'est simplement plus relevé).

    Retourne (nb_cv_déplacés, nb_non_cv_déplacés, message de synthèse).
    """
    target_folder = (target_folder or "").strip()
    non_cv_folder = (non_cv_folder or "").strip()
    if not target_folder:
        return 0, 0, "Aucun dossier de rangement configuré : rien à faire."
    if not processed:
        return 0, 0, "Aucun mail traité connu pour ce dossier : rien à ranger."

    with _open_mailbox(host, port, security).login(
        user, password, initial_folder=folder
    ) as mailbox:
        # Intersection boîte réelle ∩ table des traités : on ne déplace que ce qui
        # est encore présent dans le dossier (le reste a déjà été rangé ou supprimé).
        uids = mailbox.uids("ALL")
        cv_uids = [u for u in uids if processed.get(u) == 1]
        non_cv_uids = [u for u in uids if processed.get(u) == 0] if non_cv_folder else []
        if not cv_uids and not non_cv_uids:
            return 0, 0, "Aucun mail traité à ranger (déjà rangés ou plus dans le dossier)."

        for dest in dict.fromkeys([target_folder] + ([non_cv_folder] if non_cv_uids else [])):
            if not mailbox.folder.exists(dest):
                mailbox.folder.create(dest)
                log.info("Dossier IMAP créé : %s", dest)

        # chunks=200 : borne la longueur de la commande UID MOVE/COPY (certains
        # serveurs rejettent les lignes trop longues sur les grosses boîtes).
        if cv_uids:
            mailbox.move(cv_uids, target_folder, chunks=200)
        if non_cv_uids:
            mailbox.move(non_cv_uids, non_cv_folder, chunks=200)

    detail = f"{len(cv_uids)} CV rangé(s) dans « {target_folder} »"
    if non_cv_folder:
        detail += f" et {len(non_cv_uids)} non-CV dans « {non_cv_folder} »"
    log.info("Rangement IMAP (%s) : %s", folder, detail)
    return len(cv_uids), len(non_cv_uids), detail + "."


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
