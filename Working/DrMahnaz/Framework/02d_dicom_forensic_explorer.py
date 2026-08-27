# 03_dicom_forensic_explorer.py

import os

import pandas as pd
import pydicom

from config import dicom_dir

# -----------------------------
# SETTINGS
# -----------------------------
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 1200)

results = []


# =============================
# 1. DEEP SR TREE WALKER
# =============================
def walk_sr(seq, study_uid, series_uid, sop_uid, path="ROOT"):
    """
    Recursively extract ALL SR nodes (deep + nested)
    """

    output = []

    for item in seq:

        name = None
        value = None

        # Concept name
        if hasattr(item, "ConceptNameCodeSequence"):
            try:
                name = item.ConceptNameCodeSequence[0].CodeMeaning
            except:
                pass

        # Text value
        if hasattr(item, "TextValue"):
            value = str(item.TextValue)

        # Numeric value
        if hasattr(item, "MeasuredValueSequence"):
            try:
                mv = item.MeasuredValueSequence[0]
                value = mv.get("NumericValue", value)
            except:
                pass

        if name or value:
            output.append({
                "StudyInstanceUID": study_uid,
                "SeriesInstanceUID": series_uid,
                "SOPInstanceUID": sop_uid,
                "Path": path + "/" + str(name),
                "Value": value,
                "Source": "SR"
            })

        # 🔥 RECURSION (critical)
        if hasattr(item, "ContentSequence"):
            output.extend(
                walk_sr(
                    item.ContentSequence,
                    study_uid,
                    series_uid,
                    sop_uid,
                    path + "/" + str(name)
                )
            )

    return output


# =============================
# 2. US METADATA EXTRACTOR
# =============================
def extract_us(ds):
    return {
        "ViewName": str(ds.get("ViewName", "")),
        "SeriesDescription": str(ds.get("SeriesDescription", "")),
        "StudyDescription": str(ds.get("StudyDescription", "")),
        "ProtocolName": str(ds.get("ProtocolName", "")),
        "ImageType": str(ds.get("ImageType", "")),
    }


# =============================
# 3. PRIVATE TAG SCANNER
# =============================
def extract_private_tags(ds):
    private_data = []

    for elem in ds.iterall():
        try:
            if elem.tag.is_private:
                private_data.append(str(elem.value))
        except:
            continue

    return private_data


# =============================
# 4. KEYWORD DETECTOR
# =============================
KEYWORDS = [
    "crl", "crown", "rump",
    "nt", "nuchal",
    "fhr", "heart rate", "bpm",
    "doppler",
    "biometry",
    "gestation",
    "edd",
    "ga"
]


def detect_keywords(text_list):
    joined = " ".join([str(t).lower() for t in text_list if t])
    hits = [k for k in KEYWORDS if k in joined]
    return hits


# =============================
# 5. MAIN PIPELINE
# =============================
def run():
    print("\n🔍 Starting full forensic DICOM exploration...\n")

    for root, _, files in os.walk(dicom_dir):
        for file in files:

            path = os.path.join(root, file)

            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True)

                modality = ds.get("Modality", "NA")

                study_uid = ds.get("StudyInstanceUID", "NA")
                series_uid = ds.get("SeriesInstanceUID", "NA")
                sop_uid = ds.get("SOPInstanceUID", "NA")

                all_text = []

                # ---------------------
                # SR PROCESSING
                # ---------------------
                if modality == "SR" and hasattr(ds, "ContentSequence"):
                    sr_rows = walk_sr(
                        ds.ContentSequence,
                        study_uid,
                        series_uid,
                        sop_uid
                    )
                    results.extend(sr_rows)

                    all_text += [r["Path"] + str(r["Value"]) for r in sr_rows]

                # ---------------------
                # US PROCESSING
                # ---------------------
                if modality == "US":
                    us_meta = extract_us(ds)
                    private_tags = extract_private_tags(ds)

                    all_text += list(us_meta.values()) + private_tags

                    results.append({
                        "StudyInstanceUID": study_uid,
                        "SeriesInstanceUID": series_uid,
                        "SOPInstanceUID": sop_uid,
                        "Path": "US_METADATA",
                        "Value": us_meta,
                        "Source": "US"
                    })

                # ---------------------
                # KEYWORD DETECTION
                # ---------------------
                hits = detect_keywords(all_text)

                if hits:
                    results.append({
                        "StudyInstanceUID": study_uid,
                        "SeriesInstanceUID": series_uid,
                        "SOPInstanceUID": sop_uid,
                        "Path": "KEYWORD_MATCH",
                        "Value": ",".join(hits),
                        "Source": "ANALYTICS"
                    })

            except Exception as e:
                continue

    # =============================
    # OUTPUT
    # =============================
    df = pd.DataFrame(results)

    print("\n========== FULL DICOM FORENSIC MAP ==========\n")
    print(df.head(50))

    df.to_csv("dicom_forensic_map.csv", index=False)

    print("\n✅ Saved: dicom_forensic_map.csv")
    print("📌 Total extracted rows:", len(df))


# =============================
# ENTRY POINT
# =============================
if __name__ == "__main__":
    run()
