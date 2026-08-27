import os

import matplotlib.pyplot as plt
import pandas as pd
import pydicom
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(layout="wide")
st.title("📡 IGHD DICOM Browser (DICOM-Native)")

# =========================================================
# SESSION STATE
# =========================================================
if "selected_image" not in st.session_state:
    st.session_state.selected_image = None

# =========================================================
# USER INPUT
# =========================================================
dicom_dir = st.sidebar.text_input(
    "📁 DICOM Folder",
    r"C:\Users\hassan.naqvi\OneDrive - Aga Khan University\Mahnaz Ambareen's files - QC Hassan bhai"
)

scan_button = st.sidebar.button("🔍 Scan DICOM Folder")


# =========================================================
# DICOM SCANNER
# =========================================================
@st.cache_data(show_spinner=True)
def scan_dicom_folder(folder):
    images = []
    sr_files = []

    for root, _, files in os.walk(folder):

        for f in files:

            if not f.lower().endswith(".dcm"):
                continue

            path = os.path.join(root, f)

            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True)

                modality = str(getattr(ds, "Modality", "NA"))

                record = {
                    "FilePath": path,
                    "FileName": f,
                    "PatientID": str(getattr(ds, "PatientID", "NA")),
                    "StudyDate": str(getattr(ds, "StudyDate", "NA")),
                    "StudyInstanceUID": str(getattr(ds, "StudyInstanceUID", "NA")),
                    "SeriesInstanceUID": str(getattr(ds, "SeriesInstanceUID", "NA")),
                    "SOPInstanceUID": str(getattr(ds, "SOPInstanceUID", "NA")),
                    "InstanceNumber": getattr(ds, "InstanceNumber", -1),
                    "Modality": modality
                }

                if modality == "US":
                    images.append(record)

                elif modality == "SR":
                    sr_files.append(record)

            except Exception:
                pass

    return pd.DataFrame(images), pd.DataFrame(sr_files)


# =========================================================
# SR PARSER
# =========================================================
def extract_sr_measurements(ds):
    rows = []

    def walk_sequence(seq):

        for item in seq:

            try:
                concept_name = ""

                if "ConceptNameCodeSequence" in item:
                    c = item.ConceptNameCodeSequence[0]
                    concept_name = str(getattr(c, "CodeMeaning", ""))

                value = None
                unit = None

                # NUM measurements
                if "MeasuredValueSequence" in item:

                    mv = item.MeasuredValueSequence[0]

                    value = getattr(mv, "NumericValue", None)

                    if "MeasurementUnitsCodeSequence" in mv:
                        unit_obj = mv.MeasurementUnitsCodeSequence[0]
                        unit = getattr(unit_obj, "CodeMeaning", "")

                    rows.append({
                        "Measurement": concept_name,
                        "Value": value,
                        "Unit": unit
                    })

                # recurse deeper
                if "ContentSequence" in item:
                    walk_sequence(item.ContentSequence)

            except Exception:
                pass

    if "ContentSequence" in ds:
        walk_sequence(ds.ContentSequence)

    return pd.DataFrame(rows)


# =========================================================
# LOAD DATA
# =========================================================
if scan_button:
    with st.spinner("Scanning DICOM folder..."):
        df_images, df_sr = scan_dicom_folder(dicom_dir)

    st.session_state["df_images"] = df_images
    st.session_state["df_sr"] = df_sr

# =========================================================
# CHECK DATA
# =========================================================
if "df_images" not in st.session_state:
    st.info("Select DICOM folder and click Scan")
    st.stop()

df_images = st.session_state["df_images"]
df_sr = st.session_state["df_sr"]

# =========================================================
# PATIENT SELECTION
# =========================================================
top1, top2, top3 = st.columns([1, 1, 1])

with top1:
    patient_id = st.selectbox(
        "👤 Patient",
        sorted(df_images["PatientID"].unique())
    )

patient_df = df_images[
    df_images["PatientID"] == patient_id
    ]

# =========================================================
# STUDY SELECTION
# =========================================================
study_map = patient_df[
    ["StudyDate", "StudyInstanceUID"]
].drop_duplicates()

with top2:
    study_date = st.selectbox(
        "📅 Study Date",
        sorted(study_map["StudyDate"].unique())
    )

study_uid = study_map[
    study_map["StudyDate"] == study_date
    ]["StudyInstanceUID"].iloc[0]

study_df = patient_df[
    patient_df["StudyInstanceUID"] == study_uid
    ].sort_values("InstanceNumber")


# =========================================================
# FILE MAP
# =========================================================
def build_file_map(df):
    mapping = {}

    for _, r in df.iterrows():
        label = (
            f"{r['InstanceNumber']} | "
            f"{r['FileName']}"
        )

        mapping[label] = r["FilePath"]

    return mapping


file_map = build_file_map(study_df)
file_items = list(file_map.items())

# =========================================================
# DEFAULT IMAGE
# =========================================================
if st.session_state.selected_image is None and file_items:
    st.session_state.selected_image = file_items[0][1]

# =========================================================
# SIDEBAR THUMBNAILS
# =========================================================
st.sidebar.markdown("## 🖼️ Thumbnails")


@st.cache_data(show_spinner=False)
def load_pixel_array(path):
    try:
        ds = pydicom.dcmread(path)
        return ds.pixel_array

    except Exception:
        return None


MAX_THUMBS = 24

for i in range(0, min(len(file_items), MAX_THUMBS), 2):

    c1, c2 = st.sidebar.columns(2)

    # LEFT
    label1, path1 = file_items[i]

    with c1:

        img1 = load_pixel_array(path1)

        if img1 is not None:
            st.image(img1, use_container_width=True)

        if st.button("Select", key=f"btn_{i}"):
            st.session_state.selected_image = path1
            st.rerun()

    # RIGHT
    if i + 1 < len(file_items):

        label2, path2 = file_items[i + 1]

        with c2:

            img2 = load_pixel_array(path2)

            if img2 is not None:
                st.image(img2, use_container_width=True)

            if st.button("Select", key=f"btn_{i + 1}"):
                st.session_state.selected_image = path2
                st.rerun()

# =========================================================
# LOAD SELECTED IMAGE
# =========================================================
image_path = st.session_state.selected_image

ds = pydicom.dcmread(image_path)

image_study_uid = str(getattr(ds, "StudyInstanceUID", "NA"))
image_series_uid = str(getattr(ds, "SeriesInstanceUID", "NA"))
image_sop_uid = str(getattr(ds, "SOPInstanceUID", "NA"))

# =========================================================
# FIND MATCHING SR FILES
# =========================================================
matching_sr = df_sr[
    df_sr["StudyInstanceUID"] == image_study_uid
    ]

# =========================================================
# PARSE SR
# =========================================================
study_sr = pd.DataFrame()

if not matching_sr.empty:

    sr_path = matching_sr.iloc[0]["FilePath"]

    try:

        sr_ds = pydicom.dcmread(sr_path)

        study_sr = extract_sr_measurements(sr_ds)

    except Exception as e:

        st.warning(f"SR parse error: {e}")

# =========================================================
# MAIN LAYOUT
# =========================================================
left, right = st.columns([5, 2])

# =========================================================
# IMAGE PANEL
# =========================================================
with left:
    st.subheader("🖼️ Ultrasound Image")

    if hasattr(ds, "pixel_array"):
        img = ds.pixel_array

        fig, ax = plt.subplots(figsize=(9, 9))

        ax.imshow(img, cmap="gray")
        ax.axis("off")

        st.pyplot(fig, use_container_width=True)

# =========================================================
# SR PANEL
# =========================================================
with right:
    st.subheader("Structured Report")

    if not study_sr.empty:

        st.markdown("### Key Metrics")
        # st.write(image_stins_uid + " | " + study_sr["StudyInstanceUID"].iloc[0])
        # st.write(image_seins_uid + " | " + study_sr["SeriesInstanceUID"].iloc[0])
        # st.write(image_sop_uid + " | " + study_sr["SOPInstanceUID"].iloc[0])
        # st.write(
        #     "StudyInstanceUID: " + image_stins_uid + " | SeriesInstanceUID: " + image_seins_uid + " | SOPInstanceUID: " + image_sop_uid)
        # st.write(f"CRL: {image_CRL} | {study_sr[study_sr['Measurement'] == 'Crown Rump Length']['Value'].iloc[0]}")
        # st.write(image_NT + " | " + study_sr["Nuchal Translucency"].iloc[0])
        # st.write(image_FHR + " | " + study_sr["Fetal Heart Rate"].iloc[0])

        for m in ["Crown Rump Length", "Nuchal Translucency", "Fetal Heart Rate"]:

            row = study_sr[study_sr["Measurement"] == m]
            if not row.empty:
                st.metric(m, f"{row.iloc[0]['Value']} {row.iloc[0]['Unit']}")
                # if m == "Crown Rump Length":
                #     st.write(f"CRL: {row.iloc[0]['Value']} {row.iloc[0]['Unit']}")
                # if m == "Nuchal Translucency":
                #     st.write(f"NT: {row.iloc[0]['Value']} {row.iloc[0]['Unit']}")
                # if m == "Fetal Heart Rate":
                #     st.write(f"FHR: {row.iloc[0]['Value']} {row.iloc[0]['Unit']}")
            else:
                st.metric(m, "NA")

        ##############################################################
        st.markdown("### All Measurements")

        gb = GridOptionsBuilder.from_dataframe(study_sr)

        gb.configure_default_column(
            filter=True,
            sortable=True,
            resizable=True
        )

        AgGrid(
            study_sr,
            gridOptions=gb.build(),
            use_container_width=True,
            height=350
        )

    else:

        st.info("No SR measurements found")

# =========================================================
# DEBUG PANEL
# =========================================================
with st.expander("🔍 Debug Info"):
    st.write("Selected Image")
    st.code(image_path)

    st.write("Study UID")
    st.code(image_study_uid)

    st.write("Series UID")
    st.code(image_series_uid)

    st.write("SOP UID")
    st.code(image_sop_uid)

    st.write("Matching SR Files")
    st.dataframe(matching_sr)
