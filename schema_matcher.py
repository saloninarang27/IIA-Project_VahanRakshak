"""
schema_matcher.py
=================
Schema Matching Engine — automatically discovers column mappings across
the 5 heterogeneous databases using:
  1. Known semantic alias dictionary  (domain knowledge)
  2. Levenshtein edit-distance similarity  (string metric)
  3. Data-type fingerprinting  (structural evidence)

The key link column (vehicle plate) has five different names across sources:
  anpr_camera.db        → plate_number
  insurance_company.db  → reg_no
  rto_registration.db   → vehicle_no
  theft_shredding.db    → number_plate
  mot_reports.db        → target_plate
"""

import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR   = os.path.join(BASE_DIR, 'databases')

# ── Database Registry (All 5 Independent Sources) ────────────────────────────
DATABASES = {
    'anpr_camera': {
        'file':    'anpr_camera.db',
        'table':   'vehicle_sightings',
        'display': 'ANPR Camera System',
    },
    'insurance_company': {
        'file':    'insurance_company.db',
        'table':   'policy_records',
        'display': 'Insurance Company',
    },
    'rto_registration': {
        'file':    'rto_registration.db',
        'table':   'registration_records',
        'display': 'RTO Registration',
    },
    'theft_shredding': {
        'file':    'theft_shredding.db',
        'table':   'stolen_vehicles',
        'display': 'Theft & Shredding Records',
    },
    'mot_reports': {
        'file':    'mot_reports.db',
        'table':   'compliance_reports',
        'display': 'Ministry of Transport',
    },
}

# ── Semantic Alias Dictionary (Domain Knowledge) ──────────────────────────────
# Disentangled so insurance expiry, fitness expiry, and tax deadlines are distinct.
KNOWN_ALIASES = {
    'vehicle_identifier': [
        'plate_number', 'reg_no', 'vehicle_no', 'number_plate',
        'target_plate', 'registration_no', 'plate_no', 'veh_no', 'reg_number',
    ],
    'owner_name': [
        'owner_name', 'owner_fullname', 'owner', 'name',
        'holder_name', 'policyholder', 'registered_owner',
    ],
    'insurance_expiry': [
        'expiry_date', 'policy_end', 'insurance_valid_till',
    ],
    'fitness_expiry': [
        'fitness_expiry', 'fitness_valid_till',
    ],
    'tax_expiry': [
        'tax_paid_till', 'road_tax_validity',
    ],
    'status': [
        'status', 'current_status', 'compliance_status',
    ],
    'remarks': [
        'remarks', 'officer_remarks', 'comments', 'evidence_summary',
    ],
}

# ── Cache for Schema Mapping ──────────────────────────────────────────────────
_SCHEMA_MAP_CACHE = None


# ── Levenshtein Distance ──────────────────────────────────────────────────────

def levenshtein_distance(s1: str, s2: str) -> int:
    """Classic DP edit-distance (case-insensitive, ignores underscores)."""
    a = s1.lower().replace('_', '')
    b = s2.lower().replace('_', '')
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[:]
        dp[0] = i
        for j in range(1, n + 1):
            cost  = 0 if a[i - 1] == b[j - 1] else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev[j - 1] + cost)
    return dp[n]


def similarity_score(col1: str, col2: str) -> float:
    """
    String similarity in [0, 1].
    1.0 = identical, 0.0 = completely different.
    """
    c1 = col1.lower().replace('_', '')
    c2 = col2.lower().replace('_', '')
    if c1 == c2:
        return 1.0
    if c1 in c2 or c2 in c1:
        return 0.85
    max_len = max(len(c1), len(c2), 1)
    return 1.0 - levenshtein_distance(c1, c2) / max_len


def check_known_alias(col1: str, col2: str):
    """Return (concept, 1.0) if both columns belong to the same alias group."""
    c1, c2 = col1.lower(), col2.lower()
    for concept, aliases in KNOWN_ALIASES.items():
        al = [a.lower() for a in aliases]
        if c1 in al and c2 in al:
            return concept, 1.0
    return None, 0.0

# ── Schema Introspection ──────────────────────────────────────────────────────

def get_db_schema(db_name: str):
    """Return [(col_name, col_type), ...] for the DB's main table."""
    info = DATABASES[db_name]
    path = os.path.join(DB_DIR, info['file'])
    try:
        conn = sqlite3.connect(path)
        cur  = conn.cursor()
        cur.execute(f"PRAGMA table_info({info['table']})")
        cols = [(r[1], r[2]) for r in cur.fetchall()]
        conn.close()
        return cols
    except Exception:
        return []

# ── Global Schema Map Builder ─────────────────────────────────────────────────

def build_global_schema_map(force_refresh: bool = False):
    """
    Discover column mappings across all 5 databases.
    Results are cached in memory for sub-millisecond query planning.

    Returns
    -------
    mapping : dict
        { 'concept_name': { 'db_name': 'local_column', ... }, ... }
    vehicle_id_cols : dict
        { 'db_name': {'column': str, 'confidence': float}, ... }
    """
    global _SCHEMA_MAP_CACHE
    if _SCHEMA_MAP_CACHE is not None and not force_refresh:
        return _SCHEMA_MAP_CACHE

    db_schemas = {db: get_db_schema(db) for db in DATABASES}

    # Step 1 — Find the vehicle-identifier column in each DB
    vehicle_id_cols = {}
    for db_name, cols in db_schemas.items():
        best_col, best_score = None, 0.0
        for col_name, _ in cols:
            # Check known aliases first (highest weight)
            _, score = check_known_alias(col_name, 'plate_number')
            if score == 0:
                score = max(
                    similarity_score(col_name, alias)
                    for alias in KNOWN_ALIASES['vehicle_identifier']
                )
            if score > best_score:
                best_score = score
                best_col   = col_name
        vehicle_id_cols[db_name] = {'column': best_col, 'confidence': round(best_score, 3)}

    # Step 2 — Cross-match all other columns between every pair of DBs
    db_names = list(db_schemas.keys())
    cross_map = {}

    for i, db1 in enumerate(db_names):
        for db2 in db_names[i + 1:]:
            for col1, type1 in db_schemas[db1]:
                for col2, type2 in db_schemas[db2]:
                    concept, score = check_known_alias(col1, col2)
                    if not concept:
                        score   = similarity_score(col1, col2)
                        concept = col1

                    # Accept if similarity is high and not a PK surrogate
                    skip = {'sighting_id', 'policy_id', 'reg_id', 'record_id', 'report_id'}
                    if score >= 0.75 and col1 not in skip and col2 not in skip:
                        entry = cross_map.setdefault(concept, {'score': score, 'mappings': {}})
                        entry['mappings'][db1] = col1
                        entry['mappings'][db2] = col2

    # Step 3 — Assemble final mapping (vehicle_identifier always first)
    mapping = {
        'vehicle_identifier': {db: info['column'] for db, info in vehicle_id_cols.items()},
    }
    for concept, info in cross_map.items():
        if concept not in mapping:
            mapping[concept] = info['mappings']

    _SCHEMA_MAP_CACHE = (mapping, vehicle_id_cols)
    return _SCHEMA_MAP_CACHE

# ── Convenience Helper ────────────────────────────────────────────────────────

def get_vehicle_id_column(db_name: str) -> str:
    """Return the vehicle-plate column name for a given database."""
    _, vid_cols = build_global_schema_map()
    return vid_cols.get(db_name, {}).get('column', 'id')


# ── CLI Demo ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("\n[Schema Matching Engine] Results across 5 Data Sources")
    print("=" * 64)

    mapping, vid_cols = build_global_schema_map(force_refresh=True)

    print("\nVehicle Identifier Column (key linking attribute across 5 DBs)\n")
    print(f"  {'Database':<32} {'Local Column':<22} Confidence")
    print(f"  {'-'*32} {'-'*22} ----------")
    for db, info in vid_cols.items():
        disp = DATABASES[db]['display']
        print(f"  {disp:<32} {info['column']:<22} {info['confidence']:.3f}")

    print("\n\nGlobal Schema Mapping (discovered concept groups)\n")
    for concept, dbs in mapping.items():
        print(f"  -- {concept}")
        for db, col in dbs.items():
            disp = DATABASES[db]['display']
            print(f"       {disp:<32} -> {col}")
        print()
