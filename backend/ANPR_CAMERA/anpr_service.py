"""
Highway Traffic ANPR Camera Network Microservice.
Operates on its own local database (vehicle_capture.db).
Local vehicle identifier column: plate_number.
Runs independently on Port 5005.
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
from backend.context_engine import register_context_endpoint

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vehicle_capture.db")

# Only the Mediator may call this service (signed requests); bulk and write endpoints need a role.
# No CORS: browsers never talk to an agency directly.
ACCESS_POLICY = {
    ("GET", "/api/v1/identifiers"): {"ADMIN"},
    ("GET", "/api/v1/captures"): {"POLICE", "ADMIN"},            # raw sightings of a vehicle
    ("GET", "/api/v1/captures$"): {"ADMIN"},
    ("POST", "/api/v1/internal/execute-sql"): {"ADMIN"},
}
security.protect_service(app, DB_PATH, ACCESS_POLICY)
register_match_endpoint(app, "ANPR")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")  # FK -> PK enforced for every write, including the SQL console
    return conn

@app.route("/api/v1/health", methods=["GET"])
def health():
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM vehicle_capture").fetchone()[0]
        cams = conn.execute("SELECT COUNT(DISTINCT camera_id) FROM vehicle_capture").fetchone()[0]
    return jsonify({
        "status": "UP",
        "service": "State Highway ANPR Camera Network",
        "authority": "Traffic Police / NHAI Toll Checkpoints",
        "local_identifier": "plate_number",
        "total_captures": count,
        "active_cameras": cams
    })

@app.route("/api/v1/captures/<plate_number>", methods=["GET"])
def get_captures_for_plate(plate_number):
    clean_plate = plate_number.strip().upper().replace(" ", "").replace("-", "")
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT capture_id, plate_number, captured_timestamp, camera_id, location,
                   vehicle_type, detected_make, detected_model, detected_color, confidence_score
            FROM vehicle_capture
            WHERE plate_number = ?
            ORDER BY captured_timestamp DESC
            """,
            (clean_plate,)
        ).fetchall()

    captures = [dict(r) for r in rows]
    from datetime import timezone
    last_mod = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    resp = make_response(jsonify({
        "agency": "HIGHWAY_ANPR",
        "query_key": "plate_number",
        "plate_number": clean_plate,
        "count": len(captures),
        "captures": captures
    }))
    resp.headers["Last-Modified"] = last_mod
    return resp

@app.route("/api/v1/identifiers", methods=["GET"])
def get_identifiers():
    """Distinct vehicle identifiers held by this agency, used by the Mediator's approximate matcher."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT plate_number AS plate, COUNT(*) AS sightings, MAX(captured_timestamp) AS last_seen,
                   detected_make, detected_model, detected_color, vehicle_type
            FROM vehicle_capture GROUP BY plate_number ORDER BY plate_number
            """
        ).fetchall()
    return jsonify({
        "agency": "TRAFFIC_ANPR",
        "query_key": "plate_number",
        "count": len(rows),
        "identifiers": [dict(r) for r in rows]
    })

@app.route("/api/v1/captures", methods=["GET"])
def list_captures():
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    offset = max(0, (page - 1) * limit)
    location = request.args.get("location")

    conditions = []
    params = []
    if location:
        conditions.append("location LIKE ?")
        params.append(f"%{location}%")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with get_db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM vehicle_capture {where}", tuple(params)).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT capture_id, plate_number, captured_timestamp, camera_id, location,
                   vehicle_type, detected_make, detected_model, detected_color, confidence_score
            FROM vehicle_capture
            {where}
            ORDER BY captured_timestamp DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params) + (limit, offset)
        ).fetchall()

    return jsonify({
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if total > 0 else 1,
        "captures": [dict(r) for r in rows]
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
            "service": "Highway Toll ANPR Camera Network",
            "database": "vehicle_capture.db",
            "execution_ms": elapsed,
            "columns": columns,
            "rows": results,
            "row_count": row_count
        })
    except Exception as e:
        elapsed = round((time.time() - start_t) * 1000, 2)
        return jsonify({
            "status": "error",
            "service": "Highway Toll ANPR Camera Network",
            "database": "vehicle_capture.db",
            "execution_ms": elapsed,
            "error": str(e)
        }), 400

# The agency answers the Mediator's question itself (verdict push-down, backend/verdicts.py)
register_verdict_endpoint(app, "ANPR", get_db)
# ... and discovers context in its own tables by following its FK -> PK graph (backend/context_engine.py)
register_context_endpoint(app, "ANPR", get_db)

if __name__ == "__main__":
    port = int(os.environ.get("PORT_ANPR", 5005))
    print(f"[*] Starting Highway ANPR Camera Microservice on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
