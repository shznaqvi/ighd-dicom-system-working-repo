# 00b_study_timeline.py
import os
from collections import defaultdict

import pydicom

from config import dicom_dir

patient_studies = defaultdict(set)
study_dates = {}

for root, _, files in os.walk(dicom_dir):
    for file in files:
        path = os.path.join(root, file)
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)

            patient = ds.get("PatientID")
            study = ds.get("StudyInstanceUID")
            date = ds.get("StudyDate")

            if patient and study:
                patient_studies[patient].add(study)

            if study and date:
                study_dates[study] = date

        except:
            continue

print("\n--- Patient Follow-ups ---")
for p, studies in patient_studies.items():
    print(f"\nPatient: {p}")
    print(f"Number of visits: {len(studies)}")

    sorted_studies = sorted(list(studies), key=lambda x: study_dates.get(x, ""))
    for s in sorted_studies:
        print("   ", s, study_dates.get(s))
