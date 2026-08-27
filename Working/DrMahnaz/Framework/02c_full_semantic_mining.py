import os

import pandas as pd
import pydicom

from config import dicom_dir

results = []

KEYWORDS = [
    "crl", "crown", "rump",
    "nt", "nuchal",
    "fhr", "heart rate", "bpm",
    "doppler",
]


def extract_sr(ds):
    texts = []

    if hasattr(ds, "ContentSequence"):
        for item in ds.ContentSequence:
            try:
                if hasattr(item, "ConceptNameCodeSequence"):
                    texts.append(item.ConceptNameCodeSequence[0].CodeMeaning)
            except:
                pass

            if hasattr(item, "TextValue"):
                texts.append(str(item.TextValue))

            if hasattr(item, "MeasuredValueSequence"):
                try:
                    mv = item.MeasuredValueSequence[0]
                    if "NumericValue" in mv:
                        texts.append(str(mv.get("NumericValue")))
                except:
                    pass

    return texts


def extract_us(ds):
    return [
        str(ds.get("ViewName", "")),
        str(ds.get("SeriesDescription", "")),
        str(ds.get("StudyDescription", "")),
        str(ds.get("ProtocolName", "")),
        str(ds.get("ImageType", "")),
    ]


def find_keywords(text_list):
    joined = " ".join([t.lower() for t in text_list if t])
    hits = [k for k in KEYWORDS if k in joined]
    return hits


def run():
    for root, _, files in os.walk(dicom_dir):
        for f in files:
            path = os.path.join(root, f)

            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True)

                modality = ds.get("Modality", "NA")

                sr_text = []
                us_text = []

                if modality == "SR":
                    sr_text = extract_sr(ds)

                if modality == "US":
                    us_text = extract_us(ds)

                all_text = sr_text + us_text
                hits = find_keywords(all_text)

                if hits:
                    results.append({
                        "SOPInstanceUID": ds.get("SOPInstanceUID", "NA"),
                        "StudyInstanceUID": ds.get("StudyInstanceUID", "NA"),
                        "SeriesInstanceUID": ds.get("SeriesInstanceUID", "NA"),
                        "Modality": modality,
                        "Hits": ",".join(hits),
                        "Text": " | ".join(all_text)
                    })

            except:
                continue

    df = pd.DataFrame(results)

    print("\n========== CRL/NT/FHR SIGNAL MAP ==========\n")
    print(df.head(30))

    df.to_csv("semantic_crl_nt_fhr_map.csv", index=False)
    print("\nSaved: semantic_crl_nt_fhr_map.csv")


if __name__ == "__main__":
    run()
