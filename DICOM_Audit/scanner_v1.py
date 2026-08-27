"""
scanner.py

GE Voluson Swift DICOM Audit Toolkit
Module 1 - Dataset Scanner

Scans a directory recursively, identifies DICOM files,
and generates an inventory.

Author: Hassan + ChatGPT
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import pydicom

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

INPUT_FOLDER = Path(r"D:\dump")

OUTPUT_FOLDER = Path(r"..\data\audit")

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

INVENTORY_CSV = OUTPUT_FOLDER / "dicom_inventory.csv"
SUMMARY_JSON = OUTPUT_FOLDER / "dataset_summary.json"
LOG_FILE = OUTPUT_FOLDER / "scanner.log"

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger("").addHandler(console)


# ---------------------------------------------------------------------
# DICOM Scanner
# ---------------------------------------------------------------------

class DICOMScanner:

    def __init__(self, root_folder: Path):

        self.root_folder = root_folder

        self.inventory = []

        self.total_files = 0
        self.dicom_files = 0
        self.invalid_files = 0

    def scan(self):

        logging.info("Scanning folder: %s", self.root_folder)

        for file in self.root_folder.rglob("*"):

            if not file.is_file():
                continue

            self.total_files += 1

            try:

                ds = pydicom.dcmread(
                    file,
                    stop_before_pixels=True,
                    force=True
                )

                self.dicom_files += 1

                self.inventory.append({

                    "filepath": str(file),

                    "filename": file.name,

                    "size_mb": round(file.stat().st_size / (1024 * 1024), 3),

                    "PatientID":
                        getattr(ds, "PatientID", None),

                    "StudyInstanceUID":
                        getattr(ds, "StudyInstanceUID", None),

                    "SeriesInstanceUID":
                        getattr(ds, "SeriesInstanceUID", None),

                    "SOPInstanceUID":
                        getattr(ds, "SOPInstanceUID", None),

                    "StudyDate":
                        getattr(ds, "StudyDate", None),

                    "StudyTime":
                        getattr(ds, "StudyTime", None),

                    "Modality":
                        getattr(ds, "Modality", None),

                    "Manufacturer":
                        getattr(ds, "Manufacturer", None),

                    "Model":
                        getattr(ds, "ManufacturerModelName", None)

                })

            except Exception:

                self.invalid_files += 1

        logging.info("Finished scanning.")

    def save_inventory(self):

        df = pd.DataFrame(self.inventory)

        df.to_csv(INVENTORY_CSV, index=False)

        logging.info("Inventory saved -> %s", INVENTORY_CSV)

        return df

    def save_summary(self, df):

        summary = {

            "scan_time": datetime.now().isoformat(),

            "root_folder": str(self.root_folder),

            "total_files": self.total_files,

            "dicom_files": self.dicom_files,

            "invalid_files": self.invalid_files,

            "patients":
                df["PatientID"].nunique(),

            "studies":
                df["StudyInstanceUID"].nunique(),

            "series":
                df["SeriesInstanceUID"].nunique(),

            "instances":
                df["SOPInstanceUID"].nunique(),

            "manufacturers":
                sorted(df["Manufacturer"].dropna().unique().tolist()),

            "models":
                sorted(df["Model"].dropna().unique().tolist())

        }

        with open(SUMMARY_JSON, "w") as f:
            json.dump(summary, f, indent=4)

        logging.info("Summary saved -> %s", SUMMARY_JSON)

        return summary


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    logging.info("=" * 70)
    logging.info("GE Voluson Swift DICOM Dataset Scanner")
    logging.info("=" * 70)

    scanner = DICOMScanner(INPUT_FOLDER)

    scanner.scan()

    df = scanner.save_inventory()

    summary = scanner.save_summary(df)

    print("\nDataset Summary")
    print("-" * 50)

    for k, v in summary.items():
        print(f"{k:20}: {v}")


if __name__ == "__main__":
    main()
