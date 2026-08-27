import shutil
import sqlite3
from pathlib import Path

import pydicom
from pydicom.errors import InvalidDicomError
from tqdm import tqdm

# --- Configuration Paths ---
INPUT_FOLDER = Path(r"D:\dump")
OUTPUT_FOLDER = Path(r"..\data\pipeline")

# Derived Pipeline Destinations
CLEAN_DATASET_DIR = OUTPUT_FOLDER / "clean_dataset"
QUARANTINE_DIR = OUTPUT_FOLDER / "quarantine"
DATABASE_PATH = OUTPUT_FOLDER / "dicom_registry.db"

# Ensure output pipeline directories exist
OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
CLEAN_DATASET_DIR.mkdir(parents=True, exist_ok=True)
QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

# Target LOINC / Standard DICOM Code Meanings for SR Biometry
TARGET_CONCEPTS = {
    "11820-8": "bpd_mm", "Biparietal Diameter": "bpd_mm",
    "11979-2": "hc_mm", "Head Circumference": "hc_mm",
    "11971-9": "ac_mm", "Abdominal Circumference": "ac_mm",
    "11963-6": "fl_mm", "Femur Length": "fl_mm",
    "11727-5": "efw_g", "Estimated Fetal Weight": "efw_g",
    "11885-1": "ga_weeks", "Gestational Age": "ga_weeks"
}


def init_db(db_path: str):
    """Initializes SQLite schema for patients, studies, instances, and biometry labels."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS patients
                   (
                       patient_id
                       TEXT
                       PRIMARY
                       KEY
                   );
                   """)

    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS studies
                   (
                       study_uid
                       TEXT
                       PRIMARY
                       KEY,
                       patient_id
                       TEXT,
                       study_date
                       TEXT,
                       manufacturer
                       TEXT,
                       FOREIGN
                       KEY
                   (
                       patient_id
                   ) REFERENCES patients
                   (
                       patient_id
                   )
                       );
                   """)

    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS dicom_instances
                   (
                       sop_instance_uid
                       TEXT
                       PRIMARY
                       KEY,
                       study_uid
                       TEXT,
                       series_uid
                       TEXT,
                       modality
                       TEXT,
                       file_path
                       TEXT,
                       num_frames
                       INTEGER,
                       rows
                       INTEGER,
                       columns
                       INTEGER,
                       FOREIGN
                       KEY
                   (
                       study_uid
                   ) REFERENCES studies
                   (
                       study_uid
                   )
                       );
                   """)

    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS fetal_biometry
                   (
                       study_uid
                       TEXT
                       PRIMARY
                       KEY,
                       patient_id
                       TEXT,
                       bpd_mm
                       REAL,
                       hc_mm
                       REAL,
                       ac_mm
                       REAL,
                       fl_mm
                       REAL,
                       ga_weeks
                       REAL,
                       efw_g
                       REAL,
                       FOREIGN
                       KEY
                   (
                       study_uid
                   ) REFERENCES studies
                   (
                       study_uid
                   )
                       );
                   """)

    conn.commit()
    conn.close()


def parse_sr_content(item, record_dict):
    """Recursively walks DICOM SR ContentSequence to extract numeric measurements."""
    if hasattr(item, "ConceptNameCodeSequence") and len(item.ConceptNameCodeSequence) > 0:
        code_item = item.ConceptNameCodeSequence[0]
        code_value = getattr(code_item, "CodeValue", "")
        meaning = getattr(code_item, "CodeMeaning", "")

        matched_key = TARGET_CONCEPTS.get(code_value) or TARGET_CONCEPTS.get(meaning)

        if matched_key and getattr(item, "ValueType", "") == "NUM":
            if hasattr(item, "MeasuredValueSequence") and len(item.MeasuredValueSequence) > 0:
                val = getattr(item.MeasuredValueSequence[0], "NumericValue", None)
                if val is not None:
                    try:
                        record_dict[matched_key] = float(val)
                    except ValueError:
                        pass

    if hasattr(item, "ContentSequence"):
        for child in item.ContentSequence:
            parse_sr_content(child, record_dict)


def run_ingestion_pipeline(raw_dir: str, clean_dir: str, quarantine_dir: str, db_path: str):
    """
    Main ETL Function: Audits, quarantines, canonicalizes storage, and extracts SR labels.
    """
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    raw_path = Path(raw_dir)
    clean_path = Path(clean_dir)
    quarantine_invalid = Path(quarantine_dir) / "invalid_or_corrupt"
    quarantine_duplicates = Path(quarantine_dir) / "duplicate_sop_uids"

    quarantine_invalid.mkdir(parents=True, exist_ok=True)
    quarantine_duplicates.mkdir(parents=True, exist_ok=True)

    # Load existing SOPInstanceUIDs from database to prevent duplicate ingestion across batches
    cursor.execute("SELECT sop_instance_uid FROM dicom_instances;")
    existing_uids = set(row[0] for row in cursor.fetchall())

    files = [p for p in raw_path.rglob('*') if p.is_file() and not str(p).startswith(str(quarantine_dir))]
    print(f"\nProcessing {len(files)} files from raw directory: {raw_dir}")

    stats = {"processed": 0, "quarantined_invalid": 0, "quarantined_dup": 0, "sr_parsed": 0}

    for file_path in tqdm(files, desc="Ingesting DICOMs"):
        # 1. Reject 0-byte or unreadable files
        if file_path.stat().st_size == 0:
            shutil.move(str(file_path), str(quarantine_invalid / file_path.name))
            stats["quarantined_invalid"] += 1
            continue

        try:
            dcm = pydicom.dcmread(str(file_path), stop_before_pixels=True)
            sop_uid = getattr(dcm, "SOPInstanceUID", None)
            patient_id = getattr(dcm, "PatientID", "UNKNOWN_PATIENT")
            study_uid = getattr(dcm, "StudyInstanceUID", "UNKNOWN_STUDY")
            series_uid = getattr(dcm, "SeriesInstanceUID", "UNKNOWN_SERIES")
            modality = getattr(dcm, "Modality", "UNKNOWN")

            if not sop_uid:
                shutil.move(str(file_path), str(quarantine_invalid / file_path.name))
                stats["quarantined_invalid"] += 1
                continue

            # 2. De-duplication check against SQLite database
            if sop_uid in existing_uids:
                dest = quarantine_duplicates / patient_id
                dest.mkdir(parents=True, exist_ok=True)
                target_file = dest / file_path.name
                if target_file.exists():
                    target_file = dest / f"{file_path.stem}_dup{file_path.suffix}"
                shutil.move(str(file_path), str(target_file))
                stats["quarantined_dup"] += 1
                continue

            # 3. Define Canonical Target Path
            canonical_folder = clean_path / patient_id / study_uid / series_uid
            canonical_folder.mkdir(parents=True, exist_ok=True)
            canonical_path = canonical_folder / f"{sop_uid}.dcm"

            # Move or Copy file to clean directory
            shutil.move(str(file_path), str(canonical_path))

            # 4. Record metadata in DB
            cursor.execute("INSERT OR IGNORE INTO patients (patient_id) VALUES (?);", (patient_id,))
            cursor.execute(
                "INSERT OR IGNORE INTO studies (study_uid, patient_id, study_date, manufacturer) VALUES (?, ?, ?, ?);",
                (study_uid, patient_id, getattr(dcm, "StudyDate", ""), getattr(dcm, "Manufacturer", ""))
            )

            num_frames = int(getattr(dcm, "NumberOfFrames", 1))
            rows = getattr(dcm, "Rows", None)
            cols = getattr(dcm, "Columns", None)

            cursor.execute(
                "INSERT INTO dicom_instances (sop_instance_uid, study_uid, series_uid, modality, file_path, num_frames, rows, columns) VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
                (sop_uid, study_uid, series_uid, modality, str(canonical_path), num_frames, rows, cols)
            )

            # 5. Extract SR Measurements if modality is SR
            if modality == "SR":
                full_dcm = pydicom.dcmread(str(canonical_path))
                biometry = {"study_uid": study_uid, "patient_id": patient_id}
                if hasattr(full_dcm, "ContentSequence"):
                    for top_item in full_dcm.ContentSequence:
                        parse_sr_content(top_item, biometry)

                cursor.execute("""
                INSERT OR REPLACE INTO fetal_biometry (study_uid, patient_id, bpd_mm, hc_mm, ac_mm, fl_mm, ga_weeks, efw_g)
                VALUES (:study_uid, :patient_id, :bpd_mm, :hc_mm, :ac_mm, :fl_mm, :ga_weeks, :efw_g);
                """, {
                    "study_uid": study_uid,
                    "patient_id": patient_id,
                    "bpd_mm": biometry.get("bpd_mm"),
                    "hc_mm": biometry.get("hc_mm"),
                    "ac_mm": biometry.get("ac_mm"),
                    "fl_mm": biometry.get("fl_mm"),
                    "ga_weeks": biometry.get("ga_weeks"),
                    "efw_g": biometry.get("efw_g")
                })
                stats["sr_parsed"] += 1

            existing_uids.add(sop_uid)
            stats["processed"] += 1

        except (InvalidDicomError, Exception):
            shutil.move(str(file_path), str(quarantine_invalid / file_path.name))
            stats["quarantined_invalid"] += 1

    conn.commit()
    conn.close()

    print("\n" + "=" * 50)
    print("           INGESTION & INDEXING COMPLETE         ")
    print("=" * 50)
    print(f"Successfully Cleaned & Indexed : {stats['processed']} files")
    print(f"Parsed Structured Reports      : {stats['sr_parsed']} files")
    print(f"Quarantined (Invalid / 0-byte) : {stats['quarantined_invalid']} files")
    print(f"Quarantined (Duplicates)       : {stats['quarantined_dup']} files")
    print(f"Database Updated               : {Path(db_path).resolve()}")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    INPUT_FOLDER = Path(r"D:\dump")
    OUTPUT_FOLDER = Path(r"..\data\pipeline")

    CLEAN_DATASET_DIR = OUTPUT_FOLDER / "clean_dataset"
    QUARANTINE_DIR = OUTPUT_FOLDER / "quarantine"
    DATABASE_PATH = OUTPUT_FOLDER / "dicom_registry.db"

    # Run complete ETL & indexing pipeline
    run_ingestion_pipeline(
        raw_dir=str(INPUT_FOLDER),
        clean_dir=str(CLEAN_DATASET_DIR),
        quarantine_dir=str(QUARANTINE_DIR),
        db_path=str(DATABASE_PATH)
    )
