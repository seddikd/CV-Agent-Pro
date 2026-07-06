"""Chiffrement au repos des secrets (mots de passe IMAP/SMTP, clé API cloud).

Sur Windows, on utilise DPAPI (`CryptProtectData`) en portée MACHINE : le secret
est chiffré avec une clé dérivée de la machine, sans fichier de clé à gérer. Un
`state.db` copié sur une autre machine devient inexploitable (les blobs ne s'y
déchiffrent pas). La portée MACHINE (et non UTILISATEUR) évite les échecs de
déchiffrement quand l'app tourne tantôt en session interactive, tantôt via la
tâche planifiée : n'importe quel compte de CETTE machine peut relire.

Schéma de stockage : les valeurs chiffrées sont préfixées « enc:v1: » suivi du
blob DPAPI en base64. Une valeur SANS ce préfixe est considérée comme un secret
« legacy » en clair (compat ascendante) et renvoyée telle quelle par decrypt().

Hors Windows (dev Linux/Mac), DPAPI est indisponible : encrypt() renvoie la
valeur inchangée (stockée en clair) et logge un avertissement. La cible de
production étant Windows, ce repli n'affecte pas le déploiement réel.
"""

import base64
import logging
import sys

log = logging.getLogger("cv_agent.secrets")

_PREFIX = "enc:v1:"
_CRYPTPROTECT_LOCAL_MACHINE = 0x04


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


def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(_PREFIX)


def encrypt(plaintext: str) -> str:
    """Chiffre un secret pour le stockage. Idempotent ; no-op sur valeur vide.

    Renvoie la valeur en clair (inchangée) si DPAPI est indisponible ou échoue,
    afin de ne jamais bloquer l'enregistrement des réglages."""
    if not plaintext or is_encrypted(plaintext):
        return plaintext
    if not _dpapi_available():
        log.warning("DPAPI indisponible (%s) : secret stocké en clair.", sys.platform)
        return plaintext
    try:
        blob = _dpapi_encrypt(plaintext.encode("utf-8"))
        return _PREFIX + base64.b64encode(blob).decode("ascii")
    except Exception as e:  # noqa: BLE001 - repli sûr : ne pas planter l'UI réglages
        log.warning("Chiffrement DPAPI échoué (%s) : secret stocké en clair.", e)
        return plaintext


def decrypt(value: str) -> str:
    """Déchiffre une valeur stockée. Une valeur sans préfixe (legacy/clair) est
    renvoyée telle quelle. En cas d'échec (ex. base migrée sur une autre machine),
    renvoie une chaîne vide plutôt que de planter — le pipeline traitera cela
    comme « pas d'identifiants »."""
    if not is_encrypted(value):
        return value
    if not _dpapi_available():
        log.warning("Valeur chiffrée mais DPAPI indisponible : secret illisible.")
        return ""
    try:
        blob = base64.b64decode(value[len(_PREFIX):])
        return _dpapi_decrypt(blob).decode("utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("Déchiffrement DPAPI échoué (%s) : secret illisible.", e)
        return ""
