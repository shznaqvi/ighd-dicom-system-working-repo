import pandas as pd

df = pd.read_csv(r"..\data\audit\dicom_audit_report.csv")

# Group valid files by Patient ID to see visit and SR distribution
patient_summary = df[df["is_valid_dicom"]].groupby("patient_id").agg(
    total_files=("file_name", "count"),
    unique_studies=("study_uid", "nunique"),
    sr_count=("modality", lambda x: (x == "SR").sum()),
    us_count=("modality", lambda x: (x == "US").sum())
).reset_index()

print(patient_summary.to_string(index=False))
