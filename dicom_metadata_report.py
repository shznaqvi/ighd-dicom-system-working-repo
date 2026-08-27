import os

import pandas as pd
import pydicom

# Root folder of your DICOM dataset
root_folder = r"H:\voluson swift\GE-voluson\Dicom\Dicom"

# Columns we want in the CSV
columns = [
    "PatientID", "PatientName", "StudyInstanceUID", "StudyDate", "StudyTime",
    "AccessionNumber", "SeriesInstanceUID", "SeriesNumber", "Modality",
    "SOPInstanceUID", "Rows", "Columns", "PixelSpacing", "FrameTime",
    "FrameNumber", "SRMeasurements"
]

data = []


def extract_sr_measurements(ds):
    """Extract simple text from Structured Report if present"""
    measurements = {}
    if hasattr(ds, "ContentSequence"):
        for item in ds.ContentSequence:
            if hasattr(item, "ConceptNameCodeSequence") and hasattr(item, "TextValue"):
                name = item.ConceptNameCodeSequence[0].CodeMeaning
                value = item.TextValue
                measurements[name] = value
    return measurements if measurements else None


for dirpath, dirnames, filenames in os.walk(root_folder):
    for file in filenames:
        file_path = os.path.join(dirpath, file)
        try:
            ds = pydicom.dcmread(file_path, stop_before_pixels=True)
            if 'Modality' not in ds:
                print(f"Skipping non-image file: {path}")
                continue
            # Extract SR measurements if modality is SR
            sr_data = extract_sr_measurements(ds) if ds.Modality == "SR" else None

            row = {
                "PatientID": getattr(ds, "PatientID", None),
                "PatientName": getattr(ds, "PatientName", None),
                "StudyInstanceUID": getattr(ds, "StudyInstanceUID", None),
                "StudyDate": getattr(ds, "StudyDate", None),
                "StudyTime": getattr(ds, "StudyTime", None),
                "AccessionNumber": getattr(ds, "AccessionNumber", None),
                "SeriesInstanceUID": getattr(ds, "SeriesInstanceUID", None),
                "SeriesNumber": getattr(ds, "SeriesNumber", None),
                "Modality": getattr(ds, "Modality", None),
                "SOPInstanceUID": getattr(ds, "SOPInstanceUID", None),
                "Rows": getattr(ds, "Rows", None),
                "Columns": getattr(ds, "Columns", None),
                "PixelSpacing": getattr(ds, "PixelSpacing", None),
                "FrameTime": getattr(ds, "FrameTime", None),
                "FrameNumber": getattr(ds, "InstanceNumber", None),
                "SRMeasurements": sr_data
            }
            data.append(row)
            print(ds.PatientID, ds.Modality)

        except Exception as e:
            print(f"Skipping {file_path}, error: {e}")

# Save to CSV
df = pd.DataFrame(data, columns=columns)
output_csv = os.path.join(root_folder, "dicom_metadata_summary.csv")
df.to_csv(output_csv, index=False)
print(f"Metadata extracted and saved to {output_csv}")
