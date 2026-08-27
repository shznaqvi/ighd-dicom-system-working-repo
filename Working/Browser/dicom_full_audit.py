import re

import pandas as pd

# ── CONFIG ─────────────────────────────────────────────────────────────
FILE_PATH = "pure_raw_dicom_dump.csv"
OUTPUT_FILE = "meaningful_dicom_dump.csv"


# ───────────────────────────────────────────────────────────────────────

def get_base_node(path):
    """
    Strips the terminal DICOM wrappers to find the true structural 'parent' node.
    Example: 'ContentSequence[1]/MeasuredValueSequence[0]/NumericValue' -> 'ContentSequence[1]'
    """
    path = str(path)
    # 1. Strip the sequence blocks used for definitions
    base = re.sub(r'/(ConceptNameCodeSequence|MeasuredValueSequence|MeasurementUnitsCodeSequence)\[\d+\].*$', '', path)
    # 2. Strip standard terminal fields
    base = re.sub(
        r'/(TextValue|NumericValue|Date|Time|UID|CodeValue|CodeMeaning|CodingSchemeDesignator|RelationshipType)$', '',
        base)
    return base


def enhance_raw_dump():
    print(f"Loading '{FILE_PATH}'... (This might take a moment)")
    try:
        df = pd.read_csv(FILE_PATH, dtype=str)
    except FileNotFoundError:
        print(f"❌ Error: '{FILE_PATH}' not found.")
        return

    df['Path'] = df['Path'].fillna("")
    df['Value'] = df['Value'].fillna("")

    print("Calculating structural hierarchy (Base Nodes)...")
    df['BaseNode'] = df['Path'].apply(get_base_node)

    print("Extracting Concept Names (Medical Terminology)...")
    # Identify all rows that contain the human-readable concept name
    concept_mask = df['Path'].str.endswith('ConceptNameCodeSequence[0]/CodeMeaning', na=False)
    # Create a lookup dictionary: (FileName, BaseNode) -> ConceptName
    concepts = df[concept_mask].set_index(['FileName', 'BaseNode'])['Value'].to_dict()

    print("Extracting Measurement Units...")
    # Identify all rows that contain the unit string
    unit_mask = df['Path'].str.endswith('MeasurementUnitsCodeSequence[0]/CodeMeaning', na=False)
    # Create a lookup dictionary: (FileName, BaseNode) -> Unit
    units = df[unit_mask].set_index(['FileName', 'BaseNode'])['Value'].to_dict()

    print("Propagating decoded contexts to all 52,000+ rows...")
    # Map the lookup dictionaries back to the main dataframe
    mapping_keys = list(zip(df['FileName'], df['BaseNode']))
    df['Decoded_Concept'] = [concepts.get(k, "") for k in mapping_keys]
    df['Decoded_Unit'] = [units.get(k, "") for k in mapping_keys]

    # For standard metadata tags (like PatientID) that don't have a "ConceptName" sequence,
    # just use the standard keyword found at the end of the path.
    def fallback_concept(row):
        if row['Decoded_Concept'] != "":
            return row['Decoded_Concept']
        return str(row['Path']).split('/')[-1]

    df['Decoded_Concept'] = df.apply(fallback_concept, axis=1)

    # Reorder columns for optimal readability
    cols = ['FileName', 'Decoded_Concept', 'Value', 'Decoded_Unit', 'Tag', 'VR', 'Path']
    df = df[cols]

    print(f"Saving enriched dataset to '{OUTPUT_FILE}'...")
    df.to_csv(OUTPUT_FILE, index=False)

    print("\n" + "═" * 70)
    print(" ✅ DATASET MEANINGFULLY ENRICHED")
    print("═" * 70)
    print(f" Output File: {OUTPUT_FILE}")
    print(" Open this file in Excel. You can now filter the 'Decoded_Concept'")
    print(" column to instantly find specific clinical measurements or metadata.")


if __name__ == "__main__":
    enhance_raw_dump()
