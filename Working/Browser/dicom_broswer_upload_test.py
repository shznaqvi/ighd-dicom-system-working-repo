import json
import os
import shutil
import time
from pathlib import Path

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

# ── Sticky image column + scrollable right panel ──────────
st.markdown("""
<style>
/* Pin the image column so it stays visible while the form scrolls */
[data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child {
    position: sticky;
    top: 3.5rem;
    align-self: flex-start;
}
[data-testid="stHorizontalBlock"] {
    align-items: flex-start;
}
</style>
""", unsafe_allow_html=True)

# =========================================================
# SESSION STATE
# =========================================================
for key, default in [
    ("selected_image", None),
    ("cancel_import", False),
    ("importing", False),
    ("viability_forms", {}),
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
# IMPORT
# =========================================================
def import_dicom_folder(source_folder, dest_root, warning_ph):
    """Copy DICOM files from user's local folder into the app's data folder."""
    if not source_folder:
        warning_ph.error("Provide a source folder path.", icon="⚠️")
        return 0
    source_folder = Path(source_folder)
    if not source_folder.exists():
        warning_ph.error(f"Path does not exist: {source_folder}", icon="⚠️")
        return 0
    dicom_files = list(source_folder.rglob("*.dcm"))
    if not dicom_files:
        warning_ph.warning("No DICOM files found in that folder.")
        return 0
    total, copied, skipped = len(dicom_files), 0, 0
    start = time.time()
    progress = st.progress(0)
    status = st.empty()
    metrics = st.empty()
    for i, fp in enumerate(dicom_files):
        if st.session_state.cancel_import:
            status.warning("⛔ Import cancelled.")
            break
        try:
            rel = fp.relative_to(source_folder)
            target = Path(dest_root) / rel
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
        status.write(f"Copying: {i + 1}/{total} | {fp.name}")
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
@st.cache_data(show_spinner=True, ttl=300)
def scan_dicom_folder(folder):
    images, sr_files = [], []
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


def criterion_block(title, block_key, existing=None):
    """
    title      : display heading
    block_key  : unique key = f"{sop_uid}_{block_name}"
    existing   : dict from saved form (or {})
    """
    if existing is None:
        existing = {}
    existing_crits = existing.get("criteria", {})

    st.markdown(f"**{title}**")

    overall_saved = existing.get("overall", "Acceptable")
    overall_idx = CRITERION_OPTIONS.index(overall_saved) \
        if overall_saved in CRITERION_OPTIONS else 0

    overall = st.radio(
        "Overall",
        CRITERION_OPTIONS,
        index=overall_idx,
        key=f"{block_key}_overall",
        horizontal=True,
    )

    crits = {}
    cols = st.columns(3)
    for i in range(1, 7):
        saved = existing_crits.get(f"crit_{i}", "Acceptable")
        idx = CRITERION_OPTIONS.index(saved) if saved in CRITERION_OPTIONS else 0
        with cols[(i - 1) % 3]:
            crits[f"crit_{i}"] = st.radio(
                f"C{i}",
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

with st.sidebar.expander("📥 Import DICOM Files", expanded=True):
    st.caption("Copy DICOM files from your local folder into the app data folder.")

    local_folder = st.text_input(
        "Your local folder path",
        placeholder=r"e.g. C:\Users\you\Downloads\scans",
    )
    st.caption(f"**Destination:** `{dicom_dir}`")

    warning_placeholder = st.empty()

    if st.session_state.importing:
        if st.button("🛑 Cancel", use_container_width=True):
            st.session_state.cancel_import = True

    if st.button("📥 Import Folder", use_container_width=True):
        st.session_state.cancel_import = False
        st.session_state.importing = True
        count = import_dicom_folder(local_folder, dicom_dir, warning_placeholder)
        st.session_state.importing = False
        st.session_state.cancel_import = False
        if count > 0:
            st.success(f"✅ Imported {count} file(s).")
        elif local_folder:
            st.info("No new files (all already exist or folder was empty).")
        elif local_folder:
            st.info("No new files copied (all already exist or folder empty).")

scan_button = st.sidebar.button("🔍 Scan DICOM Folder")

# =========================================================
# LOAD / SCAN
# =========================================================
if scan_button:
    with st.spinner("Scanning…"):
        df_images, df_sr = scan_dicom_folder(dicom_dir)
    st.session_state["df_images"] = df_images
    st.session_state["df_sr"] = df_sr

if "df_images" not in st.session_state:
    st.info("Click **🔍 Scan DICOM Folder** in the sidebar to begin.")
    st.stop()

df_images = st.session_state["df_images"]
df_sr = st.session_state["df_sr"]

if df_images.empty:
    st.warning("No US images found.")
    st.stop()

# =========================================================
# PATIENT / STUDY SELECTION
# =========================================================
top1, top2, _ = st.columns([1, 1, 1])
with top1:
    patient_id = st.selectbox("👤 Patient", sorted(df_images["PatientID"].unique()))

patient_df = df_images[df_images["PatientID"] == patient_id]
study_map = patient_df[["StudyDate", "StudyInstanceUID"]].drop_duplicates()

with top2:
    study_date = st.selectbox("📅 Study Date", sorted(study_map["StudyDate"].unique()))

study_uid = study_map[study_map["StudyDate"] == study_date]["StudyInstanceUID"].iloc[0]
study_df = patient_df[patient_df["StudyInstanceUID"] == study_uid].sort_values("InstanceNumber")


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

# =========================================================
# SIDEBAR THUMBNAILS
# =========================================================
st.sidebar.markdown("## 🖼️ Thumbnails")
MAX_THUMBS = 24
for i in range(0, min(len(file_items), MAX_THUMBS), 2):
    c1, c2 = st.sidebar.columns(2)
    label1, path1 = file_items[i]
    with c1:
        img1 = load_pixel_array(path1)
        if img1 is not None:
            st.image(img1, use_container_width=True)
        qc_done1 = path1 in [
            row.get("image_path") for row in st.session_state.viability_forms.values()
        ]
        label_btn1 = "✅" if qc_done1 else "Select"
        if st.button(label_btn1, key=f"btn_{i}"):
            st.session_state.selected_image = path1
            st.rerun()
    if i + 1 < len(file_items):
        label2, path2 = file_items[i + 1]
        with c2:
            img2 = load_pixel_array(path2)
            if img2 is not None:
                st.image(img2, use_container_width=True)
            qc_done2 = path2 in [
                row.get("image_path") for row in st.session_state.viability_forms.values()
            ]
            label_btn2 = "✅" if qc_done2 else "Select"
            if st.button(label_btn2, key=f"btn_{i + 1}"):
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

# =========================================================
# MAIN LAYOUT — image left, report + QC form right
# =========================================================
left, right = st.columns([6, 4])

# ── IMAGE ─────────────────────────────────────────────────
with left:
    st.subheader("🖼️ Ultrasound Image")

    # Show QC badge for this image
    if image_sop_uid in st.session_state.viability_forms:
        st.success("✅ QC form saved for this image")
    else:
        st.warning("⚠️ QC not yet completed for this image")

    pixel_data = load_pixel_array(image_path)
    if pixel_data is not None:
        fig, ax = plt.subplots(figsize=(9, 9))
        ax.imshow(pixel_data, cmap="gray")
        ax.axis("off")
        st.pyplot(fig, use_container_width=True)
    else:
        st.warning("Could not decode pixel data.")

# ── REPORT + FORM ─────────────────────────────────────────
with right:
    tab_report, tab_form = st.tabs(["📊 Structured Report", "🧪 QC Viability Form"])

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
            AgGrid(image_sr, gridOptions=gb.build(),
                   use_container_width=True, height=320)
        else:
            st.info("No SR measurements found for this image.")

    # ── TAB 2 : QC VIABILITY FORM (per image) ─────────────
    with tab_form:
        with st.container(height=680, border=False):
            st.subheader("🧪 QC Viability Form")
            st.caption(f"Image: `{os.path.basename(image_path)}`")

            # Load existing saved form for this image (if any)
            existing = st.session_state.viability_forms.get(image_sop_uid, {})

            # ── Doctor / Case / Date ───────────────────────
            col1, col2 = st.columns(2)
            with col1:
                doctor_options = ["Dr. A", "Dr. B", "Dr. C"]
                doctor_saved = existing.get("doctor", "Dr. A")
                doctor_idx = doctor_options.index(doctor_saved) \
                    if doctor_saved in doctor_options else 0
                doctor = st.selectbox(
                    "Doctor's Name", doctor_options,
                    index=doctor_idx,
                    key=f"{image_sop_uid}_doctor",
                )
            with col2:
                case_no = st.text_input(
                    "Case No.",
                    value=existing.get("case_no", ""),
                    key=f"{image_sop_uid}_case_no",
                )

            date_saved = existing.get("date", None)
            date_value = pd.to_datetime(date_saved).date() \
                if date_saved else pd.Timestamp.today().date()
            scan_date = st.date_input(
                "Scan Date",
                value=date_value,
                key=f"{image_sop_uid}_date",
            )

            st.divider()

            # ── CRL criteria ──────────────────────────────
            crl_form = criterion_block(
                "Crown Rump Length (CRL)",
                f"{image_sop_uid}_crl",
                existing.get("crl", {}),
            )

            st.divider()

            # ── NT criteria ───────────────────────────────
            nt_form = criterion_block(
                "Nuchal Translucency (NT)",
                f"{image_sop_uid}_nt",
                existing.get("nt", {}),
            )

            st.divider()

            # ── SAVE ──────────────────────────────────────
            if st.button("💾 Save QC Record", use_container_width=True, type="primary"):
                st.session_state.viability_forms[image_sop_uid] = {
                    "image_path": image_path,
                    "doctor": doctor,
                    "case_no": case_no,
                    "date": str(scan_date),
                    "crl": crl_form,
                    "nt": nt_form,
                }
                save_viability_forms()
                st.success("✅ QC record saved!")
                st.rerun()

            # ── PROGRESS ──────────────────────────────────
            total_images = len(file_items)
            qc_done = sum(
                1 for _, p in file_items
                if str(pydicom.dcmread(p, stop_before_pixels=True).SOPInstanceUID)
                in st.session_state.viability_forms
            ) if total_images <= 50 else "—"
            st.caption(f"QC Progress: {qc_done} / {total_images} images in this study")

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
