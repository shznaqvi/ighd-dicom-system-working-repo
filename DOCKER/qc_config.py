"""
Salomon 6-Point Obstetric Ultrasound Quality Control Configuration
===================================================================

Dedicated configuration and scoring engine executing Prof. Laurent J. Salomon's
6-point objective quality control criteria for fetal biometry planes.

References:
    - Salomon, L. J., et al. (2006). Ultrasound Obstet Gynecol, 27(1), 34–40.
    - Salomon, L. J., et al. (2019). Ultrasound Obstet Gynecol, 53(6), 715–723.
"""

from typing import Dict, Any

# ==============================================================================
# SALOMON 6-POINT CRITERIA SCHEMA
# ==============================================================================
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

PASS_THRESHOLD_PLANE_SCORE = 5  # 5 out of 6 points (83.3%)
PASS_THRESHOLD_STUDY_PCT = 80.0  # Aggregate 80% passing threshold


def compute_salomon_plane_score(scores: Dict[str, int]) -> Dict[str, Any]:
    """Calculates Salomon raw score and pass/fail verdict for a single plane."""
    raw_score = sum(1 for v in scores.values() if v == 1)
    max_score = 6
    pct = round((raw_score / max_score) * 100.0, 1)
    is_pass = raw_score >= PASS_THRESHOLD_PLANE_SCORE

    return {
        "raw_score": raw_score,
        "max_score": max_score,
        "pct_score": pct,
        "is_pass": is_pass,
    }
