import os
from collections import Counter

import pydicom

dicom_dir = r"C:\Users\hassan.naqvi\OneDrive - Aga Khan University\Mahnaz Ambareen's files - QC Hassan bhai"

mods = Counter()

for root, _, files in os.walk(dicom_dir):
    for f in files:
        if f.lower().endswith(".dcm"):
            try:
                ds = pydicom.dcmread(os.path.join(root, f), stop_before_pixels=True)
                mods[getattr(ds, "Modality", "UNKNOWN")] += 1
            except:
                pass

print(mods)
