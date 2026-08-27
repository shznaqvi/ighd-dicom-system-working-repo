import re

import pandas as pd

# ── CONFIG ─────────────────────────────────────────────────────────────
INPUT_CSV = "pure_raw_dicom_dump.csv"
OUTPUT_EXCEL = "decoded_file_comparison.xlsx"

TARGET_FILES = [
    "IMG_20260415_3_SR_OBGYN.dcm",
    "IMG_20260415_1_5.dcm"
]


# ───────────────────────────────────────────────────────────────────────

def get_base_node(path):
    path = str(path)
    base = re.sub(r'/(ConceptNameCodeSequence|MeasuredValueSequence|MeasurementUnitsCodeSequence)\[\d+\].*$', '', path)
    base = re.sub(
        r'/(TextValue|NumericValue|Date|Time|UID|CodeValue|CodeMeaning|CodingSchemeDesignator|RelationshipType)$', '',
        base)
    return base


def decode_specific_files():
    print(f"Loading master dump...")
    try:
        # We only load the rows we need to save memory
        iter_csv = pd.read_csv(INPUT_CSV, dtype=str, chunksize=10000)
        df = pd.concat([chunk[chunk['FileName'].isin(TARGET_FILES)] for chunk in iter_csv])
    except FileNotFoundError:
        print(f"❌ Error: '{INPUT_CSV}' not found.")
        return

    if df.empty:
        print("❌ Error: Specified files not found in the CSV.")
        return

    df['Path'] = df['Path'].fillna("")
    df['Value'] = df['Value'].fillna("")
    df['Group'] = df['Tag'].str.extract(r'\((....),')

    # 1. Map Private Creators
    creator_mask = df['Tag'].str.contains(r'\(..[13579BDEF],00[1-9A-F].\)', regex=True)
    creators = df[creator_mask].set_index(['FileName', 'Group'])['Value'].to_dict()

    # 2. Extract Structural Context
    df['BaseNode'] = df['Path'].apply(get_base_node)

    # 3. Extract Concepts and Units
    concept_mask = df['Path'].str.endswith('ConceptNameCodeSequence[0]/CodeMeaning', na=False)
    concepts = df[concept_mask].set_index(['FileName', 'BaseNode'])['Value'].to_dict()

    unit_mask = df['Path'].str.endswith('MeasurementUnitsCodeSequence[0]/CodeMeaning', na=False)
    units = df[unit_mask].set_index(['FileName', 'BaseNode'])['Value'].to_dict()

    print("Applying decoding logic...")

    def decode_row(row):
        f_name, b_node, group = row['FileName'], row['BaseNode'], row['Group']
        concept = concepts.get((f_name, b_node), "")

        if not concept and "Private" in row['Path']:
            owner = creators.get((f_name, group), "Unknown Private")
            return f"[{owner}] {row['Path'].split('/')[-1]}"

        if not concept:
            return str(row['Path']).split('/')[-1]

        return concept

    mapping_keys = list(zip(df['FileName'], df['BaseNode']))
    df['Decoded_Concept'] = [concepts.get(k, "") for k in mapping_keys]
    df['Decoded_Unit'] = [units.get(k, "") for k in mapping_keys]
    df['Decoded_Concept'] = df.apply(decode_row, axis=1)

    # 4. Save to Separate Sheets
    print(f"Writing to {OUTPUT_EXCEL}...")
    with pd.ExcelWriter(OUTPUT_EXCEL, engine='openpyxl') as writer:
        for file_name in TARGET_FILES:
            sheet_df = df[df['FileName'] == file_name].copy()
            # Clean up column order for the sheet
            final_df = sheet_df[['Decoded_Concept', 'Value', 'Decoded_Unit', 'Tag', 'VR', 'Path']]

            # Excel sheet names have a 31-char limit and can't have special chars
            safe_name = file_name.replace(".dcm", "")[-31:]
            final_df.to_excel(writer, sheet_name=safe_name, index=False)

    print("\n" + "═" * 60)
    print(" ✅ DECODED COMPARISON READY")
    print("═" * 60)
    print(f" File: {OUTPUT_EXCEL}")
    print(f" Sheet 1: {TARGET_FILES[0]} ({len(df[df['FileName'] == TARGET_FILES[0]])} rows)")
    print(f" Sheet 2: {TARGET_FILES[1]} ({len(df[df['FileName'] == TARGET_FILES[1]])} rows)")


if __name__ == "__main__":
    decode_specific_files()
