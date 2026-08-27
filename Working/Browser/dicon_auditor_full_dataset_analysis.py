import warnings

import pandas as pd

# Suppress openpyxl warnings about data validation/extensions (common with large pandas exports)
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

# ── CONFIG ─────────────────────────────────────────────────────────────
FILE_PATH = "dicom_full_audit_report.xlsx"


# ───────────────────────────────────────────────────────────────────────

def print_sheet_summaries(file_path):
    print(f"Loading '{file_path}' (this might take a moment)...\n")
    try:
        # sheet_name=None loads all sheets into a dictionary of DataFrames
        sheets = pd.read_excel(file_path, sheet_name=None)
    except FileNotFoundError:
        print(f"❌ Error: Could not find '{file_path}'. Ensure it is in the same directory.")
        return
    except Exception as e:
        print(f"❌ Error loading Excel file: {e}")
        return

    for sheet_name, df in sheets.items():
        print("═" * 80)
        print(f" 📑 SHEET: {sheet_name.upper()}")
        print(f"    Total Rows: {len(df):,} | Total Columns: {len(df.columns)}")
        print("═" * 80)

        if df.empty:
            print("    (Sheet is empty)\n")
            continue

        for col in df.columns:
            # Basic stats
            non_null = df[col].notna().sum()
            fill_pct = (non_null / len(df)) * 100 if len(df) > 0 else 0
            n_unique = df[col].nunique(dropna=True)
            dtype = str(df[col].dtype)

            print(f" 🔹 Field: {col}")
            print(f"    Type: {dtype:<10} | Populated: {non_null:,} ({fill_pct:.1f}%) | Unique Values: {n_unique:,}")

            if non_null > 0:
                # If the field is numerical, show Min/Max/Mean
                if pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_bool_dtype(df[col]):
                    min_val = df[col].min()
                    max_val = df[col].max()
                    mean_val = df[col].mean()
                    print(f"    Stats: Min = {min_val} | Max = {max_val} | Mean = {mean_val:.2f}")

                # Show the top 3 most common values to give clinical/metadata context
                top_vals = df[col].value_counts().head(3)
                top_str = ",  ".join([f"'{k}' (x{v})" for k, v in top_vals.items()])
                print(f"    Top Values: {top_str}")
            print()
        print("\n")


if __name__ == "__main__":
    print_sheet_summaries(FILE_PATH)
