"""
Context discovery INSIDE one agency database (runs on the agency's own machine).

POST /api/v1/context  {"seeds": {"plate": [...], "owner_id": [...], "fir_no": [...], "text": [...]},
                       "terms": [...], "max_hops": 2, "limit": 30}

1. Seed rows: rows whose key column holds one of the seed values (or, for "text" seeds, rows
   whose text mentions the query words).
2. Walk the database's own FK -> PK graph, read with PRAGMA foreign_key_list (no hard-coded
   joins), up to max_hops: from a seed row both up (child -> parent) and down (parent -> its
   children); once a path has gone UP to a parent it only continues up. Otherwise a shared parent
   (an RTO office, an insurer, a police station) would lead down to every other vehicle under it,
   which is unrelated to the query and would leak other vehicles' data.
3. Score every reached row:  relevance = HOP_DECAY[hop] * (1 + TERM_WEIGHT * query terms in the row)
   so rows close to the seed and about what the user asked rank first.
4. Return the top facts, plus the cross-database keys found in them (an owner id, an FIR number,
   another plate ...) so the Mediator can continue in the databases that hold those keys.
5. SCORE term weights (Roy et al.): for every short text value t in column A of a returned fact,
       TW(t) = POP * DIFF,  POP = NQ,  DIFF = log10((1 + NR) / (1 + NR - NQ))
   NQ = rows reached by this query (the FK-augmented result) with A = t, NR = rows of the whole table
   with A = t. A value frequent in the result but rare in the database (this car's plate, its FIR)
   gets a high weight; a value common everywhere (a big city, a popular make) gets almost none.
   A value of a parent (dimension) table is counted through the FK join, as in SCORE's augmented
   query AQ = Q JOIN_FK R: "Tata" in vehicle_model is one row, but hundreds of registrations join
   to it, so it is common and weighs little. Only the agency can count NR in its own database, so
   this is computed here (push-down).

Need-to-know: a table the caller's role may not see is still walked through (so its keys can
lead on), but its facts come back with only the key columns ("redacted": true). Personal fields
are masked by security.protect_service as for every response.

The per-agency description below (CONTEXT_SPECS) says which columns accept which seed key
types and which columns export which cross-database key types: it is each agency's published
"context interface", the counterpart of the identifier map in matching/sources.py.
"""
import math

from flask import g, jsonify, request

HOP_DECAY = {0: 1.0, 1: 0.6, 2: 0.35, 3: 0.2}
TERM_WEIGHT = 0.5
MAX_SEED_VALUES = 20          # per key type: a context request cannot be turned into a bulk export
MAX_ROWS_PER_STEP = 25        # children followed per parent row
MAX_TEXT_SEEDS = 40
_ALL = None                   # visible to every role

CONTEXT_SPECS = {
    "VAHAN": {
        "seeds": {"plate": [("vehicle_registration", "vehicle_registration_id")],
                  "owner_id": [("owner", "owner_id")],
                  "chassis_no": [("vehicle_registration", "chassis_no")]},
        "exports": {("vehicle_registration", "vehicle_registration_id"): "plate",
                    ("owner", "owner_id"): "owner_id"},
        "visible": {},
        "labels": {"vehicle_registration": "Registration (RC)", "owner": "Owner", "vehicle_model": "Vehicle model",
                   "rto_office": "RTO office", "ownership_transfer": "Ownership transfer", "hypothecation": "Loan / hypothecation"},
    },
    "IIB": {
        "seeds": {"plate": [("insurance_policy", "registration_no")],
                  "owner_id": [("policyholder", "owner_ref")],
                  "fir_no": [("claim", "fir_reference")],
                  "policy_number": [("insurance_policy", "policy_number")]},
        "exports": {("insurance_policy", "registration_no"): "plate", ("policyholder", "owner_ref"): "owner_id",
                    ("claim", "fir_reference"): "fir_no", ("insurance_policy", "policy_number"): "policy_number"},
        "visible": {t: {"INSURER", "ADMIN"} for t in ("insurance_policy", "policyholder", "claim", "premium_payment")},
        "labels": {"insurance_policy": "Insurance policy", "insurer": "Insurer", "policyholder": "Policyholder",
                   "claim": "Insurance claim", "premium_payment": "Premium payment"},
    },
    "POLICE": {
        "seeds": {"plate": [("theft_scrap_record", "vehicle_no"), ("fir", "vehicle_no")],
                  "fir_no": [("fir", "fir_no")],
                  "owner_id": [("fir", "complainant_owner_ref")]},
        "exports": {("theft_scrap_record", "vehicle_no"): "plate", ("fir", "vehicle_no"): "plate",
                    ("fir", "fir_no"): "fir_no", ("fir", "complainant_owner_ref"): "owner_id"},
        "visible": {t: {"POLICE", "ADMIN"} for t in ("fir", "recovery", "theft_scrap_record")},
        "labels": {"theft_scrap_record": "Theft / scrap record", "fir": "FIR", "police_station": "Police station",
                   "recovery": "Recovery", "rvsf_facility": "Scrapping facility"},
    },
    "ANPR": {
        "seeds": {"plate": [("vehicle_capture", "plate_number")]},
        "exports": {("vehicle_capture", "plate_number"): "plate"},
        "visible": {t: {"POLICE", "ADMIN"} for t in ("vehicle_capture", "anpr_alert", "toll_transaction")},
        "labels": {"vehicle_capture": "Camera sighting", "camera": "Camera", "toll_plaza": "Toll plaza",
                   "anpr_alert": "ANPR alert", "toll_transaction": "FASTag transaction"},
    },
    "ECHALLAN": {
        "seeds": {"plate": [("ministry_report", "vehicle_identifier")]},
        "exports": {("ministry_report", "vehicle_identifier"): "plate"},
        "visible": {t: {"POLICE", "ADMIN"} for t in ("ministry_report", "challan_payment", "court_case")},
        "labels": {"ministry_report": "e-Challan / report", "offence_code": "Offence", "enforcement_officer": "Officer",
                   "challan_payment": "Challan payment", "court_case": "Court case"},
    },
}


def _norm_key(key_type, value):
    value = str(value or "").strip()
    return "".join(ch for ch in value.upper() if ch.isalnum()) if key_type == "plate" else value.upper()


def fk_graph(conn):
    """[(child_table, child_col, parent_table, parent_col)] from PRAGMA foreign_key_list."""
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                                         "AND name NOT IN ('access_audit')")]
    edges = []
    for t in tables:
        for fk in conn.execute(f"PRAGMA foreign_key_list({t})"):
            edges.append((t, fk[3], fk[2], fk[4]))
    return tables, edges


def _rows(conn, table, column, values, limit):
    if not values:
        return []
    marks = ",".join("?" * len(values))
    cur = conn.execute(f'SELECT rowid AS _rid, * FROM "{table}" WHERE "{column}" IN ({marks}) LIMIT {int(limit)}', list(values))
    return [dict(r) for r in cur]


def _row_text(row):
    return " ".join(str(v) for k, v in row.items() if k != "_rid" and v is not None).lower()


def _term_hits(row, terms):
    text = _row_text(row)
    return [t for t in terms if t in text]


def score_tw(nq, nr):
    """SCORE term weight: POP * DIFF = NQ * log10((1 + NR) / (1 + NR - NQ)). Lecture example: NQ=3, NR=4 -> 1.194."""
    return round(nq * math.log10((1 + nr) / (1 + nr - nq)), 3)


def _score_term_weights(conn, nodes, facts, edges):
    """TW = POP * DIFF for the short text values of the returned (unredacted) facts. See step 5."""
    wanted = {}
    for f in facts:
        if f["redacted"]:
            continue
        for col, v in f["row"].items():
            if isinstance(v, str) and 2 <= len(v) <= 40 and "*" not in v:
                wanted.setdefault((f["table"], col), set()).add(v)
    reached = {}
    for n in nodes.values():
        reached.setdefault(n["table"], []).append(n["row"])
    tw = {}
    for (table, col), values in wanted.items():
        marks = ",".join("?" * len(values))
        # count in the augmented relation: through an FK from a reached child table, else in the table itself
        edge = next(((c, cc, pc) for c, cc, p, pc in edges if p == table and c in reached and c != table), None)
        if edge:
            child, ccol, pcol = edge
            keys = {}
            for v, k in conn.execute(f'SELECT "{col}", "{pcol}" FROM "{table}" WHERE "{col}" IN ({marks})', list(values)):
                keys.setdefault(v, set()).add(k)
            nr = {v: conn.execute(f'SELECT COUNT(*) FROM "{child}" WHERE "{ccol}" IN ({",".join("?" * len(ks))})',
                                  list(ks)).fetchone()[0] for v, ks in keys.items()}
            nq = {v: sum(1 for r in reached[child] if r.get(ccol) in ks) for v, ks in keys.items()}
        else:
            nr = dict(conn.execute(f'SELECT "{col}", COUNT(*) FROM "{table}" WHERE "{col}" IN ({marks}) GROUP BY "{col}"',
                                   list(values)).fetchall())
            nq = {}
            for r in reached.get(table, []):
                if r.get(col) in values:
                    nq[r[col]] = nq.get(r[col], 0) + 1
        for v, r in nr.items():
            q = min(max(nq.get(v, 0), 1), r) if r else 0
            if q:
                tw[(table, col, v)] = score_tw(q, r)
    for f in facts:
        f["term_weights"] = {c: tw[(f["table"], c, v)] for c, v in f["row"].items() if (f["table"], c, v) in tw}


def discover(conn, agency, seeds, terms, role, max_hops=2, limit=30):
    spec = CONTEXT_SPECS[agency]
    tables, edges = fk_graph(conn)
    terms = [t.lower() for t in terms if t and len(t) >= 3][:30]
    max_hops = max(0, min(int(max_hops), 3))
    limit = max(1, min(int(limit), 60))

    nodes = {}   # (table, rowid) -> {"table", "row", "hop", "via"}

    def visit(table, row, hop, via, up_only=False):
        key = (table, row["_rid"])
        if key not in nodes or nodes[key]["hop"] > hop:
            nodes[key] = {"table": table, "row": row, "hop": hop, "via": via, "up_only": up_only}
            return True
        return False

    # 1. seed rows
    seed_count = 0
    for key_type, values in (seeds or {}).items():
        if key_type == "text":
            continue
        values = sorted({_norm_key(key_type, v) for v in values if v})[:MAX_SEED_VALUES]
        for table, column in spec["seeds"].get(key_type, []):
            for row in _rows(conn, table, column, values, MAX_ROWS_PER_STEP * 2):
                seed_count += visit(table, row, 0, f"seed: {table}.{column} = {row.get(column)}")
    text_terms = [t.lower() for t in (seeds or {}).get("text", []) if t and len(t) >= 4][:10]
    if text_terms and not seed_count:
        candidates = []
        for table in tables:
            cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{table}")') if (c[2] or "").upper() == "TEXT"]
            if not cols:
                continue
            where = " OR ".join(f'LOWER("{c}") LIKE ?' for c in cols for _ in text_terms)
            params = [f"%{t}%" for c in cols for t in text_terms]
            for row in conn.execute(f'SELECT rowid AS _rid, * FROM "{table}" WHERE {where} LIMIT 200', params):
                row = dict(row)
                candidates.append((len(_term_hits(row, text_terms)), table, row))
        candidates.sort(key=lambda c: -c[0])
        for hits, table, row in candidates[:MAX_TEXT_SEEDS]:
            seed_count += visit(table, row, 0, f"seed: text match ({hits} query words) in {table}")

    # 2. breadth-first walk over the FK -> PK graph, both directions
    frontier = [k for k, n in nodes.items() if n["hop"] == 0]
    for hop in range(1, max_hops + 1):
        nxt = []
        for key in frontier:
            node = nodes[key]
            table, row = node["table"], node["row"]
            for child, ccol, parent, pcol in edges:
                if child == table and row.get(ccol) is not None:            # follow FK up to the parent
                    for prow in _rows(conn, parent, pcol, [row[ccol]], 1):
                        if visit(parent, prow, hop, f"{child}.{ccol} -> {parent}.{pcol}", up_only=True):
                            nxt.append((parent, prow["_rid"]))
                if parent == table and not node["up_only"] and row.get(pcol) is not None:  # down to the children
                    for crow in _rows(conn, child, ccol, [row[pcol]], MAX_ROWS_PER_STEP):
                        if visit(child, crow, hop, f"{parent}.{pcol} <- {child}.{ccol}"):
                            nxt.append((child, crow["_rid"]))
        frontier = nxt

    # 3. score, redact, export keys
    facts, keys = [], {}
    for node in nodes.values():
        table, row, hop = node["table"], node["row"], node["hop"]
        hits = _term_hits(row, terms)
        score = round(HOP_DECAY.get(hop, 0.1) * (1 + TERM_WEIGHT * len(hits)), 3)
        exported = {}
        for (t, col), key_type in spec["exports"].items():
            if t == table and row.get(col):
                exported[col] = row[col]
                keys.setdefault(key_type, {})
                keys[key_type][_norm_key(key_type, row[col])] = max(score, keys[key_type].get(_norm_key(key_type, row[col]), 0))
        allowed = spec["visible"].get(table, _ALL)
        redacted = allowed is not None and role not in allowed
        data = {k: v for k, v in row.items() if k != "_rid"}
        if redacted:
            data = exported
        facts.append({"agency": agency, "table": table, "label": spec["labels"].get(table, table), "hop": hop,
                      "via": node["via"], "score": score, "matched_terms": hits, "redacted": redacted, "row": data})
    facts.sort(key=lambda f: (-f["score"], f["hop"], f["table"]))
    facts = facts[:limit]
    _score_term_weights(conn, nodes, facts, edges)
    return {
        "agency": agency,
        "accepts": sorted(spec["seeds"]),
        "facts": facts,
        "keys": {k: [{"value": v, "score": s} for v, s in sorted(vals.items(), key=lambda x: -x[1])] for k, vals in keys.items()},
        "stats": {"seed_rows": sum(1 for n in nodes.values() if n["hop"] == 0), "rows_reached": len(nodes),
                  "tables_reached": sorted({n["table"] for n in nodes.values()}), "fk_edges": len(edges),
                  "facts_returned": min(limit, len(facts))},
    }


def register_context_endpoint(app, agency, get_db):
    """Add POST /api/v1/context to an agency service."""

    @app.route("/api/v1/context", methods=["POST"])
    def context():
        body = request.get_json(force=True, silent=True) or {}
        seeds = body.get("seeds") or {}
        if not isinstance(seeds, dict) or not any(seeds.values()):
            return jsonify({"status": "error", "error": "seeds are required"}), 400
        with get_db() as conn:
            return jsonify(discover(conn, agency, seeds, body.get("terms") or [], g.get("fed_role"),
                                    body.get("max_hops", 2), body.get("limit", 30)))
