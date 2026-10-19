"""
Approximate plate matcher.

Scores a (noisy) plate against every registered vehicle with all similarity
methods, keeps every plausible candidate above a threshold (not just exact hits)
and ranks them.

A "reference index" is a list of dicts, one per registered vehicle, with at least
{"vehicle_id", "plate"} and optionally make / model / color / vehicle_type / fuel_type.
"""
from matching.normalize import normalize_plate
from matching.similarity import (
    jaro_winkler,
    levenshtein_similarity,
    ocr_similarity,
    hybrid_similarity,
    HYBRID_OCR_WEIGHT,
)

METHODS = {
    "levenshtein": levenshtein_similarity,
    "jaro_winkler": jaro_winkler,
    "ocr_weighted": ocr_similarity,
    "hybrid": hybrid_similarity,
}

METHOD_LABELS = {
    "levenshtein": "Levenshtein (unit cost)",
    "jaro_winkler": "Jaro-Winkler",
    "ocr_weighted": "OCR-weighted edit distance",
    "hybrid": f"Hybrid ({int(HYBRID_OCR_WEIGHT * 100)}% OCR-weighted + {int(round((1 - HYBRID_OCR_WEIGHT) * 100))}% Jaro-Winkler)",
}

# Selected by matching.evaluation (highest F1 on the labelled OCR-noise test set,
# see docs/approximate_matching.md). tests/test_matching.py re-checks this choice.
DEFAULT_METHOD = "ocr_weighted"

# Minimum plate similarity (under the chosen method) for a vehicle to be listed as a
# plausible candidate. 0.80 on a 10-character plate ~= two real character edits (or
# up to eight OCR glyph confusions).
DEFAULT_CANDIDATE_THRESHOLD = 0.80


def score_plate(query: str, plate: str) -> dict:
    """All similarity scores between two normalised plates."""
    jw = jaro_winkler(query, plate)
    ocr = ocr_similarity(query, plate)
    return {
        "levenshtein": round(levenshtein_similarity(query, plate), 4),
        "jaro_winkler": round(jw, 4),
        "ocr_weighted": round(ocr, 4),
        "hybrid": round(HYBRID_OCR_WEIGHT * ocr + (1 - HYBRID_OCR_WEIGHT) * jw, 4),
    }


def find_candidates(raw_plate, index, method: str = DEFAULT_METHOD,
                    threshold: float = DEFAULT_CANDIDATE_THRESHOLD, limit: int = None):
    """
    Return every registered vehicle whose plate similarity (under `method`) is at
    least `threshold`, ranked best-first. Each candidate carries all method scores.
    """
    if method not in METHODS:
        raise ValueError(f"Unknown similarity method '{method}'. Choose from {list(METHODS)}")
    query = normalize_plate(raw_plate)
    if not query:
        return []

    primary = METHODS[method]
    candidates = []
    for vehicle in index:
        plate = vehicle["plate"]
        # Cheap length gate: a 3+ character length difference can never reach 0.80
        if abs(len(plate) - len(query)) > 3:
            continue
        score = ocr_similarity(query, plate, threshold) if method == "ocr_weighted" else primary(query, plate)
        if score < threshold:
            continue
        scores = score_plate(query, plate)
        candidates.append({
            **vehicle,
            "plate_score": round(score, 4),
            "scores": scores,
            "exact": plate == query,
        })

    candidates.sort(key=lambda c: (-c["plate_score"], -c["scores"]["jaro_winkler"], c["plate"]))
    for rank, c in enumerate(candidates, 1):
        c["rank"] = rank
    return candidates[:limit] if limit else candidates


def best_match(query: str, plates, scorer):
    """
    Return (best_plate, best_score, runner_up_score) of a normalised query against a
    list of plates. Used by the evaluation harness, where only the top-2 matter.
    """
    best_plate, best, second = None, -1.0, -1.0
    for plate in plates:
        s = scorer(query, plate)
        if s > best:
            second = best
            best, best_plate = s, plate
        elif s > second:
            second = s
    return best_plate, best, second
