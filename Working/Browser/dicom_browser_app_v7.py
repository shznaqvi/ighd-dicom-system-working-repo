# dicom_browser_app_v4_form.py
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import imageio
import matplotlib.pyplot as plt
import pandas as pd
import pydicom
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder


# =========================================================
# PAGE CONFIG
# =========================================================
def optimize_ui_and_health_check():
    """Transforms the top header into a titled navigation bar, collapses spacing, and checks server health."""

    # =========================================================
    # 1. CONSOLIDATED LAYOUT & NAVIGATION BAR STYLING
    # =========================================================
    st.markdown(
        """
        <style>
        /* A. Turn the native header into a permanent, dark navigation bar */
        [data-testid="stHeader"], .stAppHeader {
            display: flex !important;
            background-color: #1E293B !important; /* Dark slate blue background */
            border-bottom: 2px solid #38BDF8;    /* Clean cyan bottom boundary line */
            height: 50px !important;
            justify-content: flex-start;
            align-items: center;
            padding-left: 1.5rem !important;
        }

        /* B. Inject your title text directly inside that top header frame */
        [data-testid="stHeader"]::before {
            content: "📡 IGHD DICOM Browser";
            color: #F8FAFC !important;           /* Bright crisp text color */
            font-size: 18px !important;
            font-weight: 600 !important;
            font-family: 'Source Sans Pro', sans-serif;
            white-space: nowrap;
        }

        /* C. Style the top right running indicators to contrast cleanly on dark blue */
        [data-testid="stToolbar"] {
            top: 5px !important;
        }
        [data-testid="stToolbar"] svg {
            fill: #F8FAFC !important;
        }

        /* D. Adjust content padding slightly so elements sit nicely below your new top bar
        [data-testid="stMainBlockContainer"], .block-container {
            padding-top: 1.5rem !important;
            margin-top: 0rem !important;
        } */
        [data-testid="stSidebarContent"] {
            padding-top: 0rem !important;
        }

        /* E. Secure layout alignment wrappers */
        [data-testid="stHorizontalBlock"] {
            align-items: flex-start;
        }

        /* F. Pin the image column frame so it stays anchored while data forms scroll */
        [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child {
            position: sticky;
            top: 4.5rem; /* Adjusted to sit comfortably below the 50px top navigation bar */
            align-self: flex-start;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="IGHD DICOM Browser", layout="wide")
st.set_page_config(layout="wide")
optimize_ui_and_health_check()  ### Apply the UI optimizations and health check immediately on page load

# st.title("📡 IGHD DICOM Browser")


# =========================================================
# SESSION STATE
# =========================================================
for key, default in [
    ("selected_image", None),
    ("cancel_upload", False),
    ("uploading", False),
    ("viability_forms", {}),
    ("playing", False),  # Track if video is playing
    ("frame_idx", 0),  # Current frame for cine loops
]:
    if key not in st.session_state:
        st.session_state[key] = default

VIABILITY_FILE = "viability_forms.json"


def load_viability_forms():
    if os.path.exists(VIABILITY_FILE):
        with open(VIABILITY_FILE) as f:
            st.session_state.viability_forms = json.load(f)


def save_viability_forms():
    with open(VIABILITY_FILE, "w") as f:
        json.dump(st.session_state.viability_forms, f, indent=2)


if not st.session_state.viability_forms:
    load_viability_forms()


# =========================================================
# UPLOAD
# =========================================================
def upload_folder_to_server(local_folder, server_root, warning_ph):
    if not local_folder or not server_root:
        warning_ph.error("Provide both local folder and server root.", icon="⚠️")
        return 0
    local_folder = Path(local_folder)
    if not local_folder.exists():
        warning_ph.error(f"Path does not exist: {local_folder}", icon="⚠️")
        return 0
    dicom_files = list(local_folder.rglob("*.dcm"))
    if not dicom_files:
        warning_ph.warning("No DICOM files found.")
        return 0
    total, copied, skipped = len(dicom_files), 0, 0
    start = time.time()
    progress = st.progress(0)
    status = st.empty()
    metrics = st.empty()
    for i, fp in enumerate(dicom_files):
        if st.session_state.cancel_upload:
            status.warning("⛔ Upload cancelled.")
            break
        try:
            rel = fp.relative_to(local_folder)
            target = Path(server_root) / rel
            if target.exists():
                skipped += 1
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fp, target)
                copied += 1
        except Exception as e:
            st.warning(f"Failed to copy {fp.name}: {e}")
        elapsed = time.time() - start
        avg = elapsed / (i + 1)
        remaining = avg * (total - i - 1)
        progress.progress((i + 1) / total)
        status.write(f"Processing: {i + 1}/{total} | {fp.name}")
        metrics.markdown(
            f"**⏱ Elapsed:** {elapsed:.1f}s &nbsp;|&nbsp; "
            f"**⏳ ETA:** {remaining:.1f}s &nbsp;|&nbsp; "
            f"**📦 Copied:** {copied}/{total} &nbsp;|&nbsp; "
            f"**🚫 Skipped:** {skipped} &nbsp;|&nbsp; "
            f"**⚡ Speed:** {avg:.2f}s/file"
        )
    return copied


# =========================================================
# DICOM SCANNER
# =========================================================
@st.cache_data(show_spinner=True, ttl=18 * 3600)
def scan_dicom_folder(folder):
    # st.write(f"Scanning DICOM folder: {folder}")
    images, sr_files = [], []
    for root, _, files in os.walk(folder):
        # st.write(f"Scanning folder: {root} | {len(files)} files")
        # print(f"Scanning folder: {root} | {len(files)} files")
        for f in files:
            if not f.lower().endswith(".dcm"):
                st.write(f"Skipping non-DICOM file: {f}")
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
                    "InstanceNumber": int(getattr(ds, "InstanceNumber", -1)),
                    "Modality": modality,
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

    def walk(seq, parent_ref_sop=""):
        for item in seq:
            try:
                # Inherit parent's ref_sop, override if this item has its own
                ref_sop = parent_ref_sop
                if "ReferencedSOPSequence" in item:
                    ref_sop = str(getattr(
                        item.ReferencedSOPSequence[0],
                        "ReferencedSOPInstanceUID", ""
                    ))

                name = ""
                if "ConceptNameCodeSequence" in item:
                    name = str(getattr(item.ConceptNameCodeSequence[0], "CodeMeaning", ""))

                if "MeasuredValueSequence" in item:
                    mv = item.MeasuredValueSequence[0]
                    value = getattr(mv, "NumericValue", None)
                    unit = ""
                    if "MeasurementUnitsCodeSequence" in mv:
                        unit = str(getattr(mv.MeasurementUnitsCodeSequence[0], "CodeMeaning", ""))
                    rows.append({
                        "Measurement": name,
                        "Value": value,
                        "Unit": unit,
                        "ReferencedSOPInstanceUID": ref_sop,  # inherited or own
                    })

                if "ContentSequence" in item:
                    walk(item.ContentSequence, ref_sop)  # pass ref_sop to children

            except Exception:
                pass

    if "ContentSequence" in ds:
        walk(ds.ContentSequence)
    return pd.DataFrame(rows)


# =========================================================
# SR MATCHER — direct SOP-reference → study fallback
# =========================================================
@st.cache_data(show_spinner=False)
def get_sr_referenced_uids(sr_path):
    try:
        ds = pydicom.dcmread(sr_path, stop_before_pixels=True)
        return {str(e.value) for e in ds.iterall() if e.keyword == "ReferencedSOPInstanceUID"}
    except Exception:
        return set()


def find_matching_sr(df_sr, sop_uid, study_uid):
    study_srs = df_sr[df_sr["StudyInstanceUID"] == study_uid]
    direct = [r for _, r in study_srs.iterrows()
              if sop_uid in get_sr_referenced_uids(r["FilePath"])]
    return pd.DataFrame(direct) if direct else study_srs


# =========================================================
# PIXEL LOADER
# =========================================================
@st.cache_data(show_spinner=False)
def load_pixel_array(path):
    try:
        return pydicom.dcmread(path).pixel_array
    except Exception:
        return None


# =========================================================
# QC CRITERION BLOCK  — renders per image using SOP-scoped keys
# =========================================================
CRITERION_OPTIONS = ["Acceptable", "Unacceptable", "Not Applicable"]

CRL_LABELS = [
    "Mid-sagittal section",
    "Neutral Position",
    "Horizontal Position",
    "Crown and Rump clearly visible",
    "Correct Caliper Placement",
    "Good Magnification"
]

NT_LABELS = [
    "Magnification",
    "True mid-sagittal section",
    "Neutral fetal position",
    "Caliper ''ON-to-ON''",
    "Maximum Lucency",
    "Thin Nuchal Membrane"
]

# --- GROWTH SCAN LABELS ---
GROWTH_CEPHALIC_LABELS = [
    "Crit-1: Symmetrical plane",
    "Crit-2: Thalami visible",
    "Crit-3: Cavum septum pellucidi visible",
    "Crit-4: Cerebellum not visible",
    "Crit-5: Head occupying 30% of image",
    "Crit-6: Calipers/ellipse placed correctly"
]
GROWTH_ABDOMINAL_LABELS = [
    "Crit-1: Symmetrical plane",
    "Crit-2: Stomach bubble visible",
    "Crit-3: Portal sinus visible",
    "Crit-4: Kidneys not visible",
    "Crit-5: Abdomen occupying 30% of image",
    "Crit-6: Calipers/ellipse placed correctly"
]
GROWTH_FEMORAL_LABELS = [
    "Crit-1: Both ends of the bone clearly visible",
    "Crit-2: Angle <45 degrees",
    "Crit-3: Femur occupying at least 30% of image",
    "Crit-4: Calipers placed correctly"
]

# --- ANOMALY SCAN LABELS ---
ANOMALY_HEAD_TV_LABELS = [
    "Crit-1: Symmetrical place with midline fax",
    "Crit-2: Cavum septum visible",
    "Crit-3: Cerebellum not visible",
    "Crit-4: Ventricles visible at atrium",
    "Crit-5: Magnification 30% of screen",
    "Crit-6: Head circumference calipers outer parts of skul",
    "Crit-7: Calipers measuring lateral ventricles at level of atrium"
]
ANOMALY_HEAD_TC_LABELS = [
    "Crit-1: Symmetrical place with midline fax",
    "Crit-2: Cavum septum visible",
    "Crit-3: Cerebellum visible",
    "Crit-4: Cisterna magna visible",
    "Crit-5: Magnification 30% of screen",
    "Crit-6: Calipers placed on outer level of cerebellar hemispheres",
    "Crit-7: Calipers placed on outer limits of cisterna magna"
]
ANOMALY_ABDOMEN_LABELS = [
    "Crit-1: Stomach bubble visible",
    "Crit-2: Umbilical vein 1/3rd of way along anteroposterior diameter at portal sinus level",
    "Crit-3: Circular plane",
    "Crit-4: Kidneys not visible",
    "Crit-5: Magnification at least 30% of screen",
    "Crit-6: Calipers placed on outer parts of abdomen"
]
ANOMALY_FEMUR_LABELS = [
    "Crit-1: Both ends of ossified diaphysis clear",
    "Crit-2: Angle of insonation 45-90 degree",
    "Crit-3: Magnification at least 30% of screen",
    "Crit-4: Calipers placed on clear ends of diaphysis"
]
ANOMALY_SPINE_LABELS = [
    "Crit-1: Magnification up to 30% of screen",
    "Crit-2: Continuity intact and posterior skin edge visible",
    "Crit-3: Alignment of vertebrae visible",
    "Crit-4: Amniotic fluid visible beyond skin",
    "Crit-5: Lower sacrum visible",
    "Crit-6: Middle thoracic/lumbar visible",
    "Crit-7: Upper cervical/thoracic visible"
]
ANOMALY_FACE_LABELS = [
    "Crit-1: Upper lip visible",
    "Crit-2: Both nostrils visible",
    "Crit-3: Both lip angles visible",
    "Crit-4: Adequate magnification"
]

# --- SCAN CONFIGURATION DICTIONARY ---
SCAN_CONFIGS = {
    "Viability Scan": {
        "crl": {"title": "Crown Rump Length (CRL)", "labels": CRL_LABELS},
        "nt": {"title": "Nuchal Translucency (NT)", "labels": NT_LABELS},
    },
    "Growth Scan": {
        "growth_ceph": {"title": "Cephalic Plane", "labels": GROWTH_CEPHALIC_LABELS},
        "growth_abd": {"title": "Abdominal Plane", "labels": GROWTH_ABDOMINAL_LABELS},
        "growth_femur": {"title": "Femoral Plane", "labels": GROWTH_FEMORAL_LABELS},
    },
    "Anomaly Scan": {
        "anom_head_tv": {"title": "Head Transventricular", "labels": ANOMALY_HEAD_TV_LABELS},
        "anom_head_tc": {"title": "Head trans cerebellar", "labels": ANOMALY_HEAD_TC_LABELS},
        "anom_abd": {"title": "Abdomen", "labels": ANOMALY_ABDOMEN_LABELS},
        "anom_femur": {"title": "Femur", "labels": ANOMALY_FEMUR_LABELS},
        "anom_spine": {"title": "Spine", "labels": ANOMALY_SPINE_LABELS},
        "anom_face": {"title": "Coronal face", "labels": ANOMALY_FACE_LABELS},
    }
}


@st.fragment
def criterion_block(title, block_key, labels, existing=None):
    if existing is None:
        existing = {}

    existing_crits = existing.get("criteria", {})

    with st.container(border=True):
        st.markdown(f"### {title}")

        # Default to None if not previously saved
        overall_saved = existing.get("overall", None)

        overall = st.segmented_control(
            "**Overall Status**",
            CRITERION_OPTIONS,
            default=overall_saved,
            key=f"{block_key}_overall",
            selection_mode="single",
        )

        crits = {}
        cols = st.columns(2)

        for i, label_text in enumerate(labels):
            crit_id = f"crit_{i + 1}"  # Evaluates to "crit_1", "crit_2", etc.

            # Fetch previously saved data
            saved = existing_crits.get(crit_id, None)

            with cols[i % 2]:
                # Calculate the correct index
                idx = CRITERION_OPTIONS.index(saved) if saved in CRITERION_OPTIONS else None

                # 1. FIXED: Use crit_id to keep saving/loading aligned
                # 2. FIXED: Pass `index=idx` instead of `index=0`
                crits[crit_id] = st.radio(
                    f"**Crit-{i + 1}:** {label_text}",
                    CRITERION_OPTIONS,
                    index=idx,
                    key=f"{block_key}_crit_{i}",
                    horizontal=False,
                )

    return {"overall": overall, "criteria": crits}


# =========================================================
# SIDEBAR — folder settings & upload
# =========================================================
dicom_dir = r"D:\IGHD_DICOM_VIEWER\raw_data"

# with st.sidebar.expander("📁 DICOM Folder Settings", expanded=True):
#     st.markdown("## 📤 Upload Folder to Server")
#     local_folder      = st.text_input("Local DICOM Folder Path")
#     warning_placeholder = st.empty()
#
#     if st.session_state.uploading:
#         if st.button("🛑 Cancel Upload", use_container_width=True):
#             st.session_state.cancel_upload = True
#     if st.button("🚀 Upload Folder"):
#         st.session_state.cancel_upload = False
#         st.session_state.uploading     = True
#         count = upload_folder_to_server(local_folder, dicom_dir, warning_placeholder)
#         st.session_state.uploading     = False
#         st.session_state.cancel_upload = False
#         if count > 0:
#             st.success(f"✅ Uploaded {count} file(s).")
#         elif local_folder:
#             st.info("No new files (all already exist or folder empty).")
with st.sidebar:
    if st.button("🔄 Force Re-scan DICOM Folder"):
        with st.spinner("Scanning…"):
            df_images, df_sr = scan_dicom_folder(dicom_dir)
            st.session_state["df_images"] = df_images
            st.session_state["df_sr"] = df_sr
        st.rerun()  # Instantly refresh the page UI with new data

# =========================================================
# LOAD / SCAN (Cached & Automated)
# =========================================================

# 1. Auto-scan on first load if session state is empty
if "df_images" not in st.session_state or "df_sr" not in st.session_state:
    with st.spinner("🔄 Automatically scanning DICOM Folder... Please wait."):
        df_images, df_sr = scan_dicom_folder(dicom_dir)
        st.session_state["df_images"] = df_images
        st.session_state["df_sr"] = df_sr
        st.session_state["known_files"] = set(df_images["FilePath"])
        st.session_state["last_scan_time"] = time.time()

# 2. Provide a manual refresh button if the user *wants* to re-scan
if st.button("🔄 Force Re-scan DICOM Folder"):
    with st.spinner("Scanning…"):
        df_images, df_sr = scan_dicom_folder(dicom_dir)
        st.session_state["df_images"] = df_images
        st.session_state["df_sr"] = df_sr
    st.rerun()  # Instantly refresh the page UI with new data

# 3. Pull data from session state safely
df_images = st.session_state["df_images"]
df_sr = st.session_state["df_sr"]

# 4. Handle empty states gracefully
if df_images.empty:
    st.warning("No US images found in the specified directory.")
    st.stop()

# =========================================================
# SILENT BACKGROUND CHECK
# =========================================================
now = time.time()
SCAN_INTERVAL = 90  # seconds

if now - st.session_state.get("last_scan_time", 0) > SCAN_INTERVAL:

    new_df_images, new_df_sr = scan_dicom_folder(dicom_dir)

    current_files = set(new_df_images["FilePath"])
    known_files = st.session_state.get("known_files", set())

    new_files = current_files - known_files

    # ONLY ACT IF CHANGE DETECTED
    if new_files:
        # update cache silently
        st.session_state["df_images"] = new_df_images
        st.session_state["df_sr"] = new_df_sr
        st.session_state["known_files"] = current_files

        # ONLY THEN show alert
        st.toast(f"🆕 {len(new_files)} new DICOM file(s) detected!")

    # always update timestamp (silent)
    st.session_state["last_scan_time"] = now

# =========================================================
# PATIENT / STUDY SELECTION
# =========================================================


# --- 1. INITIALIZE WIDGET STATE ONCE FROM URL (CRUCIAL PRE-RENDERING STEP) ---
region_options = ["All Regions", "Matiari", "TMK", "Mithi"]
url_patient_id = st.query_params.get("PatientID", "").rstrip("__")

# Determine default region index based on URL parameters before rendering selectboxes
if "selected_region_index" not in st.session_state:
    if url_patient_id and url_patient_id[0].isdigit():
        extracted_index = int(url_patient_id[0])
        if 0 <= extracted_index < len(region_options):
            st.session_state.selected_region_index = extracted_index
        else:
            st.session_state.selected_region_index = 0
    else:
        st.session_state.selected_region_index = 0

# --- 2. LAYOUT RENDERING ---
region_col, top1, top2 = st.columns([1, 1, 1])

with region_col:
    # Render using the managed session state index
    region = st.selectbox(
        "📍 Region",
        options=region_options,
        index=st.session_state.selected_region_index,
        key="region_selector"  # Give it a key to maintain state stability
    )

# Filter df_images by selected region
# Note: Using region_options.index(region) ensures we match the active UI choice
if not url_patient_id:
    if region != "All Regions":
        current_region_idx = region_options.index(region)
        df_images = df_images[df_images["PatientID"].str.startswith(str(current_region_idx))]

# Calculate valid options based on the filtered dataframe
patient_options = sorted(df_images["PatientID"].unique())

with top1:
    default_patient_index = 0

    if url_patient_id:
        if url_patient_id in patient_options:
            default_patient_index = patient_options.index(url_patient_id)
        else:
            st.warning(f"URL PatientID '{url_patient_id}' not found. Defaulting to first patient.")

    patient_id = st.selectbox(
        "👤 Select Patient ID",
        options=patient_options,
        index=default_patient_index
    )

patient_df = df_images[df_images["PatientID"] == patient_id]
study_map = patient_df[["StudyDate", "StudyInstanceUID"]].drop_duplicates()

with top2:
    default_studydate_index = 0
    studydate_options = sorted(study_map["StudyDate"].unique())
    url_study_date = st.query_params.get("StudyDate", "")

    if url_study_date:
        if url_study_date in studydate_options:
            default_studydate_index = studydate_options.index(url_study_date)
        else:
            st.warning(f"URL StudyDate '{url_study_date}' not found. Defaulting to first study date.")

    study_date = st.selectbox(
        "📅 Study Date",
        options=studydate_options,
        index=default_studydate_index
    )

if study_date:
    study_uid = study_map[study_map["StudyDate"] == study_date]["StudyInstanceUID"].iloc[0]
    study_df = patient_df[patient_df["StudyInstanceUID"] == study_uid].sort_values("InstanceNumber")
else:
    if patient_df.empty:
        st.warning("No patient records found for this region.")
    elif study_map.empty:
        st.warning("No study dates found for this patient.")

    st.stop()


# default_index = 0
# options = sorted(study_map["StudyDate"].unique())
# url_study_date = st.query_params.get("StudyDate")
# if url_study_date:
#     if url_study_date in options:
#         default_index = options.index(url_study_date)
#     study_date = st.query_params.get("StudyDate", "")[0:8]
#     # st.write(f"study_date: {study_date}")
#
#     study_uid = study_map[study_map["StudyDate"] == study_date]["StudyDate"].iloc[0]
# =========================================================
# Testing


# =========================================================
# FILE MAP
# =========================================================
def build_file_map(df):
    return {
        f"{r['InstanceNumber']} | {r['FileName']}": r["FilePath"]
        for _, r in df.iterrows()
    }


file_map = build_file_map(study_df)
file_items = list(file_map.items())

if not file_items:
    st.warning("No image files for this study.")
    st.stop()

if st.session_state.selected_image is None:
    st.session_state.selected_image = file_items[0][1]

from PIL import ImageDraw


def add_play_overlay(np_array):
    """Adds a centered play button overlay to a numpy image array."""
    # Convert numpy array to PIL Image
    img = Image.fromarray(np_array).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    w, h = img.size
    cx, cy = w // 2, h // 2
    r = min(w, h) // 4  # Radius of the play button circle

    # Draw a semi-transparent white circle
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 200), width=4)

    # Draw the triangle (play symbol)
    triangle = [
        (cx - r // 3, cy - r // 2),
        (cx - r // 3, cy + r // 2),
        (cx + r // 2, cy)
    ]
    draw.polygon(triangle, fill=(255, 255, 255, 220))

    # Merge and return as RGB for st.image
    return Image.alpha_composite(img, overlay).convert("RGB")


# =========================================================
# LOAD SELECTED IMAGE
# =========================================================
image_path = st.session_state.selected_image
ds = pydicom.dcmread(image_path)
filename = os.path.basename(image_path)

image_study_uid = str(getattr(ds, "StudyInstanceUID", "NA"))
image_series_uid = str(getattr(ds, "SeriesInstanceUID", "NA"))
image_sop_uid = str(getattr(ds, "SOPInstanceUID", "NA"))

# =========================================================
# MATCH + PARSE SR
# =========================================================
matching_sr = find_matching_sr(df_sr, image_sop_uid, image_study_uid)
study_sr = pd.DataFrame()
image_sr = pd.DataFrame()

if not matching_sr.empty:
    try:
        sr_ds = pydicom.dcmread(matching_sr.iloc[0]["FilePath"])
        study_sr = extract_sr_measurements(sr_ds)  # all measurements in SR

        # Filter to only measurements linked to the selected image.
        # Rows with no ReferencedSOPInstanceUID ("") included as fallback
        # for vendors that don't populate the tag.
        image_sr = study_sr[
            (study_sr["ReferencedSOPInstanceUID"] == image_sop_uid) |
            (study_sr["ReferencedSOPInstanceUID"] == "")
            ]
    except Exception as e:
        st.warning(f"SR parse error: {e}")


@st.cache_data(show_spinner=False)
def convert_to_mp4(pixel_array, fps=20):
    """Converts a multi-frame DICOM pixel array to an MP4 buffer with macro-block fix."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmpfile:
        # Setting macro_block_size to None prevents the resizing warning
        imageio.mimwrite(
            tmpfile.name,
            pixel_array,
            fps=fps,
            format='FFMPEG',
            codec='libx264',
            macro_block_size=None  # <--- The fix
        )
        with open(tmpfile.name, "rb") as f:
            video_bytes = f.read()
    os.unlink(tmpfile.name)
    return video_bytes


import io
from PIL import Image


@st.fragment
def video_player_component(pixel_data, num_frames):
    # 1. Setup the Persistent Container
    # Using a static key in st.image is the "secret sauce" to stop the blink

    if st.session_state.frame_idx >= num_frames:
        st.session_state.frame_idx = 0

    # ─── OPTIMIZED RENDERING ─────────────────────────────────
    # Convert numpy to low-weight JPEG bytes for faster transit
    current_frame = pixel_data[st.session_state.frame_idx]

    # Normalize if needed (uint8)
    if current_frame.dtype != 'uint8':
        # Simple normalization for display speed
        norm_frame = ((current_frame - current_frame.min()) / (current_frame.max() - current_frame.min()) * 255).astype(
            'uint8')
    else:
        norm_frame = current_frame

    img_pil = Image.fromarray(norm_frame)
    buf = io.BytesIO()
    img_pil.save(buf, format="JPEG", quality=85)  # Quality 85 is usually plenty for QC

    # Render with a STATIC KEY to prevent the component "blink"
    st.image(
        buf.getvalue(),
        use_container_width=True,
        key="cine_frame_viewer",  # <--- CRITICAL: Keeps the image placeholder stable
        caption=f"Frame {st.session_state.frame_idx + 1} / {num_frames}"
    )

    # ─── PLAYER CONTROLS ─────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("⏮ Previous", use_container_width=True):
            st.session_state.playing = False
            st.session_state.frame_idx = (st.session_state.frame_idx - 1) % num_frames
            st.rerun(scope="fragment")

    with c2:
        label = "⏸ Pause" if st.session_state.playing else "▶ Play"
        if st.button(label, use_container_width=True):
            st.session_state.playing = not st.session_state.playing
            st.rerun(scope="fragment")

    with c3:
        if st.button("Next ⏭", use_container_width=True):
            st.session_state.playing = False
            st.session_state.frame_idx = (st.session_state.frame_idx + 1) % num_frames
            st.rerun(scope="fragment")

    # ─── ANIMATION LOOP ──────────────────────────────────────
    if st.session_state.playing:
        st.session_state.frame_idx = (st.session_state.frame_idx + 1) % num_frames
        # Increase sleep slightly if network is slow; 0.03s is ~30fps
        time.sleep(0.03)
        st.rerun(scope="fragment")


# =========================================================
# SIDEBAR THUMBNAILS
# =========================================================
st.sidebar.markdown("## 🖼️ Thumbnails")
MAX_THUMBS = 24

for i in range(0, min(len(file_items), MAX_THUMBS), 2):
    cols = st.sidebar.columns(2)

    for j in range(2):
        idx = i + j
        if idx < len(file_items):
            label, path = file_items[idx]

            with ((((cols[j])))):
                # 1. Fast metadata check for video status
                ds_meta = pydicom.dcmread(path, stop_before_pixels=True)
                is_video = int(getattr(ds_meta, "NumberOfFrames", 1)) > 1

                # 2. Load and process thumbnail
                raw_pixels = load_pixel_array(path)
                if raw_pixels is not None:
                    # Use the first frame for the thumbnail
                    thumb_np = raw_pixels[0] if is_video else raw_pixels

                    if is_video:
                        # Apply the play symbol
                        processed_img = add_play_overlay(thumb_np)
                        st.image(processed_img, use_container_width=True, output_format="JPEG")
                        st.caption("📽️ Cine Loop")
                    else:
                        st.image(thumb_np, use_container_width=True, output_format="JPEG")
                        st.caption("📄 Static Image")

                thumb_sop_uid = str(getattr(ds_meta, "SOPInstanceUID", "NA"))
                # 3. Selection Button
                record = st.session_state.viability_forms.get(thumb_sop_uid, {})

                # Check which forms exist in this image's record
                has_v = "Viability" in record
                has_g = "Growth" in record
                has_a = "Anomaly" in record
                qc_done = has_v and has_g and has_a
                btn_label = (
                    "✅ Selected" if path == st.session_state.selected_image else
                    "✔️ Done" if has_v and has_g and has_a else
                    "⚠️ Partial" if has_v or has_g or has_a else
                    "Select"
                )

                if st.button(btn_label, key=f"thumb_btn_{idx}", use_container_width=True):
                    st.session_state.selected_image = path
                    filename = os.path.basename(image_path)
                    st.rerun()
# =========================================================
# MAIN LAYOUT — image left, report + QC form right
# =========================================================
left, right = st.columns([6, 4])

# ── IMAGE ─────────────────────────────────────────────────
with left:
    head_col, badge_col = st.columns([6, 4])

    record = st.session_state.viability_forms.get(image_sop_uid, {})

    # Check which forms exist in this image's record
    has_v = "Viability" in record
    has_g = "Growth" in record
    has_a = "Anomaly" in record

    with head_col:
        st.subheader("🖼️ Ultrasound View")
    with badge_col:
        if has_v and has_g and has_a:
            st.write("")
            st.caption("✅ :green[**Full QC Complete (Viability, Growth, Anomaly)**]")

        elif has_v or has_g or has_a:
            # Build a string showing what is missing
            missing = []
            if not has_v: missing.append("Viability")
            if not has_g: missing.append("Growth")
            if not has_a: missing.append("Anomaly")
            st.write("")
            st.caption(f"🔄 :orange[**Partial QC Saved.** Missing forms: **{', '.join(missing)}**]")
        else:
            st.write("")
            st.caption("⚠️ :red[**QC not yet completed.**]")

    # ── 1. QC STATUS BADGE ────────────────────────────────
    # record = st.session_state.viability_forms.get(image_sop_uid, {})
    #
    # # Check which forms exist in this image's record
    # has_v = "Viability" in record
    # has_g = "Growth" in record
    # has_a = "Anomaly" in record
    #
    # if has_v and has_g and has_a:
    #     st.success("✅ **Full QC Complete** (Viability, Growth, Anomaly)")
    #
    # elif has_v or has_g or has_a:
    #     # Build a string showing what is missing
    #     missing = []
    #     if not has_v: missing.append("Viability")
    #     if not has_g: missing.append("Growth")
    #     if not has_a: missing.append("Anomaly")
    #
    #     st.warning(f"🔄 **Partial QC Saved.** Missing forms: **{', '.join(missing)}**")
    # else:
    #     st.error("⚠️ QC not yet completed.")

    # ── 2. PIXEL DATA LOADING ─────────────────────────────
    pixel_data = load_pixel_array(image_path)

    if pixel_data is not None:
        # Check for Cine Loop (Multi-frame)
        num_frames = int(getattr(ds, "NumberOfFrames", 1))

        if num_frames > 1:
            st.info(f"📽️ Cine Loop: {num_frames} frames detected.")

            # --- 1. THE PLAYER UI ---
            # Create a container for the frame to keep it at the top
            frame_placeholder = st.empty()

            # Navigation Buttons
            c1, c2, c3 = st.columns(3)

            with c1:
                if st.button("⏮ Previous", use_container_width=True):
                    st.session_state.playing = False  # Pause if moving manually
                    st.session_state.frame_idx = max(0, st.session_state.frame_idx - 1)

            with c2:
                play_label = "⏸ Pause" if st.session_state.playing else "▶ Play"
                if st.button(play_label, use_container_width=True):
                    st.session_state.playing = not st.session_state.playing

            with c3:
                if st.button("Next ⏭", use_container_width=True):
                    st.session_state.playing = False  # Pause if moving manually
                    st.session_state.frame_idx = min(num_frames - 1, st.session_state.frame_idx + 1)

            # --- 2. RENDERING LOGIC ---
            # Ensure current frame index is valid
            if st.session_state.frame_idx >= num_frames:
                st.session_state.frame_idx = 0

            with frame_placeholder.container():
                st.image(
                    pixel_data[st.session_state.frame_idx],
                    use_container_width=True,
                    clamp=True,
                    caption=f"Frame {st.session_state.frame_idx + 1} / {num_frames}"
                )

            # --- 3. ANIMATION LOOP ---
            if st.session_state.playing:
                # Move to next frame or loop back to start
                st.session_state.frame_idx = (st.session_state.frame_idx + 1) % num_frames
                time.sleep(0.05)  # Adjust sleep for desired FPS (0.05s = 20 FPS)
                st.rerun()

            # --- 4. DOWNLOAD BUTTON ---
            video_buffer = convert_to_mp4(pixel_data, fps=20)
            st.download_button(
                label="📥 Download Full Cine Loop (MP4)",
                data=video_buffer,
                file_name=f"{os.path.basename(image_path)}.mp4",
                mime="video/mp4",
                use_container_width=True
            )
        else:
            # ── CASE B: STATIC IMAGE ─────────────────────
            fig, ax = plt.subplots(figsize=(9, 9))
            ax.imshow(pixel_data, cmap="gray")
            ax.axis("off")
            st.pyplot(fig, use_container_width=True)

            # --- SAVE IMAGE LOGIC ---
            # Prepare PNG buffer for export
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches='tight', pad_inches=0)
            buf.seek(0)

            st.download_button(
                label="💾 Download Current Frame (PNG)",
                data=buf,
                file_name=f"{os.path.splitext(os.path.basename(image_path))[0]}.png",
                mime="image/png",
                use_container_width=True
            )
    else:
        # ── 3. ERROR HANDLING ─────────────────────────────
        st.error("❌ Failed to load pixel data. The DICOM file may be corrupted or use an unsupported Transfer Syntax.")

# ── REPORT + FORM ─────────────────────────────────────────
with right:
    tab_report, tab_form_01, tab_form_02, tab_form_03 = st.tabs([
        "📊 Structured Report",
        "🧪 QC Viability Form",
        "📈 Growth Scan Form",
        "🔍 Anomaly Scan Form"
    ])

    with tab_report:
        if not image_sr.empty:
            st.markdown("### Key Metrics")

            col_crl, col_nt, col_fhr = st.columns(3)
            for col, metric, label in [
                (col_crl, "Crown Rump Length", "CRL"),
                (col_nt, "Nuchal Translucency", "NT"),
                (col_fhr, "Fetal Heart Rate", "FHR"),
            ]:
                row = image_sr[image_sr["Measurement"] == metric]
                with col:
                    if not row.empty:
                        r = row.iloc[0]
                        st.metric(f"{label}", f"{r['Value']} {r['Unit']}")
                    else:
                        st.metric(f"{label}", "—")

            st.markdown("### All Measurements")
            gb = GridOptionsBuilder.from_dataframe(image_sr)
            gb.configure_default_column(filter=True, sortable=True, resizable=True)

            # Get the name of the column at index 3 and configure it to be hidden
            col_to_hide = image_sr.columns[3]
            gb.configure_column(col_to_hide, hide=True)

            AgGrid(image_sr, gridOptions=gb.build(),
                   use_container_width=True, height=320)
        else:
            st.info("No SR measurements found for this image.")
        pass

    # ── TAB 2 : QC VIABILITY FORM (per image) ─────────────
    with tab_form_01:
        st.markdown("""
            <style>
            div[data-testid="stColumn"]:nth-of-type(3) div[data-testid="stTextInput"] {
                width: 130px !important;
            }
            div[data-testid="stColumn"]:nth-of-type(4) div[data-testid="stTextInput"] input {
                color: #555; 
                font-family: monospace;
            }
            </style>
        """, unsafe_allow_html=True)

        with st.container(height=680, border=False):
            st.subheader("🧪 QC Viability Form")
            st.caption(f"Image: `{os.path.basename(image_path)}`")

            existing = st.session_state.viability_forms.get(image_sop_uid, {})
            file_name = os.path.basename(image_path)

            if len(study_date) == 8 and study_date.isdigit():
                display_date = f"{study_date[:4]}-{study_date[4:6]}-{study_date[6:8]}"
            else:
                display_date = study_date

            col1, col2, col3 = st.columns([1.5, 1.5, 1])
            DOCTOR_MAP = {"00": "", "01": "Dr. A", "02": "Dr. B", "03": "Dr. C"}

            with col1:
                id_suffix = str(patient_id)[-2:]
                mapped_dr_name = DOCTOR_MAP.get(id_suffix, "")
                doctor_options = list(DOCTOR_MAP.values())
                doctor_saved = existing.get("doctor", mapped_dr_name)

                try:
                    current_index = doctor_options.index(doctor_saved)
                except ValueError:
                    current_index = 0

                doctor_v = st.selectbox("Doctor's Name", options=doctor_options, key=f"{image_sop_uid}_doc_v",
                                        index=current_index)

            with col2:
                st.text_input("Case No.", value=patient_id, disabled=True, key=f"{image_sop_uid}_case_v")
                case_no = patient_id

            with col3:
                st.text_input("Scan Date", value=display_date, disabled=True, key=f"{image_sop_uid}_date_v")
            existing.get("Viability", {}).get("crl", {})
            crl_form = criterion_block("Crown Rump Length (CRL)", f"{image_sop_uid}_crl", CRL_LABELS,
                                       existing.get("Viability", {}).get("crl", {}))
            nt_form = criterion_block("Nuchal Translucency (NT)", f"{image_sop_uid}_nt", NT_LABELS,
                                      existing.get("Viability", {}).get("nt", {}))

            form_validation_error = st.empty()  # Placeholder for form validation messages
            if st.button("💾 Save QC Record", use_container_width=True, type="primary", key=f"save_v_{image_sop_uid}"):
                missing_overall = []
                if crl_form["overall"] is None: missing_overall.append("CRL")
                if nt_form["overall"] is None: missing_overall.append("NT")

                if missing_overall:
                    form_validation_error.error(f"⚠️ Mandatory Assessment Missing: {', '.join(missing_overall)}")
                else:
                    # 1. Initialize the dictionary for this image if it doesn't exist
                    if image_sop_uid not in st.session_state.viability_forms:
                        st.session_state.viability_forms[image_sop_uid] = {}

                    st.session_state.viability_forms[image_sop_uid]["details"] = {
                        "doctor": doctor_v,
                        "case_no": patient_id,
                        "date": display_date,
                        "dicom_filename": filename,
                    }

                    # 2. Save ONLY to the "Viability" key
                    st.session_state.viability_forms[image_sop_uid]["Viability"] = {
                        "crl": crl_form,
                        "nt": nt_form,
                    }
                    save_viability_forms()
                    st.success("✅ Viability QC Summary Saved!")
                    st.rerun()

            # study_sop_uids = study_df["SOPInstanceUID"].tolist()
            # total_images = len(study_sop_uids)
            # if total_images > 0:
            #     qc_done = sum(1 for uid in study_sop_uids if uid in st.session_state.viability_forms)
            #     st.write("")
            #     st.caption(f"QC Progress: {qc_done} / {total_images} images in this study")
            #     st.progress(qc_done / total_images)
        pass

    # ── TAB 3 : GROWTH SCAN FORM ──────────────────────────
    with tab_form_02:
        with st.container(height=680, border=False):
            st.subheader("📈 Growth Scan Form")
            st.caption(f"Image: `{os.path.basename(image_path)}`")

            existing = st.session_state.viability_forms.get(image_sop_uid, {})

            col1, col2, col3 = st.columns([1, 1, 0.75])
            with col1:
                doctor_g = st.selectbox("Doctor's Name", options=doctor_options, key=f"{image_sop_uid}_doc_g",
                                        index=current_index)
            with col2:
                st.text_input("Case No.", value=patient_id, disabled=True, key=f"{image_sop_uid}_case_g")
            with col3:
                st.text_input("Scan Date", value=display_date, disabled=True, key=f"{image_sop_uid}_date_g")

            ceph_form = criterion_block("Cephalic Plane", f"{image_sop_uid}_g_ceph", GROWTH_CEPHALIC_LABELS,
                                        existing.get("Growth", {}).get("ceph", {}))
            abd_form = criterion_block("Abdominal Plane", f"{image_sop_uid}_g_abd", GROWTH_ABDOMINAL_LABELS,
                                       existing.get("Growth", {}).get("abd", {}))
            fem_form = criterion_block("Femoral Plane", f"{image_sop_uid}_g_fem", GROWTH_FEMORAL_LABELS,
                                       existing.get("Growth", {}).get("fem", {}))
            form_validation_error = st.empty()  # Placeholder for form validation messages

            if st.button("💾 Save Growth Record", use_container_width=True, type="primary",
                         key=f"save_g_{image_sop_uid}"):
                missing_overall = []
                if ceph_form["overall"] is None: missing_overall.append("Cephalic Plane")
                if abd_form["overall"] is None: missing_overall.append("Abdominal Plane")
                if fem_form["overall"] is None: missing_overall.append("Femoral Plane")

                if missing_overall:
                    form_validation_error.error(f"⚠️ Mandatory Assessment Missing: {', '.join(missing_overall)}")

                else:
                    # 1. Initialize the dictionary for this image if it doesn't exist
                    if image_sop_uid not in st.session_state.viability_forms:
                        st.session_state.viability_forms[image_sop_uid] = {}

                    # 2. Save ONLY to the "Viability" key
                    st.session_state.viability_forms[image_sop_uid]["Growth"] = {
                        "ceph": ceph_form,
                        "abd": abd_form,
                        "fem": fem_form,

                    }
                    save_viability_forms()
                    st.success("✅ Viability QC Summary Saved!")
                    st.rerun()
        pass

    # ── TAB 4 : ANOMALY SCAN FORM ─────────────────────────
    with tab_form_03:
        with st.container(height=680, border=False):
            st.subheader("🔍 Anomaly Scan Form")
            st.caption(f"Image: `{os.path.basename(image_path)}`")

            existing = st.session_state.viability_forms.get(image_sop_uid, {})

            col1, col2, col3 = st.columns([1.5, 1.5, 1])
            with col1:
                doctor_a = st.selectbox("Doctor's Name", options=doctor_options, key=f"{image_sop_uid}_doc_a",
                                        index=current_index)
            with col2:
                st.text_input("Case No.", value=patient_id, disabled=True, key=f"{image_sop_uid}_case_a")
            with col3:
                st.text_input("Scan Date", value=display_date, disabled=True, key=f"{image_sop_uid}_date_a")

            head_tv_form = criterion_block("Head Transventricular", f"{image_sop_uid}_a_htv", ANOMALY_HEAD_TV_LABELS,
                                           existing.get("Anomaly", {}).get("head_tv", {}))
            head_tc_form = criterion_block("Head Transcerebellar", f"{image_sop_uid}_a_htc", ANOMALY_HEAD_TC_LABELS,
                                           existing.get("Anomaly", {}).get("head_tc", {}))
            anom_abd_form = criterion_block("Abdomen", f"{image_sop_uid}_a_abd", ANOMALY_ABDOMEN_LABELS,
                                            existing.get("Anomaly", {}).get("anom_abd", {}))
            anom_fem_form = criterion_block("Femur", f"{image_sop_uid}_a_fem", ANOMALY_FEMUR_LABELS,
                                            existing.get("Anomaly", {}).get("anom_fem", {}))
            spine_form = criterion_block("Spine", f"{image_sop_uid}_a_spine", ANOMALY_SPINE_LABELS,
                                         existing.get("Anomaly", {}).get("spine", {}))
            face_form = criterion_block("Coronal Face", f"{image_sop_uid}_a_face", ANOMALY_FACE_LABELS,
                                        existing.get("Anomaly", {}).get("face", {}))
            form_validation_error = st.empty()  # Placeholder for form validation messages

            if st.button("💾 Save Anomaly Record", use_container_width=True, type="primary",
                         key=f"save_a_{image_sop_uid}"):
                missing_overall = []
                if head_tv_form["overall"] is None: missing_overall.append("Head TV")
                if head_tc_form["overall"] is None: missing_overall.append("Head TC")
                if anom_abd_form["overall"] is None: missing_overall.append("Abdomen")
                if anom_fem_form["overall"] is None: missing_overall.append("Femur")
                if spine_form["overall"] is None: missing_overall.append("Spine")
                if face_form["overall"] is None: missing_overall.append("Coronal Face")

                if missing_overall:
                    form_validation_error.error(f"⚠️ Mandatory Assessment Missing: {', '.join(missing_overall)}")
                    st.info("If a plane is not present, mark it as 'Not Applicable'.")
                else:
                    if image_sop_uid not in st.session_state.viability_forms:
                        st.session_state.viability_forms[image_sop_uid] = {}

                    st.session_state.viability_forms[image_sop_uid]["Anomaly"] = {
                        "head_tv": head_tv_form,
                        "head_tc": head_tc_form,
                        "anom_abd": anom_abd_form,
                        "anom_fem": anom_fem_form,
                        "spine": spine_form,
                        "face": face_form,
                    }
                    save_viability_forms()
                    st.success("✅ Anomaly QC Summary Saved!")
                    st.rerun()
        pass

    # ── PROGRESS BAR (Outside the tabs) ──────────────────────────
    st.divider()

    study_sop_uids = study_df["SOPInstanceUID"].tolist()
    total_images = len(study_sop_uids)

    if total_images > 0:
        # Each image needs 3 forms, so total required forms = total_images * 3
        total_required_forms = total_images * 3
        forms_completed = 0

        fully_completed_images = 0
        partially_completed_images = 0

        for uid in study_sop_uids:
            rec = st.session_state.viability_forms.get(uid, {})

            # Count how many forms are saved for this specific image
            completed_count = 0
            if "Viability" in rec: completed_count += 1
            if "Growth" in rec: completed_count += 1
            if "Anomaly" in rec: completed_count += 1

            forms_completed += completed_count

            # Categorize the image for the display text
            if completed_count == 3:
                fully_completed_images += 1
            elif completed_count > 0:
                partially_completed_images += 1

        # Calculate granular progress (e.g., 1 out of 3 forms = 33% progress)
        progress_pct = forms_completed / total_required_forms

        # Display rich metrics
        st.caption(f"**Study QC Progress:** {int(progress_pct * 100)}% Complete")

        col_metric1, col_metric2, col_metric3 = st.columns(3)
        col_metric1.write(f"✅ **Fully Complete:** {fully_completed_images} / {total_images}")
        col_metric2.write(f"🔄 **Partially Done:** {partially_completed_images}")
        col_metric3.write(f"📄 **Total Forms:** {forms_completed} / {total_required_forms}")

        st.progress(progress_pct)

# =========================================================
# DEBUG PANEL
# =========================================================
with st.expander("🔍 Debug Info"):
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.write("**Study UID**");
        st.code(image_study_uid)
    with col_b:
        st.write("**Series UID**");
        st.code(image_series_uid)
    with col_c:
        st.write("**SOP UID**");
        st.code(image_sop_uid)
    st.write("**Image path:**");
    st.code(image_path)
    st.write(f"**Matching SRs:** {len(matching_sr)}")
    if not matching_sr.empty:
        st.dataframe(matching_sr[["FileName", "SOPInstanceUID"]])
    if not study_sr.empty:
        st.markdown("**Extracted measurements (full SR):**")
        st.dataframe(study_sr)
        st.markdown("**Unique ReferencedSOPInstanceUIDs in SR:**")
        st.write(study_sr["ReferencedSOPInstanceUID"].unique().tolist())
        st.markdown(f"**Current image SOP UID:** `{image_sop_uid}`")
        st.markdown(f"**Rows matching this image:** {len(image_sr)} / {len(study_sr)}")
