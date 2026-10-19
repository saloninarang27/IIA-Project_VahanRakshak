"""
Contextual evidence: compares the vehicle attributes observed alongside a noisy
plate (camera make/model/colour detection, insurer records, ...) with those of a
registered candidate vehicle.

Each attribute resolves to MATCH, MISMATCH or MISSING (unknown on either side).
Missing information is never treated as agreement - it only reduces the amount
of evidence available to the decision engine.
"""
import re

from matching.similarity import jaro_winkler

# (attribute, weight). Model is the most discriminating, colour the least reliable.
CONTEXT_ATTRIBUTES = [
    ("make", 0.30),
    ("model", 0.35),
    ("color", 0.20),
    ("vehicle_type", 0.15),
]

ATTRIBUTE_MATCH_THRESHOLD = 0.92

_SYNONYMS = {
    "gray": "grey",
    "maruti": "maruti suzuki",
    "suzuki": "maruti suzuki",
    "vw": "volkswagen",
    "mg motor": "mg",
    "silver grey": "silver",
    "wine red": "maroon",
}


def _clean(value):
    if value is None:
        return ""
    text = re.sub(r"[^a-z0-9 ]", " ", str(value).lower())
    text = re.sub(r"\s+", " ", text).strip()
    return _SYNONYMS.get(text, text)


def compare_attribute(observed, registered) -> dict:
    a, b = _clean(observed), _clean(registered)
    if not a or not b:
        return {"status": "MISSING", "observed": observed, "registered": registered, "similarity": None}
    if a == b:
        sim = 1.0
    elif a.replace(" ", "") == b.replace(" ", ""):
        sim = 1.0
    else:
        sim = jaro_winkler(a, b)
    status = "MATCH" if sim >= ATTRIBUTE_MATCH_THRESHOLD else "MISMATCH"
    return {"status": status, "observed": observed, "registered": registered, "similarity": round(sim, 3)}


def has_context(observed: dict) -> bool:
    return any(_clean((observed or {}).get(attr)) for attr, _ in CONTEXT_ATTRIBUTES)


def compare_context(observed: dict, candidate: dict) -> dict:
    """
    Returns {"score": float|None, "matches": int, "mismatches": int, "missing": int,
             "attributes": {attr: comparison}}.
    score is the weighted share of compared attributes that agree, None if nothing
    could be compared.
    """
    observed = observed or {}
    attributes = {}
    matched_w = compared_w = 0.0
    matches = mismatches = missing = 0
    for attr, weight in CONTEXT_ATTRIBUTES:
        cmp = compare_attribute(observed.get(attr), candidate.get(attr))
        attributes[attr] = cmp
        if cmp["status"] == "MISSING":
            missing += 1
            continue
        compared_w += weight
        if cmp["status"] == "MATCH":
            matched_w += weight
            matches += 1
        else:
            mismatches += 1
    score = round(matched_w / compared_w, 4) if compared_w else None
    return {"score": score, "matches": matches, "mismatches": mismatches,
            "missing": missing, "attributes": attributes}
