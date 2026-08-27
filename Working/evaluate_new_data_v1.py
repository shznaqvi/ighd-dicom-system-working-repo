# evaluate_new_dataset.py

import json
import os
from collections import defaultdict

import pandas as pd
import pydicom

# -----------------------------
# CONFIG
# -----------------------------
DICOM_FOLDER = r"H:\voluson swift\GE-voluson\Dicom\Dicom"
METADATA_CSV = os.path.join(DICOM_FOLDER, "metadata.csv")  # auto-generate if missing
REPORT_FOLDER = os.path.join(DICOM_FOLDER, "Report")
os.makedirs(REPORT_FOLDER, exist_ok=True)


# -----------------------------
# UTILS
# -----------------------------
def is_dicom(file_path):
    try:
        with open(file_path, "rb") as f:
            return b"DICM" in f.read(132)
    except:
        return False


def is_image_dicom(ds):
    return hasattr(ds, "PixelData") or getattr(ds, "Modality", "").upper() == "US"


def is_sr(ds):
    return getattr(ds, "Modality", "") == "SR"


def safe_dcmread(path, stop_before_pixels=True):
    try:
        return pydicom.dcmread(path, stop_before_pixels=stop_before_pixels)
    except:
        return None


# -----------------------------
# STEP 1: GENERATE METADATA IF MISSING
# -----------------------------
if not os.path.exists(METADATA_CSV):
    print("📝 Metadata CSV not found. Generating metadata...")
    metadata_list = []
    for root, _, files in os.walk(DICOM_FOLDER):
        for f in files:
            file_path = os.path.join(root, f)
            if not is_dicom(file_path):
                continue
            ds = safe_dcmread(file_path, stop_before_pixels=True)
            if ds is None:
                continue
            metadata_list.append({
                "PatientID": getattr(ds, "PatientID", "Unknown"),
                "SOPInstanceUID": str(getattr(ds, "SOPInstanceUID", "")),
                "Modality": getattr(ds, "Modality", ""),
                "StudyDate": getattr(ds, "StudyDate", ""),
                "SeriesDescription": getattr(ds, "SeriesDescription", ""),
                "FilePath": file_path
            })
    df_metadata = pd.DataFrame(metadata_list)
    df_metadata.to_csv(METADATA_CSV, index=False)
    print(f"✅ Metadata CSV generated: {METADATA_CSV}")
else:
    df_metadata = pd.read_csv(METADATA_CSV)
    print(f"📄 Loaded existing metadata CSV: {METADATA_CSV}")

# -----------------------------
# STEP 2: INDEX DICOM AND SR FILES
# -----------------------------
print("🔍 Indexing DICOM and SR files...")
dicom_index = {}
sr_index = {}
issues = defaultdict(list)

for _, row in df_metadata.iterrows():
    file_path = row['FilePath']
    ds = safe_dcmread(file_path)
    if ds is None:
        issues['unreadable_dicom'].append(file_path)
        continue
    uid = str(getattr(ds, "SOPInstanceUID", ""))
    if not uid:
        issues['missing_uid'].append(file_path)
        continue
    dicom_index[uid] = file_path
    if is_sr(ds):
        sr_index[uid] = file_path

print(f"✅ Indexed DICOMs: {len(dicom_index)} | SR files: {len(sr_index)}")
print(f"⚠️ Issues detected so far: { {k: len(v) for k, v in issues.items()} }")

# -----------------------------
# STEP 3: VALIDATE IMAGES
# -----------------------------
pixel_shapes = {}
for _, row in df_metadata.iterrows():
    file_path = row['FilePath']
    ds = safe_dcmread(file_path, stop_before_pixels=False)
    if ds is None:
        issues['cannot_read_pixel'].append(file_path)
        continue
    if not is_image_dicom(ds):
        issues['non_image_dicom'].append(file_path)
        continue
    try:
        arr = ds.pixel_array
        pixel_shapes[file_path] = arr.shape
    except Exception as e:
        issues['pixel_array_error'].append({'file': file_path, 'error': str(e)})

# -----------------------------
# STEP 4: VALIDATE SR REFERENCES
# -----------------------------
sr_mapping_issues = []
for sr_uid, sr_path in sr_index.items():
    ds = safe_dcmread(sr_path, stop_before_pixels=True)
    if ds is None:
        issues['sr_unreadable'].append(sr_path)
        continue
    refs = getattr(ds, "ReferencedSOPSequence", [])
    for ref in refs:
        ref_uid = getattr(ref, "ReferencedSOPInstanceUID", None)
        if ref_uid not in dicom_index:
            sr_mapping_issues.append({'sr_file': sr_path, 'ref_uid': ref_uid})
if sr_mapping_issues:
    issues['sr_invalid_refs'] = sr_mapping_issues

# -----------------------------
# STEP 5: SUMMARY STATISTICS
# -----------------------------
report = {
    'total_dicom_files': len(dicom_index),
    'total_sr_files': len(sr_index),
    'total_patients': df_metadata['PatientID'].nunique(),
    'total_frames': len(df_metadata),
    'pixel_shapes': list(set(pixel_shapes.values())),
    'issues_summary': {k: len(v) for k, v in issues.items()},
}

# -----------------------------
# STEP 6: SAVE REPORT
# -----------------------------
report_path = os.path.join(REPORT_FOLDER, 'dataset_evaluation_report.json')
with open(report_path, 'w') as f:
    json.dump({'report': report, 'issues': issues}, f, indent=2)

print(f"\n✅ Evaluation complete! Report saved at: {report_path}")
print(f"📊 Summary: {report}")
