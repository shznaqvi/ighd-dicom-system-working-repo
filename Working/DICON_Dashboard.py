# Voluson DICOM Dataset EDA & Visualization Notebook
# Author: Hassan Naqvi
# Purpose: Full exploratory analysis, anomaly detection, and interactive report generation

# ===========================
# 1. Import Libraries
# ===========================
import os
import warnings
from collections import Counter

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pydicom
import seaborn as sns
from tqdm import tqdm

warnings.filterwarnings("ignore")
sns.set(style='whitegrid')

# Optional: HTML report
from ydata_profiling import ProfileReport  # pip install ydata-profiling

# ===========================
# 2. Dataset Paths
# ===========================
dicom_dir = r"H:\voluson swift\GE-voluson\Dicom\Dicom"

# ===========================
# 3. Collect DICOM & SR files
# ===========================
dicom_files, sr_files = [], []

for root, _, files in os.walk(dicom_dir):
    for f in files:
        if f.endswith('.dcm'):
            path = os.path.join(root, f)
            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
                if ds.Modality == 'SR':
                    sr_files.append(path)
                else:
                    dicom_files.append(path)
            except:
                continue

print(f"Total DICOM files: {len(dicom_files)}")
print(f"Total SR files: {len(sr_files)}")

# ===========================
# 4. Patient-Level Analysis
# ===========================
patient_ids = []
for f in dicom_files:
    ds = pydicom.dcmread(f, stop_before_pixels=True, force=True)
    patient_ids.append(ds.PatientID)

patient_counts = Counter(patient_ids)
patient_df = pd.DataFrame.from_dict(patient_counts, orient='index', columns=['num_dicoms'])
patient_df.sort_values('num_dicoms', ascending=False, inplace=True)

# Histogram of DICOMs per patient
plt.figure(figsize=(10, 6))
sns.histplot(patient_df['num_dicoms'], bins=30)
plt.title('Distribution of DICOMs per Patient')
plt.xlabel('Number of DICOMs')
plt.ylabel('Number of Patients')
plt.show()

# ===========================
# 5. Frame Number Analysis
# ===========================
frames_per_patient = {}
for f in dicom_files:
    ds = pydicom.dcmread(f, stop_before_pixels=True, force=True)
    pid = ds.PatientID
    frames_per_patient.setdefault(pid, []).append(getattr(ds, 'FrameNumber', 1))

frames_count = {pid: len(frames) for pid, frames in frames_per_patient.items()}
plt.figure(figsize=(10, 6))
sns.histplot(list(frames_count.values()), bins=30)
plt.title('Number of Frames per Patient')
plt.xlabel('Number of Frames')
plt.ylabel('Number of Patients')
plt.show()

# ===========================
# 6. Image Properties
# ===========================
rows_list, cols_list, mean_pixel, min_pixel, max_pixel = [], [], [], [], []

for f in tqdm(dicom_files, desc="Processing DICOMs"):
    ds = pydicom.dcmread(f, force=True)
    if 'PixelData' in ds:
        img = ds.pixel_array.astype(np.float32)
        rows_list.append(ds.Rows)
        cols_list.append(ds.Columns)
        mean_pixel.append(np.mean(img))
        min_pixel.append(np.min(img))
        max_pixel.append(np.max(img))

image_stats = pd.DataFrame({
    'Rows': rows_list,
    'Cols': cols_list,
    'MeanPixel': mean_pixel,
    'MinPixel': min_pixel,
    'MaxPixel': max_pixel
})

sns.histplot(image_stats['MeanPixel'], bins=50)
plt.title("Distribution of Mean Pixel Values")
plt.show()

sns.boxplot(data=image_stats[['Rows', 'Cols', 'MeanPixel', 'MinPixel', 'MaxPixel']])
plt.title("Image Properties Boxplot")
plt.show()


# Sample normalized images
def show_sample_images(files, n=5):
    plt.figure(figsize=(15, 5))
    for i, f in enumerate(files[:n]):
        ds = pydicom.dcmread(f, force=True)
        img = ds.pixel_array.astype(np.float32)
        img_norm = (img - np.min(img)) / (np.max(img) - np.min(img))
        plt.subplot(1, n, i + 1)
        plt.imshow(img_norm, cmap='gray')
        plt.title(f"Patient: {ds.PatientID}")
        plt.axis('off')
    plt.show()


show_sample_images(dicom_files, n=5)

# ===========================
# 7. Structured Report (SR) Analysis
# ===========================
sr_patient_counts = []
sr_fields = []

for f in sr_files:
    ds = pydicom.dcmread(f, force=True)
    sr_patient_counts.append(ds.PatientID)
    try:
        for item in ds.ContentSequence:
            sr_fields.append(item.ConceptNameCodeSequence[0].CodeMeaning)
    except:
        continue

sr_counter = Counter(sr_patient_counts)
sr_df = pd.DataFrame.from_dict(sr_counter, orient='index', columns=['num_sr'])
sr_df.plot(kind='bar', figsize=(12, 4), title='SR Count per Patient')
plt.show()

sr_field_counts = Counter(sr_fields)
print("Top 20 SR Fields:")
print(sr_field_counts.most_common(20))

# ===========================
# 8. Metadata Analysis
# ===========================
pixel_spacing, frame_time = [], []

for f in dicom_files:
    ds = pydicom.dcmread(f, stop_before_pixels=True, force=True)
    pixel_spacing.append(getattr(ds, 'PixelSpacing', [np.nan, np.nan])[0])
    frame_time.append(getattr(ds, 'FrameTime', np.nan))

meta_df = pd.DataFrame({'PixelSpacing': pixel_spacing, 'FrameTime': frame_time})

sns.histplot(meta_df['PixelSpacing'].dropna(), bins=30)
plt.title('Pixel Spacing Distribution')
plt.show()

sns.histplot(meta_df['FrameTime'].dropna(), bins=30)
plt.title('FrameTime Distribution')
plt.show()

sns.heatmap(meta_df.corr(), annot=True, cmap='coolwarm')
plt.title('Metadata Correlation Heatmap')
plt.show()

# ===========================
# 9. Correlation Analysis
# ===========================
frame_numbers, frame_times = [], []

for f in dicom_files:
    ds = pydicom.dcmread(f, stop_before_pixels=True, force=True)
    frame_numbers.append(getattr(ds, 'FrameNumber', np.nan))
    frame_times.append(getattr(ds, 'FrameTime', np.nan))

plt.figure(figsize=(8, 6))
sns.scatterplot(x=frame_numbers, y=frame_times)
plt.title("FrameNumber vs FrameTime")
plt.xlabel("FrameNumber")
plt.ylabel("FrameTime")
plt.show()

# ===========================
# 10. Anomaly Detection
# ===========================
missing_pixel_data = [f for f in dicom_files if
                      'PixelData' not in pydicom.dcmread(f, stop_before_pixels=True, force=True)]
print(f"Corrupted/missing PixelData: {len(missing_pixel_data)} files")

# Patients with unusually few/many frames
low_frames = [pid for pid, count in frames_count.items() if count < 5]
high_frames = [pid for pid, count in frames_count.items() if count > 2000]
print(f"Patients with very few frames (<5): {low_frames}")
print(f"Patients with very high frames (>2000): {high_frames}")

# ===========================
# 11. Optional: Interactive HTML Report
# ===========================
# ProfileReport will generate a full interactive HTML summary
eda_report = ProfileReport(meta_df, title="Voluson DICOM Metadata Report", explorative=True)
eda_report.to_file("Voluson_DICOM_Metadata_Report.html")
print("HTML report generated: Voluson_DICOM_Metadata_Report.html")
