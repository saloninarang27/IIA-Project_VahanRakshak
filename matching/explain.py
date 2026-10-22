"""
Step-by-step explanation of how a candidate's scores were calculated, for the UI.

Every number comes from the same functions that produce the scores (matching/similarity.py,
matching/context.py, matching/cleansing.py), so the explanation always agrees with the
values shown in the decision and the candidate table.
"""
from matching.context import CONTEXT_ATTRIBUTES
from matching.similarity import (
    HYBRID_OCR_WEIGHT,
    common_prefix,
    is_ocr_confusable,
    jaro,
    jaro_counts,
    jaro_winkler,
    levenshtein_distance,
    ocr_alignment,
    ocr_weighted_distance,
)

ATTRIBUTE_LABELS = {"make": "Make", "model": "Model", "color": "Colour", "vehicle_type": "Type"}

_EDIT_KIND = {
    "insert": "missing character",
    "delete": "extra character",
    "transpose": "two characters swapped",
}


def _f(x, d=3):
    return f"{x:.{d}f}"


def _ocr_weighted(reading, plate):
    edits = []
    for e in ocr_alignment(reading, plate):
        if e["op"] == "substitute":
            kind = "look-alike swap" if is_ocr_confusable(e["from"], e["to"]) else "substitution"
        else:
            kind = _EDIT_KIND[e["op"]]
        edits.append({**e, "kind": kind})
    cost = ocr_weighted_distance(reading, plate)
    longest = max(len(reading), len(plate))
    value = max(0.0, 1.0 - cost / longest) if longest else 1.0
    return {
        "label": "OCR-weighted edit distance",
        "edits": edits,
        "total_cost": round(cost, 4),
        "longest": longest,
        "value": round(value, 4),
        "formula": f"1 − {cost:g} ÷ {longest} = {_f(value)}",
        "note": "look-alike swap (O/0, I/1, B/8 …) costs 0.25 (letter↔letter 0.5); any other edit costs 1",
    }


def _levenshtein(reading, plate):
    distance = levenshtein_distance(reading, plate)
    longest = max(len(reading), len(plate))
    value = 1.0 - distance / longest if longest else 1.0
    return {
        "label": "Levenshtein",
        "distance": distance,
        "longest": longest,
        "value": round(value, 4),
        "formula": f"1 − {distance} edit(s) ÷ {longest} = {_f(value)}",
        "note": "every insertion, deletion or substitution costs 1",
    }


def _jaro_winkler(reading, plate):
    value = jaro_winkler(reading, plate)
    if reading == plate:
        return {"label": "Jaro–Winkler", "value": 1.0, "formula": "identical strings = 1.000",
                "note": "", "matches": len(reading), "transpositions": 0, "prefix": len(reading[:4])}
    m, t = jaro_counts(reading, plate)
    j = jaro(reading, plate)
    prefix = common_prefix(reading, plate)
    jaro_formula = (f"Jaro = ({m}/{len(reading)} + {m}/{len(plate)} + ({m}−{t})/{m}) ÷ 3 = {_f(j)}"
                    if m else "Jaro = 0 (no matching characters)")
    if j > 0.7:
        boost = (f"Jaro–Winkler = {_f(j)} + {prefix} × 0.1 × (1 − {_f(j)}) = {_f(value)}"
                 f"  (bonus for {prefix} shared leading character{'s' if prefix != 1 else ''})")
    else:
        boost = f"Jaro–Winkler = Jaro = {_f(value)}  (no prefix bonus when Jaro ≤ 0.7)"
    return {
        "label": "Jaro–Winkler",
        "matches": m,
        "transpositions": t,
        "prefix": prefix,
        "jaro": round(j, 4),
        "value": round(value, 4),
        "formula": f"{jaro_formula};  {boost}",
        "note": "matching characters within a window, transpositions, plus a bonus for a shared start",
    }


def _hybrid(ocr, jw):
    w = HYBRID_OCR_WEIGHT
    value = w * ocr["value"] + (1 - w) * jw["value"]
    return {
        "label": "Hybrid",
        "value": round(value, 4),
        "formula": f"{w:g} × {_f(ocr['value'])} + {1 - w:.1f} × {_f(jw['value'])} = {_f(value)}",
        "note": "OCR-weighted and Jaro–Winkler blended",
    }


def _context(context):
    if not context or context.get("score") is None:
        return None
    rows, matched_w, compared_w = [], 0.0, 0.0
    for attr, weight in CONTEXT_ATTRIBUTES:
        c = context["attributes"][attr]
        if c["status"] != "MISSING":
            compared_w += weight
            if c["status"] == "MATCH":
                matched_w += weight
        rows.append({"attribute": ATTRIBUTE_LABELS[attr], "weight": weight, "status": c["status"],
                     "observed": c["observed"], "registered": c["registered"]})
    matched_terms = " + ".join(f"{r['weight']:.2f}" for r in rows if r["status"] == "MATCH") or "0"
    compared_terms = " + ".join(f"{r['weight']:.2f}" for r in rows if r["status"] != "MISSING")
    return {
        "attributes": rows,
        "matched_weight": round(matched_w, 4),
        "compared_weight": round(compared_w, 4),
        "value": context["score"],
        "formula": f"agreeing weight ÷ compared weight = ({matched_terms}) ÷ ({compared_terms}) = {_f(context['score'])}",
        "note": "only attributes that were observed are compared; missing ones are never counted as agreement",
    }


def score_breakdown(reading, candidate, method, plate_weight, context_weight):
    """
    reading: normalised plate; candidate: a matcher candidate (plate, plate_score, context,
    combined_score). Returns {"method", "plate", "context", "combined", "methods"}.
    """
    plate = candidate["plate"]
    ocr = _ocr_weighted(reading, plate)
    lev = _levenshtein(reading, plate)
    jw = _jaro_winkler(reading, plate)
    methods = {"ocr_weighted": ocr, "levenshtein": lev, "jaro_winkler": jw, "hybrid": _hybrid(ocr, jw)}

    plate_score = candidate["plate_score"]
    context = _context(candidate.get("context"))
    combined = candidate.get("combined_score", plate_score)
    if context:
        combined_formula = (f"{plate_weight:.2f} × plate similarity + {context_weight:.2f} × context score = "
                            f"{plate_weight:.2f} × {_f(plate_score)} + {context_weight:.2f} × {_f(context['value'])} = {_f(combined)}")
    else:
        combined_formula = f"no vehicle attributes observed, so combined = plate similarity = {_f(plate_score)}"
    return {
        "reading": reading,
        "plate": plate,
        "method": method,
        "plate_similarity": {**methods[method], "value": plate_score},
        "context": context,
        "combined": {"value": combined, "formula": combined_formula,
                     "plate_weight": plate_weight, "context_weight": context_weight},
        "methods": methods,
    }
