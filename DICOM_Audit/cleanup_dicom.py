import shutil
from pathlib import Path

import pandas as pd


def cleanup_dicom_dataset(csv_report_path: str, quarantine_dir: str):
    df = pd.read_csv(csv_report_path)
    quarantine_path = Path(quarantine_dir)
    quarantine_invalid = quarantine_path / "invalid_0kb_files"
    quarantine_duplicates = quarantine_path / "duplicate_sop_uids"

    quarantine_invalid.mkdir(parents=True, exist_ok=True)
    quarantine_duplicates.mkdir(parents=True, exist_ok=True)

    print(f"Starting Dataset Cleanup using report: {csv_report_path}\n")

    # 1. Quarantine Invalid / 0-Byte Files
    invalid_df = df[~df["is_valid_dicom"]]
    print(f"--> Moving {len(invalid_df)} invalid / 0-byte files...")

    for _, row in invalid_df.iterrows():
        src_file = Path(row["file_path"])
        if src_file.exists():
            dest_file = quarantine_invalid / src_file.name
            if dest_file.exists():
                dest_file = quarantine_invalid / f"{src_file.stem}_{src_file.parent.name}{src_file.suffix}"
            shutil.move(str(src_file), str(dest_file))

    # 2. Quarantine Duplicate SOPInstanceUIDs (Keeping 1 canonical copy)
    valid_df = df[df["is_valid_dicom"]].copy()
    valid_df["path_depth"] = valid_df["file_path"].apply(lambda p: len(Path(p).parts))
    valid_df = valid_df.sort_values(by=["sop_instance_uid", "path_depth"])

    canonical_mask = ~valid_df.duplicated(subset=["sop_instance_uid"], keep="first")
    duplicates_df = valid_df[~canonical_mask]

    print(f"--> Moving {len(duplicates_df)} duplicate SOPInstanceUID files...")

    for _, row in duplicates_df.iterrows():
        src_file = Path(row["file_path"])
        if src_file.exists():
            patient_folder = quarantine_duplicates / str(row["patient_id"])
            patient_folder.mkdir(parents=True, exist_ok=True)

            dest_file = patient_folder / src_file.name
            if dest_file.exists():
                dest_file = patient_folder / f"{src_file.stem}_dup{src_file.suffix}"

            shutil.move(str(src_file), str(dest_file))

    print("\n" + "=" * 50)
    print("CLEANUP COMPLETE")
    print(f"Cleaned dataset remains in: D:\\dump")
    print(f"Quarantined files moved to: {quarantine_path.resolve()}")
    print("=" * 50)


if __name__ == "__main__":
    CSV_REPORT = r"..\data\audit\dicom_audit_report.csv"
    # Quarantine placed OUTSIDE D:\dump so recursive scans ignore it
    QUARANTINE_DIR = r"D:\quarantine"

    cleanup_dicom_dataset(CSV_REPORT, QUARANTINE_DIR)
