# inspect_sr_dicom_file.py

import pydicom

FILE_PATH = r'H:\voluson swift\GE-voluson\Dicom\Dicom\E0000002\SR000001'

print("📂 Loading SR DICOM...")
ds = pydicom.dcmread(FILE_PATH)

print("\n🧾 Basic Info:")
print("Modality:", getattr(ds, 'Modality', 'N/A'))
print("Study Date:", getattr(ds, 'StudyDate', 'N/A'))
print("Patient ID:", getattr(ds, 'PatientID', 'N/A'))

print("\n📦 Full DICOM Dump (important fields):")
print(ds)


# -----------------------------
# Explore Structured Content
# -----------------------------
def explore_sequence(seq, level=0):
    indent = "  " * level
    for item in seq:
        if hasattr(item, 'ConceptNameCodeSequence'):
            concept = item.ConceptNameCodeSequence[0]
            name = getattr(concept, 'CodeMeaning', 'Unknown')
        else:
            name = "Unknown"

        value = None

        if hasattr(item, 'MeasuredValueSequence'):
            mv = item.MeasuredValueSequence[0]
            value = getattr(mv, 'NumericValue', None)

        elif hasattr(item, 'TextValue'):
            value = item.TextValue

        print(f"{indent}📌 {name}: {value}")

        if hasattr(item, 'ContentSequence'):
            explore_sequence(item.ContentSequence, level + 1)


# Run exploration
if hasattr(ds, 'ContentSequence'):
    print("\n🔍 Exploring Structured Report:")
    explore_sequence(ds.ContentSequence)
else:
    print("\n⚠️ No structured content found.")
