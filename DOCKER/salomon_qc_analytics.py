# salomon_qc_analytics.py
# Standalone Salomon 6-Point Quality Control Analytics & Scorecard Dashboard (Port 8505)
"""
Salomon 6-Point Quality Control Analytics & Physician Scorecard Dashboard
==========================================================================

Streamlit analytics module providing sonographer scorecards, defect heatmaps,
and longitudinal compliance reporting parsed from persistent `salomon_qc.json` payloads.

References:
    - Salomon, L. J., et al. (2006). Ultrasound Obstet Gynecol, 27(1), 34–40.
    - Salomon, L. J., et al. (2019). Ultrasound Obstet Gynecol, 53(6), 715–723.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any

import pandas as pd
import plotly.express as px
import streamlit as st

# ------------------------------------------------------------------------------
# Configuration & Environment
# ------------------------------------------------------------------------------
QC_FILE_PATH = Path(os.getenv("QC_FILE", "/qc_data/salomon_qc.json"))


# ------------------------------------------------------------------------------
# Data Loading & Ingestion Engine
# ------------------------------------------------------------------------------
def load_raw_qc_json(file_path: Path) -> Dict[str, Any]:
    """Safely loads the JSON audit payload from host storage."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Error reading JSON database ({file_path}): {e}")
        return {}


def parse_qc_database(raw_db: Dict[str, Any]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Flattens the hierarchical study JSON into structured Pandas DataFrames.

    Returns:
        Tuple containing:
            - studies_df: High-level study summary metrics.
            - planes_df: Granular plane-level scores and defect details.
    """
    study_records = []
    plane_records = []

    for study_uid, study_data in raw_db.items():
        meta = study_data.get("study_metadata", {})
        summary = study_data.get("study_summary", {})

        study_records.append({
            "study_instance_uid": study_uid,
            "patient_id": meta.get("patient_id", "N/A"),
            "operator_id": meta.get("operator_id", "UNASSIGNED"),
            "reviewer_id": meta.get("reviewer_id", "N/A"),
            "gestational_age_weeks": meta.get("gestational_age_weeks", None),
            "review_timestamp": meta.get("review_timestamp", None),
            "total_planes_evaluated": summary.get("total_planes_evaluated", 0),
            "total_points_earned": summary.get("total_points_earned", 0),
            "total_points_possible": summary.get("total_points_possible", 0),
            "aggregate_percentage": summary.get("aggregate_percentage", 0.0),
            "overall_study_status": summary.get("overall_study_status", "PENDING")
        })

        for sop_uid, plane_data in study_data.get("planes", {}).items():
            defects = plane_data.get("defect_reasons", [])
            plane_records.append({
                "study_instance_uid": study_uid,
                "sop_instance_uid": sop_uid,
                "operator_id": meta.get("operator_id", "UNASSIGNED"),
                "plane_type": plane_data.get("plane_type", "UNKNOWN"),
                "total_score": plane_data.get("total_score", 0),
                "max_score": plane_data.get("max_score", 6),
                "plane_status": plane_data.get("plane_status", "FAIL"),
                "defect_reasons": defects if defects else ["None"],
                "review_timestamp": meta.get("review_timestamp", None)
            })

    studies_df = pd.DataFrame(study_records)
    planes_df = pd.DataFrame(plane_records)

    if not studies_df.empty and "review_timestamp" in studies_df.columns:
        studies_df["review_timestamp"] = pd.to_datetime(studies_df["review_timestamp"], errors="coerce")
    if not planes_df.empty and "review_timestamp" in planes_df.columns:
        planes_df["review_timestamp"] = pd.to_datetime(planes_df["review_timestamp"], errors="coerce")

    return studies_df, planes_df


# ------------------------------------------------------------------------------
# Main Application
# ------------------------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="Salomon Ultrasound QC Analytics",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("📊 Salomon 6-Point Quality Control Analytics")
    st.caption("Sonographer Scorecards & Systematic Defect Monitoring (ISUOG Guidelines)")

    raw_db = load_raw_qc_json(QC_FILE_PATH)
    studies_df, planes_df = parse_qc_database(raw_db)

    if studies_df.empty or planes_df.empty:
        st.warning(f"No evaluated studies found in database at `{QC_FILE_PATH}`.")
        st.info("Perform quality evaluations using the Salomon DICOM Reviewer to populate analytics.")
        return

    # --------------------------------------------------------------------------
    # Sidebar Filters
    # --------------------------------------------------------------------------
    st.sidebar.header("🔍 Filter Analytics")

    operators = ["All Operators"] + sorted(studies_df["operator_id"].dropna().unique().tolist())
    selected_operator = st.sidebar.selectbox("Filter by Operator / Sonographer", options=operators)

    plane_types = ["All Planes"] + sorted(planes_df["plane_type"].dropna().unique().tolist())
    selected_plane = st.sidebar.selectbox("Filter by Anatomical Plane", options=plane_types)

    # Apply Filters
    filtered_studies = studies_df.copy()
    filtered_planes = planes_df.copy()

    if selected_operator != "All Operators":
        filtered_studies = filtered_studies[filtered_studies["operator_id"] == selected_operator]
        filtered_planes = filtered_planes[filtered_planes["operator_id"] == selected_operator]

    if selected_plane != "All Planes":
        filtered_planes = filtered_planes[filtered_planes["plane_type"] == selected_plane]

    # --------------------------------------------------------------------------
    # Top-Level Executive KPIs
    # --------------------------------------------------------------------------
    total_studies_cnt = len(filtered_studies)
    total_planes_cnt = len(filtered_planes)
    passed_planes_cnt = len(filtered_planes[filtered_planes["plane_status"] == "PASS"])
    overall_pass_rate = (passed_planes_cnt / total_planes_cnt * 100.0) if total_planes_cnt > 0 else 0.0
    avg_score = filtered_planes["total_score"].mean() if not filtered_planes.empty else 0.0

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Evaluated Studies", f"{total_studies_cnt}")
    kpi2.metric("Evaluated Planes", f"{total_planes_cnt}")
    kpi3.metric("Plane Pass Rate (≥5/6)", f"{overall_pass_rate:.1f}%")
    kpi4.metric("Mean Salomon Score", f"{avg_score:.2f} / 6.0")

    st.markdown("---")

    # --------------------------------------------------------------------------
    # Tab Navigation
    # --------------------------------------------------------------------------
    tab_scorecard, tab_heatmaps, tab_raw = st.tabs([
        "👨‍⚕️ Physician & Sonographer Scorecards",
        "🔥 Defect Heatmaps & Failure Analysis",
        "📄 Raw Audit Records"
    ])

    # --------------------------------------------------------------------------
    # Tab 1: Operator Scorecards
    # --------------------------------------------------------------------------
    with tab_scorecard:
        st.subheader("Sonographer Performance Matrix")

        # Group metrics by operator
        op_metrics = planes_df.groupby("operator_id").agg(
            total_planes=("sop_instance_uid", "count"),
            passed_planes=("plane_status", lambda s: (s == "PASS").sum()),
            avg_salomon_score=("total_score", "mean")
        ).reset_index()

        op_metrics["pass_rate_pct"] = (op_metrics["passed_planes"] / op_metrics["total_planes"] * 100.0).round(1)
        op_metrics["compliance_tier"] = op_metrics["pass_rate_pct"].apply(
            lambda r: "🟢 Compliant (≥80%)" if r >= 80.0 else "🔴 Suboptimal (<80%)"
        )

        st.dataframe(
            op_metrics[[
                "operator_id", "total_planes", "passed_planes",
                "pass_rate_pct", "avg_salomon_score", "compliance_tier"
            ]].rename(columns={
                "operator_id": "Operator / Sonographer ID",
                "total_planes": "Planes Evaluated",
                "passed_planes": "Planes Passed",
                "pass_rate_pct": "Pass Rate (%)",
                "avg_salomon_score": "Mean Salomon Score",
                "compliance_tier": "Audit Status"
            }),
            use_container_width=True
        )

        # Plotly Bar Chart: Operator Pass Rates vs 80% Benchmark
        fig_op = px.bar(
            op_metrics,
            x="operator_id",
            y="pass_rate_pct",
            color="compliance_tier",
            color_discrete_map={"🟢 Compliant (≥80%)": "#1e7e34", "🔴 Suboptimal (<80%)": "#bd2130"},
            labels={"operator_id": "Operator ID", "pass_rate_pct": "Pass Rate (%)"},
            title="Sonographer Pass Rate vs. 80% ISUOG Quality Threshold",
            text="pass_rate_pct"
        )
        fig_op.add_hline(y=80.0, line_dash="dash", line_color="orange", annotation_text="80% Target")
        fig_op.update_layout(yaxis_range=[0, 105])
        st.plotly_chart(fig_op, use_container_width=True)

    # --------------------------------------------------------------------------
    # Tab 2: Defect Heatmaps
    # --------------------------------------------------------------------------
    with tab_heatmaps:
        st.subheader("Systematic Defect Heatmap")
        st.caption("Distribution of anatomical defect justifications across biometry planes.")

        # Explode defect lists into individual records for failed planes
        failed_planes_df = filtered_planes[filtered_planes["plane_status"] == "FAIL"].explode("defect_reasons")
        failed_planes_df = failed_planes_df[failed_planes_df["defect_reasons"] != "None"]

        if failed_planes_df.empty:
            st.success("🎉 No defect patterns detected across the selected criteria!")
        else:
            # Pivot table: Defect Reason vs Plane Type
            heatmap_pivot = pd.crosstab(
                index=failed_planes_df["defect_reasons"],
                columns=failed_planes_df["plane_type"],
                margins=False
            )

            fig_heatmap = px.imshow(
                heatmap_pivot
