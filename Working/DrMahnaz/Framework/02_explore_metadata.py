import os
from collections import Counter, defaultdict

import pydicom

from config import dicom_dir


def clean_text(value):
    if value is None:
        return "unknown"
    return str(value).strip().lower()


def explore_metadata():
    modality_counter = Counter()
    study_desc = Counter()
    series_desc = Counter()
    body_parts = Counter()
    manufacturers = Counter()

    study_to_series = defaultdict(set)

    for root, _, files in os.walk(dicom_dir):
        for file in files:
            path = os.path.join(root, file)

            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True)

                modality = ds.get("Modality", "Unknown")
                modality_counter[modality] += 1

                study = clean_text(ds.get("StudyDescription"))
                series = clean_text(ds.get("SeriesDescription"))
                body = clean_text(ds.get("BodyPartExamined"))
                manu = clean_text(ds.get("Manufacturer"))

                study_desc[study] += 1
                series_desc[series] += 1
                body_parts[body] += 1
                manufacturers[manu] += 1

                study_uid = ds.get("StudyInstanceUID")
                series_uid = ds.get("SeriesInstanceUID")

                if study_uid and series_uid:
                    study_to_series[study_uid].add(series_uid)

            except:
                continue

    # ---- OUTPUT ----
    print("\n========== METADATA EXPLORATION ==========")

    print("\n--- Modality Distribution ---")
    for k, v in modality_counter.items():
        print(f"{k}: {v}")

    print("\n--- Study Descriptions ---")
    for k, v in study_desc.most_common():
        print(f"{k}: {v}")

    print("\n--- Series Descriptions ---")
    for k, v in series_desc.most_common():
        print(f"{k}: {v}")

    print("\n--- Body Parts ---")
    for k, v in body_parts.most_common():
        print(f"{k}: {v}")

    print("\n--- Manufacturers ---")
    for k, v in manufacturers.most_common():
        print(f"{k}: {v}")

    print("\n--- Study → Series Mapping ---")
    for study, series_set in list(study_to_series.items())[:5]:
        print(f"{study} → {len(series_set)} series")


if __name__ == "__main__":
    explore_metadata()
