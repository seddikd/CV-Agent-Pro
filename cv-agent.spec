# -*- mode: python ; coding: utf-8 -*-
# Spec PyInstaller pour l'application desktop CV Agent.
# Build : voir build_exe.ps1  (ou : pyinstaller cv-agent.spec --noconfirm)
#
# Mode "onedir" : dossier dist\CV-Agent\ contenant CV-Agent.exe + _internal\.
# Démarrage rapide, dépendances rassemblées dans le même dossier (rien à installer).

from PyInstaller.utils.hooks import collect_submodules, collect_all

# pystray charge son backend dynamiquement : collect_all embarque tout le paquet.
_ps_datas, _ps_binaries, _ps_hidden = collect_all("pystray")

# psycopg (PostgreSQL) et son binaire : collect_all pour embarquer les libs natives.
_pg_datas, _pg_binaries, _pg_hidden = collect_all("psycopg")
_pgb_datas, _pgb_binaries, _pgb_hidden = collect_all("psycopg_binary")

# Backends d'import Outlook (PST/OST), optionnels selon l'environnement de build :
# pypff (libpff, extension C) et win32com (Outlook). collect_all/submodules guardés
# pour ne pas casser le build si l'un n'est pas installé sur la machine de build.
_ol_datas, _ol_binaries, _ol_hidden = [], [], []
try:
    _pf_datas, _pf_binaries, _pf_hidden = collect_all("pypff")
    _ol_datas += _pf_datas; _ol_binaries += _pf_binaries; _ol_hidden += _pf_hidden
except Exception:
    pass
try:
    _ol_hidden += collect_submodules("win32com") + ["pythoncom", "pywintypes", "win32api"]
except Exception:
    pass

# uvicorn charge dynamiquement ses boucles/protocoles/lifespan : à forcer.
hiddenimports = (
    collect_submodules("uvicorn")
    + _ps_hidden + _pg_hidden + _pgb_hidden + _ol_hidden
    + [
        "app_paths", "app_runtime", "webapp", "web_db", "web_auth", "web_pipeline",
        "db", "state_db", "secret_store", "excel_export", "mail_fetcher", "pdf_extractor",
        "outlook_fetcher",
        "llm_provider", "llm_classifier", "llm_extractor", "notifier",
        # Socle + logique partagés des modules ATS.
        "web_core", "matching_core", "alerts_engine", "entretien_reminders",
        # Référentiel géographique (wilayas/communes d'Algérie) utilisé par mod_search.
        "algeria_geo",
        # Routeurs de modules ATS (mod_*.py) — importés au runtime par webapp.
        "mod_dashboard", "mod_search", "mod_jobs", "mod_compare", "mod_notes",
        "mod_duplicates", "mod_summary", "mod_documents", "mod_matching",
        "mod_search_ia", "mod_pipeline", "mod_stats", "mod_alerts", "mod_api",
        "mod_entretiens",
        "PIL.Image",  # icône du systray
    ]
)

# Ressources embarquées en lecture seule (l'UI + le modèle de config).
datas = [
    ("templates", "templates"),
    ("static", "static"),
    ("config.yaml", "."),
] + _ps_datas + _pg_datas + _pgb_datas + _ol_datas

a = Analysis(
    ["desktop.py"],
    pathex=["."],
    binaries=_ps_binaries + _pg_binaries + _pgb_binaries + _ol_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "matplotlib", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CV-Agent",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # application fenêtrée : pas de console noire
    icon="static/app.ico" if __import__("os").path.exists("static/app.ico") else None,
    version="version_info.txt" if __import__("os").path.exists("version_info.txt") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CV-Agent",
)
