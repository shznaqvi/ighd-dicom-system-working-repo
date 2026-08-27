# dicom_upload_server.py
import asyncio
import io
import json
import zipfile
from pathlib import Path, PurePosixPath

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

# =========================================================
# CONFIG
# =========================================================
DICOM_ROOT = Path(r"D:\IGHD_DICOM_VIEWER\raw_data")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Shared session storage for progress tracking
_sessions = {}


def _sanitise_relative_path(rel_path):
    """Prevents directory traversal attacks."""
    parts = [p for p in PurePosixPath(rel_path).parts if p not in ("", ".", "..")]
    return Path(*parts)


@app.get("/health")
async def health():
    # Check if the folder actually exists on the E:\ drive
    if DICOM_ROOT.exists():
        return {"status": "ok", "dicom_root": str(DICOM_ROOT)}
    else:
        # If the drive was unplugged or the folder was deleted, return a 500 error
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="DICOM root directory not found on server")


# =========================================================
# BACKGROUND WORKER (Runs safely outside the event loop)
# =========================================================
def _extract_zip_in_background(zip_bytes: bytes, session_id: str) -> int:
    """Synchronous function that does the heavy lifting in a background thread."""
    zip_buffer = io.BytesIO(zip_bytes)

    with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
        file_list = zip_ref.namelist()

        # Update the global tracker that the thread has started
        _sessions[session_id]["total"] = len(file_list)
        _sessions[session_id]["status"] = "extracting"

        count = 0
        for member in file_list:
            if member.endswith('/') or "__MACOSX" in member:
                continue

            safe_rel = _sanitise_relative_path(member)
            dest_path = DICOM_ROOT / safe_rel

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(zip_ref.read(member))

            count += 1
            # Real-time update to the global dictionary
            _sessions[session_id]["done"] = count

        _sessions[session_id]["status"] = "completed"
        return count


# ----------------------------------------------------------
# POST /upload-zip
# This is where the "Decompressing" happens on the server
# ----------------------------------------------------------
@app.post("/upload-zip")
async def upload_zip(
        file: UploadFile = File(...),
        session_id: str = Form(...)
):
    try:
        # 1. Read the network stream into memory (Async)
        content = await file.read()

        # 2. Immediately register the session so the frontend can start tracking
        _sessions[session_id] = {
            "total": 0,
            "done": 0,
            "status": "starting"
        }

        # 3. Offload the heavy extraction loop to a separate CPU thread!
        # This prevents FastAPI from freezing, allowing the progress endpoint to work.
        count = await asyncio.to_thread(_extract_zip_in_background, content, session_id)

        return {
            "status": "saved",
            "message": f"Successfully extracted {count} files",
            "session_id": session_id
        }

    except Exception as e:
        return JSONResponse(
            {"status": "error", "reason": str(e)},
            status_code=422
        )


@app.get("/upload-progress/{session_id}")
async def get_progress(session_id: str):
    """The Streamlit frontend will rapidly ping this to draw the progress bar."""
    if session_id in _sessions:
        return _sessions[session_id]

    return {"status": "not_found", "total": 0, "done": 0}


@app.get("/studies")
async def list_studies():
    if not DICOM_ROOT.exists():
        return []

    studies = []
    # Traverse DICOM_ROOT to find Patient/Study folders
    for p_dir in sorted(DICOM_ROOT.iterdir()):
        if not p_dir.is_dir(): continue
        for s_dir in sorted(p_dir.iterdir()):
            if not s_dir.is_dir(): continue

            # Count DICOM files in this study
            dcms = list(s_dir.rglob("*.dcm"))
            studies.append({
                "patient_id": p_dir.name,
                "study_uid": s_dir.name,
                "file_count": len(dcms)
            })
    return studies


@app.get("/qc")
async def load_qc_summary(qc_file="study_qc.json"):
    """Read local QC forms and return {patient_id: {v, g, a}} counts."""
    if not os.path.exists(qc_file):
        return {}
    try:
        with open(qc_file) as f:
            forms = json.load(f)
    except Exception:
        return {}

    summary = {}
    for record in forms.values():
        pid = record.get("details", {}).get("case_no", "")
        if not pid:
            continue
        s = summary.setdefault(pid, {"v": 0, "g": 0, "a": 0, "c": 0})
        if "Viability" in record: s["v"] += 1
        if "Growth" in record: s["g"] += 1
        if "Anomaly" in record: s["a"] += 1
        if ("Viability" in record and "Growth" in record and "Anomaly" in record):
            s["c"] += 1
    return summary


if __name__ == "__main__":
    DICOM_ROOT.mkdir(parents=True, exist_ok=True)
    uvicorn.run(app, host="0.0.0.0", port=8502)
