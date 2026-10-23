# dicom_upload_server.py

import json
import logging
import os
import shutil
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict

import pydicom
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Path as PathParam,
    Query,
    UploadFile,
    status,
    Request
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

# =========================================================
# 1. VERBOSE LOGGING CONFIGURATION (Docker stdout)
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d) - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("dicom_upload_server")

app = FastAPI(title="IGHD DICOM Upload & Inventory Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/raw_data")
QC_FILE = os.getenv("QC_FILE", "/qc_data/study_qc.json")

# Optimal worker count for I/O & decompression
MAX_WORKERS = min(32, (os.cpu_count() or 4) * 2)

upload_progress: Dict[str, dict] = {}

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.dirname(QC_FILE), exist_ok=True)


# =========================================================
# 2. HEALTH & PROGRESS ENDPOINTS
# =========================================================
@app.get("/")
@app.get("/health")
@app.get("/health/")
def health_check():
    return {"status": "online", "dicom_root": OUTPUT_DIR}


def _extract_single_member(zip_path: str, member_name: str, output_dir: str):
    """Worker task for parallel zip extraction."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extract(member_name, output_dir)


def process_zip_extraction(session_id: str, zip_path: str):
    """Background task to extract zip bundles using multi-threaded parallel workers."""
    logger.info(f"[Session {session_id}] Starting parallel zip extraction from: {zip_path}")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            members = [m.filename for m in zip_ref.infolist() if not m.is_dir()]
            total_files = len(members)
            upload_progress[session_id] = {"done": 0, "total": total_files, "status": "extracting"}
            logger.info(f"[Session {session_id}] Total files to extract: {total_files} using {MAX_WORKERS} workers.")

        # Parallel extraction using ThreadPoolExecutor
        completed = 0
        update_interval = max(1, total_files // 20)  # Update progress state every 5%

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [
                executor.submit(_extract_single_member, zip_path, member, OUTPUT_DIR)
                for member in members
            ]

            for future in as_completed(futures):
                future.result()  # Raise exception if worker failed
                completed += 1
                if completed % update_interval == 0 or completed == total_files:
                    upload_progress[session_id]["done"] = completed

        upload_progress[session_id]["status"] = "completed"
        logger.info(f"[Session {session_id}] Parallel zip extraction completed successfully.")

    except zipfile.BadZipFile as e:
        upload_progress[session_id]["status"] = f"failed: Bad Zip File - {str(e)}"
        logger.error(f"[Session {session_id}] Corrupt or invalid zip archive uploaded.", exc_info=True)

    except PermissionError as e:
        upload_progress[session_id]["status"] = f"failed: Write Permission Error - {str(e)}"
        logger.error(f"[Session {session_id}] Permission denied writing to {OUTPUT_DIR}.", exc_info=True)

    except Exception as e:
        upload_progress[session_id]["status"] = f"failed: {str(e)}"
        logger.error(f"[Session {session_id}] Unexpected error during extraction: {str(e)}", exc_info=True)

    finally:
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
                logger.info(f"[Session {session_id}] Temporary zip artifact cleaned up: {zip_path}")
            except Exception as cleanup_err:
                logger.warning(f"[Session {session_id}] Failed to remove temp file {zip_path}: {cleanup_err}")


@app.post("/upload")
@app.post("/upload/")
@app.post("/upload-zip")
@app.post("/upload-zip/")
async def upload_zip(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        session_id: str = Form(...)
):
    """Handles zipped DICOM uploads with 1MB chunked streaming for fast buffering."""
    logger.info(f"[Session {session_id}] Incoming zip upload request. Filename: '{file.filename}'")
    try:
        temp_dir = "/tmp" if os.path.exists("/tmp") else OUTPUT_DIR
        temp_zip_path = os.path.join(temp_dir, f"{session_id}.zip")

        # 1MB chunked buffer write for faster disk ingestion
        CHUNK_SIZE = 1024 * 1024  # 1MB
        with open(temp_zip_path, "wb") as buffer:
            while chunk := await file.read(CHUNK_SIZE):
                buffer.write(chunk)

        file_size_mb = os.path.getsize(temp_zip_path) / (1024 * 1024)
        logger.info(
            f"[Session {session_id}] Zip payload written to disk ({file_size_mb:.2f} MB). Handing off to background extractor.")

        upload_progress[session_id] = {"done": 0, "total": 0, "status": "queued"}
        background_tasks.add_task(process_zip_extraction, session_id, temp_zip_path)

        return {"message": "Upload received", "session_id": session_id}

    except Exception as e:
        logger.error(f"[Session {session_id}] Failed to receive or buffer uploaded zip file.", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to buffer zip payload: {str(e)}")


@app.get("/upload-progress/{session_id}")
@app.get("/upload-progress/{session_id}/")
def get_progress(session_id: str):
    return upload_progress.get(session_id, {"done": 0, "total": 0, "status": "unknown"})


# =========================================================
# 3. FAST INVENTORY MANAGEMENT ENDPOINTS
# =========================================================
def is_dicom_file(file_path: str) -> bool:
    """Fast magic-byte check for DICOM files before invoking pydicom parser."""
    try:
        with open(file_path, "rb") as f:
            f.seek(128)
            return f.read(4) == b"DICM"
    except Exception:
        return False


def scan_study_assets(study_path: str) -> dict:
    """Recursively scans directory and categorizes files with fast header checks."""
    counts = {"images": 0, "videos": 0, "reports": 0, "total": 0}

    for root, _, files in os.walk(study_path):
        for file in files:
            file_path = os.path.join(root, file)
            ext = file.lower().split('.')[-1]

            if ext in ["pdf", "txt", "doc", "docx", "json"]:
                counts["reports"] += 1
                counts["total"] += 1
                continue
            elif ext in ["mp4", "avi", "mov"]:
                counts["videos"] += 1
                counts["total"] += 1
                continue
            elif ext in ["png", "jpg", "jpeg"]:
                counts["images"] += 1
                counts["total"] += 1
                continue

            # Quick check: Only run pydicom if file has 'DICM' header or .dcm extension
            if ext == "dcm" or is_dicom_file(file_path):
                try:
                    ds = pydicom.dcmread(file_path, stop_before_pixels=True, force=True)
                    sop_class = str(getattr(ds, "SOPClassUID", ""))
                    num_frames = int(getattr(ds, "NumberOfFrames", 1))

                    if "1.2.840.10008.5.1.4.1.1.88" in sop_class or "1.2.840.10008.5.1.4.1.1.104" in sop_class:
                        counts["reports"] += 1
                    elif num_frames > 1:
                        counts["videos"] += 1
                    else:
                        counts["images"] += 1

                    counts["total"] += 1
                except Exception as e:
                    logger.debug(f"Skipped non-DICOM / unparseable file '{file_path}': {e}")
            else:
                counts["total"] += 1

    return counts


def _scan_single_study(patient_folder: str, study_folder: str, patient_path: str) -> dict:
    study_path = os.path.join(patient_path, study_folder)
    if not os.path.isdir(study_path):
        return None

    asset_counts = scan_study_assets(study_path)
    if asset_counts["total"] > 0:
        return {
            "patient_id": patient_folder,
            "study_uid": study_folder,
            "total_files": asset_counts["total"],
            "images_count": asset_counts["images"],
            "videos_count": asset_counts["videos"],
            "reports_count": asset_counts["reports"]
        }
    return None


@app.get("/studies")
@app.get("/studies/")
def get_studies():
    """Scans /raw_data in parallel and returns all Patient / Study records."""
    studies_list = []
    if not os.path.exists(OUTPUT_DIR):
        logger.warning(f"OUTPUT_DIR directory does not exist: {OUTPUT_DIR}")
        return studies_list

    try:
        tasks = []
        for patient_folder in os.listdir(OUTPUT_DIR):
            patient_path = os.path.join(OUTPUT_DIR, patient_folder)
            if not os.path.isdir(patient_path):
                continue

            for study_folder in os.listdir(patient_path):
                tasks.append((patient_folder, study_folder, patient_path))

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [
                executor.submit(_scan_single_study, p_f, s_f, p_p)
                for p_f, s_f, p_p in tasks
            ]
            for future in as_completed(futures):
                res = future.result()
                if res:
                    studies_list.append(res)

    except Exception as e:
        logger.error(f"Error scanning inventory directory {OUTPUT_DIR}", exc_info=True)

    return studies_list


# =========================================================
# 4. STUDY DELETION LOGIC & ENDPOINTS
# =========================================================
def has_qc_records(patient_id: str, study_uid: str) -> bool:
    """Checks QC file to verify if a study has active QC entries."""
    if not os.path.exists(QC_FILE):
        return False
    try:
        with open(QC_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        target_pid = patient_id.rstrip("__")
        target_date = study_uid[:8]

        for record in data.values():
            details = record.get("details", {})
            pid = str(details.get("case_no", "")).rstrip("__")
            date_str = str(details.get("date", "")).replace("-", "")

            if pid == target_pid and date_str == target_date:
                if any(k in record for k in ["Viability", "Growth", "Anomaly"]):
                    return True
    except Exception as e:
        logger.error(f"Error reading QC JSON file during delete validation: {e}")
    return False


def safe_delete_study_folder(patient_id: str, study_uid: str):
    """Validates parameters, checks QC protection, and removes study folder."""
    root_path = Path(OUTPUT_DIR).resolve()
    target_dir = (root_path / patient_id / study_uid).resolve()

    if not str(target_dir).startswith(str(root_path)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid parameter input: Directory traversal attempt detected."
        )

    if has_qc_records(patient_id, study_uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Deletion blocked: Study '{study_uid}' for Patient '{patient_id}' has recorded QC entries."
        )

    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Study directory not found for Patient '{patient_id}' and Study UID '{study_uid}'."
        )

    try:
        shutil.rmtree(target_dir)
        logger.info(f"Successfully deleted study directory: {target_dir}")
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Permission denied: Lacks system permission to delete study files."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove study directory: {str(e)}"
        )

    patient_dir = target_dir.parent
    if patient_dir.exists() and patient_dir.is_dir() and not any(patient_dir.iterdir()):
        try:
            patient_dir.rmdir()
            logger.info(f"Removed empty parent patient folder: {patient_dir}")
        except Exception as e:
            logger.warning(f"Could not remove empty patient folder {patient_dir}: {e}")

    return {
        "status": "success",
        "message": f"Successfully deleted study '{study_uid}' for Patient '{patient_id}'.",
        "patient_id": patient_id,
        "study_uid": study_uid
    }


@app.delete("/studies/{patient_id}/{study_uid}", status_code=status.HTTP_200_OK)
@app.delete("/studies/{patient_id}/{study_uid}/", status_code=status.HTTP_200_OK)
def delete_study_path(
        patient_id: str = PathParam(..., description="Patient ID folder name"),
        study_uid: str = PathParam(..., description="Study UID folder name")
):
    """Deletes a study directory using URL path parameters."""
    return safe_delete_study_folder(patient_id, study_uid)


@app.delete("/studies", status_code=status.HTTP_200_OK)
@app.delete("/studies/", status_code=status.HTTP_200_OK)
def delete_study_query(
        patient_id: str = Query(..., description="Patient ID folder name"),
        study_uid: str = Query(..., description="Study UID folder name")
):
    """Deletes a study directory using query string parameters."""
    return safe_delete_study_folder(patient_id, study_uid)


# =========================================================
# 405 & ERROR DEBUGGING MIDDLEWARE
# =========================================================
@app.middleware("http")
async def log_405_method_not_allowed(request: Request, call_next):
    response = await call_next(request)

    if response.status_code == 405:
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        referer = request.headers.get("referer", "none")

        logger.warning(
            f"⚠️ [405 METHOD NOT ALLOWED] "
            f"Method: {request.method} | "
            f"URL: {request.url} | "
            f"Client IP: {client_ip} | "
            f"Referer: {referer} | "
            f"User-Agent: {user_agent}"
        )

    return response
