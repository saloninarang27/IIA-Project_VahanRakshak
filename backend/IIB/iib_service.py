"""
IIB (Insurance Information Bureau of India - IRDAI) Microservice.
Operates on its own local database (insurance_iib.db).
Local vehicle identifier column: registration_no.
Runs independently on Port 5002.
"""
import os
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, make_response
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend import security
from matching.sources import register_match_endpoint
from backend.verdicts import register_verdict_endpoint

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "insurance_iib.db")

# Only the Mediator may call this service (signed requests); bulk and write endpoints need a role.
# No CORS: browsers never talk to an agency directly.
ACCESS_POLICY = {
    ("GET", "/api/v1/identifiers"): {"ADMIN"},
    ("GET", "/api/v1/policies"): {"INSURER", "ADMIN"},           # raw policy rows
    ("POST", "/api/v1/policies"): {"INSURER", "ADMIN"},
    ("POST", "/api/v1/internal/execute-sql"): {"ADMIN"},
}
security.protect_service(app, DB_PATH, ACCESS_POLICY)
register_match_endpoint(app, "IIB")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")  # FK -> PK enforced for every write, including the SQL console
    return conn

@app.route("/api/v1/health", methods=["GET"])
def health():
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM insurance_policy").fetchone()[0]
    return jsonify({
        "status": "UP",
        "service": "IIB (Insurance Information Bureau of India)",
        "agency": "IRDAI",
        "local_identifier": "registration_no",
        "records_count": count
    })

@app.route("/api/v1/policies/<registration_no>", methods=["GET"])
def get_policies_for_vehicle(registration_no):
    reg_clean = registration_no.strip().upper().replace(" ", "").replace("-", "")
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT policy_id, registration_no, insurer_name, policy_number,
                   policy_start_date, policy_expiry_date, insurance_status, policy_type
            FROM insurance_policy
            WHERE registration_no = ?
            ORDER BY policy_expiry_date DESC
            """,
            (reg_clean,)
        ).fetchall()
        
    policies = [dict(r) for r in rows]
    
    from datetime import timezone
    last_mod = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    resp = make_response(jsonify({
        "agency": "IIB_IRDAI",
        "query_key": "registration_no",
        "registration_no": reg_clean,
        "count": len(policies),
        "policies": policies
    }))
    resp.headers["Last-Modified"] = last_mod
    return resp

@app.route("/api/v1/identifiers", methods=["GET"])
def get_identifiers():
    """Distinct vehicle identifiers held by this agency, used by the Mediator's approximate matcher."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT registration_no AS plate, COUNT(*) AS policies, MAX(policy_expiry_date) AS latest_expiry
            FROM insurance_policy GROUP BY registration_no ORDER BY registration_no
            """
        ).fetchall()
    return jsonify({
        "agency": "IIB_IRDAI",
        "query_key": "registration_no",
        "count": len(rows),
        "identifiers": [dict(r) for r in rows]
    })

@app.route("/api/v1/policies", methods=["POST"])
def create_policy():
    data = request.get_json(force=True)
    required = ["registration_no", "insurer_name", "policy_number", "policy_start_date", "policy_expiry_date", "insurance_status"]
    for f in required:
        if f not in data:
            return jsonify({"error": f"Missing required field: {f}"}), 400
            
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO insurance_policy
                (registration_no, insurer_name, policy_number, policy_start_date, policy_expiry_date, insurance_status, policy_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["registration_no"].strip().upper().replace(" ", "").replace("-", ""),
                data["insurer_name"],
                data["policy_number"],
                data["policy_start_date"],
                data["policy_expiry_date"],
                data["insurance_status"].upper(),
                data.get("policy_type", "Comprehensive")
            )
        )
        conn.commit()
    return jsonify({"message": "Policy created successfully", "policy_number": data["policy_number"]}), 201

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
            "service": "IIB (Insurance Information Bureau)",
            "database": "insurance_iib.db",
            "execution_ms": elapsed,
            "columns": columns,
            "rows": results,
            "row_count": row_count
        })
    except Exception as e:
        elapsed = round((time.time() - start_t) * 1000, 2)
        return jsonify({
            "status": "error",
            "service": "IIB (Insurance Information Bureau)",
            "database": "insurance_iib.db",
            "execution_ms": elapsed,
            "error": str(e)
        }), 400

# The agency answers the Mediator's question itself (verdict push-down, backend/verdicts.py)
register_verdict_endpoint(app, "IIB", get_db)

if __name__ == "__main__":
    port = int(os.environ.get("PORT_IIB", 5002))
    print(f"[*] Starting IIB Microservice on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
