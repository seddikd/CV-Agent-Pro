"""Convertit les manuels Markdown -> PDF via Edge en mode headless.

Sans argument, génère TOUS les manuels ci-dessous. Avec un argument (nom de base
sans extension, ex. « MANUEL_DEPLOIEMENT »), ne génère que celui-là.
"""

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import markdown


HERE = Path(__file__).parent

# (fichier .md, titre affiché dans le PDF). Le .pdf porte le même nom de base.
MANUELS = [
    ("MANUEL_UTILISATION.md", "Manuel utilisateur — CV Agent"),
    ("MANUEL_DEPLOIEMENT.md", "Manuel de déploiement — CV Agent"),
]

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
* { box-sizing: border-box; }
body {
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.45;
    color: #1f2328;
    max-width: 100%;
}
h1 { font-size: 22pt; color: #0b3d91; border-bottom: 2px solid #0b3d91; padding-bottom: 6px; margin-top: 0; }
h2 { font-size: 16pt; color: #0b3d91; border-bottom: 1px solid #d0d7de; padding-bottom: 4px; margin-top: 22pt; page-break-after: avoid; }
h3 { font-size: 13pt; color: #1f4e79; margin-top: 16pt; page-break-after: avoid; }
h4 { font-size: 11pt; color: #1f4e79; margin-top: 12pt; }
p { margin: 6pt 0; }
ul, ol { margin: 6pt 0 6pt 18pt; }
li { margin: 2pt 0; }
code {
    font-family: "Cascadia Mono", "Consolas", monospace;
    background: #f3f4f6;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 9.5pt;
    color: #c7254e;
}
pre {
    background: #0d1117;
    color: #e6edf3;
    padding: 10px 12px;
    border-radius: 6px;
    overflow-x: auto;
    page-break-inside: avoid;
    font-size: 9pt;
    line-height: 1.4;
}
pre code { background: transparent; color: inherit; padding: 0; font-size: inherit; }
table {
    border-collapse: collapse;
    width: 100%;
    margin: 8pt 0;
    page-break-inside: avoid;
    font-size: 9.5pt;
}
th, td {
    border: 1px solid #d0d7de;
    padding: 5px 7px;
    text-align: left;
    vertical-align: top;
}
th { background: #305496; color: white; font-weight: 600; }
tr:nth-child(even) td { background: #f6f8fa; }
blockquote {
    border-left: 4px solid #ffa500;
    background: #fff8e6;
    padding: 6px 12px;
    margin: 8pt 0;
    color: #6a4a00;
    page-break-inside: avoid;
}
hr { border: none; border-top: 1px solid #d0d7de; margin: 16pt 0; }
a { color: #0969da; text-decoration: none; }
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>"""


def find_edge() -> str:
    for path in EDGE_CANDIDATES:
        if Path(path).exists():
            return path
    sys.exit("Edge introuvable. Vérifie l'installation de Microsoft Edge.")


# Marqueurs de la page d'erreur d'Edge (rendue en PDF quand il ne trouve pas la
# source) — sert de garde-fou pour ne jamais livrer un PDF vide/corrompu.
_ERREUR_MARQUEURS = ("File not found", "moved, edited, or deleted", "ERR_FILE_NOT_FOUND")


def _attendre_pdf_stable(pdf_path: Path, timeout: float = 40.0) -> bool:
    """Attend que le PDF existe ET que sa taille soit stable (écriture terminée).

    Edge peut rendre la main avant la fin de l'écriture ; on considère le fichier
    prêt quand sa taille (> 0) est identique sur deux lectures consécutives.
    """
    deadline = time.monotonic() + timeout
    derniere = -1
    stable = 0
    while time.monotonic() < deadline:
        taille = pdf_path.stat().st_size if pdf_path.exists() else 0
        if taille > 0 and taille == derniere:
            stable += 1
            if stable >= 2:
                return True
        else:
            stable = 0
        derniere = taille
        time.sleep(0.5)
    return pdf_path.exists() and pdf_path.stat().st_size > 0


def _verifier_pdf(pdf_path: Path, md_name: str) -> None:
    """Refuse un PDF qui serait en réalité la page d'erreur d'Edge (best effort)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return  # pypdf absent : on ne peut pas vérifier, on laisse passer.
    try:
        texte = (PdfReader(str(pdf_path)).pages[0].extract_text() or "")
    except Exception:
        return
    if any(m in texte for m in _ERREUR_MARQUEURS):
        pdf_path.unlink(missing_ok=True)
        sys.exit(
            f"PDF invalide (page d'erreur Edge) pour {md_name} : "
            "génération annulée. Fermez les instances Edge et réessayez."
        )


def build_one(edge_exe: str, md_name: str, title: str) -> None:
    md_path = HERE / md_name
    pdf_path = md_path.with_suffix(".pdf")
    if not md_path.exists():
        sys.exit(f"Fichier introuvable : {md_path}")

    md_text = md_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "sane_lists", "nl2br"],
    )
    full_html = HTML_TEMPLATE.format(css=CSS, body=html_body, title=title)

    # HTML temporaire écrit DANS le dossier projet : Edge headless échoue à charger
    # les fichiers de %TEMP% (il rend alors sa page d'erreur « File not found » en
    # PDF). Nom unique préfixé « . », supprimé dans le finally.
    tmp_html_path = HERE / f".__pdf_{md_path.stem}.html"
    tmp_html_path.write_text(full_html, encoding="utf-8")

    print(f"Génération PDF -> {pdf_path.name}")
    pdf_path.unlink(missing_ok=True)  # repart d'un état propre (pas de vieux PDF)

    try:
        # msedge.exe rend souvent la main AVANT qu'un process enfant ait fini
        # d'écrire le PDF. On attend donc son apparition ET la stabilisation de sa
        # taille (écriture terminée) avant de conclure — sinon un retry lancerait un
        # 2e Edge qui écrit le même fichier en concurrence (PDF corrompu). Chaque
        # essai a son propre user-data-dir (isolation de profil, requise).
        result = None
        ok = False
        for essai in range(1, 4):
            profile_dir = Path(tempfile.mkdtemp(prefix="cvagent_pdf_"))
            result = subprocess.run(
                [
                    edge_exe,
                    "--headless=new",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-pdf-header-footer",
                    f"--user-data-dir={profile_dir}",
                    f"--print-to-pdf={pdf_path}",
                    tmp_html_path.as_uri(),
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )
            ok = _attendre_pdf_stable(pdf_path)
            shutil.rmtree(profile_dir, ignore_errors=True)
            if ok:
                break
            pdf_path.unlink(missing_ok=True)  # purge un éventuel partiel avant retry
            if essai < 3:
                print(f"  essai {essai} échoué — nouvelle tentative…")
                time.sleep(2)
    finally:
        tmp_html_path.unlink(missing_ok=True)

    if not ok:
        print("returncode:", result.returncode if result else "?")
        print("STDOUT:", result.stdout if result else "")
        print("STDERR:", result.stderr if result else "")
        sys.exit(f"Échec de la génération PDF : {md_name}")

    _verifier_pdf(pdf_path, md_name)
    size_kb = pdf_path.stat().st_size / 1024
    print(f"OK ({size_kb:.0f} KB) : {pdf_path.name}")


def main() -> None:
    # Filtre optionnel : nom de base (avec ou sans .md) pour ne générer qu'un manuel.
    cible = sys.argv[1] if len(sys.argv) > 1 else None
    manuels = MANUELS
    if cible:
        base = Path(cible).stem
        manuels = [(md, t) for md, t in MANUELS if Path(md).stem == base]
        if not manuels:
            sys.exit(f"Manuel inconnu : {cible} (attendus : "
                     + ", ".join(Path(m).stem for m, _ in MANUELS) + ")")

    edge_exe = find_edge()
    for md_name, title in manuels:
        build_one(edge_exe, md_name, title)


if __name__ == "__main__":
    main()
