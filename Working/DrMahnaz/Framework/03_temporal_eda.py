import os

import matplotlib.pyplot as plt
import pandas as pd
import pydicom

from config import dicom_dir


def load_study_index():
    """
    Build a structured table of:
    Patient → Study → Date → Modality presence
    """

    records = []

    for root, _, files in os.walk(dicom_dir):
        for file in files:
            path = os.path.join(root, file)

            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True)

                patient = ds.get("PatientID")
                study = ds.get("StudyInstanceUID")
                date = ds.get("StudyDate")
                modality = ds.get("Modality")

                if patient and study:
                    records.append({
                        "PatientID": patient,
                        "StudyInstanceUID": study,
                        "StudyDate": date,
                        "Modality": modality
                    })

            except:
                continue

    df = pd.DataFrame(records)
    return df


def build_timeline(df):
    """
    Create ordered patient timelines
    """

    df = df.drop_duplicates(subset=["PatientID", "StudyInstanceUID"])
    # df["StudyDate"] = pd.to_datetime(df["StudyDate"], errors="coerce")
    df = df.copy()
    df.loc[:, "StudyDate"] = pd.to_datetime(df["StudyDate"], errors="coerce")

    timelines = {}

    for patient, group in df.groupby("PatientID"):
        group = group.sort_values("StudyDate")

        timelines[patient] = group

    return timelines


def plot_patient_timeline(timelines):
    """
    Visualize follow-up structure
    """

    plt.figure(figsize=(10, 5))

    y = 0
    for patient, df in timelines.items():
        dates = df["StudyDate"].dropna()

        plt.scatter(dates, [y] * len(dates), label=patient)

        for d in dates:
            plt.text(d, y + 0.05, d.strftime("%Y-%m-%d"), fontsize=8)

        y += 1

    plt.yticks([])
    plt.title("Patient Follow-up Timeline")
    plt.xlabel("Date")
    plt.legend()
    plt.show()


def compute_gaps(timelines):
    """
    Compute time gaps between visits
    """

    print("\n--- Visit Gaps (Days) ---")

    for patient, df in timelines.items():
        dates = df["StudyDate"].dropna().sort_values()

        gaps = dates.diff().dt.days.dropna()

        print(f"\nPatient: {patient}")
        print("Gaps (days):", gaps.tolist())


def modality_per_visit(df):
    """
    Check if SR exists per study
    """

    pivot = df.pivot_table(
        index=["PatientID", "StudyInstanceUID"],
        columns="Modality",
        aggfunc="size",
        fill_value=0
    )

    pivot["SR_present"] = pivot.get("SR", 0) > 0

    print("\n--- SR Coverage Per Study ---")
    print(pivot["SR_present"].value_counts())


def main():
    print("\nLoading dataset...")
    df = load_study_index()

    print(f"Total records: {len(df)}")
    print(f"Unique studies: {df['StudyInstanceUID'].nunique()}")

    timelines = build_timeline(df)

    compute_gaps(timelines)
    modality_per_visit(df)
    plot_patient_timeline(timelines)


if __name__ == "__main__":
    main()
