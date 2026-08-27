import os

import pandas as pd
import pydicom
import streamlit as st

# -----------------------------
# PAGE CONFIG
# -----------------------------
st.set_page_config(page_title="Live DICOM Browser", layout="wide")
st.title("🧠 Live DICOM Forensic Explorer (No CSV)")


# -----------------------------
# SIMPLE CLASSIFIER (from your pipeline)
# -----------------------------
def classify(text):
    if not text:
        return "UNKNOWN", ""

    t = str(text).lower()
    evidence = []

    if "nt" in t or "nuchal" in t:
        evidence.append("NT")
    if "crown" in t or "rump" in t:
        evidence.append("CRL")
    if "heart rate" in t:
        evidence.append("FHR")
    if "doppler" in t:
        evidence.append("DOPPLER")
    if "biometry" in t:
        evidence.append("BIOMETRY")
    if "edd" in t or "gestation" in t:
        evidence.append("GA_EDD")

    if len(evidence) == 0:
        return "UNKNOWN", t

    return ",".join(sorted(set(evidence))), t


# -----------------------------
# DICOM LOADER
# -----------------------------
def load_dicom_folder(folder):
    records = []

    for root, _, files in os.walk(folder):
        for f in files:
            path = os.path.join(root, f)

            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True)

                study = getattr(ds, "StudyInstanceUID", None)
                series = getattr(ds, "SeriesInstanceUID", None)
                sop = getattr(ds, "SOPInstanceUID", None)

                # SR detection
                is_sr = getattr(ds, "Modality", "") == "SR"

                text = ""

                if is_sr:
                    # try structured report content
                    try:
                        text = str(ds)
                    except:
                        text = ""

                scan_type, evidence = classify(text)

                records.append({
                    "Path": path,
                    "StudyInstanceUID": study,
                    "SeriesInstanceUID": series,
                    "SOPInstanceUID": sop,
                    "IsSR": is_sr,
                    "ScanType": scan_type,
                    "Evidence": evidence
                })

            except Exception:
                continue

    return pd.DataFrame(records)


# -----------------------------
# UI: FOLDER INPUT
# -----------------------------
folder = st.text_input("📁 Enter DICOM Folder Path")

if folder and os.path.exists(folder):

    with st.spinner("🔍 Scanning DICOM files..."):
        df = load_dicom_folder(folder)

    st.success(f"Loaded {len(df)} DICOM objects")

    # -----------------------------
    # FILTERS
    # -----------------------------
    st.sidebar.header("Filters")

    scan_types = sorted(df["ScanType"].dropna().unique())
    selected = st.sidebar.multiselect("Scan Type", scan_types, default=scan_types)

    df = df[df["ScanType"].isin(selected)]

    # -----------------------------
    # MAIN TABLE
    # -----------------------------
    st.subheader("📊 Live DICOM Index")

    st.dataframe(
        df[[
            "ScanType",
            "IsSR",
            "StudyInstanceUID",
            "SeriesInstanceUID",
            "SOPInstanceUID",
            "Path"
        ]],
        use_container_width=True
    )

    # -----------------------------
    # DETAIL VIEW
    # -----------------------------
    st.subheader("🔬 Scan Inspector")

    selected_sop = st.selectbox("Select SOPInstanceUID", df["SOPInstanceUID"].dropna().unique())

    row = df[df["SOPInstanceUID"] == selected_sop]

    if not row.empty:
        r = row.iloc[0]

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 🧬 Metadata")
            st.write("Study:", r["StudyInstanceUID"])
            st.write("Series:", r["SeriesInstanceUID"])
            st.write("SR:", r["IsSR"])

        with col2:
            st.markdown("### 🧠 Classification")
            st.write("ScanType:", r["ScanType"])

            if r["ScanType"] == "UNKNOWN":
                st.warning("UNKNOWN scan detected")
                st.code(r["Evidence"])
            else:
                st.success("Classified scan")
                st.code(r["Evidence"])

    # -----------------------------
    # STATS
    # -----------------------------
    st.subheader("📈 Scan Distribution")
    st.bar_chart(df["ScanType"].value_counts())

else:
    st.info("Please enter a valid DICOM folder path")
