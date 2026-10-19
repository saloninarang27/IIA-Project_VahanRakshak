"""
Data-quality store: staged noisy records, the append-only correction audit
trail and cached algorithm-evaluation runs (schemas/data_quality_schema.sql).
"""
import json
import os
import sqlite3
from datetime import datetime

from matching.noisy_records import generate_noisy_records

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schemas", "data_quality_schema.sql")

REVIEW_ACTIONS = {
    "ACCEPT_ORIGINAL": ("ACCEPT", "REVIEWED_ACCEPTED"),
    "CORRECT": ("CORRECT", "REVIEWED_CORRECTED"),
    "REJECT": ("REJECT", "REVIEWED_REJECTED"),
}

_CANDIDATE_FIELDS = ("rank", "vehicle_id", "plate", "make", "model", "color", "vehicle_type",
                     "plate_score", "scores", "combined_score", "context", "exact")


def _now():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_store(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        ddl = f.read()
    with connect(db_path) as conn:
        conn.executescript(ddl)


def reference_index_from_rows(rows):
    """Map VAHAN registry rows (API payload or DB rows) to the matcher's reference index."""
    return [{
        "vehicle_id": r["registration_id"],
        "plate": r["vehicle_registration_id"],
        "make": r["vehicle_make"],
        "model": r["vehicle_model"],
        "color": r["color"],
        "vehicle_type": r["vehicle_type"],
        "fuel_type": r["fuel_type"],
        "registration_status": r["registration_status"],
    } for r in rows]


def load_reference_index_from_db(vahan_db_path):
    """Read the registry straight from a VAHAN database file (setup / offline fallback)."""
    with connect(vahan_db_path) as conn:
        rows = conn.execute(
            """SELECT registration_id, vehicle_registration_id, vehicle_make, vehicle_model, color,
                      vehicle_type, fuel_type, registration_status
               FROM vehicle_registration ORDER BY vehicle_registration_id"""
        ).fetchall()
    return reference_index_from_rows(rows)


def seed_noisy_records(db_path, index):
    """Load the deterministic noisy-record fixtures once (no-op if already staged)."""
    with connect(db_path) as conn:
        if conn.execute("SELECT COUNT(*) FROM dq_noisy_records").fetchone()[0]:
            return 0
        records = generate_noisy_records(index)
        now = _now()
        conn.executemany(
            """
            INSERT INTO dq_noisy_records
                (source_system, source_reference, raw_plate, make, model, color, vehicle_type,
                 observed_at, scenario, ground_truth_plate, expected_decision, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(r["source_system"], r["source_reference"], r["raw_plate"], r["make"], r["model"], r["color"],
              r["vehicle_type"], r["observed_at"], r["scenario"], r["ground_truth_plate"],
              r["expected_decision"], now) for r in records],
        )
        conn.commit()
        return len(records)


def get_noisy_record(db_path, record_id):
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM dq_noisy_records WHERE record_id = ?", (record_id,)).fetchone()
    return dict(row) if row else None


def list_noisy_records(db_path, decision_status=None, source_system=None):
    """Staged records joined with their current decision (if any)."""
    conditions, params = [], []
    if decision_status:
        if decision_status == "UNPROCESSED":
            conditions.append("d.audit_id IS NULL")
        else:
            conditions.append("d.decision_status = ?")
            params.append(decision_status)
    if source_system:
        conditions.append("r.source_system = ?")
        params.append(source_system)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT r.*, d.audit_id, d.normalized_plate, d.corrected_plate, d.suggested_plate,
                   d.matched_vehicle_id, d.matched_plate, d.similarity_method, d.similarity_score,
                   d.context_score, d.combined_score, d.decision, d.decision_status, d.rule,
                   d.reason_code, d.reason, d.flags, d.decided_by, d.created_at AS decided_at
            FROM dq_noisy_records r
            LEFT JOIN v_dq_current_decision d ON d.record_id = r.record_id
            {where}
            ORDER BY r.record_id
            """,
            params,
        ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["flags"] = json.loads(item["flags"]) if item.get("flags") else []
        out.append(item)
    return out


def _slim_candidates(candidates, limit=10):
    return [{k: c.get(k) for k in _CANDIDATE_FIELDS if k in c} for c in (candidates or [])[:limit]]


def record_decision(db_path, assessment, source_system, record_id=None, decided_by="RULE_ENGINE",
                    supersedes_audit_id=None):
    """Append one decision to the audit trail and return its audit_id."""
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO dq_plate_corrections
                (record_id, source_system, original_plate, normalized_plate, corrected_plate, suggested_plate,
                 matched_vehicle_id, matched_plate, similarity_method, similarity_score, context_score,
                 combined_score, decision, decision_status, rule, reason_code, reason, flags,
                 candidates_json, decided_by, supersedes_audit_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id, source_system, assessment.get("original_plate"), assessment.get("normalized_plate"),
                assessment.get("corrected_plate"), assessment.get("suggested_plate"),
                assessment.get("matched_vehicle_id"), assessment.get("matched_plate"),
                assessment.get("method"), assessment.get("similarity_score"), assessment.get("context_score"),
                assessment.get("combined_score"), assessment["decision"], assessment["decision_status"],
                assessment.get("rule"), assessment.get("reason_code"), assessment.get("reason"),
                json.dumps(assessment.get("flags") or []),
                json.dumps(_slim_candidates(assessment.get("candidates"))),
                decided_by, supersedes_audit_id, _now(),
            ),
        )
        conn.commit()
        return cur.lastrowid


def current_decision(db_path, record_id):
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM v_dq_current_decision WHERE record_id = ?", (record_id,)).fetchone()
    return dict(row) if row else None


def record_review(db_path, record_id, action, reviewer, note=None, corrected_plate=None, matched_vehicle=None):
    """
    Append a human review decision that supersedes the record's current decision.
    action: ACCEPT_ORIGINAL | CORRECT | REJECT. CORRECT requires corrected_plate
    (validated by the caller against the registry, passed in as matched_vehicle).
    """
    if action not in REVIEW_ACTIONS:
        raise ValueError(f"action must be one of {list(REVIEW_ACTIONS)}")
    record = get_noisy_record(db_path, record_id)
    if not record:
        raise LookupError(f"record {record_id} not found")
    previous = current_decision(db_path, record_id)
    decision, status = REVIEW_ACTIONS[action]
    base = {k: previous.get(k) for k in ("normalized_plate", "similarity_method", "similarity_score",
                                          "context_score", "combined_score", "matched_vehicle_id",
                                          "matched_plate", "suggested_plate")} if previous else {}
    assessment = {
        **base,
        "original_plate": record["raw_plate"],
        "method": base.get("similarity_method"),
        "decision": decision,
        "decision_status": status,
        "rule": "MANUAL_REVIEW",
        "reason_code": f"REVIEW_{action}",
        "reason": note or f"Reviewer {reviewer} chose {action.replace('_', ' ').lower()}.",
        "corrected_plate": None,
        "flags": [],
        "candidates": json.loads(previous["candidates_json"]) if previous and previous.get("candidates_json") else [],
    }
    if action == "CORRECT":
        if not matched_vehicle:
            raise ValueError("A registered corrected_plate is required to correct a record")
        assessment.update({"corrected_plate": matched_vehicle["plate"],
                           "matched_plate": matched_vehicle["plate"],
                           "matched_vehicle_id": matched_vehicle["vehicle_id"]})
    elif action == "REJECT":
        assessment.update({"matched_plate": None, "matched_vehicle_id": None})
    return record_decision(db_path, assessment, record["source_system"], record_id=record_id,
                           decided_by=reviewer, supersedes_audit_id=previous["audit_id"] if previous else None)


def list_audit(db_path, record_id=None, limit=100, offset=0):
    params = []
    where = ""
    if record_id is not None:
        where = "WHERE record_id = ?"
        params.append(record_id)
    with connect(db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM dq_plate_corrections {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM dq_plate_corrections {where} ORDER BY audit_id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    entries = []
    for r in rows:
        item = dict(r)
        item["flags"] = json.loads(item["flags"]) if item.get("flags") else []
        item["candidates"] = json.loads(item.pop("candidates_json") or "[]")
        entries.append(item)
    return {"total": total, "entries": entries}


def decision_summary(db_path):
    with connect(db_path) as conn:
        staged = conn.execute("SELECT COUNT(*) FROM dq_noisy_records").fetchone()[0]
        rows = conn.execute(
            "SELECT decision_status, COUNT(*) AS n FROM v_dq_current_decision GROUP BY decision_status"
        ).fetchall()
        audit_rows = conn.execute("SELECT COUNT(*) FROM dq_plate_corrections").fetchone()[0]
    by_status = {r["decision_status"]: r["n"] for r in rows}
    return {"staged_records": staged, "processed": sum(by_status.values()),
            "by_status": by_status, "audit_entries": audit_rows}


def save_evaluation(db_path, report):
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO dq_evaluation_runs (created_at, selected_method, report_json) VALUES (?, ?, ?)",
            (_now(), report.get("selected_method"), json.dumps(report)),
        )
        conn.commit()
        return cur.lastrowid


def latest_evaluation(db_path):
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM dq_evaluation_runs ORDER BY run_id DESC LIMIT 1").fetchone()
    if not row:
        return None
    report = json.loads(row["report_json"])
    report.update({"run_id": row["run_id"], "created_at": row["created_at"]})
    return report
