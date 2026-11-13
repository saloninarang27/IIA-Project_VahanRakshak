"""
MoRTH e-Challan & Ministry of Transport Reporting Microservice.
Operates on its own local database (ministry_echallan.db).
Local vehicle identifier column: vehicle_identifier.
Runs independently on Port 5006.
"""
import os
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, make_response
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend import security
from matching.sources import register_match_endpoint
import urllib.request
import json

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ministry_echallan.db")

# Only the Mediator may call this service (signed requests); bulk and write endpoints need a role.
# No CORS: browsers never talk to an agency directly.
ACCESS_POLICY = {
    ("GET", "/api/v1/identifiers"): {"ADMIN"},
    ("GET", "/api/v1/challans$"): {"POLICE", "ADMIN"},
    ("POST", "/api/v1/challans"): {"POLICE", "ADMIN"},
    ("PUT", "/api/v1/challans"): {"POLICE", "ADMIN"},
    ("POST", "/api/v1/internal/execute-sql"): {"ADMIN"},
}
security.protect_service(app, DB_PATH, ACCESS_POLICY)
register_match_endpoint(app, "ECHALLAN")

def _mediator_base_url():
    """
    Where to send cache-invalidation webhooks.
    An explicit URL_MEDIATOR / HOST_MEDIATOR setting wins. Otherwise use the caller's
    address: challan writes arrive proxied from the Mediator, so the caller IS the
    Mediator - this also works when the Mediator runs on another machine.
    """
    port = os.environ.get("PORT_MEDIATOR", "5001")
    if os.environ.get("URL_MEDIATOR"):
        return os.environ["URL_MEDIATOR"].rstrip("/")
    host = os.environ.get("HOST_MEDIATOR") or request.remote_addr or "127.0.0.1"
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    return f"http://{host}:{port}"

def _notify_mediator(vehicle_identifier, reason):
    """Webhook ping so the Mediator invalidates its cached dossier for this vehicle."""
    try:
        req = security.signed_request(
            f"{_mediator_base_url()}/api/v1/sync/invalidate", "POST",
            {"vehicle_identifier": vehicle_identifier, "reason": reason}, role="ADMIN", caller="echallan"
        )
        urllib.request.urlopen(req, timeout=1.0)
    except Exception:
        pass  # Mediator might be starting or offline; its cache TTL still bounds staleness

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

@app.route("/api/v1/health", methods=["GET"])
def health():
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM ministry_report").fetchone()[0]
        submitted = conn.execute("SELECT COUNT(*) FROM ministry_report WHERE report_status = 'SUBMITTED'").fetchone()[0]
        resolved = conn.execute("SELECT COUNT(*) FROM ministry_report WHERE report_status IN ('CLOSED', 'RESOLVED')").fetchone()[0]
    return jsonify({
        "status": "UP",
        "service": "MoRTH e-Challan & Ministry Reporting System",
        "authority": "Ministry of Road Transport and Highways (MoRTH)",
        "local_identifier": "vehicle_identifier",
        "total_challans": count,
        "pending_review": submitted,
        "resolved_challans": resolved
    })

@app.route("/api/v1/challans/<vehicle_identifier>", methods=["GET"])
def get_challans_for_vehicle(vehicle_identifier):
    clean_id = vehicle_identifier.strip().upper().replace(" ", "").replace("-", "")
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT report_id, vehicle_identifier, report_type, report_reason,
                   detected_at, severity, report_status, submitted_at, ministry_reference
            FROM ministry_report
            WHERE vehicle_identifier = ?
            ORDER BY submitted_at DESC
            """,
            (clean_id,)
        ).fetchall()

    challans = [dict(r) for r in rows]
    from datetime import timezone
    last_mod = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    resp = make_response(jsonify({
        "agency": "MORTH_ECHALLAN",
        "query_key": "vehicle_identifier",
        "vehicle_identifier": clean_id,
        "count": len(challans),
        "challans": challans
    }))
    resp.headers["Last-Modified"] = last_mod
    return resp

@app.route("/api/v1/identifiers", methods=["GET"])
def get_identifiers():
    """Distinct vehicle identifiers held by this agency, used by the Mediator's approximate matcher."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT vehicle_identifier AS plate, COUNT(*) AS challans
            FROM ministry_report GROUP BY vehicle_identifier ORDER BY vehicle_identifier
            """
        ).fetchall()
    return jsonify({
        "agency": "MORTH_ECHALLAN",
        "query_key": "vehicle_identifier",
        "count": len(rows),
        "identifiers": [dict(r) for r in rows]
    })

@app.route("/api/v1/challans", methods=["POST"])
def issue_challan():
    data = request.get_json(force=True)
    clean_id = data.get("vehicle_identifier", "").strip().upper().replace(" ", "").replace("-", "")
    if not clean_id:
        return jsonify({"error": "Missing vehicle_identifier"}), 400

    report_type = data.get("report_type", "UNINSURED_VEHICLE")
    report_reason = data.get("report_reason", "Vehicle detected operating on public road without mandatory insurance (MV Act Sec 196)")
    severity = data.get("severity", "HIGH")
    detected_at = data.get("detected_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    submitted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM ministry_report").fetchone()[0] + 1
        year = datetime.now().year
        ref = f"ECHALLAN-{year}-{count:06d}"
        
        conn.execute(
            """
            INSERT INTO ministry_report
                (vehicle_identifier, report_type, report_reason, detected_at, severity, report_status, submitted_at, ministry_reference)
            VALUES (?, ?, ?, ?, ?, 'SUBMITTED', ?, ?)
            """,
            (clean_id, report_type, report_reason, detected_at, severity, submitted_at, ref)
        )
        conn.commit()
        last_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    _notify_mediator(clean_id, "NEW_ECHALLAN_ISSUED")

    return jsonify({
        "message": "e-Challan issued successfully",
        "report_id": last_id,
        "ministry_reference": ref,
        "vehicle_identifier": clean_id,
        "status": "SUBMITTED",
        "fine_amount": 2000,
        "legal_section": "Motor Vehicles Act Section 196"
    }), 201

@app.route("/api/v1/challans/<int:report_id>/status", methods=["PUT"])
def update_challan_status(report_id):
    data = request.get_json(force=True)
    new_status = data.get("status", "UNDER_REVIEW").upper()
    valid_statuses = ["SUBMITTED", "UNDER_REVIEW", "FINED", "RESOLVED", "CLOSED"]
    if new_status not in valid_statuses:
        return jsonify({"error": f"Invalid status. Must be one of {valid_statuses}"}), 400

    with get_db() as conn:
        row = conn.execute("SELECT vehicle_identifier FROM ministry_report WHERE report_id = ?", (report_id,)).fetchone()
        if not row:
            return jsonify({"error": "Challan record not found"}), 404
        vehicle_id = row[0]
        
        conn.execute("UPDATE ministry_report SET report_status = ? WHERE report_id = ?", (new_status, report_id))
        conn.commit()

    _notify_mediator(vehicle_id, "STATUS_CHANGED")

    return jsonify({"message": f"Challan {report_id} status updated to {new_status}", "report_id": report_id, "status": new_status})

@app.route("/api/v1/challans", methods=["GET"])
def list_challans():
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    offset = max(0, (page - 1) * limit)
    status = request.args.get("status")

    conditions = []
    params = []
    if status:
        conditions.append("report_status = ?")
        params.append(status.upper())

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with get_db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM ministry_report {where}", tuple(params)).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT report_id, vehicle_identifier, report_type, report_reason,
                   detected_at, severity, report_status, submitted_at, ministry_reference
            FROM ministry_report
            {where}
            ORDER BY submitted_at DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params) + (limit, offset)
        ).fetchall()

    return jsonify({
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if total > 0 else 1,
        "challans": [dict(r) for r in rows]
    })

import time

@app.route("/api/v1/internal/execute-sql", methods=["POST"])
def execute_sql():
    """Internal SQL query execution endpoint for distributed REPL demo."""
    data = request.get_json(force=True) or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Empty SQL query"}), 400

    start_t = time.time()
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(query)
            if cur.description:
                columns = [col[0] for col in cur.description]
                rows = cur.fetchall()
                results = [list(r) for r in rows]
                row_count = len(results)
            else:
                conn.commit()
                columns = ["affected_rows"]
                results = [[cur.rowcount]]
                row_count = cur.rowcount

        elapsed = round((time.time() - start_t) * 1000, 2)
        return jsonify({
            "status": "success",
            "service": "MoRTH e-Challan Portal",
            "database": "ministry_echallan.db",
            "execution_ms": elapsed,
            "columns": columns,
            "rows": results,
            "row_count": row_count
        })
    except Exception as e:
        elapsed = round((time.time() - start_t) * 1000, 2)
        return jsonify({
            "status": "error",
            "service": "MoRTH e-Challan Portal",
            "database": "ministry_echallan.db",
            "execution_ms": elapsed,
            "error": str(e)
        }), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT_ECHALLAN", 5006))
    print(f"[*] Starting MoRTH e-Challan Microservice on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
