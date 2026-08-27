import pandas as pd


# =========================================================
# IMPROVED SCAN CLASSIFIER (PATH-BASED)
# =========================================================
def classify_scan(path, value):
    text = str(path).lower()

    labels = []

    # -------------------------
    # FETAL HEART RATE
    # -------------------------
    if "heart rate" in text or "fetal heart" in text or "fhr" in text:
        labels.append("FHR")

    # -------------------------
    # CROWN RUMP LENGTH
    # -------------------------
    if "crown rump" in text or "crl" in text:
        labels.append("CRL")

    # -------------------------
    # NUCHAL TRANSLUCENCY
    # -------------------------
    if "nuchal" in text or "nt" in text:
        labels.append("NT")

    # -------------------------
    # BIOMETRY (general fetal measurements)
    # -------------------------
    if "biometry" in text:
        labels.append("BIOMETRY")

    # -------------------------
    # GESTATION / DATING
    # -------------------------
    if "gestation" in text or "edd" in text or "ga" in text:
        labels.append("GA_EDD")

    # -------------------------
    # DOPPLER STUDIES
    # -------------------------
    if "doppler" in text:
        labels.append("DOPPLER")

    return ",".join(labels) if labels else "UNKNOWN (" + text + ")"


# =========================================================
# APPLY TO YOUR EXISTING FILE
# =========================================================
df = pd.read_csv("us_sr_linked_scan_map.csv")

df["ScanType"] = df.apply(
    lambda row: classify_scan(row["Path"], row["Value"]),
    axis=1
)

# =========================================================
# SAVE CLEAN VERSION
# =========================================================
df.to_csv("us_sr_linked_scan_map_labeled.csv", index=False)

print("\n✅ Updated ScanType classification complete")
print(df["ScanType"].value_counts().head(20))
