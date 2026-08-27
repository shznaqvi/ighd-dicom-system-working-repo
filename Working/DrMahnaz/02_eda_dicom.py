import numpy as np
import pandas as pd

# ==========================
# CONFIG
# ==========================
DATA_FILE = "dicom_metadata_clean.csv"

# ==========================
# LOAD DATA
# ==========================
print("\n📦 Loading cleaned DICOM dataset...")
df = pd.read_csv(DATA_FILE)

print("\n==============================")
print("📊 BASIC DATA OVERVIEW")
print("==============================")

print(f"Rows: {len(df)}")
print(f"Patients: {df['PatientID'].nunique()}")
print(f"Studies: {df['StudyInstanceUID'].nunique()}")
print(f"Series: {df['SeriesInstanceUID'].nunique()}")
print(f"Modalities: {df['Modality'].unique()}")

# ==========================
# PIXEL SPACING ANALYSIS
# ==========================
print("\n==============================")
print("📏 PIXEL SPACING ANALYSIS")
print("==============================")


def parse_ps(x):
    try:
        if pd.isna(x):
            return np.nan
        if isinstance(x, str):
            x = x.replace("[", "").replace("]", "")
            parts = [float(i) for i in x.split(",") if i.strip() != ""]
            return np.mean(parts)
        return float(x)
    except:
        return np.nan


df["PixelSpacing_flat"] = df["PixelSpacing"].apply(parse_ps)

print(f"Missing PixelSpacing: {df['PixelSpacing_flat'].isna().sum()}")
print(f"Valid PixelSpacing: {df['PixelSpacing_flat'].notna().sum()}")

print("\nPixelSpacing stats:")
print(df["PixelSpacing_flat"].describe())

print("\nTop PixelSpacing values:")
print(df["PixelSpacing_flat"].round(6).value_counts().head(10))

# ==========================
# STUDY STRUCTURE ANALYSIS
# ==========================
print("\n==============================")
print("🧠 STUDY STRUCTURE ANALYSIS")
print("==============================")

study_stats = df.groupby("StudyInstanceUID").agg({
    "SOPInstanceUID": "count",
    "SeriesInstanceUID": "nunique"
}).rename(columns={
    "SOPInstanceUID": "num_images",
    "SeriesInstanceUID": "num_series"
})

print(study_stats.describe())

print("\nStudies with very low images (<10):",
      (study_stats["num_images"] < 10).sum())

print("Studies with high images (>200):",
      (study_stats["num_images"] > 200).sum())

# ==========================
# PATIENT-LEVEL STRUCTURE
# ==========================
print("\n==============================")
print("👩‍⚕️ PATIENT STRUCTURE")
print("==============================")

patient_visits = df.groupby("PatientID")["StudyInstanceUID"].nunique()

print("\nVisits per patient:")
print(patient_visits.describe())

print("\nDistribution:")
print(patient_visits.value_counts().sort_index())

# ==========================
# TIME BEHAVIOR
# ==========================
print("\n==============================")
print("⏱ TEMPORAL STRUCTURE")
print("==============================")

df["StudyDate"] = pd.to_datetime(df["StudyDate"], errors="coerce")

timeline_check = df.sort_values(["PatientID", "StudyDate"])

print("\nPatients with missing/invalid dates:",
      df["StudyDate"].isna().sum())


# Check ordering consistency
def is_sorted(x):
    return x.is_monotonic_increasing


order_check = timeline_check.groupby("PatientID")["StudyDate"].apply(is_sorted)

print("\nNon-chronological patients:", (~order_check).sum())

# ==========================
# PIXELSPACING GROUP BEHAVIOR
# ==========================
print("\n==============================")
print("📐 PIXEL SPACING GROUP BEHAVIOR")
print("==============================")

df["spacing_group"] = pd.qcut(
    df["PixelSpacing_flat"],
    q=5,
    labels=["E_very_low", "D_low", "C_medium", "B_med_high", "A_high"]
)

print(df["spacing_group"].value_counts(dropna=False))

group_stats = df.groupby("spacing_group")["SOPInstanceUID"].count()
print("\nImages per spacing group:")
print(group_stats)

# ==========================
# VISIT VARIABILITY SIGNAL
# ==========================
print("\n==============================")
print("🔬 VISIT VARIABILITY SIGNAL")
print("==============================")

visit_df = df.groupby("StudyInstanceUID").agg({
    "PixelSpacing_flat": "mean",
    "SOPInstanceUID": "count",
    "SeriesInstanceUID": "nunique"
}).rename(columns={
    "SOPInstanceUID": "num_images",
    "SeriesInstanceUID": "num_series"
})

visit_df["image_density"] = visit_df["num_images"] / visit_df["num_series"]

print("\nVisit-level stats:")
print(visit_df.describe())

# ==========================
# DUPLICATION CHECK
# ==========================
print("\n==============================")
print("🧾 DUPLICATION CHECK")
print("==============================")

print("Duplicate SOPInstanceUIDs:",
      df["SOPInstanceUID"].duplicated().sum())

# ==========================
# MODEL READINESS SIGNALS
# ==========================
print("\n==============================")
print("🤖 MODEL READINESS SIGNALS")
print("==============================")

missing_spacing_pct = df["PixelSpacing_flat"].isna().mean() * 100

print(f"Missing PixelSpacing (%): {missing_spacing_pct:.2f}")
print(f"Avg images per study: {study_stats['num_images'].mean():.2f}")

print("\n==============================")
print("✅ EDA COMPLETE")
print("==============================")
