"""
Registration-record cleansing rule engine.

assess_record() combines plate similarity with contextual evidence and decides:

    ACCEPT  - the plate is a registered plate and nothing contradicts it
    CORRECT - the plate is not registered, and the evidence is strong enough to
              replace it with exactly one registered plate
    REJECT  - nothing plausible to match (missing / unreadable / unregistered plate)
    REVIEW  - plausible but conflicting, ambiguous or under-evidenced: a human decides

Rules, applied in order (thresholds below):

  R1  plate missing or shorter than 4 chars               -> REJECT  MISSING_PLATE / UNREADABLE_PLATE
  R2  no registered plate with similarity >= 0.80         -> REJECT  NO_PLAUSIBLE_MATCH
  R3  exact plate hit, an attribute contradicts it        -> REVIEW  CONFLICTING_ATTRIBUTES
  R4  exact plate hit, no contradiction                   -> ACCEPT  EXACT_MATCH
  R5  two candidates within 0.05 combined score           -> REVIEW  AMBIGUOUS_MATCH
  R6  best candidate contradicted by an attribute         -> REVIEW  CONFLICTING_ATTRIBUTES
  R7  similarity >= 0.85 and >= 2 attributes agree        -> CORRECT CONTEXT_CONFIRMED
  R8  no context, every edit is an OCR-confusable glyph swap,
      similarity >= 0.90 and >= 0.05 ahead of runner-up   -> CORRECT OCR_CONFUSION_ONLY
  R9  anything else                                       -> REVIEW  INSUFFICIENT_EVIDENCE
"""
from matching.normalize import normalize_plate, is_valid_plate_format, MIN_PLATE_LENGTH
from matching.matcher import find_candidates, DEFAULT_METHOD, DEFAULT_CANDIDATE_THRESHOLD
from matching.context import compare_context, has_context, CONTEXT_ATTRIBUTES
from matching.similarity import explain_edits

CORRECTION_THRESHOLD = 0.85
OCR_ONLY_CORRECTION_THRESHOLD = 0.90
AMBIGUITY_MARGIN = 0.05
MIN_AGREEING_ATTRIBUTES = 2
PLATE_WEIGHT = 0.65
CONTEXT_WEIGHT = 0.35
MAX_CANDIDATES_RETURNED = 25

DECISION_STATUS = {
    "ACCEPT": "ACCEPTED",
    "CORRECT": "CORRECTED",
    "REJECT": "REJECTED",
    "REVIEW": "PENDING_REVIEW",
}

RULES = [
    {"rule": "R1", "condition": "Plate missing or shorter than 4 characters", "decision": "REJECT", "reason_code": "MISSING_PLATE / UNREADABLE_PLATE"},
    {"rule": "R2", "condition": f"No registered plate with similarity >= {DEFAULT_CANDIDATE_THRESHOLD}", "decision": "REJECT", "reason_code": "NO_PLAUSIBLE_MATCH"},
    {"rule": "R3", "condition": "Exact registered plate, but make/model/colour/type contradicts it", "decision": "REVIEW", "reason_code": "CONFLICTING_ATTRIBUTES"},
    {"rule": "R4", "condition": "Exact registered plate, no contradicting attribute", "decision": "ACCEPT", "reason_code": "EXACT_MATCH"},
    {"rule": "R5", "condition": f"Runner-up within {AMBIGUITY_MARGIN} combined score of the best candidate", "decision": "REVIEW", "reason_code": "AMBIGUOUS_MATCH"},
    {"rule": "R6", "condition": "Best candidate contradicted by an observed attribute", "decision": "REVIEW", "reason_code": "CONFLICTING_ATTRIBUTES"},
    {"rule": "R7", "condition": f"Plate similarity >= {CORRECTION_THRESHOLD} and >= {MIN_AGREEING_ATTRIBUTES} attributes agree, none contradict", "decision": "CORRECT", "reason_code": "CONTEXT_CONFIRMED"},
    {"rule": "R8", "condition": f"No context available, every edit is an OCR-confusable glyph swap, similarity >= {OCR_ONLY_CORRECTION_THRESHOLD} and unique", "decision": "CORRECT", "reason_code": "OCR_CONFUSION_ONLY"},
    {"rule": "R9", "condition": "Any other plausible match", "decision": "REVIEW", "reason_code": "INSUFFICIENT_EVIDENCE"},
]


def _observed_context(record: dict) -> dict:
    return {attr: record.get(attr) for attr, _ in CONTEXT_ATTRIBUTES}


def _combined(plate_score: float, context_score):
    if context_score is None:
        return plate_score
    return PLATE_WEIGHT * plate_score + CONTEXT_WEIGHT * context_score


def _describe(c):
    return f"{c['plate']} (#{c['vehicle_id']}, {c.get('make') or '?'} {c.get('model') or '?'}, {c.get('color') or '?'})"


def assess_record(record: dict, index, method: str = DEFAULT_METHOD,
                  threshold: float = DEFAULT_CANDIDATE_THRESHOLD,
                  max_candidates: int = MAX_CANDIDATES_RETURNED) -> dict:
    """
    record: {"plate": raw plate, optional "make", "model", "color", "vehicle_type"}
    index:  reference index of registered vehicles (see matching.matcher)
    threshold: minimum plate similarity for a vehicle to count as a plausible candidate
    """
    original = record.get("plate")
    normalized = normalize_plate(original)
    observed = _observed_context(record)
    context_available = has_context(observed)

    result = {
        "original_plate": original,
        "normalized_plate": normalized,
        "format_valid": is_valid_plate_format(normalized) if normalized else False,
        "observed": observed,
        "context_available": context_available,
        "method": method,
        "decision": None,
        "decision_status": None,
        "rule": None,
        "reason_code": None,
        "reason": None,
        "flags": [],
        "corrected_plate": None,
        "suggested_plate": None,
        "matched_vehicle_id": None,
        "matched_plate": None,
        "similarity_score": None,
        "context_score": None,
        "combined_score": None,
        "edits": [],
        "candidate_count": 0,
        "candidates": [],
    }

    def decide(decision, rule, reason_code, reason, match=None, corrected=None, suggested=None):
        result.update({
            "decision": decision,
            "decision_status": DECISION_STATUS[decision],
            "rule": rule,
            "reason_code": reason_code,
            "reason": reason,
            "corrected_plate": corrected,
            "suggested_plate": suggested,
        })
        if match:
            result.update({
                "matched_vehicle_id": match["vehicle_id"],
                "matched_plate": match["plate"],
                "similarity_score": match["plate_score"],
                "context_score": match["context"]["score"],
                "combined_score": match["combined_score"],
                "edits": explain_edits(normalized, match["plate"]),
            })
        return result

    # R1 - missing information
    if not normalized:
        result["flags"].append("MISSING_PLATE")
        return decide("REJECT", "R1", "MISSING_PLATE", "No registration number was supplied or readable.")
    if len(normalized) < MIN_PLATE_LENGTH:
        result["flags"].append("UNREADABLE_PLATE")
        return decide("REJECT", "R1", "UNREADABLE_PLATE",
                      f"'{normalized}' is too short ({len(normalized)} chars) to identify a vehicle.")
    if not result["format_valid"]:
        result["flags"].append("NON_STANDARD_FORMAT")
    if not context_available:
        result["flags"].append("MISSING_CONTEXT")

    candidates = find_candidates(normalized, index, method=method, threshold=threshold)
    for c in candidates:
        c["context"] = compare_context(observed, c)
        c["combined_score"] = round(_combined(c["plate_score"], c["context"]["score"]), 4)
    candidates.sort(key=lambda c: (-c["combined_score"], -c["plate_score"], c["plate"]))
    for rank, c in enumerate(candidates, 1):
        c["rank"] = rank
    result["candidate_count"] = len(candidates)
    result["candidates"] = candidates[:max_candidates]

    # R2 - nothing plausible
    if not candidates:
        return decide("REJECT", "R2", "NO_PLAUSIBLE_MATCH",
                      f"No registered vehicle has a plate similarity >= {threshold} to '{normalized}'.")

    exact = next((c for c in candidates if c["exact"]), None)
    if exact:
        ctx = exact["context"]
        if ctx["mismatches"]:
            # R3 - the plate exists, but the vehicle it belongs to looks different
            result["flags"].append("CONFLICT")
            conflicting = [a for a, v in ctx["attributes"].items() if v["status"] == "MISMATCH"]
            alternative = next((c for c in candidates
                                if not c["exact"] and c["plate_score"] >= CORRECTION_THRESHOLD
                                and c["context"]["mismatches"] == 0
                                and c["context"]["matches"] >= MIN_AGREEING_ATTRIBUTES), None)
            reason = (f"{normalized} is registered, but observed {', '.join(conflicting)} contradict the registry "
                      f"({_describe(exact)}). Possible misread of another plate or a cloned plate.")
            if alternative:
                reason += f" Observed attributes fit {_describe(alternative)} instead."
            return decide("REVIEW", "R3", "CONFLICTING_ATTRIBUTES", reason, match=exact,
                          suggested=alternative["plate"] if alternative else None)
        # R4
        evidence = (f"; {ctx['matches']} contextual attribute(s) agree" if ctx["matches"]
                    else "; no contextual attributes to cross-check")
        sources = exact.get("sources")
        if sources and "VAHAN" not in sources:
            # The reading is a real plate known to other agencies, but it has no registration record
            result["flags"].append("NOT_IN_VAHAN")
            return decide("ACCEPT", "R4", "EXACT_MATCH",
                          f"{normalized} exists in {', '.join(sources)} but is NOT registered in VAHAN{evidence}.",
                          match=exact)
        found = f" (found in {', '.join(sources)})" if sources else ""
        return decide("ACCEPT", "R4", "EXACT_MATCH",
                      f"{normalized} is a registered plate{found}{evidence}.", match=exact)

    best = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None
    ctx = best["context"]

    # R5 - ambiguity
    if runner_up and best["combined_score"] - runner_up["combined_score"] < AMBIGUITY_MARGIN:
        result["flags"].append("AMBIGUOUS")
        tied = [c for c in candidates if best["combined_score"] - c["combined_score"] < AMBIGUITY_MARGIN]
        shown = ", ".join(c["plate"] for c in tied[:5]) + (" ..." if len(tied) > 5 else "")
        return decide("REVIEW", "R5", "AMBIGUOUS_MATCH",
                      f"{len(tied)} registered vehicles score within {AMBIGUITY_MARGIN} of each other ({shown}); "
                      f"the record cannot be resolved to a single vehicle.",
                      match=best, suggested=best["plate"])

    # R6 - contradicted best candidate
    if ctx["mismatches"]:
        result["flags"].append("CONFLICT")
        conflicting = [a for a, v in ctx["attributes"].items() if v["status"] == "MISMATCH"]
        return decide("REVIEW", "R6", "CONFLICTING_ATTRIBUTES",
                      f"Closest plate {_describe(best)} contradicts the observed {', '.join(conflicting)}.",
                      match=best, suggested=best["plate"])

    # R7 - plate + context agree
    if best["plate_score"] >= CORRECTION_THRESHOLD and ctx["matches"] >= MIN_AGREEING_ATTRIBUTES:
        agreeing = [a for a, v in ctx["attributes"].items() if v["status"] == "MATCH"]
        return decide("CORRECT", "R7", "CONTEXT_CONFIRMED",
                      f"'{normalized}' is not registered. {best['plate']} is {best['plate_score']:.2f} similar and "
                      f"its {', '.join(agreeing)} agree with the observation.",
                      match=best, corrected=best["plate"])

    # R8 - pure OCR glyph confusion, unique
    plate_gap = best["plate_score"] - (runner_up["plate_score"] if runner_up else 0.0)
    edits = explain_edits(normalized, best["plate"])
    glyph_swaps_only = bool(edits) and all(e["op"] == "substitute" and e["ocr_confusable"] for e in edits)
    if (not context_available and glyph_swaps_only and best["plate_score"] >= OCR_ONLY_CORRECTION_THRESHOLD
            and plate_gap >= AMBIGUITY_MARGIN):
        swaps = ", ".join(f"{e['from']}->{e['to']}" for e in edits)
        return decide("CORRECT", "R8", "OCR_CONFUSION_ONLY",
                      f"'{normalized}' differs from {best['plate']} only by OCR-confusable glyphs ({swaps}) "
                      f"and no other registered plate is close.",
                      match=best, corrected=best["plate"])

    # R9
    result["flags"].append("INSUFFICIENT_EVIDENCE")
    why = "no contextual attributes were supplied" if not context_available else (
        f"only {ctx['matches']} attribute(s) agree" if best["plate_score"] >= CORRECTION_THRESHOLD
        else f"plate similarity {best['plate_score']:.2f} is below {CORRECTION_THRESHOLD}")
    return decide("REVIEW", "R9", "INSUFFICIENT_EVIDENCE",
                  f"Closest registered plate is {_describe(best)}, but {why}.",
                  match=best, suggested=best["plate"])
