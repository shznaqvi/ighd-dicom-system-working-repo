import json
import os
import tempfile
import time

import imageio
import matplotlib.pyplot as plt
import pandas as pd
import pydicom
import streamlit as st
from PIL import Image, ImageDraw


# =========================================================
# PAGE CONFIG & NAVIGATION BAR STYLING
# =========================================================
def optimize_ui_and_health_check():
    """Transforms top header into a titled navigation bar and collapses spacing."""
    st.markdown(
        """
        <style>
        [data-testid="stHeader"], .stAppHeader {
            display: flex !important;
            background-color: #1E293B !important;
            border-bottom: 2px solid #38BDF8;
            height: 50px !important;
            justify-content: flex-start;
            align-items: center;
            padding-left: 1.5rem !important;
        }
        [data-testid="stHeader"]::before {
            content: "📡 IGHD DICOM Browser (PACS Reviewer)";
            color: #F8FAFC !important;
            font-size: 18px !important;
            font-weight: 600 !important;
            font-family: 'Source Sans Pro', sans-serif;
            white-space: nowrap;
        }
        [data-testid="stToolbar"] { top: 5px !important; }
        [data-testid="stToolbar"] svg { fill: #F8FAFC !important; }
        [data-testid="stSidebarContent"] { padding-top: 0rem !important; }
        [data-testid="stHorizontalBlock"] { align-items: flex-start; }
        [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child {
            position: sticky;
            top: 4.5rem;
            align-self: flex-start;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def enable_column_resizing():
    """Injects JS to create a draggable resizer handle between Streamlit columns."""
    st.markdown(
        """
        <style>
        .st-column-resizer {
            width: 8px !important;
            background: #334155;
            cursor: col-resize !important;
            transition: background 0.2s ease;
            border-radius: 4px;
            margin: 0 4px;
            flex-shrink: 0;
            z-index: 10;
        }
        .st-column-resizer:hover, .st-column-resizer.dragging {
            background: #38BDF8 !important;
        }
        </style>

        <script>
        (function injectColumnResizer() {
            const doc = window.parent.document;

            function initResizer() {
                const blocks = doc.querySelectorAll('[data-testid="stHorizontalBlock"]');

                blocks.forEach(block => {
                    const cols = block.querySelectorAll(':scope > [data-testid="column"]');

                    if (cols.length === 2 && !block.querySelector('.st-column-resizer')) {
                        const leftCol = cols[0];
                        const rightCol = cols[1];

                        const resizer = doc.createElement('div');
                        resizer.className = 'st-column-resizer';
                        resizer.title = 'Drag to resize columns';
                        leftCol.after(resizer);

                        let isDragging = false;

                        resizer.addEventListener('mousedown', (e) => {
                            isDragging = true;
                            resizer.classList.add('dragging');
                            doc.body.style.cursor = 'col-resize';
                            e.preventDefault();
                        });

                        doc.addEventListener('mousemove', (e) => {
                            if (!isDragging) return;

                            const blockRect = block.getBoundingClientRect();
                            const offsetLeft = e.clientX - blockRect.left;
                            const totalWidth = blockRect.width;

                            let leftPct = (offsetLeft / totalWidth) * 100;
                            leftPct = Math.max(20, Math.min(80, leftPct));
                            const rightPct = 100 - leftPct;

                            leftCol.style.flex = `${leftPct} 1 0%`;
                            leftCol.style.width = `${leftPct}%`;
                            rightCol.style.flex = `${rightPct} 1 0%`;
                            rightCol.style.width = `${rightPct}%`;
                        });

                        doc.addEventListener('mouseup', () => {
                            if (isDragging) {
                                isDragging = false;
                                resizer.classList.remove('dragging');
                                doc.body.style.cursor = 'default';
                            }
                        });
                    }
                });
            }

            setTimeout(initResizer, 500);
            setTimeout(initResizer, 1500);
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="IGHD DICOM Browser", layout="wide")
optimize_ui_and_health_check()


def get_browser_host():
    try:
        return st.context.headers.get("Host", "localhost").split(":")[0]
    except Exception:
        return "localhost"


# =========================================================
# CONFIG & DOCKER ENV VARIABLES
# =========================================================
dicom_dir = os.getenv("DICOM_DIR", "/raw_data")
QC_FILE = os.getenv("QC_FILE", "/qc_data/study_qc.json")

UPLOADER_URL = f"http://{get_browser_host()}/dicomuploader"

# =========================================================
# SESSION STATE & QC PERSISTENCE
# =========================================================
for key, default in [
    ("current_image_path", None),
    ("current_image_number", -1),
    ("current_filename", ""),
    ("current_sop_uid", ""),
    ("current_series_uid", ""),
    ("cancel_upload", False),
    ("uploading", False),
    ("qc_forms", {}),
    ("playing", False),
    ("frame_idx", 0),
]:
    if key not in st.session_state:
        st.session_state[key] = default


def load_qc_forms():
    if os.path.exists(QC_FILE):
        try:
            with open(QC_FILE, "r", encoding="utf-8") as f:
                st.session_state.qc_forms = json.load(f)
        except Exception:
            st.session_state.qc_forms = {}


def save_qc_forms():
    os.makedirs(os.path.dirname(QC_FILE), exist_ok=True)
    with open(QC_FILE, "w", encoding="utf-8") as f:
        json.dump(st.session_state.qc_forms, f, indent=2)


if not st.session_state.qc_forms:
    load_qc_forms()


# =========================================================
# DICOM SCANNER (FULL ATTRIBUTES & MODALITY MATCHING)
# =========================================================
@st.cache_data(show_spinner=True, ttl=18 * 3600)
def scan_dicom_folder(folder):
    images, sr_files = [], []
    cols = [
        "FilePath", "FileName", "PatientID", "PatientName", "StudyDate", "StudyTime",
        "StudyDescription", "StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID",
        "InstanceNumber", "Modality", "SeriesDescription", "ProtocolName",
        "OperatorsName", "PerformingPhysicianName", "InstitutionName",
        "Manufacturer", "ManufacturerModelName", "DeviceSerialNumber",
        "NumberOfFrames", "Rows", "Columns", "ImageComments"
    ]

    if os.path.exists(folder):
        for root, _, files in os.walk(folder):
            for f in files:
                if not f.lower().endswith(".dcm") and "." in f:
                    continue
                path = os.path.join(root, f)
                try:
                    ds = pydicom.dcmread(path, stop_before_pixels=True)
                    modality = str(getattr(ds, "Modality", "NA")).upper().strip()
                    record = {
                        "FilePath": path,
                        "FileName": f,
                        "PatientID": str(getattr(ds, "PatientID", "NA")),
                        "PatientName": str(getattr(ds, "PatientName", "")),
                        "StudyDate": str(getattr(ds, "StudyDate", "NA")),
                        "StudyTime": str(getattr(ds, "StudyTime", "")),
                        "StudyDescription": str(getattr(ds, "StudyDescription", "")),
                        "StudyInstanceUID": str(getattr(ds, "StudyInstanceUID", "NA")),
                        "SeriesInstanceUID": str(getattr(ds, "SeriesInstanceUID", "NA")),
                        "SOPInstanceUID": str(getattr(ds, "SOPInstanceUID", "NA")),
                        "InstanceNumber": int(getattr(ds, "InstanceNumber", -1)),
                        "Modality": modality,
                        "SeriesDescription": str(getattr(ds, "SeriesDescription", "")),
                        "ProtocolName": str(getattr(ds, "ProtocolName", "")),
                        "OperatorsName": str(getattr(ds, "OperatorsName", "")).strip(),
                        "PerformingPhysicianName": str(getattr(ds, "PerformingPhysicianName", "")).strip(),
                        "InstitutionName": str(getattr(ds, "InstitutionName", "")).strip(),
                        "Manufacturer": str(getattr(ds, "Manufacturer", "")).strip(),
                        "ManufacturerModelName": str(getattr(ds, "ManufacturerModelName", "")).strip(),
                        "DeviceSerialNumber": str(getattr(ds, "DeviceSerialNumber", "")).strip(),
                        "NumberOfFrames": int(getattr(ds, "NumberOfFrames", 1)),
                        "Rows": int(getattr(ds, "Rows", 0)),
                        "Columns": int(getattr(ds, "Columns", 0)),
                        "ImageComments": str(getattr(ds, "ImageComments", "")).strip(),
                    }
                    if modality == "SR":
                        sr_files.append(record)
                    else:
                        images.append(record)
                except Exception:
                    pass

    df_img = pd.DataFrame(images, columns=cols) if images else pd.DataFrame(columns=cols)
    df_sr_out = pd.DataFrame(sr_files, columns=cols) if sr_files else pd.DataFrame(columns=cols)
    return df_img, df_sr_out


# =========================================================
# SR PARSER
# =========================================================
def extract_sr_measurements(ds):
    rows = []

    def walk(seq, parent_ref_sop=""):
        for item in seq:
            try:
                ref_sop = parent_ref_sop
                if "ReferencedSOPSequence" in item:
                    ref_sop = str(getattr(item.ReferencedSOPSequence[0], "ReferencedSOPInstanceUID", ref_sop))
                elif "SourceImageSequence" in item:
                    ref_sop = str(getattr(item.SourceImageSequence[0], "ReferencedSOPInstanceUID", ref_sop))

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
                        "ReferencedSOPInstanceUID": ref_sop,
                    })

                if "ContentSequence" in item:
                    walk(item.ContentSequence, ref_sop)

            except Exception:
                pass

    if "ContentSequence" in ds:
        walk(ds.ContentSequence)
    return pd.DataFrame(rows)


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
# QC CRITERION LABELS & VALIDATION HELPER
# =========================================================
CRITERION_OPTIONS = ["Acceptable", "Unacceptable", "Not Applicable"]
CRL_LABELS = ["Mid-sagittal section", "Neutral Position", "Horizontal Position", "Crown and Rump clearly visible",
              "Correct Caliper Placement", "Good Magnification"]
NT_LABELS = ["Magnification", "True mid-sagittal section", "Neutral fetal position", "Caliper ''ON-to-ON''",
             "Maximum Lucency", "Thin Nuchal Membrane"]
GROWTH_CEPHALIC_LABELS = ["Crit-1: Symmetrical plane", "Crit-2: Thalami visible",
                          "Crit-3: Cavum septum pellucidi visible", "Crit-4: Cerebellum not visible",
                          "Crit-5: Head occupying 30% of image", "Crit-6: Calipers/ellipse placed correctly"]
GROWTH_ABDOMINAL_LABELS = ["Crit-1: Symmetrical plane", "Crit-2: Stomach bubble visible",
                           "Crit-3: Portal sinus visible", "Crit-4: Kidneys not visible",
                           "Crit-5: Abdomen occupying 30% of image", "Crit-6: Calipers/ellipse placed correctly"]
GROWTH_FEMORAL_LABELS = ["Crit-1: Both ends of the bone clearly visible", "Crit-2: Angle <45 degrees",
                         "Crit-3: Femur occupying at least 30% of image", "Crit-4: Calipers placed correctly"]
ANOMALY_HEAD_TV_LABELS = ["Crit-1: Symmetrical place with midline fax", "Crit-2: Cavum septum visible",
                          "Crit-3: Cerebellum not visible", "Crit-4: Ventricles visible at atrium",
                          "Crit-5: Magnification 30% of screen",
                          "Crit-6: Head circumference calipers outer parts of skul",
                          "Crit-7: Calipers measuring lateral ventricles at level of atrium"]
ANOMALY_HEAD_TC_LABELS = ["Crit-1: Symmetrical place with midline fax", "Crit-2: Cavum septum visible",
                          "Crit-3: Cerebellum visible", "Crit-4: Cisterna magna visible",
                          "Crit-5: Magnification 30% of screen",
                          "Crit-6: Calipers placed on outer level of cerebellar hemispheres",
                          "Crit-7: Calipers placed on outer limits of cisterna magna"]
ANOMALY_ABDOMEN_LABELS = ["Crit-1: Stomach bubble visible",
                          "Crit-2: Umbilical vein 1/3rd of way along anteroposterior diameter at portal sinus level",
                          "Crit-3: Circular plane", "Crit-4: Kidneys not visible",
                          "Crit-5: Magnification at least 30% of screen",
                          "Crit-6: Calipers placed on outer parts of abdomen"]
ANOMALY_FEMUR_LABELS = ["Crit-1: Both ends of ossified diaphysis clear", "Crit-2: Angle of insonation 45-90 degree",
                        "Crit-3: Magnification at least 30% of screen",
                        "Crit-4: Calipers placed on clear ends of diaphysis"]
ANOMALY_SPINE_LABELS = ["Crit-1: Magnification up to 30% of screen",
                        "Crit-2: Continuity intact and posterior skin edge visible",
                        "Crit-3: Alignment of vertebrae visible", "Crit-4: Amniotic fluid visible beyond skin",
                        "Crit-5: Lower sacrum visible", "Crit-6: Middle thoracic/lumbar visible",
                        "Crit-7: Upper cervical/thoracic visible"]
ANOMALY_FACE_LABELS = ["Crit-1: Upper lip visible", "Crit-2: Both nostrils visible", "Crit-3: Both lip angles visible",
                       "Crit-4: Adequate magnification"]


def validate_block(block_data, expected_count):
    """Ensures overall status and all criterion radios are filled for a block."""
    if not block_data or block_data.get("overall") is None:
        return False
    crits = block_data.get("criteria", {})
    if len(crits) < expected_count or any(v is None for v in crits.values()):
        return False
    return True


# =========================================================
# QC CRITERION BLOCK
# =========================================================
def criterion_block(title, block_key, labels, record_key, form_name, assessment_key):
    existing_study = st.session_state.qc_forms.get(record_key, {})
    existing_form = existing_study.get(form_name, {})
    existing_assessment = existing_form.get(assessment_key, {})

    existing_crits = existing_assessment.get("criteria", {})
    existing_evidence = existing_assessment.get("evidence", {})

    with st.container(border=True):
        st.markdown(f"### {title}")
        st.markdown("**Evidence Image:**")
        if existing_evidence and existing_evidence.get("filename"):
            ev_col1, ev_col2 = st.columns([3, 2])
            with ev_col1:
                st.info(
                    f"📷 **Image {existing_evidence.get('image_number', 'N/A')}** (`{existing_evidence.get('filename')}`)")
            with ev_col2:
                if st.button("👁️ Jump to Image", key=f"{block_key}_jump_ev", use_container_width=True):
                    ev_path = existing_evidence.get("filepath")
                    if not ev_path or not os.path.exists(ev_path):
                        target_sop = existing_evidence.get("sop_uid")
                        df_imgs = st.session_state.get("df_images", pd.DataFrame())
                        if not df_imgs.empty:
                            match = df_imgs[df_imgs["SOPInstanceUID"] == target_sop]
                            if not match.empty:
                                ev_path = match.iloc[0]["FilePath"]

                    if ev_path and os.path.exists(ev_path):
                        if ev_path == st.session_state.current_image_path:
                            st.toast("ℹ️ This evidence image is already active in the viewport.")
                        else:
                            st.session_state.current_image_path = ev_path
                            st.toast(f"Switched viewport to Evidence Image {existing_evidence.get('image_number')}!")
                            st.rerun()
                    else:
                        st.error("Could not locate evidence file on disk.")
        else:
            st.caption("⚠️ *No evidence image selected.*")

        if st.button("📌 Use Current Image as Evidence", key=f"{block_key}_attach_ev"):
            if record_key not in st.session_state.qc_forms:
                st.session_state.qc_forms[record_key] = {}
            if form_name not in st.session_state.qc_forms[record_key]:
                st.session_state.qc_forms[record_key][form_name] = {}
            if assessment_key not in st.session_state.qc_forms[record_key][form_name]:
                st.session_state.qc_forms[record_key][form_name][assessment_key] = {}

            st.session_state.qc_forms[record_key][form_name][assessment_key]["evidence"] = {
                "image_number": st.session_state.current_image_number,
                "filename": st.session_state.current_filename,
                "sop_uid": st.session_state.current_sop_uid,
                "series_uid": st.session_state.current_series_uid,
                "filepath": st.session_state.current_image_path,
            }
            save_qc_forms()
            st.toast(f"Attached Image {st.session_state.current_image_number} as evidence for {title}!")
            st.rerun()

        st.divider()
        overall_saved = existing_assessment.get("overall", None)
        overall = st.segmented_control(
            "**Overall Status**", CRITERION_OPTIONS, default=overall_saved,
            key=f"{block_key}_overall", selection_mode="single"
        )

        crits = {}
        cols = st.columns(2)
        for i, label_text in enumerate(labels):
            crit_id = f"crit_{i + 1}"
            saved = existing_crits.get(crit_id, None)
            with cols[i % 2]:
                idx = CRITERION_OPTIONS.index(saved) if saved in CRITERION_OPTIONS else None
                crits[crit_id] = st.radio(
                    f"**Crit-{i + 1}:** {label_text}", CRITERION_OPTIONS, index=idx,
                    key=f"{block_key}_crit_{i}", horizontal=False
                )

    return {"overall": overall, "criteria": crits, "evidence": existing_evidence}


# =========================================================
# SIDEBAR CONTROLS & DICOM DIRECTORY
# =========================================================
with st.sidebar:
    st.link_button("🚀 Open Study Uploader", UPLOADER_URL, use_container_width=True)
    if st.button("🔄 Force Re-scan DICOM Folder"):
        with st.spinner("Scanning…"):
            df_images, df_sr = scan_dicom_folder(dicom_dir)
            st.session_state["df_images"] = df_images
            st.session_state["df_sr"] = df_sr
        st.rerun()

if not os.path.exists(dicom_dir):
    st.error(f"📁 **DICOM Folder Not Found:** `{dicom_dir}`\n\nPlease check storage volume mounting.")
    st.stop()

if "df_images" not in st.session_state or "df_sr" not in st.session_state:
    with st.spinner("🔄 Automatically scanning DICOM Folder... Please wait."):
        df_images, df_sr = scan_dicom_folder(dicom_dir)
        st.session_state["df_images"] = df_images
        st.session_state["df_sr"] = df_sr
        st.session_state["known_files"] = set(df_images["FilePath"]) if not df_images.empty else set()
        st.session_state["last_scan_time"] = time.time()

df_images = st.session_state["df_images"]
df_sr = st.session_state["df_sr"]

if df_images.empty:
    st.warning("No DICOM images found in the specified directory.")
    st.stop()

now = time.time()
if now - st.session_state.get("last_scan_time", 0) > 90:
    new_df_images, new_df_sr = scan_dicom_folder(dicom_dir)
    current_files = set(new_df_images["FilePath"]) if not new_df_images.empty else set()
    new_files = current_files - st.session_state.get("known_files", set())
    if new_files:
        st.session_state["df_images"] = new_df_images
        st.session_state["df_sr"] = new_df_sr
        st.session_state["known_files"] = current_files
        st.toast(f"🆕 {len(new_files)} new DICOM file(s) detected!")
    st.session_state["last_scan_time"] = now

# =========================================================
# PATIENT / STUDY SELECTION
# =========================================================
region_options = ["All Regions", "Matiari", "TMK", "Mithi"]

raw_url_patient_id = st.query_params.get("PatientID", "") or st.query_params.get("patient_id", "")
clean_url_patient_id = raw_url_patient_id.rstrip("__")
url_study_date = st.query_params.get("StudyDate", "") or st.query_params.get("study_date", "")

target_pid = raw_url_patient_id or clean_url_patient_id

if target_pid:
    existing_pids = set(df_images["PatientID"].unique()) if not df_images.empty else set()
    existing_clean_pids = {p.rstrip("__") for p in existing_pids}

    if target_pid not in existing_pids and target_pid not in existing_clean_pids:
        st.cache_data.clear()
        df_images, df_sr = scan_dicom_folder(dicom_dir)
        st.session_state["df_images"] = df_images
        st.session_state["df_sr"] = df_sr
        st.session_state["known_files"] = set(df_images["FilePath"]) if not df_images.empty else set()

if "selected_region_index" not in st.session_state:
    if target_pid and target_pid[0].isdigit():
        extracted_index = int(target_pid[0])
        st.session_state.selected_region_index = extracted_index if 0 <= extracted_index < len(region_options) else 0
    else:
        st.session_state.selected_region_index = 0

region_col, top1, top2 = st.columns([1, 1, 1])

with region_col:
    region = st.selectbox("📍 Region", options=region_options, index=st.session_state.get("selected_region_index", 0),
                          key="region_selector")

if not target_pid and region != "All Regions":
    current_region_idx = region_options.index(region)
    df_images = df_images[df_images["PatientID"].str.startswith(str(current_region_idx))]

patient_options = sorted(df_images["PatientID"].unique())

default_patient_index = 0
if target_pid:
    for idx, pid in enumerate(patient_options):
        if pid == raw_url_patient_id or pid == clean_url_patient_id or pid.rstrip("__") == clean_url_patient_id:
            default_patient_index = idx
            break

with top1:
    patient_id = st.selectbox("👤 Select Patient ID", options=patient_options, index=default_patient_index)

patient_df = df_images[df_images["PatientID"] == patient_id]

study_map = patient_df[["StudyDate", "StudyTime", "StudyDescription", "StudyInstanceUID"]].drop_duplicates(
    subset=["StudyInstanceUID"]).copy()


def format_study_label(row):
    d = str(row["StudyDate"])
    t = str(row["StudyTime"])
    desc = str(row["StudyDescription"])
    uid = str(row["StudyInstanceUID"])

    formatted_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else d
    formatted_time = f" {t[:2]}:{t[2:4]}" if len(t) >= 4 and t[:4].isdigit() else ""
    desc_str = f" - {desc}" if desc and desc.upper() not in ["NA", "NONE", ""] else ""
    short_uid = f" (..{uid[-6:]})" if len(uid) > 6 else ""

    return f"{formatted_date}{formatted_time}{desc_str}{short_uid}"


study_map["DisplayLabel"] = study_map.apply(format_study_label, axis=1)
study_map = study_map.sort_values(by=["StudyDate", "StudyTime"], ascending=False)

study_options = study_map["DisplayLabel"].tolist()
label_to_uid = dict(zip(study_map["DisplayLabel"], study_map["StudyInstanceUID"]))
label_to_date = dict(zip(study_map["DisplayLabel"], study_map["StudyDate"]))

default_study_index = 0
if url_study_date:
    clean_study_date = url_study_date.replace("-", "").strip()
    for idx, lbl in enumerate(study_options):
        raw_date = str(label_to_date.get(lbl, ""))
        if (url_study_date in lbl) or (raw_date == url_study_date) or (raw_date == clean_study_date):
            default_study_index = idx
            break

with top2:
    selected_study_label = st.selectbox("📅 Select Study", options=study_options, index=default_study_index)

if selected_study_label:
    study_uid = label_to_uid[selected_study_label]
    study_date = label_to_date[selected_study_label]
    study_df = patient_df[patient_df["StudyInstanceUID"] == study_uid].sort_values("InstanceNumber")
    display_date = f"{study_date[:4]}-{study_date[4:6]}-{study_date[6:8]}" if len(
        study_date) == 8 and study_date.isdigit() else study_date
else:
    if patient_df.empty:
        st.warning("No patient records found.")
    st.stop()

# Shared persistent storage record key
record_key = f"{patient_id.rstrip('__')}{study_date[:8]}"

# =========================================================
# FILE MAP & VIEWPORT METADATA
# =========================================================
file_map = {f"{r['InstanceNumber']} | {r['FileName']}": r["FilePath"] for _, r in study_df.iterrows()}
file_items = list(file_map.items())

if not file_items:
    st.warning("No image files for this study.")
    st.stop()

if st.session_state.current_image_path is None or st.session_state.current_image_path not in file_map.values():
    st.session_state.current_image_path = file_items[0][1]

current_image_path = st.session_state.current_image_path
ds_curr = pydicom.dcmread(current_image_path, stop_before_pixels=True)

st.session_state.current_filename = os.path.basename(current_image_path)
st.session_state.current_sop_uid = str(getattr(ds_curr, "SOPInstanceUID", "NA"))
st.session_state.current_series_uid = str(getattr(ds_curr, "SeriesInstanceUID", "NA"))
st.session_state.current_image_number = int(getattr(ds_curr, "InstanceNumber", -1))


def add_play_overlay(np_array):
    try:
        arr = np_array.astype(float)
        arr = (arr - np.min(arr)) / (np.max(arr) - np.min(arr) + 1e-5) * 255.0
        img = Image.fromarray(arr.astype(np.uint8)).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        w, h = img.size
        cx, cy = w // 2, h // 2
        r = min(w, h) // 4
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 200), width=4)
        draw.polygon([(cx - r // 3, cy - r // 2), (cx - r // 3, cy + r // 2), (cx + r // 2, cy)],
                     fill=(255, 255, 255, 220))
        return Image.alpha_composite(img, overlay).convert("RGB")
    except Exception:
        return np_array


# =========================================================
# PARSE ALL SR FILES
# =========================================================
study_sr_files = df_sr[df_sr["StudyInstanceUID"] == study_uid]
all_sr_dfs = []

if not study_sr_files.empty:
    for _, sr_row in study_sr_files.iterrows():
        try:
            sr_ds = pydicom.dcmread(sr_row["FilePath"])
            df_ext = extract_sr_measurements(sr_ds)
            if not df_ext.empty:
                all_sr_dfs.append(df_ext)
        except Exception as e:
            st.warning(f"SR parse error on {sr_row['FileName']}: {e}")

study_sr = pd.concat(all_sr_dfs, ignore_index=True).drop_duplicates() if all_sr_dfs else pd.DataFrame()


@st.cache_data(show_spinner=False)
def convert_to_mp4(pixel_array, fps=20):
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmpfile:
        imageio.mimwrite(tmpfile.name, pixel_array, fps=fps, format='FFMPEG', codec='libx264', macro_block_size=None)
        with open(tmpfile.name, "rb") as f:
            video_bytes = f.read()
    os.unlink(tmpfile.name)
    return video_bytes


# =========================================================
# SIDEBAR THUMBNAILS
# =========================================================
@st.fragment
def render_sidebar_thumbnails(file_items, study_sr):
    st.markdown("## 🖼️ Thumbnails")
    sop_to_measurement = {}
    if not study_sr.empty and "ReferencedSOPInstanceUID" in study_sr.columns:
        for _, sr_row in study_sr.iterrows():
            ref_sop = str(sr_row.get("ReferencedSOPInstanceUID", ""))
            meas_name = str(sr_row.get("Measurement", ""))
            if ref_sop and meas_name:
                sop_to_measurement[ref_sop] = meas_name

    for i in range(0, min(len(file_items), 56), 2):
        cols = st.columns(2)
        for j in range(2):
            idx = i + j
            if idx < len(file_items):
                label, path = file_items[idx]
                with cols[j]:
                    ds_meta = pydicom.dcmread(path, stop_before_pixels=True)
                    is_video = int(getattr(ds_meta, "NumberOfFrames", 1)) > 1
                    instance_num = getattr(ds_meta, "InstanceNumber", idx + 1)
                    sop_uid = str(getattr(ds_meta, "SOPInstanceUID", ""))

                    descriptive_text = next((str(getattr(ds_meta, tag, "")).strip() for tag in
                                             ["SeriesDescription", "ProtocolName", "ImageComments"] if
                                             str(getattr(ds_meta, tag, "")).strip().upper() not in ["NA", "NONE", ""]),
                                            "")
                    if not descriptive_text and sop_uid in sop_to_measurement:
                        descriptive_text = sop_to_measurement[sop_uid]

                    raw_pixels = load_pixel_array(path)
                    if raw_pixels is not None:
                        thumb_np = raw_pixels[0] if is_video else raw_pixels
                        st.image(add_play_overlay(thumb_np) if is_video else thumb_np, use_container_width=True,
                                 output_format="JPEG")
                        caption_text = f"Img {instance_num}" + (
                            f": {descriptive_text}" if descriptive_text else f" ({os.path.splitext(os.path.basename(path))[0]})") + (
                                           " 📽️" if is_video else "")
                        st.caption(caption_text)

                    if st.button("✅ Active" if path == st.session_state.current_image_path else "View",
                                 key=f"thumb_btn_{idx}", use_container_width=True):
                        st.session_state.current_image_path = path
                        st.rerun()


with st.sidebar:
    render_sidebar_thumbnails(file_items, study_sr)

# =========================================================
# MAIN LAYOUT STRUCTURE & QC STATUS CHECK
# =========================================================
enable_column_resizing()
left, right = st.columns([6, 4])

study_record = st.session_state.qc_forms.get(record_key, {})
study_has_v = "Viability" in study_record
study_has_g = "Growth" in study_record
study_has_a = "Anomaly" in study_record

saved_forms = []
if study_has_v: saved_forms.append("Viability")
if study_has_g: saved_forms.append("Growth")
if study_has_a: saved_forms.append("Anomaly")

study_qc_done = len(saved_forms) == 3


def get_qc_completion_status(key):
    rec = st.session_state.qc_forms.get(key, {})
    saved_tabs = [t for t in ["Viability", "Growth", "Anomaly"] if t in rec]
    return len(saved_tabs) == 3, saved_tabs


# =========================================================
# FRAGMENT 3: ULTRASOUND VIEWPORT
# =========================================================
@st.fragment
def render_ultrasound_viewport(current_path, ds_obj):
    head_col, badge_col = st.columns([5, 5])
    with head_col:
        st.subheader("🖼️ Ultrasound View")
    with badge_col:
        st.write("")
        if study_qc_done:
            st.caption("✅ :green[**Full Study QC Complete**]")
        elif saved_forms:
            st.caption(f"🔄 :orange[**Partial QC Saved ({', '.join(saved_forms)}).**]")
        else:
            st.caption("⚠️ :red[**QC not yet completed.**]")

    pixel_data = load_pixel_array(current_path)
    if pixel_data is not None:
        num_frames = int(getattr(ds_obj, "NumberOfFrames", 1))
        if num_frames > 1:
            st.info(f"📽️ Cine Loop: {num_frames} frames detected.")
            frame_placeholder = st.empty()
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("⏮ Previous", use_container_width=True):
                    st.session_state.playing = False
                    st.session_state.frame_idx = max(0, st.session_state.frame_idx - 1)
                    st.rerun(scope="fragment")
            with c2:
                if st.button("⏸ Pause" if st.session_state.playing else "▶ Play", use_container_width=True):
                    st.session_state.playing = not st.session_state.playing
                    st.rerun(scope="fragment")
            with c3:
                if st.button("Next ⏭", use_container_width=True):
                    st.session_state.playing = False
                    st.session_state.frame_idx = min(num_frames - 1, st.session_state.frame_idx + 1)
                    st.rerun(scope="fragment")

            if st.session_state.frame_idx >= num_frames:
                st.session_state.frame_idx = 0
            with frame_placeholder.container():
                st.image(pixel_data[st.session_state.frame_idx], use_container_width=True, clamp=True,
                         caption=f"Frame {st.session_state.frame_idx + 1} / {num_frames}")

            if st.session_state.playing:
                st.session_state.frame_idx = (st.session_state.frame_idx + 1) % num_frames
                time.sleep(0.05)
                st.rerun(scope="fragment")
        else:
            fig, ax = plt.subplots(figsize=(9, 9))
            ax.imshow(pixel_data, cmap="gray")
            ax.axis("off")
            st.pyplot(fig, use_container_width=True)
    else:
        st.error("❌ Failed to load pixel data.")


with left:
    render_ultrasound_viewport(st.session_state.current_image_path, ds_curr)


# =========================================================
# QC FORMS & REPORT PANEL (FRAGMENTED)
# =========================================================
@st.fragment
def render_qc_forms_panel(study_uid, patient_id, display_date, file_items, study_sr, record_key):
    tab_report, tab_form_01, tab_form_02, tab_form_03 = st.tabs(
        ["📊 Structured Report", "🧪 QC Viability Form", "📈 Growth Scan Form", "🔍 Anomaly Scan Form"]
    )

    # ── TAB 1 : STRUCTURED REPORT (CLEAN TABLE) ──
    with tab_report:
        if not study_sr.empty:
            st.markdown("### Key Metrics")
            col_crl, col_nt, col_fhr = st.columns(3)
            for col, metric, label in [
                (col_crl, "Crown Rump Length", "CRL"),
                (col_nt, "Nuchal Translucency", "NT"),
                (col_fhr, "Fetal Heart Rate", "FHR"),
            ]:
                row = study_sr[study_sr["Measurement"] == metric]
                with col:
                    st.metric(f"{label}", f"{row.iloc[0]['Value']} {row.iloc[0]['Unit']}" if not row.empty else "—")

            st.markdown("### All Study Measurements")

            display_sr = study_sr.copy()

            existing_measurements = (
                st.session_state.qc_forms.get(record_key, {}).get("Measurements", {}).get("data", [])
            )
            saved_tuples = [(m.get("Measurement"), m.get("Value"), m.get("Unit")) for m in existing_measurements]

            display_sr.insert(
                0,
                "Select",
                [(row.get("Measurement"), row.get("Value"), row.get("Unit")) in saved_tuples for _, row in
                 display_sr.iterrows()],
            )

            edited_df = st.data_editor(
                display_sr,
                column_config={
                    "Select": st.column_config.CheckboxColumn("Select", default=False),
                    "ReferencedSOPInstanceUID": None,
                },
                disabled=["Measurement", "Value", "Unit"],
                hide_index=True,
                use_container_width=True,
                height=320,
                key=f"editor_{study_uid}",
            )

            st.write("")
            if st.button("💾 Save Selected Measurements", type="primary", key=f"save_meas_{study_uid}"):
                selected_rows = edited_df[edited_df["Select"] == True]
                if not selected_rows.empty:
                    clean_df = selected_rows.drop(columns=["Select"])
                    clean_records = clean_df.to_dict(orient="records")
                    if record_key not in st.session_state.qc_forms:
                        st.session_state.qc_forms[record_key] = {}
                    st.session_state.qc_forms[record_key]["Measurements"] = {
                        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "data": clean_records,
                    }
                    save_qc_forms()
                    st.success(f"✅ Successfully saved {len(clean_records)} measurements to the study record!")
                else:
                    if record_key in st.session_state.qc_forms and "Measurements" in st.session_state.qc_forms[
                        record_key]:
                        del st.session_state.qc_forms[record_key]["Measurements"]
                        save_qc_forms()
                        st.info("🗑️ Cleared all saved measurements for this study.")
                    else:
                        st.warning(
                            "⚠️ No measurements selected. Please check the boxes next to the measurements you want to save.")
        else:
            st.info("No SR measurements found for this study.")

    # Doctor Mapping with Multi-tier Fallback
    DOCTOR_MAP = {"00": "", "01": "Dr. A", "02": "Dr. B", "03": "Dr. C"}
    doctor_options = list(DOCTOR_MAP.values())

    raw_operator = str(study_df.iloc[0].get("OperatorsName", "")).strip() if not study_df.empty else ""
    raw_physician = str(study_df.iloc[0].get("PerformingPhysicianName", "")).strip() if not study_df.empty else ""
    pid_suffix = str(patient_id)[-2:] if patient_id else ""

    if raw_operator:
        auto_doctor = DOCTOR_MAP.get(raw_operator, raw_operator)
    elif raw_physician:
        auto_doctor = DOCTOR_MAP.get(raw_physician, raw_physician)
    else:
        auto_doctor = DOCTOR_MAP.get(pid_suffix, "")

    if auto_doctor and auto_doctor not in doctor_options:
        doctor_options.append(auto_doctor)

    saved_doctor = study_record.get("details", {}).get("doctor", None)
    final_selected_doctor = saved_doctor if saved_doctor else auto_doctor
    current_index = doctor_options.index(final_selected_doctor) if final_selected_doctor in doctor_options else 0

    # ── TAB 2 : QC VIABILITY FORM ───────────────────────────
    with tab_form_01:
        with st.container(height=680, border=False):
            st.subheader("🧪 QC Viability Form")
            st.caption(f"Study Date: `{display_date}` | Patient ID: `{patient_id}`")
            col1, col2, col3 = st.columns([1.5, 1.5, 1])
            with col1:
                doctor_v = st.selectbox("Doctor's Name", options=doctor_options, key=f"{study_uid}_doc_v",
                                        index=current_index)
            with col2:
                st.text_input("Case No.", value=patient_id, disabled=True, key=f"{study_uid}_case_v")
            with col3:
                st.text_input("Scan Date", value=display_date, disabled=True, key=f"{study_uid}_date_v")

            crl_form = criterion_block("Crown Rump Length (CRL)", f"{study_uid}_crl", CRL_LABELS, record_key,
                                       "Viability", "crl")
            nt_form = criterion_block("Nuchal Translucency (NT)", f"{study_uid}_nt", NT_LABELS, record_key, "Viability",
                                      "nt")

            form_validation_error = st.empty()
            if st.button("💾 Save Viability QC", use_container_width=True, type="primary", key=f"save_v_{study_uid}"):
                missing = []
                if not validate_block(crl_form, len(CRL_LABELS)):
                    missing.append("Crown Rump Length (CRL)")
                if not validate_block(nt_form, len(NT_LABELS)):
                    missing.append("Nuchal Translucency (NT)")

                if missing:
                    form_validation_error.error(
                        f"⚠️ Cannot save Viability Form: Please complete all Overall and Criterion selections for: {', '.join(missing)}")
                else:
                    if record_key not in st.session_state.qc_forms:
                        st.session_state.qc_forms[record_key] = {}
                    st.session_state.qc_forms[record_key]["details"] = {
                        "case_no": patient_id.rstrip("__"),
                        "doctor": doctor_v,
                        "patient_id": patient_id,
                        "study_uid": study_uid,
                        "date": display_date,
                        "image_count": len(file_items),
                        "last_reviewed": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    st.session_state.qc_forms[record_key]["Viability"] = {"crl": crl_form, "nt": nt_form}
                    save_qc_forms()
                    st.success(
                        "🎉 Full Study QC Completed & Saved!"
                        if get_qc_completion_status(record_key)[0]
                        else "✅ Viability QC Form Saved!"
                    )
                    st.rerun(scope="fragment")

    # ── TAB 3 : GROWTH SCAN FORM ────────────────────────────
    with tab_form_02:
        with st.container(height=680, border=False):
            st.subheader("📈 Growth Scan Form")
            col1, col2, col3 = st.columns([1.5, 1.5, 1])
            with col1:
                doctor_g = st.selectbox("Doctor's Name", options=doctor_options, key=f"{study_uid}_doc_g",
                                        index=current_index)
            with col2:
                st.text_input("Case No.", value=patient_id, disabled=True, key=f"{study_uid}_case_g")
            with col3:
                st.text_input("Scan Date", value=display_date, disabled=True, key=f"{study_uid}_date_g")

            ceph_form = criterion_block("Cephalic Plane", f"{study_uid}_g_ceph", GROWTH_CEPHALIC_LABELS, record_key,
                                        "Growth", "ceph")
            abd_form = criterion_block("Abdominal Plane", f"{study_uid}_g_abd", GROWTH_ABDOMINAL_LABELS, record_key,
                                       "Growth", "abd")
            fem_form = criterion_block("Femoral Plane", f"{study_uid}_g_fem", GROWTH_FEMORAL_LABELS, record_key,
                                       "Growth", "fem")

            form_validation_error = st.empty()
            if st.button("💾 Save Growth QC", use_container_width=True, type="primary", key=f"save_g_{study_uid}"):
                missing = []
                if not validate_block(ceph_form, len(GROWTH_CEPHALIC_LABELS)):
                    missing.append("Cephalic Plane")
                if not validate_block(abd_form, len(GROWTH_ABDOMINAL_LABELS)):
                    missing.append("Abdominal Plane")
                if not validate_block(fem_form, len(GROWTH_FEMORAL_LABELS)):
                    missing.append("Femoral Plane")

                if missing:
                    form_validation_error.error(
                        f"⚠️ Cannot save Growth Form: Please complete all Overall and Criterion selections for: {', '.join(missing)}")
                else:
                    if record_key not in st.session_state.qc_forms:
                        st.session_state.qc_forms[record_key] = {}
                    st.session_state.qc_forms[record_key]["details"] = {
                        "case_no": patient_id.rstrip("__"),
                        "doctor": doctor_g,
                        "patient_id": patient_id,
                        "study_uid": study_uid,
                        "date": display_date,
                        "image_count": len(file_items),
                        "last_reviewed": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    st.session_state.qc_forms[record_key]["Growth"] = {"ceph": ceph_form, "abd": abd_form,
                                                                       "fem": fem_form}
                    save_qc_forms()
                    st.success(
                        "🎉 Full Study QC Completed & Saved!"
                        if get_qc_completion_status(record_key)[0]
                        else "✅ Growth Scan QC Form Saved!"
                    )
                    st.rerun(scope="fragment")

    # ── TAB 4 : ANOMALY SCAN FORM ──────────────────────────
    with tab_form_03:
        with st.container(height=680, border=False):
            st.subheader("🔍 Anomaly Scan Form")
            col1, col2, col3 = st.columns([1.5, 1.5, 1])
            with col1:
                doctor_a = st.selectbox("Doctor's Name", options=doctor_options, key=f"{study_uid}_doc_a",
                                        index=current_index)
            with col2:
                st.text_input("Case No.", value=patient_id, disabled=True, key=f"{study_uid}_case_a")
            with col3:
                st.text_input("Scan Date", value=display_date, disabled=True, key=f"{study_uid}_date_a")

            head_tv_form = criterion_block("Head TV", f"{study_uid}_a_htv", ANOMALY_HEAD_TV_LABELS, record_key,
                                           "Anomaly", "head_tv")
            head_tc_form = criterion_block("Head TC", f"{study_uid}_a_htc", ANOMALY_HEAD_TC_LABELS, record_key,
                                           "Anomaly", "head_tc")
            anom_abd_form = criterion_block("Abdomen", f"{study_uid}_a_abd", ANOMALY_ABDOMEN_LABELS, record_key,
                                            "Anomaly", "anom_abd")
            anom_fem_form = criterion_block("Femur", f"{study_uid}_a_fem", ANOMALY_FEMUR_LABELS, record_key, "Anomaly",
                                            "anom_fem")
            spine_form = criterion_block("Spine", f"{study_uid}_a_spine", ANOMALY_SPINE_LABELS, record_key, "Anomaly",
                                         "spine")
            face_form = criterion_block("Coronal Face", f"{study_uid}_a_face", ANOMALY_FACE_LABELS, record_key,
                                        "Anomaly", "face")

            form_validation_error = st.empty()
            if st.button("💾 Save Anomaly QC", use_container_width=True, type="primary", key=f"save_a_{study_uid}"):
                missing = []
                if not validate_block(head_tv_form, len(ANOMALY_HEAD_TV_LABELS)):
                    missing.append("Head TV")
                if not validate_block(head_tc_form, len(ANOMALY_HEAD_TC_LABELS)):
                    missing.append("Head TC")
                if not validate_block(anom_abd_form, len(ANOMALY_ABDOMEN_LABELS)):
                    missing.append("Abdomen")
                if not validate_block(anom_fem_form, len(ANOMALY_FEMUR_LABELS)):
                    missing.append("Femur")
                if not validate_block(spine_form, len(ANOMALY_SPINE_LABELS)):
                    missing.append("Spine")
                if not validate_block(face_form, len(ANOMALY_FACE_LABELS)):
                    missing.append("Coronal Face")

                if missing:
                    form_validation_error.error(
                        f"⚠️ Cannot save Anomaly Form: Please complete all Overall and Criterion selections for: {', '.join(missing)}")
                else:
                    if record_key not in st.session_state.qc_forms:
                        st.session_state.qc_forms[record_key] = {}
                    st.session_state.qc_forms[record_key]["details"] = {
                        "case_no": patient_id.rstrip("__"),
                        "doctor": doctor_a,
                        "patient_id": patient_id,
                        "study_uid": study_uid,
                        "date": display_date,
                        "image_count": len(file_items),
                        "last_reviewed": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    st.session_state.qc_forms[record_key]["Anomaly"] = {
                        "head_tv": head_tv_form,
                        "head_tc": head_tc_form,
                        "anom_abd": anom_abd_form,
                        "anom_fem": anom_fem_form,
                        "spine": spine_form,
                        "face": face_form,
                    }
                    save_qc_forms()
                    st.success(
                        "🎉 Full Study QC Completed & Saved!"
                        if get_qc_completion_status(record_key)[0]
                        else "✅ Anomaly Scan QC Form Saved!"
                    )
                    st.rerun(scope="fragment")


with right:
    render_qc_forms_panel(study_uid, patient_id, display_date, file_items, study_sr, record_key)

# =========================================================
# DEBUG PANEL (FULL ATTRIBUTE INSPECTOR)
# =========================================================
with st.expander("🔍 Debug Info"):
    # 1. Primary UIDs & Path
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.write("**Study UID**")
        st.code(study_uid)
    with col_b:
        st.write("**Viewport Series UID**")
        st.code(st.session_state.current_series_uid)
    with col_c:
        st.write("**Viewport SOP UID**")
        st.code(st.session_state.current_sop_uid)

    st.write("**Viewport Image Path:**")
    st.code(st.session_state.current_image_path)

    st.divider()

    # 2. Active Image Formatted Attributes
    st.markdown("### 🏷️ Active Image Metadata")
    active_rows = study_df[study_df["FilePath"] == st.session_state.current_image_path]

    if not active_rows.empty:
        curr_meta = active_rows.iloc[0].to_dict()

        d_col1, d_col2, d_col3, d_col4 = st.columns(4)

        with d_col1:
            st.markdown("**Patient & Study**")
            st.caption(f"🆔 **PatientID:** `{curr_meta.get('PatientID') or 'N/A'}`")
            st.caption(f"👤 **PatientName:** `{curr_meta.get('PatientName') or 'N/A'}`")
            st.caption(f"📅 **StudyDate:** `{curr_meta.get('StudyDate') or 'N/A'}`")
            st.caption(f"📡 **Modality:** `{curr_meta.get('Modality') or 'N/A'}`")

        with d_col2:
            st.markdown("**Operator & Physician**")
            st.caption(f"👨‍⚕️ **OperatorsName:** `{curr_meta.get('OperatorsName') or 'N/A (Blank in DCM)'}`")
            st.caption(f"🩺 **PerformingPhysician:** `{curr_meta.get('PerformingPhysicianName') or 'N/A'}`")
            st.caption(f"📋 **Protocol:** `{curr_meta.get('ProtocolName') or 'None'}`")

        with d_col3:
            st.markdown("**Device & Institution**")
            st.caption(f"🏦 **Institution:** `{curr_meta.get('InstitutionName') or 'N/A'}`")
            st.caption(f"📟 **Model:** `{curr_meta.get('ManufacturerModelName') or 'N/A'}`")
            st.caption(f"🔢 **Serial No:** `{curr_meta.get('DeviceSerialNumber') or 'N/A'}`")

        with d_col4:
            st.markdown("**Image Specs & Comments**")
            st.caption(f"🎞️ **Frames:** `{curr_meta.get('NumberOfFrames', 1)}`")
            st.caption(f"📐 **Resolution:** `{curr_meta.get('Rows', 0)} x {curr_meta.get('Columns', 0)}`")
            st.caption(f"💬 **Comments:** `{curr_meta.get('ImageComments') or 'None'}`")

        # Raw Dictionary Dump
        with st.popover("📋 Inspect Raw Active Image Dictionary"):
            st.json(curr_meta)
    else:
        st.info("No metadata row found for current active file path.")

    st.divider()

    # 3. SR Files & Extracted Measurements
    st.write(f"**Study SR Files Detected:** {len(study_sr_files)}")
    if not study_sr_files.empty:
        st.dataframe(study_sr_files[["FileName", "SOPInstanceUID"]], use_container_width=True)

    if not study_sr.empty:
        st.markdown("**Extracted Measurements (All SRs):**")
        st.dataframe(study_sr, use_container_width=True)
        st.write("**Referenced SOP UIDs:**", study_sr["ReferencedSOPInstanceUID"].unique().tolist())
