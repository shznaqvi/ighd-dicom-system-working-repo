"""
Salomon 6-Point Obstetric Ultrasound Quality Control Reviewer
=============================================================

Optimized Streamlit reviewer executing Prof. Laurent J. Salomon's 6-point objective
quality control criteria for fetal biometry planes (BPD/HC, AC, FL, CRL).

Key Architectural Features:
    - Blinded Research Workflow: Indexed by Participant ID, Follow-up Date, and Performing Physician.
    - Performance Isolation: @st.fragment isolates form updates (checkboxes/dropdowns) to prevent full-page reloads.
    - Caching Layer: @st.cache_data caches DICOM directory scanning and pixel decoding.
    - GA Auto-Rollover: Accepts decimal notation (Weeks.Days) and automatically rolls over days >= 7 (e.g., 19.7 -> 20.0).

References:
    - Salomon, L. J., et al. (2006). Ultrasound Obstet Gynecol, 27(1), 34–40.
    - Salomon, L. J., et al. (2019). Ultrasound Obstet Gynecol, 53(6), 715–723.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import numpy as np
import pydicom
import streamlit as st
from PIL import Image

# Import Salomon Configuration from qc_config if available, otherwise fallback
try:
    from qc_config import SALOMON_QC_CONFIG, compute_salomon_plane_score
except ImportError:
    SALOMON_QC_CONFIG: Dict[str, Dict[str, Any]] = {
        "BPD_HC": {
            "title": "BPD / Head Circumference (Transthalamic Plane)",
            "max_score": 6,
            "criteria": [
                ("symmetrical_shape", "1. Symmetrical cross-section (oval shape)"),
                ("falx_cerebri", "2. Midline falx cerebri continuous"),
                ("cavum_septi_pellucidi", "3. Cavum septi pellucidi (CSP) visible"),
                ("thalami_symmetry", "4. Both thalami visible & symmetrical"),
                ("cerebellum_absent", "5. Cerebellum NOT visible in trans-thalamic plane"),
                ("magnification_calipers", "6. Proper magnification & calipers (head fills >50% frame)"),
            ],
        },
        "AC": {
            "title": "Abdominal Circumference (Transverse Abdomen)",
            "max_score": 6,
            "criteria": [
                ("circular_shape", "1. Circular cross-section"),
                ("umbilical_vein", "2. Umbilical vein visible at portal sinus ('J' shape)"),
                ("stomach_bubble", "3. Stomach bubble visible"),
                ("kidneys_lungs_absent", "4. Kidneys and lungs NOT visible"),
                ("symmetrical_ribs", "5. Symmetrical short ribs (single pair visible)"),
                ("magnification_calipers", "6. Proper magnification & calipers (abdomen fills >50% frame)"),
            ],
        },
        "FL": {
            "title": "Femur Length (Diaphysis Axis)",
            "max_score": 6,
            "criteria": [
                ("diaphysis_visible", "1. Both ends of diaphysis clearly visible"),
                ("horizontal_alignment", "2. Diaphysis horizontal alignment (<45° angle)"),
                ("no_epiphysis", "3. No femoral epiphysis included in measurement"),
                ("perpendicular_beam", "4. Beam-to-bone angle near 90° (perpendicular)"),
                ("sharp_interface", "5. Sharp bone-tissue acoustic interface"),
                ("magnification_calipers", "6. Proper magnification & calipers (femur fills >50% width)"),
            ],
        },
        "CRL": {
            "title": "Crown-Rump Length (1st Trimester Profile)",
            "max_score": 6,
            "criteria": [
                ("midsagittal_profile", "1. Mid-sagittal view (profile, tip of nose & spine visible)"),
                ("horizontal_alignment", "2. Horizontal alignment of fetus (<30° to horizontal)"),
                ("amniotic_membrane", "3. Amniotic membrane clearly distinguished from fetus"),
                ("caliper_placement", "4. Caliper placement: crown to rump (excl. yolk sac/limbs)"),
                ("neutral_position", "5. Neutral fetal position (no hyper-extension/flexion)"),
                ("magnification_calipers", "6. Proper magnification (fetus fills >60% frame)"),
            ],
        },
    }


    def compute_salomon_plane_score(scores: Dict[str, int]) -> Dict[str, Any]:
        raw_score = sum(1 for v in scores.values() if v == 1)
        max_score = 6
        pct = round((raw_score / max_score) * 100.0, 1)
        is_pass = raw_score >= 5
        return {
            "raw_score": raw_score,
            "max_score": max_score,
            "pct_score": pct,
            "is_pass": is_pass,
        }

# ------------------------------------------------------------------------------
# Configuration & Environment
# ------------------------------------------------------------------------------
DICOM_DIR = Path(os.getenv("DICOM_DIR", "/raw_data"))
QC_FILE_PATH = Path(os.getenv("QC_FILE", "/qc_data/salomon_qc.json"))

COMMON_DEFECT_REASONS = [
    "Suboptimal anatomical plane section",
    "Inadequate magnification / scaling",
    "Improper caliper positioning",
    "Acoustic shadowing / attenuation",
    "Fetal motion artifact",
    "Incorrect gain / contrast settings",
    "Non-perpendicular beam orientation",
    "Inclusion of non-target anatomical structures",
]


# ------------------------------------------------------------------------------
# JSON Persistence Handlers
# ------------------------------------------------------------------------------
def load_qc_database(file_path: Path) -> Dict[str, Any]:
    """Loads JSON database safely, returning empty dict if missing or corrupt."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Error loading QC database ({file_path}): {e}")
        return {}


def save_qc_database(file_path: Path, data: Dict[str, Any]) -> bool:
    """Writes QC payload to JSON using atomic write via temporary file."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=file_path.parent, delete=False, encoding="utf-8") as tf:
            json.dump(data, tf, indent=2, ensure_ascii=False)
            temp_name = tf.name
        os.replace(temp_name, file_path)
        return True
    except Exception as e:
        st.error(f"Failed to persist QC data: {e}")
        return False


# ------------------------------------------------------------------------------
# Cached Heavy File I/O Operations (Blinded Metadata Clustering)
# ------------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def scan_dicom_directory_cached(base_dir_str: str) -> Dict[str, Dict[str, Any]]:
    """
    Scans directory and clusters DICOM paths under a blinded research key:
    {participant_id}_{raw_date}
    """
    base_dir = Path(base_dir_str)
    studies: Dict[str, Dict[str, Any]] = {}
    if not base_dir.exists():
        return studies

    for entry in base_dir.rglob("*"):
        if entry.is_file() and not entry.name.startswith("."):
            try:
                ds = pydicom.dcmread(entry, stop_before_pixels=True, force=True)

                participant_id = str(getattr(ds, "PatientID", "UNKNOWN_PARTICIPANT")).strip()
                raw_date = str(getattr(ds, "StudyDate", "UNKNOWN_DATE")).strip()

                if len(raw_date) == 8 and raw_date.isdigit():
                    followup_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
                else:
                    followup_date = raw_date

                physician = str(
                    getattr(ds, "PerformingPhysicianName",
                            getattr(ds, "OperatorsName", "UNSPECIFIED_PHYSICIAN"))
                ).strip()

                study_key = f"{participant_id}_{raw_date}"

                if study_key not in studies:
                    studies[study_key] = {
                        "participant_id": participant_id,
                        "followup_date": followup_date,
                        "performing_physician_name": physician,
                        "file_paths": []
                    }

                studies[study_key]["file_paths"].append(str(entry))

            except Exception:
                continue

    return studies


@st.cache_data(show_spinner=False)
def load_dicom_image_cached(file_path_str: str) -> Tuple[Optional[Image.Image], Dict[str, Any]]:
    """Decodes DICOM pixel payload into PIL image and extracts blinded research attributes."""
    file_path = Path(file_path_str)
    try:
        ds = pydicom.dcmread(file_path, force=True)
        raw_date = str(getattr(ds, "StudyDate", "UNKNOWN_DATE")).strip()
        followup_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}" if len(
            raw_date) == 8 and raw_date.isdigit() else raw_date

        meta = {
            "participant_id": str(getattr(ds, "PatientID", "UNKNOWN_PARTICIPANT")).strip(),
            "followup_date": followup_date,
            "performing_physician_name": str(
                getattr(ds, "PerformingPhysicianName",
                        getattr(ds, "OperatorsName", "UNSPECIFIED_PHYSICIAN"))
            ).strip(),
            "SOPInstanceUID": str(getattr(ds, "SOPInstanceUID", file_path.stem)),
            "Modality": str(getattr(ds, "Modality", "US")),
            "Manufacturer": str(getattr(ds, "Manufacturer", "N/A")),
            "Filename": file_path.name
        }

        if "PixelData" not in ds:
            return None, meta

        arr = ds.pixel_array.astype(float)

        slope = getattr(ds, "RescaleSlope", 1)
        intercept = getattr(ds, "RescaleIntercept", 0)
        arr = arr * slope + intercept

        min_val, max_val = arr.min(), arr.max()
        if max_val > min_val:
            arr = ((arr - min_val) / (max_val - min_val) * 255.0).astype(np.uint8)
        else:
            arr = np.zeros_like(arr, dtype=np.uint8)

        if arr.ndim == 3 and arr.shape[2] == 3:
            img = Image.fromarray(arr, mode="RGB")
        elif arr.ndim == 2:
            img = Image.fromarray(arr, mode="L").convert("RGB")
        elif arr.ndim == 3 and arr.shape[0] in (1, 3):
            arr = np.transpose(arr, (1, 2, 0))
            img = Image.fromarray(arr, mode="RGB")
        else:
            img = Image.fromarray(arr.astype(np.uint8))

        return img, meta
    except Exception as e:
        return None, {"Error": str(e), "Filename": file_path.name, "SOPInstanceUID": file_path.stem}


# ------------------------------------------------------------------------------
# Isolated Form Component (@st.fragment)
# ------------------------------------------------------------------------------
@st.fragment
def render_salomon_qc_form(
        selected_study_key: str,
        sop_instance_uid: str,
        participant_id: str,
        followup_date: str,
        performing_physician_name: str,
        reviewer_id: str,
        qc_file_path: Path
):
    """Isolated Streamlit fragment. Reruns locally on checkbox/dropdown changes without reloading full page."""
    st.subheader("📝 6-Point Quality Evaluation")

    # Load active database state
    qc_db = load_qc_database(qc_file_path)
    existing_study = qc_db.get(selected_study_key, {})
    existing_planes = existing_study.get("planes", {})
    existing_plane_data = existing_planes.get(sop_instance_uid, {})

    # Load saved plane choice or default to BPD_HC
    saved_plane = existing_plane_data.get("plane_type", "BPD_HC")
    if saved_plane not in SALOMON_QC_CONFIG:
        saved_plane = "BPD_HC"

    default_index = list(SALOMON_QC_CONFIG.keys()).index(saved_plane)

    plane_type = st.selectbox(
        "Anatomical Biometry Plane",
        options=list(SALOMON_QC_CONFIG.keys()),
        format_func=lambda k: SALOMON_QC_CONFIG[k]["title"],
        index=default_index,
        key=f"select_plane_{sop_instance_uid}"
    )

    st.markdown("---")
    st.markdown(f"**Criteria Checklist for {plane_type}:**")

    plane_spec = SALOMON_QC_CONFIG[plane_type]
    criteria_list = plane_spec["criteria"]
    existing_scores = existing_plane_data.get("scores", {})

    current_scores = {}
    for key, description in criteria_list:
        default_val = bool(existing_scores.get(key, 0))
        is_checked = st.checkbox(
            description,
            value=default_val,
            key=f"chk_{sop_instance_uid}_{plane_type}_{key}"
        )
        current_scores[key] = 1 if is_checked else 0

    # Real-time score computation
    score_metrics = compute_salomon_plane_score(current_scores)
    total_score = score_metrics["raw_score"]
    plane_status = "PASS" if score_metrics["is_pass"] else "FAIL"

    st.markdown("---")
    st.markdown("### Score Summary")
    if plane_status == "PASS":
        st.markdown(f"<div class='score-pass'>Score: {total_score} / 6 — PASS</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='score-fail'>Score: {total_score} / 6 — DEFECT (FAIL)</div>", unsafe_allow_html=True)

    # Defect selection (Mandatory for failed scores)
    defect_reasons = []
    if plane_status == "FAIL":
        st.warning("Score is below 5/6 (80%). Select defect justification(s):")
        defect_reasons = st.multiselect(
            "Primary Defect Causes",
            options=COMMON_DEFECT_REASONS,
            default=existing_plane_data.get("defect_reasons", []),
            key=f"defects_{sop_instance_uid}_{plane_type}"
        )

    # --------------------------------------------------------------------------
    # Gestational Age Decimal Input with Auto-Rollover Logic (.7 -> 1.0)
    # --------------------------------------------------------------------------
    raw_ga_input = st.number_input(
        "Gestational Age (Weeks.Days)",
        min_value=8.0,
        max_value=42.6,
        value=float(existing_study.get("study_metadata", {}).get("gestational_age_weeks", 20.0)),
        step=0.1,
        format="%.1f",
        key=f"ga_{selected_study_key}"
    )

    weeks = int(raw_ga_input)
    days = int(round((raw_ga_input - weeks) * 10))

    # if days >= 7:
    #     weeks += days // 7
    #     days = days % 7
    #     st.info(f"💡 Day roll-over applied: Saved as **{weeks}w + {days}d**")

    ga_float_weeks = round(weeks + (days / 7.0), 2)
    formatted_ga_str = f"{weeks}w+{days}d"
    total_days = (weeks * 7) + days

    st.caption(f"📅 **Active Value:** `{formatted_ga_str}` ({total_days} total days)")

    # Commit evaluation payload to disk
    if st.button("💾 Save Evaluation to salomon_qc.json", type="primary", use_container_width=True):
        if plane_status == "FAIL" and not defect_reasons:
            st.error("Please select at least one defect reason for failed image evaluations.")
            return

        plane_eval_payload = {
            "plane_type": plane_type,
            "scores": current_scores,
            "total_score": total_score,
            "max_score": 6,
            "plane_status": plane_status,
            "defect_reasons": defect_reasons
        }

        study_node = qc_db.get(selected_study_key, {
            "study_metadata": {
                "participant_id": participant_id,
                "followup_date": followup_date,
                "performing_physician_name": performing_physician_name,
                "reviewer_id": reviewer_id,
                "gestational_age_weeks": ga_float_weeks,
                "gestational_age_formatted": formatted_ga_str,
                "gestational_age_days": total_days,
                "review_timestamp": datetime.now(timezone.utc).isoformat()
            },
            "planes": {},
            "study_summary": {}
        })

        study_node["study_metadata"]["participant_id"] = participant_id
        study_node["study_metadata"]["followup_date"] = followup_date
        study_node["study_metadata"]["performing_physician_name"] = performing_physician_name
        study_node["study_metadata"]["reviewer_id"] = reviewer_id
        study_node["study_metadata"]["gestational_age_weeks"] = ga_float_weeks
        study_node["study_metadata"]["gestational_age_formatted"] = formatted_ga_str
        study_node["study_metadata"]["gestational_age_days"] = total_days
        study_node["study_metadata"]["review_timestamp"] = datetime.now(timezone.utc).isoformat()
        study_node["planes"][sop_instance_uid] = plane_eval_payload

        # Aggregated metrics calculation
        all_planes = study_node["planes"].values()
        earned_pts = sum(p["total_score"] for p in all_planes)
        possible_pts = len(all_planes) * 6
        pct = round((earned_pts / possible_pts) * 100, 2) if possible_pts > 0 else 0.0

        study_node["study_summary"] = {
            "total_planes_evaluated": len(all_planes),
            "total_points_earned": earned_pts,
            "total_points_possible": possible_pts,
            "aggregate_percentage": pct,
            "overall_study_status": "PASS" if pct >= 80.0 else "FAIL"
        }

        qc_db[selected_study_key] = study_node

        if save_qc_database(qc_file_path, qc_db):
            st.success(f"Saved evaluation for instance `{sop_instance_uid[:12]}...`")
            st.balloons()


# ------------------------------------------------------------------------------
# Main Application Layout
# ------------------------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="Salomon 6-Point Ultrasound QC Reviewer",
        page_icon="🩺",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.markdown("""
        <style>
            .stApp { max-width: 100%; }
            .score-pass { font-size: 20px; font-weight: bold; color: #1e7e34; }
            .score-fail { font-size: 20px; font-weight: bold; color: #bd2130; }
        </style>
    """, unsafe_allow_html=True)

    st.title("🩺 Salomon 6-Point Quality Control Engine")
    st.caption("Standardized Obstetric Ultrasound Biometry Audit System (Salomon et al., 2006, 2019)")

    # --------------------------------------------------------------------------
    # Sidebar Operations (Blinded Selection)
    # --------------------------------------------------------------------------
    st.sidebar.header("📋 Review Operations")
    reviewer_id = st.sidebar.text_input("Reviewer ID / Staff Code", value="")

    # Cached directory scanning
    dicom_studies = scan_dicom_directory_cached(str(DICOM_DIR))

    if not dicom_studies:
        st.warning(f"No valid DICOM files found under target directory: `{DICOM_DIR}`")
        st.info("Verify host directory mounts or upload fresh DICOM files via the ingestion pipeline.")
        return

    study_keys = list(dicom_studies.keys())

    # Blinded dropdown menu displaying Participant ID & Follow-up Date
    selected_study_key = st.sidebar.selectbox(
        "Select Participant Visit",
        options=study_keys,
        format_func=lambda
            k: f"Participant: {dicom_studies[k]['participant_id']} | Date: {dicom_studies[k]['followup_date']}"
    )

    study_data = dicom_studies[selected_study_key]
    files_in_study = study_data["file_paths"]

    selected_file_path_str = st.sidebar.selectbox(
        "Select Image Instance",
        options=files_in_study,
        format_func=lambda p: Path(p).name
    )

    # Cached image decoding
    img, meta = load_dicom_image_cached(selected_file_path_str)

    participant_id = meta.get("participant_id", study_data["participant_id"])
    followup_date = meta.get("followup_date", study_data["followup_date"])
    performing_physician_name = meta.get("performing_physician_name", study_data["performing_physician_name"])
    sop_instance_uid = meta.get("SOPInstanceUID", Path(selected_file_path_str).stem)

    # Blinded study header
    st.info(
        f"🆔 **Participant ID:** `{participant_id}` | 📅 **Follow-up Date:** `{followup_date}` | 🩺 **Physician/Sonographer:** `{performing_physician_name}`")

    # --------------------------------------------------------------------------
    # Main 2-Column Split: Viewport vs Isolated Evaluation Fragment
    # --------------------------------------------------------------------------
    col_viewport, col_form = st.columns([3, 2], gap="medium")

    with col_viewport:
        st.subheader("📷 Image Viewport")
        if img:
            st.image(img, use_container_width=True, caption=f"Instance UID: {sop_instance_uid}")
        else:
            st.error("Unable to render pixel array for selected DICOM instance.")

        with st.expander("🔍 Extended DICOM Metadata"):
            st.json({
                "Modality": meta.get("Modality", "US"),
                "Manufacturer": meta.get("Manufacturer", "N/A"),
                "Filename": meta.get("Filename", "N/A"),
                "SOPInstanceUID": sop_instance_uid
            })

    with col_form:
        # Isolated Streamlit Fragment call
        render_salomon_qc_form(
            selected_study_key=selected_study_key,
            sop_instance_uid=sop_instance_uid,
            participant_id=participant_id,
            followup_date=followup_date,
            performing_physician_name=performing_physician_name,
            reviewer_id=reviewer_id,
            qc_file_path=QC_FILE_PATH
        )


if __name__ == "__main__":
    main()
