# prepare_voluson_dicom_dataset_v4.py

import json
import multiprocessing
import os
from functools import partial
from multiprocessing import Pool, cpu_count

import numpy as np
import pandas as pd
import pydicom
from sklearn.model_selection import train_test_split

# -----------------------------
# CONFIG
# -----------------------------
# DICOM_FOLDER = r'H:\voluson swift\GE-voluson\Dicom\Dicom'
# METADATA_CSV = r'H:\voluson swift\GE-voluson\Dicom\Dicom\dicom_metadata_summary.csv'
# OUTPUT_FOLDER = r'H:\voluson swift\GE-voluson\Dicom\Dataset'

# These are your primary paths. The script will now strictly use these.
dicom_dir = r"C:\Users\hassan.naqvi\OneDrive - Aga Khan University\Mahnaz Ambareen's files - QC Hassan bhai"
csv_output = r"..\DrMahnaz\MaternalDICOM_summary.csv"
json_output = r"..\DrMahnaz\MaternalDICOM_summary.json"

IMG_FORMAT = 'npy'  # 'npy' or 'png'
N_PROCESSES = max(1, cpu_count() - 1)


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


def load_dicom_array(path):
    ds = pydicom.dcmread(path)
    arr = ds.pixel_array.astype(np.float32)
    arr = (arr - arr.min()) / (arr.max() - arr.min() + 1e-6)
    return arr


def extract_sr_content(ds):
    sr_data = {}

    def recurse(seq, parent="root"):
        for idx, item in enumerate(seq):
            concept = getattr(item.ConceptNameCodeSequence[0], 'CodeMeaning', f"item{idx}")
            if getattr(item, "ValueType", None) == "NUM":
                try:
                    sr_data[f"{parent}_{concept}"] = float(item.MeasuredValueSequence[0].NumericValue)
                except:
                    continue
            elif getattr(item, "ValueType", None) == "TEXT":
                try:
                    sr_data[f"{parent}_{concept}"] = item.TextValue
                except:
                    continue
            if hasattr(item, "ContentSequence"):
                recurse(item.ContentSequence, parent=f"{parent}_{concept}")

    if hasattr(ds, "ContentSequence"):
        recurse(ds.ContentSequence)
    return sr_data


def process_row(row, sr_index, split_folder):
    out_entry = {}
    try:
        ds = pydicom.dcmread(row[4], stop_before_pixels=False)  # row[4] = dicom_path
        if not is_image_dicom(ds):
            return None
        arr = load_dicom_array(row[4])
        fname = f"{row[0]}_{row[1]}.{IMG_FORMAT}"  # row[0]=PatientID, row[1]=FrameNumber
        out_path = os.path.join(split_folder, fname)
        if IMG_FORMAT == 'npy':
            np.save(out_path, arr)
        elif IMG_FORMAT == 'png':
            from PIL import Image
            Image.fromarray((arr * 255).astype(np.uint8)).save(out_path)
        # Attach SR labels if referenced
        sr_values = {}
        for sr_uid, sr_path in sr_index.items():
            sr_ds = pydicom.dcmread(sr_path, stop_before_pixels=True)
            refs = getattr(sr_ds, "ReferencedSOPSequence", [])
            if any(getattr(ref, "ReferencedSOPInstanceUID", None) == row[2] for ref in refs):  # row[2]=SOPInstanceUID
                sr_values.update(extract_sr_content(sr_ds))
        out_entry = {
            'file': out_path,
            'PatientID': row[0],
            'FrameNumber': row[1],
            'Modality': row[3],  # row[3]=Modality
            'sr_labels': sr_values
        }
    except Exception as e:
        # print(f"⚠️ Skipping {row[4]} | Error: {e}")
        return None
    return out_entry


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
# SPLIT DATASET
# -----------------------------
patients = df['PatientID'].unique()
train_patients, test_patients = train_test_split(patients, test_size=0.2, random_state=42)
train_patients, val_patients = train_test_split(train_patients, test_size=0.2, random_state=42)
splits = {'train': train_patients, 'val': val_patients, 'test': test_patients}

# -----------------------------
# PROCESS DATA WITH MULTIPROCESSING
# -----------------------------
os.makedirs(OUTPUT_FOLDER, exist_ok=True)


def process_split(split_name, patient_ids, df, sr_index, output_folder):
    print(f"\n➡️ Processing split: {split_name}")
    split_folder = os.path.join(output_folder, split_name)
    os.makedirs(split_folder, exist_ok=True)
    df_split = df[df['PatientID'].isin(patient_ids)]
    rows = list(df_split.itertuples(index=False, name=None))
    func = partial(process_row, sr_index=sr_index, split_folder=split_folder)
    all_labels = []
    with Pool(N_PROCESSES) as pool:
        results = pool.map(func, rows)
    all_labels.extend([r for r in results if r is not None])
    return all_labels


def main():
    final_labels = []
    for split_name, patient_ids in splits.items():
        labels = process_split(split_name, patient_ids, df, sr_index, OUTPUT_FOLDER)
        final_labels.extend(labels)

    # -----------------------------
    # SAVE LABELS
    # -----------------------------
    labels_path = os.path.join(OUTPUT_FOLDER, 'labels_with_sr.json')
    with open(labels_path, 'w') as f:
        json.dump(final_labels, f, indent=2)

    print(f"\n✅ Finished processing all splits. Total labels: {len(final_labels)}")
    print(f"📁 Output folder: {OUTPUT_FOLDER}")
    print(f"🧾 Labels file: {labels_path}")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # safe on Windows
    main()
