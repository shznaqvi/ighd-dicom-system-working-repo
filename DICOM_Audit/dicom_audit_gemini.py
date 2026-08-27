# https://gemini.google.com/app/03828531f4db2e26
# dicom_audit_gemini.py
from pathlib import Path

import pandas as pd
import pydicom
from pydicom.errors import InvalidDicomError
from tqdm import tqdm

INPUT_FOLDER = Path(r"D:\dump")
OUTPUT_FOLDER = Path(r"..\data\audit")


def audit_dicom_directory(root_dir: str, export_csv: str = None) -> pd.DataFrame:
    """
    Recursively audits a folder for DICOM files, extracts metadata,
    and returns a summarized Pandas DataFrame of all valid and invalid files.
    """
    root_path = Path(root_dir)
    records = []

    # Gather all file paths
    file_paths = [p for p in root_path.rglob('*') if p.is_file()]
    print(f"Found {len(file_paths)} total files in '{root_dir}'. Auditing...")

    for file_path in tqdm(file_paths, desc="Auditing DICOMs", unit="file"):
        file_record = {
            "file_path": str(file_path),
            "file_name": file_path.name,
            "file_size_kb": round(file_path.stat().st_size / 1024, 2),
            "is_valid_dicom": False,
            "error_msg": None,
            "patient_id": None,
            "study_uid": None,
            "series_uid": None,
            "sop_instance_uid": None,
            "modality": None,
            "study_date": None,
            "series_description": None,
            "rows": None,
            "columns": None,
            "num_frames": 1,
            "transfer_syntax": None,
            "manufacturer": None
        }

        try:
            # stop_before_pixels=True reads ONLY header metadata (10-100x faster)
            dcm = pydicom.dcmread(str(file_path), stop_before_pixels=True, force=False)

            file_record["is_valid_dicom"] = True
            file_record["patient_id"] = getattr(dcm, "PatientID", "MISSING")
            file_record["study_uid"] = getattr(dcm, "StudyInstanceUID", "MISSING")
            file_record["series_uid"] = getattr(dcm, "SeriesInstanceUID", "MISSING")
            file_record["sop_instance_uid"] = getattr(dcm, "SOPInstanceUID", "MISSING")
            file_record["modality"] = getattr(dcm, "Modality", "UNKNOWN")
            file_record["study_date"] = getattr(dcm, "StudyDate", None)
            file_record["series_description"] = getattr(dcm, "SeriesDescription", None)
            file_record["rows"] = getattr(dcm, "Rows", None)
            file_record["columns"] = getattr(dcm, "Columns", None)
            file_record["num_frames"] = getattr(dcm, "NumberOfFrames", 1)
            file_record["manufacturer"] = getattr(dcm, "Manufacturer", None)

            # Extract transfer syntax if available in meta header
            if hasattr(dcm, "file_meta") and "TransferSyntaxUID" in dcm.file_meta:
                file_record["transfer_syntax"] = dcm.file_meta.TransferSyntaxUID.name

        except InvalidDicomError:
            file_record["error_msg"] = "Invalid DICOM Header / Non-DICOM file"
        except Exception as e:
            file_record["error_msg"] = f"Corrupted file or read error: {str(e)}"

        records.append(file_record)

    df = pd.DataFrame(records)

    if export_csv:
        df.to_csv(export_csv, index=False)
        print(f"\nItemized audit report saved to: {export_csv}")

    generate_summary_report(df)
    return df


def generate_summary_report(df: pd.DataFrame):
    """Prints a high-level data quality summary to stdout."""
    total_files = len(df)
    valid_dicoms = df[df["is_valid_dicom"]]
    invalid_dicoms = df[~df["is_valid_dicom"]]

    print("\n" + "=" * 50)
    print("               DICOM AUDIT SUMMARY              ")
    print("=" * 50)
    print(f"Total Files Scanned      : {total_files}")
    print(f"Valid DICOM Files        : {len(valid_dicoms)} ({len(valid_dicoms) / total_files * 100:.1f}%)")
    print(f"Invalid / Failed Files   : {len(invalid_dicoms)}")

    if not valid_dicoms.empty:
        print("-" * 50)
        print(f"Unique Patients          : {valid_dicoms['patient_id'].nunique()}")
        print(f"Unique Studies           : {valid_dicoms['study_uid'].nunique()}")
        print(f"Unique Series            : {valid_dicoms['series_uid'].nunique()}")
        print("\nBreakdown by Modality:")
        print(valid_dicoms['modality'].value_counts().to_string())

        # Anomaly Detection Checks
        missing_uids = valid_dicoms[
            (valid_dicoms["study_uid"] == "MISSING") |
            (valid_dicoms["series_uid"] == "MISSING") |
            (valid_dicoms["sop_instance_uid"] == "MISSING")
            ]
        duplicate_slices = valid_dicoms[valid_dicoms.duplicated(subset=["sop_instance_uid"], keep=False)]

        print("-" * 50)
        print("DATA INTEGRITY CHECKS:")
        print(f" - Files with Missing Core UIDs : {len(missing_uids)}")
        print(f" - Duplicate SOPInstanceUIDs    : {len(duplicate_slices)}")

    print("=" * 50 + "\n")


# Execution Example
if __name__ == "__main__":
    DATASET_DIRECTORY = INPUT_FOLDER  # Replace with target path
    audit_df = audit_dicom_directory(DATASET_DIRECTORY, export_csv=OUTPUT_FOLDER / "dicom_audit_report.csv")
