"""
Deterministic noisy registration records for the data-cleansing demo and tests.

Each record imitates a row arriving from an agency feed (ANPR camera read, insurer
policy entry, police FIR, e-challan) whose registration number may be corrupted.
Every record carries:
    scenario            - which data-quality problem it exercises
    ground_truth_plate  - the vehicle it really refers to (None if unregistered);
                          evaluation label only, never read by the rule engine
    expected_decision   - what a careful operator would decide

Scenarios (item 20 of the brief):
    CLEAN_EXACT, FORMATTING_NOISE                     -> ACCEPT
    OCR_CONFUSION_WITH_CONTEXT, OCR_CONFUSION_NO_CONTEXT,
    TYPO_WITH_CONTEXT                                 -> CORRECT
    TYPO_MISSING_CONTEXT, CONFLICTING_DETAILS,
    WRONG_VALID_PLATE, MULTIPLE_MATCHES               -> REVIEW
    MISSING_PLATE, UNREADABLE_PLATE, NOT_REGISTERED   -> REJECT
"""
import random

from matching.similarity import levenshtein_distance

# Unambiguous glyph confusions used to corrupt plates (each maps to exactly one
# character class that can appear in that position of a registered plate).
_OCR_INJECT = {
    "0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B",
    "D": "0", "L": "1", "B": "8", "A": "4", "S": "5", "Z": "2",
}

# Spelling variants an upstream system might use for the same attribute value
_ATTRIBUTE_VARIANTS = {
    "Grey": "Gray", "Maruti Suzuki": "Maruti", "Volkswagen": "VW", "Silver": "silver",
    "Toyota": "TOYOTA", "Hyundai": "hyundai",
}

SCENARIOS = [
    # (scenario, count, expected_decision, source_system)
    ("CLEAN_EXACT", 12, "ACCEPT", "ANPR_CAMERA"),
    ("FORMATTING_NOISE", 10, "ACCEPT", "IIB"),
    ("OCR_CONFUSION_WITH_CONTEXT", 20, "CORRECT", "ANPR_CAMERA"),
    ("OCR_CONFUSION_NO_CONTEXT", 10, "CORRECT", "ANPR_CAMERA"),
    ("TYPO_WITH_CONTEXT", 12, "CORRECT", "IIB"),
    ("TYPO_MISSING_CONTEXT", 8, "REVIEW", "ECHALLAN"),
    ("MISSING_PLATE", 4, "REJECT", "POLICE_CCTNS"),
    ("UNREADABLE_PLATE", 2, "REJECT", "ANPR_CAMERA"),
    ("CONFLICTING_DETAILS", 10, "REVIEW", "POLICE_CCTNS"),
    ("WRONG_VALID_PLATE", 8, "REVIEW", "ANPR_CAMERA"),
    ("MULTIPLE_MATCHES", 8, "REVIEW", "ECHALLAN"),
    ("NOT_REGISTERED", 8, "REJECT", "ANPR_CAMERA"),
]

_OTHER_STATES = ["MH", "KA", "TN", "GJ", "RJ", "WB", "UP", "KL"]
_SOURCE_PREFIX = {"ANPR_CAMERA": "CAP", "IIB": "POL", "POLICE_CCTNS": "FIR", "ECHALLAN": "CHN"}


def _vary(value, rng):
    if value in _ATTRIBUTE_VARIANTS and rng.random() < 0.35:
        return _ATTRIBUTE_VARIANTS[value]
    return value


def _context(vehicle, rng, fields=("make", "model", "color", "vehicle_type")):
    return {f: (_vary(vehicle.get(f), rng) if f in fields else None)
            for f in ("make", "model", "color", "vehicle_type")}


def inject_ocr_errors(plate, k, rng, registered):
    positions = [i for i, ch in enumerate(plate) if ch in _OCR_INJECT]
    for _ in range(50):
        chars = list(plate)
        for i in rng.sample(positions, k):
            chars[i] = _OCR_INJECT[chars[i]]
        noisy = "".join(chars)
        if noisy not in registered:
            return noisy
    raise ValueError(f"could not corrupt {plate}")


def _profile(v):
    return (v.get("make"), v.get("model"), v.get("color"), v.get("vehicle_type"))


def _typo(vehicle, rng, vehicles, registered, require_unique_profile):
    """
    Single insertion or deletion that does not land on another registered plate.
    With require_unique_profile, also avoid typos that are one edit away from a
    different vehicle with an identical make/model/colour/type - such a record is
    genuinely unresolvable (even for a human) and belongs to MULTIPLE_MATCHES.
    """
    plate = vehicle["plate"]
    for _ in range(50):
        pos = rng.randrange(2, len(plate))
        if rng.random() < 0.5:
            noisy = plate[:pos] + plate[pos + 1:]
        else:
            noisy = plate[:pos] + rng.choice("0123456789") + plate[pos:]
        if noisy in registered:
            continue
        if require_unique_profile and any(
                o["plate"] != plate and _profile(o) == _profile(vehicle)
                and levenshtein_distance(noisy, o["plate"]) <= 1 for o in vehicles):
            continue
        return noisy
    raise ValueError(f"could not corrupt {plate}")


def _formatting(plate, rng):
    state, rto, series, number = plate[:2], plate[2:4], plate[4:6], plate[6:]
    style = rng.randrange(5)
    if style == 0:
        return f"{state} {rto} {series} {number}".lower()
    if style == 1:
        return f"{state}-{rto}-{series}-{number}"
    if style == 2:
        return f"{state}.{rto}.{series}.{number}"
    if style == 3:
        return f" {state}{rto} / {series}{number} "
    return f"{state} {rto}{series}-{number}".title()


def _differs_fully(a, b):
    return a["make"] != b["make"] and a["model"] != b["model"] and a["color"] != b["color"]


def generate_noisy_records(index, seed: int = 7):
    """Build the noisy-record fixture list from the reference index of registered vehicles."""
    rng = random.Random(seed)
    vehicles = sorted(index, key=lambda v: v["plate"])
    registered = {v["plate"] for v in vehicles}
    by_plate = {v["plate"]: v for v in vehicles}
    pool = vehicles[:]
    rng.shuffle(pool)
    pool_iter = iter(pool)

    records = []
    counter = 0

    def add(scenario, expected, source, plate, ctx, truth):
        nonlocal counter
        counter += 1
        records.append({
            "source_system": source,
            "source_reference": f"{_SOURCE_PREFIX[source]}-{100000 + counter * 37}",
            "raw_plate": plate,
            "make": ctx.get("make"),
            "model": ctx.get("model"),
            "color": ctx.get("color"),
            "vehicle_type": ctx.get("vehicle_type"),
            "observed_at": f"2026-09-{1 + counter % 14:02d} {8 + counter % 12:02d}:{counter % 60:02d}:00",
            "scenario": scenario,
            "ground_truth_plate": truth,
            "expected_decision": expected,
        })

    empty_ctx = {"make": None, "model": None, "color": None, "vehicle_type": None}

    for scenario, count, expected, source in SCENARIOS:
        for i in range(count):
            v = next(pool_iter)
            plate = v["plate"]
            if scenario == "CLEAN_EXACT":
                add(scenario, expected, source, plate, _context(v, rng), plate)
            elif scenario == "FORMATTING_NOISE":
                add(scenario, expected, source, _formatting(plate, rng),
                    _context(v, rng, ("make", "color")), plate)
            elif scenario == "OCR_CONFUSION_WITH_CONTEXT":
                add(scenario, expected, source, inject_ocr_errors(plate, 1 + i % 2, rng, registered),
                    _context(v, rng), plate)
            elif scenario == "OCR_CONFUSION_NO_CONTEXT":
                add(scenario, expected, source, inject_ocr_errors(plate, 1 + i % 2, rng, registered),
                    empty_ctx, plate)
            elif scenario == "TYPO_WITH_CONTEXT":
                add(scenario, expected, source, _typo(v, rng, vehicles, registered, True),
                    _context(v, rng), plate)
            elif scenario == "TYPO_MISSING_CONTEXT":
                add(scenario, expected, source, _typo(v, rng, vehicles, registered, False), empty_ctx, plate)
            elif scenario == "MISSING_PLATE":
                add(scenario, expected, source, ["", None, " - ", "N/A"][i % 4], _context(v, rng), plate)
            elif scenario == "UNREADABLE_PLATE":
                add(scenario, expected, source, plate[:3], _context(v, rng), plate)
            elif scenario == "CONFLICTING_DETAILS":
                # Correct plate, but the attributes describe a completely different vehicle
                other = next(o for o in pool if _differs_fully(o, v))
                add(scenario, expected, source, plate, _context(other, rng), plate)
            elif scenario == "WRONG_VALID_PLATE":
                # Misread of one digit that happens to produce ANOTHER registered plate
                for _ in range(50):
                    pos = rng.randrange(7, len(plate))
                    wrong = plate[:pos] + rng.choice("0123456789") + plate[pos + 1:]
                    if wrong != plate and wrong in registered and _differs_fully(by_plate[wrong], v):
                        break
                add(scenario, expected, source, wrong, _context(v, rng), plate)
            elif scenario == "MULTIPLE_MATCHES":
                # Last digit lost and only the (non-distinctive) colour observed
                add(scenario, expected, source, plate[:-1], _context(v, rng, ("color",)), plate)
            elif scenario == "NOT_REGISTERED":
                state = _OTHER_STATES[i % len(_OTHER_STATES)]
                fake = f"{state}{rng.randint(10, 99)}{rng.choice('KMNPRXY')}{rng.choice('CEFHJTW')}{rng.randint(1000, 9999)}"
                add(scenario, expected, source, fake, _context(v, rng), None)
    return records
