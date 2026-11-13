"""
Reading free text: tokens for BM25, and the entities a document mentions (plates written any way,
FIR / policy / claim ids, places, dates, events). The documents have no plate column - the vehicle
has to be found in the text, the way people actually write it:
  "DL01AB1004", "DL 01 AB 1004", "dl-01-ab-1004", an OCR slip "DL01A81004", or "a car ending 1004".
"""
import re
from datetime import date

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP = set("""a an the is was are were be been of in on at to for from by with and or not no it its this that
these those he she they his her their there here as into about after before near over under during while
has have had will would could should may might can than then also which who whom what when where""".split())

# plate written in any style: state letters, district number, series, number - each part may be split by a
# space / hyphen / dot (the series too: Delhi's "DL 7C D 1939"), and digits may be OCR-misread as O / I / L (and series letters as 8 / 0 ...)
PLATE_RE = re.compile(r"\b[A-Za-z]{2}[\s.\-]?[0-9OoIiLl]{1,2}[\s.\-]?[A-Za-z0-9]{0,3}(?:[\s.\-][A-Za-z]{1,2})?[\s.\-]?[A-Za-z0-9]{3,4}\b")
NOT_PLATE = re.compile(r"^(FIR|POL|CLM|OWN|MOT)", re.I)   # our record ids look plate-like
ENDING_RE = re.compile(r"\b(?:ending(?: in| with)?|last (?:four|4) digits)\s*(\d{4})\b", re.I)
ID_RES = {"fir": re.compile(r"\bFIR\s*-?\s*(\d{3,6})\b", re.I),
          "policy": re.compile(r"\bPOL\s*-?\s*(\d{5,8})\b", re.I),
          "claim": re.compile(r"\bCLM\s*-?\s*(\d{4,8})\b", re.I)}
ID_PREFIX = {"fir": "FIR", "policy": "POL", "claim": "CLM"}
CITIES = ["Gurugram", "Delhi", "Bengaluru", "Mumbai", "Chennai", "Noida", "Hyderabad", "Kolkata"]
CITY_ALIASES = {"gurgaon": "Gurugram", "bangalore": "Bengaluru", "bombay": "Mumbai", "madras": "Chennai",
                "calcutta": "Kolkata", "new delhi": "Delhi"}
ISO_DATE_RE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
TEXT_DATE_RE = re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+(20\d\d)\b", re.I)
MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
EVENT_WORDS = {
    "THEFT": ["stolen", "theft", "stole", "missing", "lifted"],
    "RECOVERY": ["recovered", "traced", "found abandoned", "returned to the owner"],
    "ACCIDENT": ["accident", "collision", "collided", "crash", "rammed", "hit-and-run", "hit and run", "overturned"],
    "FIRE": ["fire", "burnt", "gutted", "caught fire", "flames"],
    "FLOOD": ["flood", "waterlogged", "submerged"],
    "SCRAP": ["scrapped", "scrapping", "dismantled", "shredded"],
    "SIGHTING": ["spotted", "seen", "sighted", "noticed", "has been parked", "parked in a no-parking"],
    "CHALLAN": ["challan", "fined", "penalty", "violation"],
    "SALE": ["sold", "resale", "transferred", "new owner"],
}


def tokens(text):
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOP and len(t) > 1]


def plate_spans(text):
    """[(as written, normalised)] for every plate-like string. Noisy readings are kept as written."""
    out = []
    for m in PLATE_RE.finditer(text or ""):
        p = re.sub(r"[^A-Za-z0-9]", "", m.group(0)).upper()
        if 8 <= len(p) <= 10 and sum(ch.isdigit() for ch in p) >= 4 and not NOT_PLATE.match(p):
            out.append((m.group(0), p))
    return out


def plates_in(text):
    """Every plate-like string, normalised (uppercase alnum)."""
    return sorted({p for _, p in plate_spans(text)})


def endings_in(text):
    return sorted({m.group(1) for m in ENDING_RE.finditer(text or "")})


def ids_in(text):
    return {kind: sorted({ID_PREFIX[kind] + m.group(1) for m in rx.finditer(text or "")}) for kind, rx in ID_RES.items()}


def cities_in(text):
    low = (text or "").lower()
    found = {c for c in CITIES if c.lower() in low}
    found |= {canon for alias, canon in CITY_ALIASES.items() if alias in low}
    return sorted(found)


def dates_in(text):
    out = set()
    for y, m, d in ISO_DATE_RE.findall(text or ""):
        out.add(f"{y}-{m}-{d}")
    for d, mon, y in TEXT_DATE_RE.findall(text or ""):
        try:
            out.add(date(int(y), MONTHS[mon[:3].lower()], int(d)).isoformat())
        except ValueError:
            pass
    return sorted(out)


def events_in(text):
    low = (text or "").lower()
    return sorted(e for e, words in EVENT_WORDS.items() if any(w in low for w in words))


def entities(text):
    ids = ids_in(text)
    return {"plates": plates_in(text), "plate_endings": endings_in(text), "firs": ids["fir"],
            "policies": ids["policy"], "claims": ids["claim"], "cities": cities_in(text),
            "dates": dates_in(text), "events": events_in(text)}
