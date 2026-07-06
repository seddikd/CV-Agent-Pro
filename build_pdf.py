"""Convert MANUEL_UTILISATION.md -> PDF using Edge headless mode."""

import subprocess
import sys
import tempfile
from pathlib import Path

import markdown


HERE = Path(__file__).parent
MD_PATH = HERE / "MANUEL_UTILISATION.md"
PDF_PATH = HERE / "MANUEL_UTILISATION.pdf"

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
<title>Manuel CV Agent</title>
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


def main() -> None:
    if not MD_PATH.exists():
        sys.exit(f"Fichier introuvable : {MD_PATH}")

    md_text = MD_PATH.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "sane_lists", "nl2br"],
    )
    full_html = HTML_TEMPLATE.format(css=CSS, body=html_body)

    with tempfile.NamedTemporaryFile(
        "w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(full_html)
        tmp_html_path = Path(tmp.name)

    edge_exe = find_edge()
    file_uri = tmp_html_path.as_uri()

    print(f"Génération PDF -> {PDF_PATH}")
    result = subprocess.run(
        [
            edge_exe,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={PDF_PATH}",
            file_uri,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    tmp_html_path.unlink(missing_ok=True)

    if result.returncode != 0 or not PDF_PATH.exists():
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        sys.exit("Échec de la génération PDF.")

    size_kb = PDF_PATH.stat().st_size / 1024
    print(f"OK ({size_kb:.0f} KB) : {PDF_PATH}")


if __name__ == "__main__":
    main()
