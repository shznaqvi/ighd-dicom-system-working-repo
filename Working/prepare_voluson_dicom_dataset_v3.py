# prepare_voluson_dicom_dataset_v3.py

import json
import os

import numpy as np
import pandas as pd
import pydicom
from sklearn.model_selection import train_test_split

# -----------------------------
# CONFIG
# -----------------------------
DICOM_FOLDER = r'H:\voluson swift\GE-voluson\Dicom\Dicom'
METADATA_CSV = r'H:\voluson swift\GE-voluson\Dicom\Dicom\dicom_metadata_summary.csv'
OUTPUT_FOLDER = r'H:\voluson swift\GE-voluson\Dicom\Dataset'
IMG_FORMAT = 'npy'  # or 'png'


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
    """Check if DICOM has pixel data (images only)."""
    # Option 1: check for PixelData attribute
    if hasattr(ds, "PixelData"):
        return True
    # Option 2: check Modality (most GE Voluson images are 'US')
    if getattr(ds, "Modality", "").upper() == "US":
        return True
    return False


def is_sr(ds):
    return getattr(ds, "Modality", "") == "SR"


def load_dicom_array(path):
    ds = pydicom.dcmread(path)
    if not hasattr(ds, "pixel_array"):
        raise ValueError(f"No pixel data: {path}")
    arr = ds.pixel_array.astype(np.float32)
    arr = (arr - arr.min()) / (arr.max() - arr.min() + 1e-6)
    return arr


def extract_sr_content(ds):
    """
    Recursively extract numeric/text values from a Structured Report.
    """
    sr_data = {}

    def recurse_content(seq, parent_name="root"):
        for idx, item in enumerate(seq):
            # Numeric measurement
            if getattr(item, "ValueType", None) == "NUM":
                try:
                    val = item.MeasuredValueSequence[0].NumericValue
                    concept = item.ConceptNameCodeSequence[0].CodeMeaning
                    sr_data[f"{parent_name}_{concept}"] = float(val)
                except:
                    continue
            # Text measurement
            elif getattr(item, "ValueType", None) == "TEXT":
                try:
                    text_val = item.TextValue
                    concept = item.ConceptNameCodeSequence[0].CodeMeaning
                    sr_data[f"{parent_name}_{concept}"] = text_val
                except:
                    continue
            # Nested container
            if hasattr(item, "ContentSequence"):
                recurse_content(item.ContentSequence,
                                parent_name=f"{parent_name}_{getattr(item, 'ConceptNameCodeSequence', [{}])[0].get('CodeMeaning', idx)}")

    if hasattr(ds, "ContentSequence"):
        recurse_content(ds.ContentSequence)
    return sr_data


# -----------------------------
# BUILD DICOM INDEX
# -----------------------------
print("🔍 Indexing DICOMs...")
dicom_index = {}
sr_index = {}

for root, _, files in os.walk(DICOM_FOLDER):
    for f in files:
        file_path = os.path.join(root, f)
        if not is_dicom(file_path):
            continue
        try:
            ds = pydicom.dcmread(file_path, stop_before_pixels=True)
            uid = str(ds.SOPInstanceUID)
            dicom_index[uid] = file_path
            if is_sr(ds):
                sr_index[uid] = file_path
        except:
            continue

print(f"✅ Total DICOMs: {len(dicom_index)} | SR files: {len(sr_index)}")

# -----------------------------
# LOAD METADATA
# -----------------------------
df = pd.read_csv(METADATA_CSV)
df['SOPInstanceUID'] = df['SOPInstanceUID'].astype(str)
df['dicom_path'] = df['SOPInstanceUID'].map(dicom_index)
df = df.dropna(subset=['dicom_path'])
print(f"Rows after mapping metadata: {len(df)} | Patients: {df['PatientID'].nunique()}")

# -----------------------------
# SPLIT DATASET (PATIENT LEVEL)
# -----------------------------
patients = df['PatientID'].unique()
train_patients, test_patients = train_test_split(patients, test_size=0.2, random_state=42)
train_patients, val_patients = train_test_split(train_patients, test_size=0.2, random_state=42)
splits = {'train': train_patients, 'val': val_patients, 'test': test_patients}

# -----------------------------
# PROCESS AND SAVE
# -----------------------------
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
all_labels = []

for split_name, patient_ids in splits.items():
    print(f"\n➡️ Processing split: {split_name}")
    split_folder = os.path.join(OUTPUT_FOLDER, split_name)
    os.makedirs(split_folder, exist_ok=True)

    df_split = df[df['PatientID'].isin(patient_ids)]
    for idx, row in df_split.iterrows():
        try:

            ds = pydicom.dcmread(row['dicom_path'], stop_before_pixels=False)

            if not is_image_dicom(ds):
                print(f"⚠️ Skipping non-image DICOM: {row['dicom_path']}")
                continue

            arr = load_dicom_array(row['dicom_path'])
            fname = f"{row['PatientID']}_{row['FrameNumber']}.{IMG_FORMAT}"
            out_path = os.path.join(split_folder, fname)
            if IMG_FORMAT == 'npy':
                np.save(out_path, arr)
            elif IMG_FORMAT == 'png':
                from PIL import Image

                Image.fromarray((arr * 255).astype(np.uint8)).save(out_path)

            # Attach SR measurements if linked
            sr_values = {}
            for sr_uid, sr_path in sr_index.items():
                sr_ds = pydicom.dcmread(sr_path)
                # Check if this SR references this image
                refs = getattr(sr_ds, "ReferencedSOPSequence", [])
                if any(getattr(ref, "ReferencedSOPInstanceUID", None) == row['SOPInstanceUID'] for ref in refs):
                    sr_values.update(extract_sr_content(sr_ds))

            # Attach SR measurements if linked
            sr_values = {}
            for sr_uid, sr_path in sr_index.items():
                sr_ds = pydicom.dcmread(sr_path)
                # Check if this SR references this image
                refs = getattr(sr_ds, "ReferencedSOPSequence", [])
                if any(getattr(ref, "ReferencedSOPInstanceUID", None) == row['SOPInstanceUID'] for ref in refs):
                    sr_values.update(extract_sr_content(sr_ds))

            all_labels.append({
                'file': out_path,
                'PatientID': row['PatientID'],
                'FrameNumber': row['FrameNumber'],
                'Modality': row.get('Modality', None),
                'PixelSpacing': row.get('PixelSpacing', None),
                'FrameTime': row.get('FrameTime', None),
                'sr_labels': sr_values
            })

        except Exception as e:
            print(f"⚠️ Skipping file: {row['dicom_path']} | Error: {e}")
            continue

# -----------------------------
# SAVE LABELS
# -----------------------------
labels_path = os.path.join(OUTPUT_FOLDER, 'labels_with_sr.json')
with open(labels_path, 'w') as f:
    json.dump(all_labels, f, indent=2)

print("\n✅ Dataset v3 prepared successfully!")
print(f"📁 Output folder: {OUTPUT_FOLDER}")
print(f"🧾 Labels file: {labels_path}")
