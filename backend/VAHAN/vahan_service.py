"""
MoRTH VAHAN (National Vehicle Registry via API Setu / NIC) Microservice.
Operates on its own local database (parivahan_vahan.db).
Local vehicle identifier column: vehicle_registration_id.
Runs independently on Port 5003.
"""
import os
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parivahan_vahan.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

@app.route("/api/v1/health", methods=["GET"])
def health():
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM vehicle_registration").fetchone()[0]
    return jsonify({
        "status": "UP",
        "service": "MoRTH VAHAN (National Vehicle Registry)",
        "platform": "API Setu / NIC",
        "local_identifier": "vehicle_registration_id",
        "records_count": count
    })

@app.route("/api/v1/rc/<vehicle_registration_id>", methods=["GET"])
def get_vehicle_rc(vehicle_registration_id):
    reg_clean = vehicle_registration_id.strip().upper().replace(" ", "").replace("-", "")
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT registration_id, vehicle_registration_id, owner_id, owner_name,
                   registration_date, registration_expiry_date, vehicle_make, vehicle_model,
                   vehicle_type, fuel_type, color, registration_status
            FROM vehicle_registration
            WHERE vehicle_registration_id = ?
            """,
            (reg_clean,)
        ).fetchone()

    if not row:
        return jsonify({
            "agency": "MoRTH_VAHAN",
            "query_key": "vehicle_registration_id",
            "vehicle_registration_id": reg_clean,
            "found": False,
            "rc_details": None
        }), 404

    rc = dict(row)
    from datetime import timezone
    last_mod = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    resp = make_response(jsonify({
        "agency": "MoRTH_VAHAN",
        "platform": "API Setu",
        "query_key": "vehicle_registration_id",
        "vehicle_registration_id": reg_clean,
        "found": True,
        "rc_details": rc
    }))
    resp.headers["Last-Modified"] = last_mod
    return resp

@app.route("/api/v1/registry/index", methods=["GET"])
def get_registry_index():
    """Lightweight projection of every registered vehicle, used by the Mediator's approximate matcher."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT registration_id, vehicle_registration_id, vehicle_make, vehicle_model,
                   color, vehicle_type, fuel_type, registration_status
            FROM vehicle_registration
            ORDER BY vehicle_registration_id
            """
        ).fetchall()
    return jsonify({
        "agency": "MoRTH_VAHAN",
        "query_key": "vehicle_registration_id",
        "count": len(rows),
        "vehicles": [dict(r) for r in rows]
    })

@app.route("/api/v1/rc", methods=["POST"])
def register_vehicle():
    data = request.get_json(force=True)
    required = ["vehicle_registration_id", "owner_id", "owner_name", "registration_date", "registration_expiry_date", "registration_status"]
    for f in required:
        if f not in data:
            return jsonify({"error": f"Missing required field: {f}"}), 400

    clean_id = data["vehicle_registration_id"].strip().upper().replace(" ", "").replace("-", "")
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO vehicle_registration
                (vehicle_registration_id, owner_id, owner_name, registration_date, registration_expiry_date,
                 vehicle_make, vehicle_model, vehicle_type, fuel_type, color, registration_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_id, data["owner_id"], data["owner_name"], data["registration_date"],
                data["registration_expiry_date"], data.get("vehicle_make"), data.get("vehicle_model"),
                data.get("vehicle_type"), data.get("fuel_type"), data.get("color"), data["registration_status"]
            )
        )
        conn.commit()
    return jsonify({"message": "Vehicle registered successfully", "vehicle_registration_id": clean_id}), 201

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
            "service": "MoRTH VAHAN Registry",
            "database": "parivahan_vahan.db",
            "execution_ms": elapsed,
            "columns": columns,
            "rows": results,
            "row_count": row_count
        })
    except Exception as e:
        elapsed = round((time.time() - start_t) * 1000, 2)
        return jsonify({
            "status": "error",
            "service": "MoRTH VAHAN Registry",
            "database": "parivahan_vahan.db",
            "execution_ms": elapsed,
            "error": str(e)
        }), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT_VAHAN", 5003))
    print(f"[*] Starting MoRTH VAHAN Microservice on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
