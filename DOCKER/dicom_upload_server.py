# dicom_upload_server.py
import os
import shutil
import zipfile
from typing import Dict

import pydicom
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="IGHD DICOM Upload & Inventory Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/raw_data")
QC_FILE = os.getenv("QC_FILE", "/qc_data/study_qc.json")

# In-memory tracking for background zip extraction progress
upload_progress: Dict[str, dict] = {}

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.dirname(QC_FILE), exist_ok=True)


@app.get("/health")
@app.get("/health/")
def health_check():
    return {"status": "online", "dicom_root": OUTPUT_DIR}


def process_zip_extraction(session_id: str, zip_path: str):
    """Background task to extract zip bundles into /raw_data."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            members = zip_ref.infolist()
            total_files = len([m for m in members if not m.is_dir()])
            upload_progress[session_id] = {"done": 0, "total": total_files, "status": "extracting"}

            for idx, member in enumerate(members, start=1):
                if member.is_dir():
                    continue
                zip_ref.extract(member, OUTPUT_DIR)
                upload_progress[session_id]["done"] = idx

        upload_progress[session_id]["status"] = "completed"
    except Exception as e:
        upload_progress[session_id]["status"] = f"failed: {str(e)}"
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)


@app.post("/upload-zip")
@app.post("/upload-zip/")
async def upload_zip(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        session_id: str = Form(...)
):
    temp_zip_path = os.path.join("/tmp" if os.path.exists("/tmp") else OUTPUT_DIR, f"{session_id}.zip")
    with open(temp_zip_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    upload_progress[session_id] = {"done": 0, "total": 0, "status": "queued"}
    background_tasks.add_task(process_zip_extraction, session_id, temp_zip_path)

    return {"message": "Upload received", "session_id": session_id}


@app.get("/upload-progress/{session_id}")
@app.get("/upload-progress/{session_id}/")
def get_progress(session_id: str):
    return upload_progress.get(session_id, {"done": 0, "total": 0, "status": "unknown"})


def scan_study_assets(study_path: str) -> dict:
    """Recursively scans directory and categorizes files into images, videos, and reports."""
    counts = {"images": 0, "videos": 0, "reports": 0, "total": 0}

    for root, _, files in os.walk(study_path):
        for file in files:
            file_path = os.path.join(root, file)
            ext = file.lower().split('.')[-1]

            # 1. Non-DICOM File Categorization
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

            # 2. DICOM Header Inspection
            try:
                ds = pydicom.dcmread(file_path, stop_before_pixels=True)
                sop_class = str(getattr(ds, "SOPClassUID", ""))
                num_frames = int(getattr(ds, "NumberOfFrames", 1))

                # Structured Reports or Encapsulated PDFs
                if "1.2.840.10008.5.1.4.1.1.88" in sop_class or "1.2.840.10008.5.1.4.1.1.104" in sop_class:
                    counts["reports"] += 1
                # Multi-frame DICOM Cine Loops (Videos)
                elif num_frames > 1:
                    counts["videos"] += 1
                # Single-frame DICOM Images
                else:
                    counts["images"] += 1

                counts["total"] += 1
            except Exception:
                continue

    return counts


@app.get("/studies")
@app.get("/studies/")
def get_studies():
    """Scans /raw_data and returns all Patient / Study records with asset counts."""
    studies_list = []
    if not os.path.exists(OUTPUT_DIR):
        return studies_list

    for patient_folder in os.listdir(OUTPUT_DIR):
        patient_path = os.path.join(OUTPUT_DIR, patient_folder)
        if not os.path.isdir(patient_path):
            continue

        for study_folder in os.listdir(patient_path):
            study_path = os.path.join(patient_path, study_folder)
            if not os.path.isdir(study_path):
                continue

            asset_counts = scan_study_assets(study_path)
            if asset_counts["total"] > 0:
                studies_list.append({
                    "patient_id": patient_folder,
                    "study_uid": study_folder,
                    "total_files": asset_counts["total"],
                    "images_count": asset_counts["images"],
                    "videos_count": asset_counts["videos"],
                    "reports_count": asset_counts["reports"]
                })

    return studies_list
