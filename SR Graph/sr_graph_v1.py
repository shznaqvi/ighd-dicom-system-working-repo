from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Tuple

import pydicom


# =========================================================
# DATA MODELS
# =========================================================

@dataclass
class Measurement:
    name: str
    value: float
    unit: str = ""
    confidence: float = 1.0


@dataclass
class SRNode:
    sr_path: str
    sr_sop: str
    study_uid: str
    series_uid: str
    referenced_sops: List[str] = field(default_factory=list)
    measurements: List[Measurement] = field(default_factory=list)


@dataclass
class SRGraph:
    image_to_sr: Dict[str, List[SRNode]] = field(default_factory=lambda: defaultdict(list))
    sr_nodes: Dict[str, SRNode] = field(default_factory=dict)


# =========================================================
# SR EXTRACTION
# =========================================================

def extract_measurements(ds) -> List[Measurement]:
    """
    Extract structured measurements from SR DICOM.
    """

    results = []

    def walk(seq):
        for item in seq:
            try:
                concept = ""

                if "ConceptNameCodeSequence" in item:
                    concept = str(item.ConceptNameCodeSequence[0].CodeMeaning)

                if "MeasuredValueSequence" in item:
                    mv = item.MeasuredValueSequence[0]
                    value = getattr(mv, "NumericValue", None)

                    unit = ""
                    if "MeasurementUnitsCodeSequence" in mv:
                        unit = mv.MeasurementUnitsCodeSequence[0].CodeMeaning

                    results.append(
                        Measurement(
                            name=concept,
                            value=value,
                            unit=unit,
                            confidence=1.0,
                        )
                    )

                if "ContentSequence" in item:
                    walk(item.ContentSequence)

            except Exception:
                continue

    if "ContentSequence" in ds:
        walk(ds.ContentSequence)

    return results


# =========================================================
# REFERENCED SOP EXTRACTION
# =========================================================

def extract_referenced_sops(ds) -> List[str]:
    """
    Extract all referenced image SOPInstanceUIDs inside SR.
    """
    refs = set()

    for elem in ds.iterall():
        if elem.keyword == "ReferencedSOPInstanceUID":
            refs.add(str(elem.value))

    return list(refs)


# =========================================================
# BUILD SR GRAPH
# =========================================================

def build_sr_graph(df_sr) -> SRGraph:
    """
    Build clinical SR graph:
    Image SOP -> SR Nodes -> Measurements
    """

    graph = SRGraph()

    for _, row in df_sr.iterrows():

        try:
            ds = pydicom.dcmread(row["FilePath"], stop_before_pixels=True)

            sr_sop = str(getattr(ds, "SOPInstanceUID", ""))
            study_uid = str(getattr(ds, "StudyInstanceUID", ""))
            series_uid = str(getattr(ds, "SeriesInstanceUID", ""))

            node = SRNode(
                sr_path=row["FilePath"],
                sr_sop=sr_sop,
                study_uid=study_uid,
                series_uid=series_uid,
                referenced_sops=extract_referenced_sops(ds),
                measurements=extract_measurements(ds),
            )

            graph.sr_nodes[sr_sop] = node

            # map SR → image SOPs
            for sop in node.referenced_sops:
                graph.image_to_sr[sop].append(node)

        except Exception:
            continue

    return graph


# =========================================================
# MATCHING ENGINE
# =========================================================

def match_sr(graph: SRGraph, image_sop: str) -> Tuple[List[SRNode], float]:
    """
    Return SR nodes linked to image SOP + confidence score.
    """

    matches = graph.image_to_sr.get(image_sop, [])

    if matches:
        return matches, 1.0  # strong clinical match

    return [], 0.0


# =========================================================
# METRIC AGGREGATION
# =========================================================

def get_metrics(sr_nodes: List[SRNode]) -> Dict[str, Measurement]:
    """
    Merge measurements across multiple SRs.
    """

    merged = defaultdict(list)

    for node in sr_nodes:
        for m in node.measurements:
            merged[m.name].append(m)

    result = {}

    for name, values in merged.items():
        # simple rule: last measurement wins (can upgrade later)
        result[name] = values[-1]

    return result


# =========================================================
# OPTIONAL DEBUG HELPERS
# =========================================================

def debug_graph(graph: SRGraph):
    print("Total SR nodes:", len(graph.sr_nodes))
    print("Image → SR mappings:", len(graph.image_to_sr))
