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
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vehicle_capture.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT_ANPR", 5005))
    print(f"[*] Starting Highway ANPR Camera Microservice on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
