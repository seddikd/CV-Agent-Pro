"""Module « Gestion documentaire » : pièces jointes par candidat. Routeur isolé."""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from web_core import require_user, render, connect
import db
import app_paths

router = APIRouter()

# Types de documents autorisés ; toute autre valeur est ramenée à « Autre ».
DOC_TYPES = ["CV", "Diplôme", "Certificat", "Portfolio", "Autre"]

# Taille maximale d'un upload (20 Mo). Lecture par blocs bornée : sans plafond, un
# fichier de plusieurs Go était bufferisé en RAM d'un coup et pouvait saturer le
# process uvicorn mono-worker (qui porte aussi le planificateur du pipeline).
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_CHUNK = 1024 * 1024


def _docs_dir() -> Path:
    """Dossier de stockage des pièces jointes (créé au besoin)."""
    d = app_paths.data_path("cv_pdfs") / "documents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _list_documents(cid: int) -> list[dict]:
    """Renvoie les documents d'un candidat, les plus récents d'abord."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, candidate_id, doc_type, filename, stored_path,
                   uploaded_by, uploaded_at
            FROM candidate_documents
            WHERE candidate_id = ?
            ORDER BY id DESC
            """,
            (cid,),
        ).fetchall()
    return [dict(r) for r in rows]


def _fragment(request: Request, cid: int):
    """Rend le fragment `_documents.html` à jour pour un candidat."""
    documents = _list_documents(cid)
    return render(
        request,
        "_documents.html",
        {"cid": cid, "documents": documents, "doc_types": DOC_TYPES},
    )


@router.get("/candidate/{cid}/documents")
def get_documents(request: Request, cid: int):
    """Fragment « Documents » : liste des pièces jointes + formulaire d'upload."""
    require_user(request)
    return _fragment(request, cid)


@router.post("/candidate/{cid}/documents")
async def add_document(
    request: Request,
    cid: int,
    fichier: UploadFile = File(...),
    doc_type: str = Form("Autre"),
):
    """Enregistre un fichier sur disque + une ligne en base, puis rend le fragment."""
    user = require_user(request)

    # Refuse si aucun fichier réellement transmis.
    if fichier is None or not fichier.filename:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni.")

    # Valide le type de document.
    if doc_type not in DOC_TYPES:
        doc_type = "Autre"

    # Anti-traversal : ne conserve que le nom de base fourni par le client.
    original = Path(fichier.filename).name or "document"

    # Nom de stockage unique : id candidat + timestamp + nom d'origine.
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    stored_name = f"{cid}_{stamp}_{original}"
    stored_path = _docs_dir() / stored_name

    # Lecture par blocs avec plafond : borne l'empreinte mémoire et refuse (413)
    # au-delà de MAX_UPLOAD_BYTES au lieu de tout charger en RAM.
    data = bytearray()
    while True:
        chunk = await fichier.read(_CHUNK)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Fichier trop volumineux (max {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo).",
            )
    if not data:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    stored_path.write_bytes(bytes(data))

    with connect() as conn:
        db.insert_returning_id(
            conn,
            """
            INSERT INTO candidate_documents
                (candidate_id, doc_type, filename, stored_path,
                 uploaded_by, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                cid,
                doc_type,
                original,
                str(stored_path),
                user["id"],
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

    return _fragment(request, cid)


@router.get("/document/{doc_id}")
def download_document(request: Request, doc_id: int):
    """Télécharge le fichier associé à un document (404 si absent base ou disque)."""
    require_user(request)
    with connect() as conn:
        row = conn.execute(
            "SELECT filename, stored_path FROM candidate_documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    path = Path(row["stored_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier absent du disque.")
    return FileResponse(str(path), filename=row["filename"])


@router.post("/document/{doc_id}/delete")
def delete_document(request: Request, doc_id: int):
    """Supprime la ligne en base ET le fichier disque, puis rend le fragment à jour."""
    require_user(request)
    with connect() as conn:
        row = conn.execute(
            "SELECT candidate_id, stored_path FROM candidate_documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Document introuvable.")
        cid = row["candidate_id"]
        stored_path = row["stored_path"]
        conn.execute("DELETE FROM candidate_documents WHERE id = ?", (doc_id,))
        conn.commit()

    # Supprime le fichier disque (ignore l'erreur s'il est déjà absent).
    try:
        Path(stored_path).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass

    return _fragment(request, cid)
