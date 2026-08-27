# 04_extract_sr.py
import os

import pandas as pd
import pydicom

from config import dicom_dir

# -----------------------------
# Display settings (EDA friendly)
# -----------------------------
pd.set_option("display.max_columns", None)  # show all columns
pd.set_option("display.max_rows", 100)  # avoid flooding terminal
pd.set_option("display.width", 1200)  # wide console output
pd.set_option("display.max_colwidth", 200)  # prevent text truncation

# Optional: better numeric readability
pd.set_option("display.float_format", lambda x: f"{x:.3f}")

sr_records = []


# ----------------------------
# SAFE SR TREE PARSER
# ----------------------------
def extract_from_sequence(seq, base_meta):
    """
    Recursively traverse SR ContentSequence
    """

    if not seq:
        return

    for item in seq:

        try:
            concept_name = None
            value = None
            unit = None

            # --- Measurement Name ---
            if hasattr(item, "ConceptNameCodeSequence"):
                concept_name = item.ConceptNameCodeSequence[0].CodeMeaning

            # --- Numeric Value ---
            if hasattr(item, "MeasuredValueSequence"):
                mv = item.MeasuredValueSequence[0]
                value = mv.get("NumericValue", None)

                if hasattr(mv, "MeasurementUnitsCodeSequence"):
                    unit = mv.MeasurementUnitsCodeSequence[0].CodeMeaning

            # --- Save measurement ---
            if concept_name and value is not None:
                sr_records.append({
                    **base_meta,
                    "Measurement": concept_name,
                    "Value": value,
                    "Unit": unit
                })

            # --- Recurse deeper ---
            if hasattr(item, "ContentSequence"):
                extract_from_sequence(item.ContentSequence, base_meta)

        except:
            continue


# ----------------------------
# MAIN SR EXTRACTION
# ----------------------------
def extract_sr():
    sr_files = 0

    for root, _, files in os.walk(dicom_dir):
        for file in files:
            path = os.path.join(root, file)

            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True)

                if ds.get("Modality") != "SR":
                    continue

                sr_files += 1

                base_meta = {
                    "PatientID": ds.get("PatientID"),
                    "StudyInstanceUID": ds.get("StudyInstanceUID"),
                    "SeriesInstanceUID": ds.get("SeriesInstanceUID"),
                    "SOPInstanceUID": ds.get("SOPInstanceUID"),
                    "StudyDate": ds.get("StudyDate"),
                }

                if hasattr(ds, "ContentSequence"):
                    extract_from_sequence(ds.ContentSequence, base_meta)

            except:
                continue

    df = pd.DataFrame(sr_records)

    print("\n========== SR EXTRACTION SUMMARY ==========")
    print("SR files found:", sr_files)
    print("Total measurements extracted:", len(df))

    if not df.empty:
        print("\n--- Sample Data ---")
        print(df.head(10))

        print("\n--- Measurement Types ---")
        print(df["Measurement"].value_counts().head(10))

        df.to_csv("sr_extracted.csv", index=False)
        print("\nSaved: sr_extracted.csv")

    else:
        print("No SR measurements extracted.")


if __name__ == "__main__":
    extract_sr()
