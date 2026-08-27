import os
from collections import defaultdict

import pydicom


def value_level_recheck(root_folder):
    # 1. Collect all unique SOP UIDs from US images
    us_sop_uids = set()
    us_study_uids = set()

    # 2. Collect every single UID value found inside SR files
    sr_all_uid_values = defaultdict(list)  # Value -> list of tags where it was found

    print(f"🕵️ Analyzing values in: {root_folder}...")

    for root, _, files in os.walk(root_folder):
        for f in files:
            if not f.lower().endswith(".dcm"):
                continue

            path = os.path.join(root, f)
            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True)
                modality = str(getattr(ds, "Modality", "OTHER"))

                if modality == "US":
                    us_sop_uids.add(str(ds.SOPInstanceUID))
                    us_study_uids.add(str(ds.StudyInstanceUID))

                elif modality == "SR":
                    # Deep scan every element in the SR for any UID strings
                    for element in ds.iterall():
                        # We only care about fields that are UIDs (VR = UI)
                        if element.VR == "UI":
                            val = str(element.value)
                            sr_all_uid_values[val].append({
                                "file": f,
                                "tag": element.name,
                                "keyword": element.keyword
                            })
            except Exception:
                continue

    # --- CROSSOVER ANALYSIS ---
    print("\n" + "=" * 60)
    print("🔎 CROSSOVER RESULTS: DO SR VALUES MATCH US IMAGES?")
    print("=" * 60)

    matches_found = 0
    for us_uid in us_sop_uids:
        if us_uid in sr_all_uid_values:
            matches_found += 1
            print(f"🎯 MATCH FOUND!")
            print(f"   US Image SOP UID: {us_uid}")
            for occurrence in sr_all_uid_values[us_uid]:
                print(f"   Found in SR [{occurrence['file']}] at Tag: {occurrence['keyword']}")

    if matches_found == 0:
        print("\n❌ NO IMAGE-LEVEL MATCHES.")
        print("Confirmed: No UID value inside any SR file matches a US Image UID.")

        # Double check Study-level glue
        study_matches = [uid for uid in us_study_uids if uid in sr_all_uid_values]
        print(f"\n✅ STUDY-LEVEL GLUE: {len(study_matches)} Studies correctly shared between US and SR.")

    print("=" * 60)


if __name__ == "__main__":
    raw_data_path = r"D:\IGHD_DICOM_VIEWER\raw_data"
    value_level_recheck(raw_data_path)
