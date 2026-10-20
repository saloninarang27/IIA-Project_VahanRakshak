"""
Identifier mapping / normalization.

The five independent databases deliberately use DIFFERENT column names for
the same real-world vehicle:

    vehicle_capture.db       -> plate_number
    insurance.db              -> registration_no
    registration.db           -> vehicle_registration_id
    theft_scrap.db            -> vehicle_no
    ministry.db                -> vehicle_identifier

The mapping itself lives in matching/sources.py (one map shared by the web system
and this in-process layer); this module exposes it and normalizes a
raw plate string (whitespace, case, hyphens) into the canonical form used
to query every source consistently.
"""

from matching.sources import SOURCES

# Derived from the single source map in matching/sources.py
SOURCE_COLUMN_MAP = {
    s["legacy_key"]: {"db_key": s["legacy_key"], "table": s["table"], "id_column": s["id_column"]}
    for s in SOURCES
}


def normalize_identifier(raw_identifier: str) -> str:
    """Normalize a captured/typed plate number into the canonical form
    used as the join value across all independent sources."""
    if raw_identifier is None:
        raise ValueError("Vehicle identifier cannot be None")
    cleaned = raw_identifier.strip().upper().replace(" ", "").replace("-", "")
    if not cleaned:
        raise ValueError("Vehicle identifier cannot be empty")
    return cleaned


def id_column_for(source_key: str) -> str:
    """Return the vehicle-identifier column name used by a given source."""
    return SOURCE_COLUMN_MAP[source_key]["id_column"]


def table_for(source_key: str) -> str:
    return SOURCE_COLUMN_MAP[source_key]["table"]
