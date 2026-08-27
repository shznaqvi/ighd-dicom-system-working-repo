import csv
import os
from collections import defaultdict
from multiprocessing import Pool, cpu_count

import pydicom

# -----------------------------
# Configuration
# -----------------------------
dicom_dir = r"H:\voluson swift\GE-voluson"
output_csv = r"H:\voluson swift\GE-voluson\Dicom\Dicom_summary.csv"


# -----------------------------
# Function to process one DICOM file
# -----------------------------
def process_file(file_path):
    try:
        ds = pydicom.dcmread(file_path, stop_before_pixels=True)  # metadata only
        patient_id = getattr(ds, "PatientID", "Unknown")
        modality = getattr(ds, "Modality", "Unknown")
        num_frames = getattr(ds, "NumberOfFrames", 1)
        report_text = ""

        # Handle SR files
        if modality == "SR" and hasattr(ds, "ContentSequence"):
            for item in ds.ContentSequence:
                if hasattr(item, "TextValue"):
                    report_text += item.TextValue + " "
            report_text = report_text.strip()

        return {
            "file_path": file_path,
            "patient_id": patient_id,
            "modality": modality,
            "num_frames": num_frames,
            "report_text": report_text
        }
    except Exception as e:
        return {
            "file_path": file_path,
            "patient_id": "ERROR",
            "modality": "ERROR",
            "num_frames": 0,
            "report_text": ""
        }


# -----------------------------
# Main evaluation
# -----------------------------
if __name__ == "__main__":
    # Collect all files
    all_files = [os.path.join(root, f)
                 for root, _, files in os.walk(dicom_dir)
                 for f in files]

    print(f"Found {len(all_files)} files. Processing with {cpu_count()} cores...")

    # Multiprocessing pool
    with Pool(cpu_count()) as pool:
        results = pool.map(process_file, all_files)

    # Summarize results
    summary = {
        "total_files": len(results),
        "patients": set(),
        "modalities": set(),
        "multi_frame": 0,
        "sr_files": 0,
        "errors": 0
    }

    patient_data = defaultdict(list)

    for r in results:
        patient_id = r["patient_id"]
        modality = r["modality"]

        if patient_id == "ERROR":
            summary["errors"] += 1
            continue

        summary["patients"].add(patient_id)
        summary["modalities"].add(modality)

        if modality == "SR":
            summary["sr_files"] += 1
        else:
            if r["num_frames"] > 1:
                summary["multi_frame"] += 1

        # Add to patient-wise data for CSV
        patient_data[patient_id].append(r)

    # -----------------------------
    # Write CSV summary
    # -----------------------------
    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["PatientID", "Modality", "FilePath", "NumFrames", "ReportText"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for patient_id, files in patient_data.items():
            for f in files:
                writer.writerow({
                    "PatientID": f["patient_id"],
                    "Modality": f["modality"],
                    "FilePath": f["file_path"],
                    "NumFrames": f["num_frames"],
                    "ReportText": f["report_text"]
                })

    # -----------------------------
    # Print final summary
    # -----------------------------
    print("----- DICOM Folder Summary -----")
    print(f"Total DICOM files: {summary['total_files']}")
    print(f"Unique patients: {len(summary['patients'])}")
    print(f"Modalities found: {summary['modalities']}")
    print(f"Multi-frame images: {summary['multi_frame']}")
    print(f"SR files: {summary['sr_files']}")
    print(f"Files with errors: {summary['errors']}")
    print(f"CSV summary saved to: {output_csv}")
