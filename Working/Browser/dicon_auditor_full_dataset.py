"""
DICOM Full Audit — Zero Assumptions
=====================================
Extracts EVERYTHING from every SR and every US file.
Cross-references the complete datasets against each other.
No sampling. No filtering. No assumed relationships.
The data tells us what is linked and how.

Run:   python dicom_full_audit.py
Output: dicom_full_audit_report.xlsx  (multi-sheet)

Sheet guide at the bottom of this file.
"""

import os

import pandas as pd
import pydicom

# ── CONFIG ─────────────────────────────────────────────────────────────────────
DICOM_DIR = r"D:\IGHD_DICOM_VIEWER\raw_data"
OUTPUT_FILE = "dicom_full_audit_report.xlsx"


# ───────────────────────────────────────────────────────────────────────────────


def sep(title=""):
    print("\n" + "═" * 72)
    if title:
        print(f"  {title}")
        print("═" * 72)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — SCAN EVERY .dcm FILE
# ═══════════════════════════════════════════════════════════════════════════════
sep("STEP 1 · Scanning folder")
print(f"  {DICOM_DIR}\n")

us_records, sr_records, other_records = [], [], []

for root, _, files in os.walk(DICOM_DIR):
    for fname in files:
        if not fname.lower().endswith(".dcm"):
            continue
        path = os.path.join(root, fname)
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)
            mod = str(getattr(ds, "Modality", "NA"))
            rec = dict(
                FilePath=path,
                FileName=fname,
                PatientID=str(getattr(ds, "PatientID", "NA")),
                PatientName=str(getattr(ds, "PatientName", "NA")),
                StudyDate=str(getattr(ds, "StudyDate", "NA")),
                StudyTime=str(getattr(ds, "StudyTime", "NA")),
                StudyDescription=str(getattr(ds, "StudyDescription", "")),
                SeriesDescription=str(getattr(ds, "SeriesDescription", "")),
                Modality=mod,
                SOPClassUID=str(getattr(ds, "SOPClassUID", "NA")),
                SOPInstanceUID=str(getattr(ds, "SOPInstanceUID", "NA")),
                StudyInstanceUID=str(getattr(ds, "StudyInstanceUID", "NA")),
                SeriesInstanceUID=str(getattr(ds, "SeriesInstanceUID", "NA")),
                FrameOfReferenceUID=str(getattr(ds, "FrameOfReferenceUID", "NA")),
                InstanceNumber=str(getattr(ds, "InstanceNumber", "NA")),
                AcquisitionNumber=str(getattr(ds, "AcquisitionNumber", "NA")),
                ImageComments=str(getattr(ds, "ImageComments", "")),
                Manufacturer=str(getattr(ds, "Manufacturer", "")),
                ManufacturerModel=str(getattr(ds, "ManufacturerModelName", "")),
                SoftwareVersions=str(getattr(ds, "SoftwareVersions", "")),
            )
            if mod == "US":
                us_records.append(rec)
            elif mod == "SR":
                sr_records.append(rec)
            else:
                other_records.append(rec)
        except Exception as e:
            print(f"  [SKIP] {fname}: {e}")

df_us = pd.DataFrame(us_records)
df_sr = pd.DataFrame(sr_records)
df_other = pd.DataFrame(other_records)

print(f"  US images : {len(df_us)}")
print(f"  SR files  : {len(df_sr)}")
print(f"  Other     : {len(df_other)}")

if df_us.empty and df_sr.empty:
    print("  ❌  Nothing found. Check DICOM_DIR.")
    exit()

if not df_us.empty:
    print(f"\n  Unique Patients (US) : {sorted(df_us['PatientID'].unique())}")
    print(f"  Unique StudyDates    : {sorted(df_us['StudyDate'].unique())}")
    print(f"  Manufacturers        : {df_us['Manufacturer'].unique().tolist()}")
    print(f"  Models               : {df_us['ManufacturerModel'].unique().tolist()}")


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def all_tags_from_ds(ds, source_file=""):
    """
    Flatten EVERY element in a dataset (recursing into sequences) into rows.
    Returns list of dicts.
    """
    rows = []

    def _recurse(dataset, path_prefix=""):
        for elem in dataset:
            tag_str = f"({elem.tag.group:04X},{elem.tag.element:04X})"
            kw = elem.keyword or f"Private_{tag_str}"
            is_priv = bool(elem.tag.group % 2)
            vr = elem.VR
            path = f"{path_prefix}/{kw}" if path_prefix else kw

            if vr == "SQ":
                # Recurse into each sequence item
                for i, item in enumerate(elem.value or []):
                    _recurse(item, f"{path}[{i}]")
                # Also record the sequence itself (length only)
                rows.append(dict(
                    SourceFile=source_file,
                    Path=path,
                    Tag=tag_str,
                    Keyword=kw,
                    VR=vr,
                    IsPrivate=is_priv,
                    Value=f"<Sequence len={len(elem.value or [])}>",
                ))
            elif vr in ("OB", "OD", "OF", "OL", "OW"):
                rows.append(dict(
                    SourceFile=source_file,
                    Path=path,
                    Tag=tag_str,
                    Keyword=kw,
                    VR=vr,
                    IsPrivate=is_priv,
                    Value=f"<Binary len={len(elem.value) if elem.value else 0}>",
                ))
            else:
                try:
                    val = str(elem.value)
                except Exception:
                    val = "<unreadable>"
                rows.append(dict(
                    SourceFile=source_file,
                    Path=path,
                    Tag=tag_str,
                    Keyword=kw,
                    VR=vr,
                    IsPrivate=is_priv,
                    Value=val[:500],
                ))

    _recurse(ds)
    return rows


def collect_all_uids(tag_rows):
    """
    From a flat tag list, pull every element whose VR == UI.
    Returns a set of UID strings.
    """
    uids = set()
    for r in tag_rows:
        if r.get("VR") == "UI" and r.get("Value"):
            v = r["Value"].strip()
            if v and v != "NA":
                uids.add(v)
    return uids


def walk_content_tree(seq, depth=0, parent_ref_sop="", parent_ref_frame="", rows=None):
    """
    Full recursive SR ContentSequence dump.
    Captures: value type, numeric value, unit, code, free text,
              referenced SOP UID, referenced frame numbers, referenced segment.
    """
    if rows is None:
        rows = []
    for item in seq:
        try:
            ref_sop = parent_ref_sop
            ref_frame = parent_ref_frame
            ref_seg = ""

            if "ReferencedSOPSequence" in item:
                rsop = item.ReferencedSOPSequence[0]
                ref_sop = str(getattr(rsop, "ReferencedSOPInstanceUID", ""))
                ref_frame = str(getattr(rsop, "ReferencedFrameNumber", ""))
                ref_seg = str(getattr(rsop, "ReferencedSegmentNumber", ""))

            concept = code = coding_scheme = ""
            if "ConceptNameCodeSequence" in item:
                c = item.ConceptNameCodeSequence[0]
                concept = str(getattr(c, "CodeMeaning", ""))
                code = str(getattr(c, "CodeValue", ""))
                coding_scheme = str(getattr(c, "CodingSchemeDesignator", ""))

            vtype = str(getattr(item, "ValueType", ""))
            num_val = unit = ""
            if "MeasuredValueSequence" in item:
                mv = item.MeasuredValueSequence[0]
                num_val = str(getattr(mv, "NumericValue", ""))
                if "MeasurementUnitsCodeSequence" in mv:
                    unit = str(getattr(
                        mv.MeasurementUnitsCodeSequence[0], "CodeMeaning", ""))

            text_val = str(getattr(item, "TextValue", ""))[:300]
            date_val = str(getattr(item, "Date", ""))
            time_val = str(getattr(item, "Time", ""))
            uid_val = str(getattr(item, "UID", ""))

            # Observation context: observer, subject
            observer = subject = ""
            if "ObserverContext" in item:
                try:
                    observer = str(item.ObserverContext[0])[:100]
                except Exception:
                    pass
            if "SubjectContext" in item:
                try:
                    subject = str(item.SubjectContext[0])[:100]
                except Exception:
                    pass

            rows.append(dict(
                Depth=depth,
                ConceptName=("  " * depth) + concept,
                Code=code,
                CodingScheme=coding_scheme,
                ValueType=vtype,
                NumericValue=num_val,
                Unit=unit,
                TextValue=text_val,
                Date=date_val,
                Time=time_val,
                UID=uid_val,
                RefSOPInstanceUID=ref_sop,
                RefFrameNumber=ref_frame,
                RefSegmentNumber=ref_seg,
                Observer=observer,
                Subject=subject,
                HasNumericValue=bool(num_val),
                HasRefSOP=bool(ref_sop),
            ))

            if "ContentSequence" in item:
                walk_content_tree(
                    item.ContentSequence,
                    depth + 1, ref_sop, ref_frame, rows
                )
        except Exception as e:
            rows.append(dict(
                Depth=depth, ConceptName=f"<error:{e}>",
                Code="", CodingScheme="", ValueType="",
                NumericValue="", Unit="", TextValue="",
                Date="", Time="", UID="",
                RefSOPInstanceUID="", RefFrameNumber="",
                RefSegmentNumber="", Observer="", Subject="",
                HasNumericValue=False, HasRefSOP=False,
            ))
    return rows


def dump_cpec(sr_ds):
    """Flatten CurrentRequestedProcedureEvidenceSequence."""
    rows = []
    for i, study_item in enumerate(
            getattr(sr_ds, "CurrentRequestedProcedureEvidenceSequence", [])):
        study_uid = str(getattr(study_item, "StudyInstanceUID", ""))
        for series_item in getattr(study_item, "ReferencedSeriesSequence", []):
            series_uid = str(getattr(series_item, "SeriesInstanceUID", ""))
            for sop_item in getattr(series_item, "ReferencedSOPSequence", []):
                rows.append(dict(
                    CPEC_Entry=i + 1,
                    StudyInstanceUID=study_uid,
                    SeriesInstanceUID=series_uid,
                    SOPInstanceUID=str(getattr(sop_item, "ReferencedSOPInstanceUID", "")),
                    SOPClassUID=str(getattr(sop_item, "ReferencedSOPClassUID", "")),
                ))
    return pd.DataFrame(rows)


def dump_predecessor_docs(sr_ds):
    """Flatten PredecessorDocumentsSequence (SR version chain)."""
    rows = []
    for item in getattr(sr_ds, "PredecessorDocumentsSequence", []):
        study_uid = str(getattr(item, "StudyInstanceUID", ""))
        for series_item in getattr(item, "ReferencedSeriesSequence", []):
            series_uid = str(getattr(series_item, "SeriesInstanceUID", ""))
            for sop_item in getattr(series_item, "ReferencedSOPSequence", []):
                rows.append(dict(
                    StudyInstanceUID=study_uid,
                    SeriesInstanceUID=series_uid,
                    SOPInstanceUID=str(getattr(sop_item, "ReferencedSOPInstanceUID", "")),
                    SOPClassUID=str(getattr(sop_item, "ReferencedSOPClassUID", "")),
                ))
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — FULL US TAG DUMP  (every tag, every file)
# ═══════════════════════════════════════════════════════════════════════════════
sep("STEP 2 · Full US tag extraction — all files, all tags")

all_us_tag_rows = []  # every single tag from every US file
us_uid_map = {}  # SOPInstanceUID → set of all UIDs in that file
us_private_rows = []  # private tags only, with file identity

for i, row in df_us.iterrows():
    try:
        ds = pydicom.dcmread(row["FilePath"], stop_before_pixels=True)
    except Exception as e:
        print(f"  [SKIP US] {row['FileName']}: {e}")
        continue

    tag_rows = all_tags_from_ds(ds, source_file=row["FileName"])

    # Attach identity columns to every row
    sop = row["SOPInstanceUID"]
    for r in tag_rows:
        r["SOPInstanceUID"] = sop
        r["PatientID"] = row["PatientID"]
        r["StudyDate"] = row["StudyDate"]
        r["StudyInstanceUID"] = row["StudyInstanceUID"]
        r["SeriesInstanceUID"] = row["SeriesInstanceUID"]
        r["InstanceNumber"] = row["InstanceNumber"]

    all_us_tag_rows.extend(tag_rows)

    # All UID values in this file
    us_uid_map[sop] = collect_all_uids(tag_rows)

    # Private tags only
    for r in tag_rows:
        if r.get("IsPrivate"):
            us_private_rows.append(r)

    if (i + 1) % 50 == 0:
        print(f"  Processed {i + 1}/{len(df_us)} US files …")

df_us_tags = pd.DataFrame(all_us_tag_rows)
df_us_private = pd.DataFrame(us_private_rows)

print(f"\n  Total US tag rows      : {len(df_us_tags):,}")
print(f"  US private tag rows    : {len(df_us_private):,}")

# Private tag frequency table (which private tags appear in how many files)
if not df_us_private.empty:
    us_priv_freq = (
        df_us_private
        .groupby(["Tag", "Keyword", "VR"])
        .agg(
            FileCount=("SOPInstanceUID", "nunique"),
            ExampleValue=("Value", "first"),
        )
        .reset_index()
        .sort_values("FileCount", ascending=False)
    )
else:
    us_priv_freq = pd.DataFrame()

# All unique UID values across all US files (flat)
all_us_uid_values = set()
for uids in us_uid_map.values():
    all_us_uid_values |= uids

# US tag-level summary per file (tag counts)
us_tag_counts = (
    df_us_tags
    .groupby(["SOPInstanceUID", "PatientID", "StudyDate", "InstanceNumber"])
    .agg(
        TotalTags=("Tag", "count"),
        PrivateTags=("IsPrivate", "sum"),
        UniqueTags=("Tag", "nunique"),
    )
    .reset_index()
)

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — FULL SR TAG DUMP + CONTENT TREE  (every SR, fully)
# ═══════════════════════════════════════════════════════════════════════════════
sep("STEP 3 · Full SR extraction — all SR files, all tags + full content trees")

all_sr_tag_rows = []
all_tree_rows = []
all_cpec_rows = []
all_pred_rows = []
sr_uid_map = {}  # SR SOPInstanceUID → set of all UIDs in that file

for i, row in df_sr.iterrows():
    sr_sop = row["SOPInstanceUID"]
    print(f"\n  SR [{i + 1}/{len(df_sr)}] {row['FileName']}")
    print(f"    Patient: {row['PatientID']}  Date: {row['StudyDate']}")

    try:
        ds = pydicom.dcmread(row["FilePath"], force=True)
    except Exception as e:
        print(f"    ❌  Cannot read: {e}")
        continue

    # All tags
    tag_rows = all_tags_from_ds(ds, source_file=row["FileName"])
    for r in tag_rows:
        r["SR_SOPInstanceUID"] = sr_sop
        r["SR_PatientID"] = row["PatientID"]
        r["SR_StudyDate"] = row["StudyDate"]
        r["SR_StudyInstanceUID"] = row["StudyInstanceUID"]
        r["SR_SeriesInstanceUID"] = row["SeriesInstanceUID"]
    all_sr_tag_rows.extend(tag_rows)

    sr_uid_map[sr_sop] = collect_all_uids(tag_rows)

    # Content tree
    if hasattr(ds, "ContentSequence"):
        tree = walk_content_tree(ds.ContentSequence)
        for r in tree:
            r["SR_SOPInstanceUID"] = sr_sop
            r["SR_PatientID"] = row["PatientID"]
            r["SR_StudyDate"] = row["StudyDate"]
            r["FileName"] = row["FileName"]
        all_tree_rows.extend(tree)

        n_num = sum(1 for r in tree if r.get("HasNumericValue"))
        n_ref = sum(1 for r in tree if r.get("HasRefSOP"))
        print(f"    Tree items: {len(tree)}  |  Numeric: {n_num}  |  RefSOP: {n_ref}")
    else:
        print("    ⚠️  No ContentSequence")

    # CPEC
    cpec_df = dump_cpec(ds)
    if not cpec_df.empty:
        cpec_df["SR_SOPInstanceUID"] = sr_sop
        cpec_df["SR_PatientID"] = row["PatientID"]
        cpec_df["SR_StudyDate"] = row["StudyDate"]
        cpec_df["SR_FileName"] = row["FileName"]
        all_cpec_rows.append(cpec_df)
        print(f"    CPEC: {len(cpec_df)} referenced images")
    else:
        print("    ⚠️  No CPEC")

    # Predecessor documents
    pred_df = dump_predecessor_docs(ds)
    if not pred_df.empty:
        pred_df["SR_SOPInstanceUID"] = sr_sop
        pred_df["SR_FileName"] = row["FileName"]
        all_pred_rows.append(pred_df)

df_sr_tags = pd.DataFrame(all_sr_tag_rows)
df_tree = pd.DataFrame(all_tree_rows)
df_cpec = pd.concat(all_cpec_rows, ignore_index=True) if all_cpec_rows else pd.DataFrame()
df_pred = pd.concat(all_pred_rows, ignore_index=True) if all_pred_rows else pd.DataFrame()

print(f"\n  Total SR tag rows  : {len(df_sr_tags):,}")
print(f"  Total tree rows    : {len(df_tree):,}")
print(f"  Total CPEC rows    : {len(df_cpec):,}")

# All unique UID values across all SR files
all_sr_uid_values = set()
for uids in sr_uid_map.values():
    all_sr_uid_values |= uids

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — UID CROSS-REFERENCE  (SR UIDs ↔ US UIDs, exhaustively)
# ═══════════════════════════════════════════════════════════════════════════════
sep("STEP 4 · UID cross-reference — every SR UID against every US UID")

#
# 4A. Which US files are referenced by each SR?
#     For every SR × US pair, check ALL five UID types.
#
xref_rows = []

for sr_sop, sr_uids in sr_uid_map.items():
    sr_meta = df_sr[df_sr["SOPInstanceUID"] == sr_sop].iloc[0]

    for us_sop, us_uids in us_uid_map.items():
        us_meta = df_us[df_us["SOPInstanceUID"] == us_sop].iloc[0]

        # Direct UID intersections
        shared_uids = sr_uids & us_uids  # any UID in common
        sop_in_sr = us_sop in sr_uids
        us_study_in_sr = us_meta["StudyInstanceUID"] in sr_uids
        us_series_in_sr = us_meta["SeriesInstanceUID"] in sr_uids
        sr_study_in_us = sr_meta["StudyInstanceUID"] in us_uids
        same_study = us_meta["StudyInstanceUID"] == sr_meta["StudyInstanceUID"]
        same_series = us_meta["SeriesInstanceUID"] == sr_meta["SeriesInstanceUID"]
        same_patient = us_meta["PatientID"] == sr_meta["PatientID"]
        same_date = us_meta["StudyDate"] == sr_meta["StudyDate"]

        xref_rows.append(dict(
            SR_FileName=sr_meta["FileName"],
            SR_SOPInstanceUID=sr_sop,
            SR_PatientID=sr_meta["PatientID"],
            SR_StudyDate=sr_meta["StudyDate"],
            SR_StudyInstanceUID=sr_meta["StudyInstanceUID"],
            SR_SeriesInstanceUID=sr_meta["SeriesInstanceUID"],

            US_FileName=us_meta["FileName"],
            US_SOPInstanceUID=us_sop,
            US_PatientID=us_meta["PatientID"],
            US_StudyDate=us_meta["StudyDate"],
            US_StudyInstanceUID=us_meta["StudyInstanceUID"],
            US_SeriesInstanceUID=us_meta["SeriesInstanceUID"],
            US_InstanceNumber=us_meta["InstanceNumber"],

            SamePatient=same_patient,
            SameStudyDate=same_date,
            SameStudy=same_study,
            SameSeries=same_series,
            US_SOP_in_SR=sop_in_sr,
            US_Study_in_SR=us_study_in_sr,
            US_Series_in_SR=us_series_in_sr,
            SR_Study_in_US=sr_study_in_us,
            SharedUID_Count=len(shared_uids),
            SharedUIDs="; ".join(sorted(shared_uids))[:500],

            # Strongest link available
            LinkStrength=(
                "SOP" if sop_in_sr else
                "Series" if us_series_in_sr else
                "Study" if (same_study or us_study_in_sr) else
                "Patient" if same_patient else
                "None"
            ),
        ))

df_xref = pd.DataFrame(xref_rows)

# Summary of link strength distribution
link_summary = df_xref["LinkStrength"].value_counts().reset_index()
link_summary.columns = ["LinkStrength", "PairCount"]

sep("STEP 4 Results · Link strength across all SR × US pairs")
print(link_summary.to_string(index=False))
print(f"\n  Total SR × US pairs evaluated: {len(df_xref):,}")

# Strongest actual links
strong = df_xref[df_xref["LinkStrength"].isin(["SOP", "Series"])]
print(f"\n  Pairs with SOP or Series link  : {len(strong):,}")
if not strong.empty:
    print(strong[["SR_FileName", "US_FileName", "US_InstanceNumber",
                  "LinkStrength", "SharedUID_Count"]].to_string(index=False))

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — SR CONTENT TREE  ×  US FILES
# Link each numeric measurement in the SR tree to its US image (if possible)
# ═══════════════════════════════════════════════════════════════════════════════
sep("STEP 5 · SR measurements × US image resolution")

us_sop_index = df_us.set_index("SOPInstanceUID")

linked_meas_rows = []

if not df_tree.empty:
    numeric_tree = df_tree[df_tree["HasNumericValue"] == True].copy()

    for _, mrow in numeric_tree.iterrows():
        ref_sop = mrow.get("RefSOPInstanceUID", "")
        ref_frame = mrow.get("RefFrameNumber", "")

        # Try to resolve the RefSOP to an actual US file
        us_fname = us_inst = us_patient = us_date = us_series = ""
        resolved = False

        if ref_sop and ref_sop in us_sop_index.index:
            us_rec = us_sop_index.loc[ref_sop]
            us_fname = us_rec["FileName"]
            us_inst = str(us_rec["InstanceNumber"])
            us_patient = us_rec["PatientID"]
            us_date = us_rec["StudyDate"]
            us_series = us_rec["SeriesInstanceUID"]
            resolved = True

        linked_meas_rows.append(dict(
            SR_FileName=mrow.get("FileName", ""),
            SR_SOPInstanceUID=mrow.get("SR_SOPInstanceUID", ""),
            SR_PatientID=mrow.get("SR_PatientID", ""),
            SR_StudyDate=mrow.get("SR_StudyDate", ""),
            Depth=mrow.get("Depth", ""),
            ConceptName=mrow.get("ConceptName", "").strip(),
            Code=mrow.get("Code", ""),
            NumericValue=mrow.get("NumericValue", ""),
            Unit=mrow.get("Unit", ""),
            RefSOPInstanceUID=ref_sop,
            RefFrameNumber=ref_frame,
            Resolved=resolved,
            US_FileName=us_fname,
            US_InstanceNumber=us_inst,
            US_PatientID=us_patient,
            US_StudyDate=us_date,
            US_SeriesInstanceUID=us_series,
        ))

df_linked_meas = pd.DataFrame(linked_meas_rows)

if not df_linked_meas.empty:
    n_res = df_linked_meas["Resolved"].sum()
    n_unres = (~df_linked_meas["Resolved"]).sum()
    print(f"\n  Numeric measurements in SR tree : {len(df_linked_meas)}")
    print(f"  Resolved to a US file           : {n_res}")
    print(f"  Unresolved (no RefSOP / unknown): {n_unres}")
    if n_res > 0:
        print("\n  Resolved measurements:")
        print(df_linked_meas[df_linked_meas["Resolved"]][
                  ["ConceptName", "NumericValue", "Unit",
                   "US_FileName", "US_InstanceNumber", "RefFrameNumber"]
              ].to_string(index=False))

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 6 — CPEC × US CROSS-CHECK
# Does each CPEC-listed SOP actually exist in our US file set?
# ═══════════════════════════════════════════════════════════════════════════════
sep("STEP 6 · CPEC referenced images × actual US files")

if not df_cpec.empty and not df_us.empty:
    us_sops_set = set(df_us["SOPInstanceUID"])
    df_cpec["US_File_Exists"] = df_cpec["SOPInstanceUID"].isin(us_sops_set)

    exists = df_cpec["US_File_Exists"].sum()
    not_exists = (~df_cpec["US_File_Exists"]).sum()
    print(f"  CPEC entries total              : {len(df_cpec)}")
    print(f"  CPEC SOPs found in US files     : {exists}")
    print(f"  CPEC SOPs NOT found in US files : {not_exists}")
    print(df_cpec.to_string(index=False))
else:
    print("  No CPEC data or no US files to compare.")

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 7 — US TAG UNIQUE-VALUE INVENTORY
# What values does each tag hold across all US files?
# Useful to spot measurement-bearing tags.
# ═══════════════════════════════════════════════════════════════════════════════
sep("STEP 7 · US tag value inventory — unique values per tag")

if not df_us_tags.empty:
    # For every tag, how many distinct values exist? What are examples?
    us_tag_inventory = (
        df_us_tags[df_us_tags["VR"] != "SQ"]
        .groupby(["Tag", "Keyword", "VR", "IsPrivate"])
        .agg(
            UniqueValues=("Value", "nunique"),
            ExampleValue1=("Value", lambda x: x.iloc[0] if len(x) > 0 else ""),
            ExampleValue2=("Value", lambda x: x.iloc[1] if len(x) > 1 else ""),
            ExampleValue3=("Value", lambda x: x.iloc[-1] if len(x) > 2 else ""),
            FileCount=("SOPInstanceUID", "nunique"),
        )
        .reset_index()
        .sort_values(["IsPrivate", "UniqueValues"], ascending=[False, False])
    )
else:
    us_tag_inventory = pd.DataFrame()

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 8 — PRIVATE TAG SHARED BETWEEN SR AND US
# ═══════════════════════════════════════════════════════════════════════════════
sep("STEP 8 · Private tag overlap — SR vs US")

sr_private_rows = []
for r in all_sr_tag_rows:
    if r.get("IsPrivate"):
        sr_private_rows.append(r)

df_sr_private = pd.DataFrame(sr_private_rows)

if not df_sr_private.empty and not df_us_private.empty:
    sr_priv_tags = set(df_sr_private["Tag"].unique())
    us_priv_tags = set(df_us_private["Tag"].unique())
    overlap = sr_priv_tags & us_priv_tags
    only_sr = sr_priv_tags - us_priv_tags
    only_us = us_priv_tags - sr_priv_tags

    print(f"  Private tags in SR files  : {len(sr_priv_tags)}")
    print(f"  Private tags in US files  : {len(us_priv_tags)}")
    print(f"  Tags in BOTH              : {len(overlap)}  ← highest-value leads")
    print(f"  Only in SR                : {len(only_sr)}")
    print(f"  Only in US                : {len(only_us)}")

    if overlap:
        print("\n  Overlapping private tags:")
        sr_ex = df_sr_private.set_index("Tag")
        us_ex = df_us_private.set_index("Tag")
        for t in sorted(overlap):
            sv = sr_ex.loc[t, "Value"].iloc[0] if isinstance(sr_ex.loc[t], pd.DataFrame) else sr_ex.loc[t, "Value"]
            uv = us_ex.loc[t, "Value"].iloc[0] if isinstance(us_ex.loc[t], pd.DataFrame) else us_ex.loc[t, "Value"]
            print(f"    {t:<24}  SR→ {str(sv)[:50]:<52}  US→ {str(uv)[:50]}")

    priv_overlap_df = pd.DataFrame([
        dict(Tag=t, InSR=t in sr_priv_tags, InUS=t in us_priv_tags,
             SR_Example=df_sr_private[df_sr_private["Tag"] == t]["Value"].iloc[0]
             if t in sr_priv_tags else "",
             US_Example=df_us_private[df_us_private["Tag"] == t]["Value"].iloc[0]
             if t in us_priv_tags else "")
        for t in sorted(sr_priv_tags | us_priv_tags)
    ])
else:
    priv_overlap_df = pd.DataFrame()
    print("  Insufficient private tag data for comparison.")

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 9 — SAVE EVERYTHING TO EXCEL
# ═══════════════════════════════════════════════════════════════════════════════
sep("STEP 9 · Saving report")


def safe_sheet(name):
    for ch in r'\/:*?[]':
        name = name.replace(ch, "_")
    return name[:31]


sheets = {
    # ── Raw file inventories ─────────────────────────────
    "01_US_FileList": df_us.drop(columns=["FilePath"], errors="ignore"),
    "02_SR_FileList": df_sr.drop(columns=["FilePath"], errors="ignore"),
    "03_Other_FileList": df_other.drop(columns=["FilePath"], errors="ignore"),

    # ── Full tag dumps ───────────────────────────────────
    "04_US_AllTags": df_us_tags,
    "05_SR_AllTags": df_sr_tags,

    # ── Inventories / frequencies ────────────────────────
    "06_US_TagInventory": us_tag_inventory,
    "07_US_TagCountsPerFile": us_tag_counts,
    "08_US_PrivateFreq": us_priv_freq,

    # ── SR content ───────────────────────────────────────
    "09_SR_ContentTree": df_tree,
    "10_SR_CPEC": df_cpec,
    "11_SR_PredecessorDocs": df_pred,

    # ── Cross-references ─────────────────────────────────
    "12_SR_x_US_XRef": df_xref,
    "13_LinkStrength_Summary": link_summary,
    "14_Measurements_Resolved": df_linked_meas,
    "15_CPEC_x_US_Check": df_cpec,  # already has US_File_Exists col

    # ── Private tag analysis ─────────────────────────────
    "16_PrivateTag_Overlap": priv_overlap_df,
    "17_US_PrivateTags_All": df_us_private,
    "18_SR_PrivateTags_All": df_sr_private,
}

with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
    written = 0
    for sname, df in sheets.items():
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            continue
        try:
            df.to_excel(writer, sheet_name=safe_sheet(sname), index=False)
            written += 1
        except Exception as e:
            print(f"  [WARN] '{sname}': {e}")
    if written == 0:
        pd.DataFrame({"error": ["No data"]}).to_excel(writer, sheet_name="Error", index=False)

sep(f"DONE — {written} sheets → {OUTPUT_FILE}")

print("""
═══════════════════════════════════════════════════════════════════════
  SHEET GUIDE — what to look at and in what order
═══════════════════════════════════════════════════════════════════════

  01_US_FileList          Every US file with its key DICOM header fields.
  02_SR_FileList          Every SR file. Note PatientID and StudyDate.
  03_Other_FileList       Any non-US, non-SR files found.

  04_US_AllTags           ★ EVERY tag from EVERY US file.
                            Sort by Tag, then scan Value — look for
                            anything that changes per image (InstanceNumber,
                            caliper data, measurement text, etc.)

  05_SR_AllTags           ★ EVERY tag from EVERY SR file.
                            Same approach — look for private tags with
                            meaningful values.

  06_US_TagInventory      Per-tag summary: how many unique values does
                            each tag have?  IsPrivate=True + UniqueValues
                            near the total file count = per-image data.

  07_US_TagCountsPerFile  Tag count per US file — outliers may carry extra data.

  08_US_PrivateFreq       Private tags ranked by how many US files contain them.
                            Tags in ALL files = consistent per-image metadata.

  09_SR_ContentTree       Full SR content tree — every node, every depth.
                            Columns: ConceptName, NumericValue, Unit,
                            RefSOPInstanceUID, RefFrameNumber.
                            RefSOPInstanceUID populated = image-linked measurement.

  10_SR_CPEC              Images the SR formally declares as evidence
                            (CurrentRequestedProcedureEvidenceSequence).

  11_SR_PredecessorDocs   Prior SR versions referenced by current SRs.

  12_SR_x_US_XRef         ★★ COMPLETE SR × US pair table.
                            Every SR paired with every US file.
                            Columns: SamePatient, SameStudy, SameSeries,
                            US_SOP_in_SR, LinkStrength, SharedUID_Count.
                            Filter LinkStrength != "None" to see all links.

  13_LinkStrength_Summary  Counts of each link type (SOP/Series/Study/None).
                            SOP = strongest; None = completely unrelated.

  14_Measurements_Resolved ★ Each numeric SR measurement with its resolved
                            US image filename + instance number (if linkable).
                            Resolved=True means we matched it to a real US file.

  15_CPEC_x_US_Check      CPEC entries with US_File_Exists column — tells
                            you if the referenced images are actually present.

  16_PrivateTag_Overlap    Tags that appear in BOTH SR and US files.
                            These share the vendor's private schema.

  17_US_PrivateTags_All    All private tag rows from all US files.
  18_SR_PrivateTags_All    All private tag rows from all SR files.

═══════════════════════════════════════════════════════════════════════
  WHAT TO PASTE BACK FOR NEXT STEPS
═══════════════════════════════════════════════════════════════════════
  1. Console output (especially Steps 4–8 results)
  2. Sheet 13 (LinkStrength_Summary) — paste the table
  3. Sheet 08 top 30 rows (US_PrivateFreq)
  4. Sheet 14 — are any rows Resolved=True?
  5. Sheet 16 — any overlapping private tags?
""")
