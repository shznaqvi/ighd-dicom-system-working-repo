"""
===============================================================================
GE Voluson Swift DICOM Intelligence Toolkit (DIT)
===============================================================================

Project : Maternal Fetal AI
Module  : Main Entry Point
Version : 0.1.0

Purpose
-------
Main application entry point for the DICOM Intelligence Toolkit.

Responsibilities
----------------
1. Display application information
2. Load configuration
3. Validate input/output folders
4. Execute audit modules
5. Display execution summary

Author : Hassan Naqvi
===============================================================================
"""

import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd
import pydicom

from config import Config
from scanner import DatasetScanner


# =============================================================================
# Utility Functions
# =============================================================================

def print_header():
    print("\n" + "=" * 78)
    print("GE VOLUSON SWIFT DICOM INTELLIGENCE TOOLKIT")
    print("Version : 0.1.0")
    print("=" * 78)


def print_environment():
    print("\nEnvironment")
    print("-" * 78)

    print(f"Python            : {platform.python_version()}")
    print(f"Operating System  : {platform.system()} {platform.release()}")
    print(f"pydicom           : {pydicom.__version__}")
    print(f"pandas            : {pd.__version__}")

    print(f"\nWorking Directory : {Path.cwd()}")


def print_configuration(config: Config):
    print("\nConfiguration")
    print("-" * 78)

    print(f"Input Folder      : {config.INPUT_FOLDER}")
    print(f"Output Folder     : {config.OUTPUT_FOLDER}")


def validate_configuration(config: Config):
    if not config.INPUT_FOLDER.exists():
        raise FileNotFoundError(
            f"Input folder does not exist:\n{config.INPUT_FOLDER}"
        )

    config.OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )


# =============================================================================
# Main
# =============================================================================

def main():
    start_time = datetime.now()

    print_header()

    print_environment()

    config = Config()

    print_configuration(config)

    validate_configuration(config)

    print("\nStarting Dataset Discovery...")
    print("-" * 78)

    scanner = DatasetScanner(config)

    scanner.scan()

    scanner.export_inventory()

    scanner.export_summary()

    print("\nDataset Discovery Complete")

    elapsed = datetime.now() - start_time

    print("\nExecution Summary")
    print("-" * 78)

    print(f"Elapsed Time      : {elapsed}")

    print("\nGenerated Files")

    print(f"  ✓ {config.INVENTORY_FILE.name}")
    print(f"  ✓ {config.SUMMARY_FILE.name}")

    print("\nNext Recommended Module")

    print("  → taxonomy.py")

    print("\nAudit completed successfully.")

    print("=" * 78)


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print("\nAudit cancelled by user.")

        sys.exit(1)

    except Exception:

        print("\nUnexpected Error")
        print("-" * 78)

        traceback.print_exc()

        sys.exit(1)
