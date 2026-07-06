"""Chiffrement au repos des secrets (mots de passe IMAP/SMTP, clé API cloud).

Deux schémas de stockage, choisis automatiquement selon le déploiement :

- « enc:v2: » — PORTABLE (déploiement multi-postes / base PostgreSQL partagée).
  Chiffrement authentifié Fernet (AES-128-CBC + HMAC-SHA256), avec une clé dérivée
  (PBKDF2-HMAC-SHA256) de la variable d'environnement CV_AGENT_SECRET. Tous les
  postes qui partagent la MÊME base ET le MÊME CV_AGENT_SECRET peuvent déchiffrer.
  Utilisé dès que CV_AGENT_SECRET est défini.

- « enc:v1: » — MACHINE-LIÉ (déploiement mono-poste, sans CV_AGENT_SECRET).
  DPAPI Windows (CryptProtectData) en portée MACHINE : pas de clé à gérer, mais un
  state.db copié ailleurs devient inexploitable. Repli quand CV_AGENT_SECRET est
  absent et que DPAPI est disponible.

Une valeur SANS préfixe est un secret « legacy » en clair (compat ascendante),
renvoyée telle quelle par decrypt(). Si aucun schéma n'est disponible (ni
CV_AGENT_SECRET, ni DPAPI — ex. dev Linux/Mac), encrypt() renvoie la valeur en
clair en logguant un avertissement, pour ne jamais bloquer l'enregistrement.
"""

import base64
import logging
import os
import sys

log = logging.getLogger("cv_agent.secrets")

_PREFIX_V1 = "enc:v1:"      # DPAPI, machine-lié
_PREFIX_V2 = "enc:v2:"      # Fernet portable (CV_AGENT_SECRET)
_CRYPTPROTECT_LOCAL_MACHINE = 0x04

# Dérivation de clé : sel applicatif fixe + itérations élevées. CV_AGENT_SECRET est
# censé être un secret à forte entropie (ex. `python -c "import secrets;
# print(secrets.token_hex(32))"`) partagé identique sur tous les postes.
_KDF_SALT = b"cv-agent/secret-store/v2"
_KDF_ITERATIONS = 200_000

# Cache (secret_env -> instance Fernet) pour éviter de redériver la clé à chaque appel.
_fernet_cache: dict[str, object] = {}


# ─── Schéma v2 : Fernet portable (CV_AGENT_SECRET) ───────────────────────────

def _portable_secret() -> str | None:
    """Secret partagé pour le chiffrement portable, ou None (=> repli DPAPI)."""
    return os.environ.get("CV_AGENT_SECRET") or None


def _fernet(secret: str):
    """Instance Fernet dérivée du secret partagé (mise en cache)."""
    cached = _fernet_cache.get(secret)
    if cached is not None:
        return cached
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=_KDF_SALT,
        iterations=_KDF_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))
    f = Fernet(key)
    _fernet_cache[secret] = f
    return f


# ─── Schéma v1 : DPAPI Windows (machine-lié) ─────────────────────────────────

def _dpapi_available() -> bool:
    return sys.platform == "win32"


if _dpapi_available():
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    def _to_blob(data: bytes) -> _DATA_BLOB:
        buf = ctypes.create_string_buffer(data, len(data))
        return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _from_blob(blob: "_DATA_BLOB") -> bytes:
        out = ctypes.create_string_buffer(blob.cbData)
        ctypes.memmove(out, blob.pbData, blob.cbData)
        return out.raw

    def _dpapi_encrypt(plaintext: bytes) -> bytes:
        in_blob = _to_blob(plaintext)
        out_blob = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(in_blob), None, None, None, None,
            _CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(out_blob),
        )
        if not ok:
            raise OSError("CryptProtectData a échoué")
        try:
            return _from_blob(out_blob)
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)

    def _dpapi_decrypt(blob_bytes: bytes) -> bytes:
        in_blob = _to_blob(blob_bytes)
        out_blob = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None,
            0, ctypes.byref(out_blob),
        )
        if not ok:
            raise OSError("CryptUnprotectData a échoué")
        try:
            return _from_blob(out_blob)
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)


# ─── API publique ────────────────────────────────────────────────────────────

def is_encrypted(value: str) -> bool:
    return bool(value) and (value.startswith(_PREFIX_V2) or value.startswith(_PREFIX_V1))


def encrypt(plaintext: str) -> str:
    """Chiffre un secret pour le stockage. Idempotent ; no-op sur valeur vide.

    Choisit le schéma portable (v2) si CV_AGENT_SECRET est défini, sinon DPAPI (v1).
    Renvoie la valeur en clair (inchangée) si aucun schéma n'est disponible ou en
    cas d'échec, afin de ne jamais bloquer l'enregistrement des réglages."""
    if not plaintext or is_encrypted(plaintext):
        return plaintext

    secret = _portable_secret()
    if secret:
        try:
            token = _fernet(secret).encrypt(plaintext.encode("utf-8"))
            return _PREFIX_V2 + token.decode("ascii")
        except Exception as e:  # noqa: BLE001 - repli sûr : ne pas planter l'UI réglages
            log.warning("Chiffrement portable (v2) échoué (%s) : repli.", e)

    if _dpapi_available():
        try:
            blob = _dpapi_encrypt(plaintext.encode("utf-8"))
            return _PREFIX_V1 + base64.b64encode(blob).decode("ascii")
        except Exception as e:  # noqa: BLE001
            log.warning("Chiffrement DPAPI (v1) échoué (%s) : secret stocké en clair.", e)
            return plaintext

    log.warning(
        "Aucun schéma de chiffrement (ni CV_AGENT_SECRET, ni DPAPI) : secret en clair."
    )
    return plaintext


def decrypt(value: str) -> str:
    """Déchiffre une valeur stockée selon son préfixe.

    Une valeur sans préfixe (legacy/clair) est renvoyée telle quelle. En cas
    d'échec (mauvais/absent CV_AGENT_SECRET pour un blob v2, base v1 copiée sur une
    autre machine…), renvoie une chaîne vide plutôt que de planter — le pipeline
    traitera cela comme « pas d'identifiants »."""
    if not value:
        return value

    if value.startswith(_PREFIX_V2):
        secret = _portable_secret()
        if not secret:
            log.warning("Secret chiffré (v2) mais CV_AGENT_SECRET absent : illisible.")
            return ""
        try:
            token = value[len(_PREFIX_V2):].encode("ascii")
            return _fernet(secret).decrypt(token).decode("utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("Déchiffrement portable (v2) échoué (%s) : illisible.", e)
            return ""

    if value.startswith(_PREFIX_V1):
        if not _dpapi_available():
            log.warning("Secret chiffré (v1/DPAPI) mais DPAPI indisponible : illisible.")
            return ""
        try:
            blob = base64.b64decode(value[len(_PREFIX_V1):])
            return _dpapi_decrypt(blob).decode("utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("Déchiffrement DPAPI (v1) échoué (%s) : illisible.", e)
            return ""

    # Pas de préfixe : secret legacy en clair.
    return value
