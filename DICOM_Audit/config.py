"""
===============================================================================
Configuration
===============================================================================
"""

from pathlib import Path


class Config:
    # ------------------------------------------------------------
    # Dataset
    # ------------------------------------------------------------

    INPUT_FOLDER = Path(r"D:\dump")

    OUTPUT_FOLDER = Path(r"..\data\audit")

    # ------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------

    REPORT_FOLDER = OUTPUT_FOLDER / "reports"

    LOG_FOLDER = OUTPUT_FOLDER / "logs"

    CSV_FOLDER = OUTPUT_FOLDER / "csv"

    JSON_FOLDER = OUTPUT_FOLDER / "json"

    # ------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------

    INVENTORY_CSV = CSV_FOLDER / "dicom_inventory.csv"

    TAXONOMY_CSV = CSV_FOLDER / "dicom_taxonomy.csv"

    STUDY_CSV = CSV_FOLDER / "study_summary.csv"

    SERIES_CSV = CSV_FOLDER / "series_summary.csv"

    OBJECT_CSV = CSV_FOLDER / "object_summary.csv"

    # ------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------

    SUMMARY_JSON = JSON_FOLDER / "dataset_summary.json"

    # ------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------

    MARKDOWN_REPORT = REPORT_FOLDER / "audit_report.md"

    HTML_REPORT = REPORT_FOLDER / "audit_report.html"

    # ------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------

    LOG_FILE = LOG_FOLDER / "audit.log"

    # ------------------------------------------------------------
    # Scanner
    # ------------------------------------------------------------

    COMPUTE_SHA256 = True

    VERIFY_DICOM = True

    READ_PIXEL_DATA = False

    VERBOSE = True

    # ------------------------------------------------------------
    # Create directories
    # ------------------------------------------------------------

    @classmethod
    def initialize(cls):
        cls.OUTPUT_FOLDER.mkdir(
            parents=True,
            exist_ok=True
        )

        cls.CSV_FOLDER.mkdir(
            parents=True,
            exist_ok=True
        )

        cls.JSON_FOLDER.mkdir(
            parents=True,
            exist_ok=True
        )

        cls.REPORT_FOLDER.mkdir(
            parents=True,
            exist_ok=True
        )

        cls.LOG_FOLDER.mkdir(
            parents=True,
            exist_ok=True
        )
