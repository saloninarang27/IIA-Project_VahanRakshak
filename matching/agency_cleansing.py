"""
Cleansing of the live recorded data in the five agency databases.

The VAHAN registry is the reference for what a valid registration is. The other four
agencies (IIB, Police, ANPR, e-Challan) record the same vehicles under their own
identifier columns, and those values can be noisy: OCR misreads, typos, formatting,
or plates that are not registered at all.

    scan()    reads every agency table through its own microservice, finds each row
              whose identifier is not a clean registered plate, and runs it through
              the same rule engine as everything else (matching/cleansing.py), using
              the make / model / colour / type found in that row - or, when the row
              has none, in an ANPR camera sighting of the same reading.
    apply()   writes the decided corrections back to the agency database with an
              UPDATE executed by that agency's own service (works across machines),
              and logs every decision with the original value (append-only).
    review()  a reviewer resolves a flagged row: correct it to a registered plate,
              accept the original, or reject it.

Anomaly kinds:
    UNREGISTERED_PLATE   identifier is not a VAHAN plate (noise, or no registration)
    NON_CANONICAL_FORMAT identifier is a registered plate written differently
                         ("dl 01-ab 1001") -> standardised to the canonical form
    MISSING_IDENTIFIER   empty identifier
    SUSPECT_REGISTRATION (VAHAN only) a registry entry that breaks the plate format and
                         looks like a misread of another registered vehicle. The
                         registry is never changed automatically: always REVIEW.
"""
import json
import re
import urllib.request
from datetime import datetime

from matching.cleansing import assess_record
from matching.matcher import DEFAULT_METHOD
from matching.normalize import normalize_plate
from matching.sources import SOURCES, SOURCES_BY_KEY

# Strict modern format; registry entries breaking it are checked for being misreads
STRICT_PLATE = re.compile(r"^[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}$")

CANDIDATES_SHOWN = 5


def _now():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _q(value):
    """SQL string literal (values come from the agency databases themselves)."""
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Talking to the agency databases (through each microservice)
# ---------------------------------------------------------------------------
def http_sql_runner(source_key, query):
    """Execute SQL on an agency database via its service's /internal/execute-sql endpoint."""
    source = SOURCES_BY_KEY[source_key]
    req = urllib.request.Request(
        source["base_url"] + "/api/v1/internal/execute-sql",
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode("utf-8"))
        except Exception:
            raise RuntimeError(f"{source_key}: HTTP {e.code}") from e
    if data.get("status") != "success":
        raise RuntimeError(f"{source_key}: {data.get('error')}")
    return {"columns": data.get("columns", []), "rows": data.get("rows", [])}


def _select(sql_runner, source_key, query):
    res = sql_runner(source_key, query)
    return [dict(zip(res["columns"], row)) for row in res["rows"]]


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------
def _row_query(source):
    cols = [source["pk_column"], source["id_column"], *source["context_columns"].values()]
    return f"SELECT {', '.join(dict.fromkeys(cols))} FROM {source['table']}"


def _context(source, row):
    return {attr: row.get(col) for attr, col in source["context_columns"].items()}


def _slim(assessment):
    keep = ("decision", "decision_status", "rule", "reason_code", "reason", "flags", "normalized_plate",
            "corrected_plate", "suggested_plate", "matched_vehicle_id", "matched_plate", "similarity_score",
            "context_score", "combined_score", "candidate_count", "edits", "format_valid")
    out = {k: assessment.get(k) for k in keep}
    out["candidates"] = [{k: c.get(k) for k in ("rank", "vehicle_id", "plate", "make", "model", "color",
                                                 "vehicle_type", "plate_score", "combined_score", "context")}
                         for c in assessment.get("candidates", [])[:CANDIDATES_SHOWN]]
    return out


def scan(vahan_index, sql_runner=http_sql_runner, method=DEFAULT_METHOD, sources=None):
    """
    Find every anomalous identifier in the agency databases and decide what to do.

    vahan_index: reference index restricted to VAHAN (registered vehicles).
    Returns {"anomalies": [...], "sources": [...per-source counts / errors...]}.
    Each anomaly has: source, table, row_id, column, original_value, kind, context,
    context_from, assessment, action (UPDATE / REVIEW / REJECT) and new_value.
    """
    registered = {v["plate"]: v for v in vahan_index}
    anomalies, summary = [], []
    rows_by_source = {}

    for source in SOURCES:
        key = source["key"]
        if sources and key not in sources:
            continue
        try:
            rows_by_source[key] = _select(sql_runner, key, _row_query(source))
            summary.append({"key": key, "label": source["label"], "table": source["table"],
                            "column": source["id_column"], "rows": len(rows_by_source[key]), "error": None})
        except Exception as e:
            rows_by_source[key] = None
            summary.append({"key": key, "label": source["label"], "table": source["table"],
                            "column": source["id_column"], "rows": None, "error": str(e)})

    # Camera evidence keyed by the reading: a noisy plate in IIB / Police / e-Challan often
    # has the same misreading in an ANPR sighting, which carries make / model / colour.
    anpr_context = {}
    anpr = SOURCES_BY_KEY["ANPR"]
    for row in rows_by_source.get("ANPR") or []:
        ctx = _context(anpr, row)
        if any(ctx.values()):
            anpr_context.setdefault(normalize_plate(row[anpr["id_column"]]), ctx)

    for source in SOURCES:
        key = source["key"]
        rows = rows_by_source.get(key)
        if not rows:
            continue
        for row in rows:
            raw = row[source["id_column"]]
            norm = normalize_plate(raw)
            row_id = row[source["pk_column"]]

            if key == "VAHAN":
                # The registry is the reference: only entries that break the plate format are suspects
                if not norm or STRICT_PLATE.match(norm) and raw == norm:
                    continue
                if norm in registered and raw != norm and STRICT_PLATE.match(norm):
                    kind = "NON_CANONICAL_FORMAT"
                else:
                    kind = "SUSPECT_REGISTRATION"
            elif raw is not None and raw == norm and norm in registered:
                continue                          # clean, registered plate
            elif not norm:
                kind = "MISSING_IDENTIFIER"
            elif norm in registered:
                kind = "NON_CANONICAL_FORMAT"
            else:
                kind = "UNREGISTERED_PLATE"

            context = _context(source, row)
            context_from = f"{key} row" if any(context.values()) else None
            if not context_from and norm in anpr_context and key != "ANPR":
                context, context_from = anpr_context[norm], "ANPR sighting of the same reading"

            if kind == "NON_CANONICAL_FORMAT":
                assessment = assess_record({"plate": raw, **context}, vahan_index, method)
                action, new_value = "UPDATE", norm
            elif kind == "SUSPECT_REGISTRATION":
                others = [v for v in vahan_index if v["plate"] != norm]
                assessment = assess_record({"plate": raw, **context}, others, method)
                if assessment["decision"] in ("CORRECT", "REVIEW") and assessment.get("matched_plate"):
                    assessment["reason"] = (f"Registry entry '{raw}' breaks the plate format and looks like a misread of "
                                            f"registered {assessment['matched_plate']}. " + assessment["reason"])
                    action, new_value = "REVIEW", None
                else:
                    continue                      # unusual, but not a misread of another vehicle
                assessment["flags"] = list(assessment.get("flags") or []) + ["SUSPECT_REGISTRATION"]
            else:
                assessment = assess_record({"plate": raw, **context}, vahan_index, method)
                if assessment["decision"] == "CORRECT":
                    action, new_value = "UPDATE", assessment["corrected_plate"]
                elif assessment["decision"] == "REJECT":
                    action, new_value = "REJECT", None
                else:
                    action, new_value = "REVIEW", None

            anomalies.append({
                "source": key, "table": source["table"], "row_id": row_id, "column": source["id_column"],
                "original_value": raw, "kind": kind, "context": context, "context_from": context_from,
                "action": action, "new_value": new_value, "assessment": _slim(assessment),
            })

    return {"anomalies": anomalies, "sources": summary}


# ---------------------------------------------------------------------------
# Apply / review (write back to the agency database + audit)
# ---------------------------------------------------------------------------
def write_back(sql_runner, source_key, row_id, original_value, new_value):
    """UPDATE one identifier, only if it still holds the value we assessed. Returns rows changed."""
    source = SOURCES_BY_KEY[source_key]
    current = (f"{source['id_column']} IS NULL" if original_value is None
               else f"{source['id_column']} = {_q(original_value)}")
    res = sql_runner(source_key,
                     f"UPDATE {source['table']} SET {source['id_column']} = {_q(new_value)} "
                     f"WHERE {source['pk_column']} = {int(row_id)} AND {current}")
    try:
        return int(res["rows"][0][0])
    except (IndexError, KeyError, TypeError, ValueError):
        return 0


def _status_for(anomaly):
    if anomaly["action"] == "UPDATE":
        return "STANDARDIZED" if anomaly["kind"] == "NON_CANONICAL_FORMAT" else "CORRECTED"
    return "PENDING_REVIEW" if anomaly["action"] == "REVIEW" else "FLAGGED_REJECTED"


def apply(anomalies, store_conn_factory, sql_runner=http_sql_runner, decided_by="RULE_ENGINE"):
    """
    Execute the scan's decisions: UPDATE rows decided as CORRECT / standardise, and log
    REVIEW / REJECT rows (once per row and original value). Human-reviewed rows are skipped.
    Returns {"outcome": {status: n}, "changed_plates": [...], "skipped_reviewed": n, "errors": [...]}.
    """
    outcome, changed, errors, skipped = {}, [], [], 0
    for a in anomalies:
        latest = latest_decision(store_conn_factory, a["source"], a["row_id"], a["original_value"])
        if latest and latest["decided_by"] != "RULE_ENGINE":
            skipped += 1                          # a reviewer already decided this row
            continue
        status = _status_for(a)
        if latest and latest["decision_status"] == status and a["action"] != "UPDATE":
            continue                              # already flagged, nothing new to log
        applied = 0
        if a["action"] == "UPDATE":
            try:
                applied = write_back(sql_runner, a["source"], a["row_id"], a["original_value"], a["new_value"])
            except Exception as e:
                errors.append(f"{a['source']} row {a['row_id']}: {e}")
                continue
            if not applied:
                errors.append(f"{a['source']} row {a['row_id']}: value changed since the scan, not updated")
                continue
            changed.append(a["new_value"])
        log_change(store_conn_factory, a, status, applied, decided_by,
                   supersedes=latest["change_id"] if latest else None)
        outcome[status] = outcome.get(status, 0) + 1
    return {"outcome": outcome, "changed_plates": changed, "skipped_reviewed": skipped, "errors": errors}


REVIEW_ACTIONS = {"CORRECT": "REVIEWED_CORRECTED", "ACCEPT_ORIGINAL": "REVIEWED_ACCEPTED", "REJECT": "REVIEWED_REJECTED"}


def review(store_conn_factory, source_key, row_id, original_value, action, reviewer, note=None,
           corrected_plate=None, matched_vehicle=None, sql_runner=http_sql_runner):
    """Reviewer decision for one agency row. CORRECT writes the registered plate back to the agency table."""
    if action not in REVIEW_ACTIONS:
        raise ValueError(f"action must be one of {list(REVIEW_ACTIONS)}")
    if source_key not in SOURCES_BY_KEY:
        raise ValueError(f"unknown source '{source_key}'")
    source = SOURCES_BY_KEY[source_key]
    applied, new_value = 0, None
    if action == "CORRECT":
        if not matched_vehicle:
            raise ValueError("A registered corrected_plate is required to correct a record")
        new_value = matched_vehicle["plate"]
        applied = write_back(sql_runner, source_key, row_id, original_value, new_value)
        if not applied:
            raise LookupError(f"{source_key} row {row_id} no longer holds '{original_value}'")
    latest = latest_decision(store_conn_factory, source_key, row_id, original_value)
    entry = {
        "source": source_key, "table": source["table"], "row_id": row_id, "column": source["id_column"],
        "original_value": original_value, "new_value": new_value, "context_from": None,
        "assessment": {
            "decision": {"CORRECT": "CORRECT", "ACCEPT_ORIGINAL": "ACCEPT", "REJECT": "REJECT"}[action],
            "rule": "MANUAL_REVIEW", "reason_code": f"REVIEW_{action}",
            "reason": note or f"Reviewer {reviewer} chose {action.replace('_', ' ').lower()}.",
            "matched_vehicle_id": (matched_vehicle or {}).get("vehicle_id"),
            "matched_plate": (matched_vehicle or {}).get("plate"),
            "suggested_plate": (latest or {}).get("suggested_plate"),
            "similarity_score": (latest or {}).get("similarity_score"),
            "context_score": (latest or {}).get("context_score"),
            "flags": [],
        },
    }
    change_id = log_change(store_conn_factory, entry, REVIEW_ACTIONS[action], applied, reviewer,
                           supersedes=latest["change_id"] if latest else None)
    return {"change_id": change_id, "applied": bool(applied), "new_value": new_value}


# ---------------------------------------------------------------------------
# Audit log (dq_agency_corrections)
# ---------------------------------------------------------------------------
def log_change(store_conn_factory, anomaly, status, applied, decided_by, supersedes=None):
    a = anomaly["assessment"]
    with store_conn_factory() as conn:
        cur = conn.execute(
            """
            INSERT INTO dq_agency_corrections
                (source_system, table_name, row_id, column_name, original_value, new_value, applied,
                 matched_vehicle_id, matched_plate, suggested_plate, similarity_score, context_score, context_from,
                 decision, decision_status, rule, reason_code, reason, flags, decided_by, supersedes_change_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (anomaly["source"], anomaly["table"], int(anomaly["row_id"]), anomaly["column"],
             anomaly["original_value"], anomaly.get("new_value") if applied else None, int(bool(applied)),
             a.get("matched_vehicle_id"), a.get("matched_plate"), a.get("suggested_plate") or a.get("corrected_plate"),
             a.get("similarity_score"), a.get("context_score"), anomaly.get("context_from"),
             a["decision"], status, a.get("rule"), a.get("reason_code"), a.get("reason"),
             json.dumps(a.get("flags") or []), decided_by, supersedes, _now()),
        )
        conn.commit()
        return cur.lastrowid


def latest_decision(store_conn_factory, source_key, row_id, original_value):
    with store_conn_factory() as conn:
        row = conn.execute(
            "SELECT * FROM v_dq_agency_latest WHERE source_system = ? AND row_id = ? AND original_value IS ?",
            (source_key, int(row_id), original_value),
        ).fetchone()
    return dict(row) if row else None


def list_changes(store_conn_factory, limit=100, offset=0):
    with store_conn_factory() as conn:
        total = conn.execute("SELECT COUNT(*) FROM dq_agency_corrections").fetchone()[0]
        rows = conn.execute("SELECT * FROM dq_agency_corrections ORDER BY change_id DESC LIMIT ? OFFSET ?",
                            (limit, offset)).fetchall()
    entries = []
    for r in rows:
        item = dict(r)
        item["flags"] = json.loads(item["flags"]) if item.get("flags") else []
        entries.append(item)
    return {"total": total, "entries": entries}
