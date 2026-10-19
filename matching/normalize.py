"""
Registration-plate normalisation.

normalize_plate() is the single canonical cleaning step applied to every plate
before matching: uppercase, and drop every character that is not A-Z or 0-9
(spaces, hyphens, dots, slashes, underscores, OCR artefacts such as '|').
It deliberately does NOT try to "fix" characters (O -> 0 etc.) - that is the
similarity layer's job, so the original reading stays auditable.
"""
import re

_NON_ALNUM = re.compile(r"[^A-Z0-9]")

# Indian registration format: state code (2 letters), RTO district (1-2 digits),
# optional series (1-3 letters), number (1-4 digits). e.g. DL01AB1001, MH12XY4821.
# The BH-series (e.g. 22BH1234AA) is also accepted.
_INDIAN_PLATE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{1,4}$")
_BH_SERIES_PLATE = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")

MIN_PLATE_LENGTH = 4


def normalize_plate(raw) -> str:
    """Uppercase and remove spaces / separators. Returns '' for missing input."""
    if raw is None:
        return ""
    return _NON_ALNUM.sub("", str(raw).upper())


def is_valid_plate_format(plate: str) -> bool:
    """True if an already-normalised plate conforms to the Indian plate grammar."""
    return bool(_INDIAN_PLATE.match(plate) or _BH_SERIES_PLATE.match(plate))
