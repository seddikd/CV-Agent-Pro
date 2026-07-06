"""Lanceur application desktop (Windows 10/11) — mode navigateur.

Démarre le serveur FastAPI en arrière-plan sur 127.0.0.1 (port libre) puis
ouvre l'interface dans le navigateur par défaut. Une icône de la barre système
garde le serveur (et le planificateur) actifs ; son menu permet de rouvrir
l'onglet ou de quitter proprement.

Avantages vs fenêtre embarquée : téléchargements natifs (Excel, PDF), aucune
dépendance WebView2, aucun risque de gel du thread UI.
"""

import os
import sys

# En exe fenêtré (PyInstaller console=False), sys.stdout/stderr valent None au
# double-clic (aucune console). uvicorn plante alors en configurant son logging
# (isatty() sur None). On redirige donc TÔT vers un fichier, avant tout import
# qui touche au logging (uvicorn, webapp).
if sys.stdout is None or sys.stderr is None:
    try:
        import app_paths as _ap
        _logdir = str(_ap.data_path("logs"))
        os.makedirs(_logdir, exist_ok=True)
        _f = open(os.path.join(_logdir, "desktop.out.log"), "a", encoding="utf-8", buffering=1)
    except Exception:
        import io
        _f = io.StringIO()
    if sys.stdout is None:
        sys.stdout = _f
    if sys.stderr is None:
        sys.stderr = _f

import socket
import threading
import time
import webbrowser

import uvicorn

import app_paths
from webapp import app as fastapi_app  # import direct : détectable par PyInstaller


APP_TITLE = "CV Agent"
_MUTEX_NAME = "Global\\CV-Agent-Desktop-SingleInstance"


def _already_running() -> bool:
    """Instance unique via un mutex nommé Windows (no-op ailleurs)."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, wintypes.BOOL(True), _MUTEX_NAME)
    ERROR_ALREADY_EXISTS = 183
    return kernel32.GetLastError() == ERROR_ALREADY_EXISTS


def _free_port(preferred: int = 8756) -> int:
    """Renvoie un port loopback libre (essaie d'abord `preferred`)."""
    for candidate in (preferred, 0):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", candidate))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError("Aucun port loopback disponible")


def _wait_until_up(port: int, timeout: float = 30.0) -> bool:
    """Attend que le serveur accepte les connexions."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.15)
    return False


def _message_box(text: str, flags: int = 0x40) -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, APP_TITLE, flags)
        except Exception:
            pass


def _create_admin_from_file(path: str) -> None:
    """Crée le 1er admin depuis un fichier (email / nom / mot de passe sur 3 lignes).

    Appelé par l'installeur (`CV-Agent.exe --create-admin <fichier>`). Idempotent :
    ne fait rien si un admin existe déjà. Le fichier est supprimé après lecture.
    """
    import state_db
    import web_db
    import web_auth

    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return
    finally:
        try:
            os.remove(path)  # ne jamais laisser traîner les identifiants
        except OSError:
            pass

    # Détection d'encodage par BOM (Inno peut écrire en UTF-16 / UTF-8 / ANSI).
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raw = data.decode("utf-16", errors="replace")
    elif data[:3] == b"\xef\xbb\xbf":
        raw = data.decode("utf-8-sig", errors="replace")
    else:
        try:
            raw = data.decode("utf-8")
        except UnicodeDecodeError:
            raw = data.decode("cp1252", errors="replace")

    if not raw:
        return
    # Découpage tolérant aux CR superflus (\r\r\n) : on scinde sur \n puis on
    # retire les \r de fin, plutôt que splitlines() qui insérerait des lignes vides.
    lines = [ln.rstrip("\r") for ln in raw.split("\n")]
    if len(lines) < 3:
        return
    email, name, password = lines[0].strip(), lines[1].strip(), lines[2]

    db = str(app_paths.db_path())
    try:
        state_db.init(db)
        web_db.seed_default_settings(db)
        if web_db.admin_count(db) == 0 and email and len(password) >= 8:
            web_db.create_user(
                db, email, name or email, web_auth.hash_password(password), role="admin"
            )
            print(f"Admin créé : {email}", flush=True)
        else:
            print("Admin non créé (déjà existant ou données invalides).", flush=True)
    except Exception as e:
        # Surfacer l'erreur dans le log plutôt qu'échouer en silence.
        print(f"Échec création admin : {e}", flush=True)


def _build_tray(url: str, server):
    """Icône de la barre système : Ouvrir dans le navigateur / Quitter."""
    import pystray
    from PIL import Image

    image = Image.open(str(app_paths.resource("static", "app.ico")))

    def _open(icon=None, item=None):
        webbrowser.open(url)

    def _quit(icon=None, item=None):
        server.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Ouvrir dans le navigateur", _open, default=True),
        pystray.MenuItem("Quitter", _quit),
    )
    return pystray.Icon("cv-agent", image, f"{APP_TITLE} — {url}", menu)


def main() -> None:
    # Création de l'admin par l'installeur (one-shot, pas de serveur).
    if "--create-admin" in sys.argv:
        i = sys.argv.index("--create-admin")
        if i + 1 < len(sys.argv):
            _create_admin_from_file(sys.argv[i + 1])
        return

    # Mode headless : sert l'app sans ouvrir le navigateur ni le systray.
    server_only = "--server-only" in sys.argv

    if not server_only and _already_running():
        _message_box("CV Agent est déjà en cours d'exécution.")
        return

    port = _free_port()

    config = uvicorn.Config(
        fastapi_app, host="127.0.0.1", port=port,
        log_level="info", lifespan="on",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    if not _wait_until_up(port):
        _message_box("Le serveur n'a pas démarré (voir logs).", 0x10)
        server.should_exit = True
        return

    url = f"http://127.0.0.1:{port}"
    print(f"CV Agent en écoute sur {url}", flush=True)

    if server_only:
        try:
            thread.join()
        except KeyboardInterrupt:
            server.should_exit = True
            thread.join(timeout=8)
        return

    # Ouvre l'interface dans le navigateur par défaut.
    webbrowser.open(url)

    # Systray sur le thread principal : garde le serveur actif, gère l'arrêt.
    try:
        icon = _build_tray(url, server)
        icon.run()  # bloque jusqu'à "Quitter"
    except Exception as e:
        # Sans systray : on GARDE le serveur actif (l'utilisateur utilise le
        # navigateur) en bloquant sur le thread, au lieu de tout arrêter.
        print(f"Systray indisponible ({e}). CV Agent tourne sur {url}.", flush=True)
        _message_box(
            f"CV Agent tourne sur {url}.\n\n"
            "Systray indisponible : pour quitter, utilise le Gestionnaire des tâches."
        )
        try:
            thread.join()   # reste vivant jusqu'à l'arrêt du processus
        except KeyboardInterrupt:
            pass

    # Arrêt propre du serveur (et du planificateur via lifespan).
    server.should_exit = True
    thread.join(timeout=8)


if __name__ == "__main__":
    main()
