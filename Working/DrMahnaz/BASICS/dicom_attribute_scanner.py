import os

import pandas as pd
import pydicom

TARGET_FOLDER = r"H:\IGHD_DICOM_VIEWER\raw_data\1101011-0003-001-01-02__\20251103_142750"


def inspect_study_folder_full(folder_path, output_csv="full_metadata_summary.csv"):
    # Configure Pandas to display full untruncated tables in console
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_colwidth", None)
    pd.set_option("display.width", 1000)

    attributes = {}
    file_count = 0

    for root, _, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                ds = pydicom.dcmread(file_path, stop_before_pixels=True)
                file_count += 1

                for elem in ds:
                    tag_key = f"({elem.tag.group:04X},{elem.tag.element:04X})"
                    keyword = elem.keyword or "Private/Unknown"
                    val = str(elem.value).strip()

                    if tag_key not in attributes:
                        attributes[tag_key] = {
                            "Tag": tag_key,
                            "Keyword": keyword,
                            "VR": elem.VR,
                            "Sample Value": val,
                            "Count": 1
                        }
                    else:
                        attributes[tag_key]["Count"] += 1
            except Exception:
                continue

    print(f"Scanned {file_count} files in: {folder_path}\n")
    df = pd.DataFrame(list(attributes.values()))

    if not df.empty:
        df_sorted = df.sort_values("Count", ascending=False)
        print(df_sorted.to_string(index=False))

        # Save to CSV for easy searching and Excel inspection
        if output_csv:
            df_sorted.to_csv(output_csv, index=False)
            print(f"\n✅ Exported full untruncated metadata summary to: {os.path.abspath(output_csv)}")


def dump_single_file_header(folder_path):
    """Prints the raw, fully nested DICOM tree structure for the first file found."""
    for root, _, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                ds = pydicom.dcmread(file_path, stop_before_pixels=True)
                print("\n" + "=" * 80)
                print(f"📄 RAW HEADER DUMP FOR FIRST FILE: {file}")
                print("=" * 80)
                print(ds)
                return
            except Exception:
                continue


if __name__ == "__main__":
    # 1. Print summary table across all files and export to CSV
    inspect_study_folder_full(TARGET_FOLDER)

    # 2. Print complete nested DICOM hierarchy for a single representative file
    dump_single_file_header(TARGET_FOLDER)
