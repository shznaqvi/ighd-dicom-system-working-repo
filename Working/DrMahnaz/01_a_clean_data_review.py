# 01_A_Clean_data_review.py

import numpy as np
import pandas as pd

# ==============================
# Load Clean Dataset
# ==============================
clean_path = "dicom_metadata_clean.csv"
visit_path = "dicom_visit_level.csv"

df = pd.read_csv(clean_path)
visit_df = pd.read_csv(visit_path)

print("\n==============================")
print("🔍 DICOM CLEAN DATA REVIEW")
print("==============================\n")

# ==============================
# 1. BASIC SANITY CHECK
# ==============================
print("📌 BASIC CHECKS")
print("------------------------------")
print("Rows:", len(df))
print("Patients:", df["PatientID"].nunique())
print("Studies:", df["StudyInstanceUID"].nunique())
print("Series:", df["SeriesInstanceUID"].nunique())
print("Modalities:", df["Modality"].unique())

# ==============================
# 2. PIXEL SPACING ANALYSIS
# ==============================
print("\n📌 PIXEL SPACING QUALITY")
print("------------------------------")

ps = df["PixelSpacing"]

print("Missing PixelSpacing:", ps.isna().sum())


# Try flattening values safely
def flatten_ps(x):
    try:
        if isinstance(x, str):
            return float(eval(x)[0])
        if isinstance(x, (list, tuple)):
            return float(x[0])
        if pd.notna(x):
            return float(x)
    except:
        return np.nan
    return np.nan


df["PixelSpacing_flat"] = df["PixelSpacing"].apply(flatten_ps)

print("Valid PixelSpacing values:", df["PixelSpacing_flat"].notna().sum())
print("PixelSpacing stats:")
print(df["PixelSpacing_flat"].describe())

print("\n⚠️ Unique PixelSpacing values (rounded):")
print(df["PixelSpacing_flat"].round(6).value_counts().head(10))

# ==============================
# 3. STUDY CONSISTENCY CHECK
# ==============================
print("\n📌 STUDY CONSISTENCY")
print("------------------------------")

study_counts = df.groupby("StudyInstanceUID")["SOPInstanceUID"].count()

print("Studies with very low images (<10):", (study_counts < 10).sum())
print("Studies with high images (>200):", (study_counts > 200).sum())

# ==============================
# 4. PATIENT VISIT STRUCTURE
# ==============================
print("\n📌 PATIENT VISIT STRUCTURE")
print("------------------------------")

visits = df.groupby("PatientID")["StudyInstanceUID"].nunique()

print("Avg visits per patient:", visits.mean())
print("Min visits:", visits.min())
print("Max visits:", visits.max())

print("\nVisit distribution:")
print(visits.value_counts().sort_index())

# ==============================
# 5. TEMPORAL CONSISTENCY
# ==============================
print("\n📌 TEMPORAL CHECK")
print("------------------------------")

df["StudyDate"] = pd.to_datetime(df["StudyDate"], errors="coerce")

timeline_issues = df.groupby("PatientID")["StudyDate"].apply(
    lambda x: x.is_monotonic_increasing
)

print("Patients with non-chronological studies:", (~timeline_issues).sum())

# ==============================
# 6. DUPLICATION CHECK
# ==============================
print("\n📌 DUPLICATION CHECK")
print("------------------------------")

dup_sop = df["SOPInstanceUID"].duplicated().sum()
print("Duplicate SOPInstanceUIDs:", dup_sop)

# ==============================
# 7. VISIT-LEVEL VALIDATION
# ==============================
print("\n📌 VISIT-LEVEL DATA CHECK")
print("------------------------------")

print("Visit-level rows:", len(visit_df))

print("\nImages per visit stats:")
print(visit_df["NumImages"].describe())

print("\nVisits with extremely low images (<5):",
      (visit_df["NumImages"] < 5).sum())

# ==============================
# 8. MODEL READINESS FLAGS
# ==============================
print("\n📌 MODEL READINESS FLAGS")
print("------------------------------")

flags = {
    "Missing PixelSpacing (%)": df["PixelSpacing_flat"].isna().mean() * 100,
    "Duplicate SOPs (%)": dup_sop / len(df) * 100,
    "Avg images per study": study_counts.mean(),
}

for k, v in flags.items():
    print(f"{k}: {v:.2f}")

print("\n==============================")
print("✅ CLEAN DATA REVIEW COMPLETE")
print("==============================")
