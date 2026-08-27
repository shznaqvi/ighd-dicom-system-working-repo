import re

import pandas as pd


# -----------------------------
# NORMALIZER
# -----------------------------
def norm(x):
    if pd.isna(x):
        return ""
    x = str(x).lower()
    x = re.sub(r"[^a-z0-9\s]", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x


# -----------------------------
# CLINICAL ONTOLOGY MAPPER
# -----------------------------
def normalize_clinical_domain(row):
    m = norm(row["Measurement"])
    cat = row["Category"]

    # ---------------- FORCE FIX: AFI / placenta ----------------
    if any(k in m for k in ["amniotic", "afi", "quadrant", "max vertical pocket", "cisterna magna"]):
        return "AMNIOTIC_PLACENTA"

    # ---------------- BIOMETRY FIX ----------------
    if any(k in m for k in [
        "head circumference", "biparietal", "abdominal circumference",
        "femur length", "occipital frontal", "crown rump",
        "trans cerebellar", "hc", "bpd", "ac", "fl", "of d", "tcd"
    ]):
        return "FETAL_BIOMETRY"

    # ---------------- DOPPLER FIX ----------------
    if any(k in m for k in [
        "pi", "ri", "psv", "edv", "velocity", "ratio",
        "a wave", "e wave", "e a", "v max",
        "ejection time", "preload", "ventricle", "doppler"
    ]):
        return "DOPPLER_CARDIAC"

    # ---------------- OBSTETRIC FIX ----------------
    if any(k in m for k in [
        "gravida", "para", "aborta",
        "fetal heart", "heart rate",
        "nuchal", "cervix", "ectopic"
    ]):
        return "OBSTETRIC_HISTORY"

    # ---------------- DERIVED FIX ----------------
    if any(k in m for k in [
        "zscore", "percentile", "normal range",
        "standard deviation", "population", "lower limit", "upper limit"
    ]):
        return "DERIVED_STATS"

    return cat  # keep original if already correct


# -----------------------------
# MAIN PIPELINE
# -----------------------------
def main():
    df = pd.read_csv("sr_restructured_long.csv")

    print("\nLoading restructured dataset...")
    print("Rows:", len(df))

    # backup original
    df["Category_original"] = df["Category"]

    # apply normalization
    df["Category"] = df.apply(normalize_clinical_domain, axis=1)

    # ---------------- summary ----------------
    print("\n========== AFTER NORMALIZATION ==========")
    print(df["Category"].value_counts())

    # ---------------- UNKNOWN check ----------------
    unknown = df[df["Category"] == "UNKNOWN"]

    print("\nRemaining UNKNOWN:", len(unknown))

    print("\nTop remaining UNKNOWN terms:")
    print(unknown["Measurement"].value_counts().head(30))

    # ---------------- save ----------------
    df.to_csv("sr_clinical_normalized.csv", index=False)

    print("\nSaved:")
    print("- sr_clinical_normalized.csv")


if __name__ == "__main__":
    main()
