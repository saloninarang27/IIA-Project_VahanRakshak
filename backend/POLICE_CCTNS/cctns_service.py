"""
Police CCTNS (Crime and Criminal Tracking Network) & RVSF Scrapping Microservice.
Operates on its own local database (theft_scrap.db).
Local vehicle identifier column: vehicle_no.
Runs independently on Port 5004.
"""
import os
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "theft_scrap.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

@app.route("/api/v1/health", methods=["GET"])
def health():
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM theft_scrap_record").fetchone()[0]
        stolen = conn.execute("SELECT COUNT(*) FROM theft_scrap_record WHERE theft_status = 'STOLEN'").fetchone()[0]
        scrapped = conn.execute("SELECT COUNT(*) FROM theft_scrap_record WHERE scrapping_status = 'SCRAPPED'").fetchone()[0]
    return jsonify({
        "status": "UP",
        "service": "Police CCTNS & RVSF Scrapping Registry",
        "authority": "State Police / MoRTH RVSF",
        "local_identifier": "vehicle_no",
        "total_records": count,
        "stolen_vehicles": stolen,
        "scrapped_vehicles": scrapped
    })

@app.route("/api/v1/records/<vehicle_no>", methods=["GET"])
def get_theft_scrap_record(vehicle_no):
    clean_no = vehicle_no.strip().upper().replace(" ", "").replace("-", "")
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT record_id, vehicle_no, theft_status, theft_report_date, recovery_date,
                   scrapping_status, scrapping_date, shredding_date, authority_reference, remarks
            FROM theft_scrap_record
            WHERE vehicle_no = ?
            """,
            (clean_no,)
        ).fetchone()

    if not row:
        return jsonify({
            "agency": "POLICE_CCTNS",
            "query_key": "vehicle_no",
            "vehicle_no": clean_no,
            "found": False,
            "status": "CLEAN",
            "record": None
        }), 200  # Return 200 with clean status

    rec = dict(row)
    from datetime import timezone
    last_mod = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    resp = make_response(jsonify({
        "agency": "POLICE_CCTNS",
        "query_key": "vehicle_no",
        "vehicle_no": clean_no,
        "found": True,
        "record": rec
    }))
    resp.headers["Last-Modified"] = last_mod
    return resp

@app.route("/api/v1/identifiers", methods=["GET"])
def get_identifiers():
    """Distinct vehicle identifiers held by this agency, used by the Mediator's approximate matcher."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT vehicle_no AS plate, theft_status, scrapping_status
            FROM theft_scrap_record GROUP BY vehicle_no ORDER BY vehicle_no
            """
        ).fetchall()
    return jsonify({
        "agency": "POLICE_CCTNS",
        "query_key": "vehicle_no",
        "count": len(rows),
        "identifiers": [dict(r) for r in rows]
    })

@app.route("/api/v1/theft", methods=["POST"])
def report_theft():
    data = request.get_json(force=True)
    if "vehicle_no" not in data or "authority_reference" not in data:
        return jsonify({"error": "Missing vehicle_no or authority_reference (FIR no)"}), 400

    clean_no = data["vehicle_no"].strip().upper().replace(" ", "").replace("-", "")
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        existing = conn.execute("SELECT record_id FROM theft_scrap_record WHERE vehicle_no = ?", (clean_no,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE theft_scrap_record
                SET theft_status = 'STOLEN', theft_report_date = ?, authority_reference = ?, remarks = ?
                WHERE vehicle_no = ?
                """,
                (today, data["authority_reference"], data.get("remarks", "Reported stolen via CCTNS"), clean_no)
            )
        else:
            conn.execute(
                """
                INSERT INTO theft_scrap_record
                    (vehicle_no, theft_status, theft_report_date, authority_reference, remarks)
                VALUES (?, 'STOLEN', ?, ?, ?)
                """,
                (clean_no, today, data["authority_reference"], data.get("remarks", "Reported stolen via CCTNS"))
            )
        conn.commit()

    return jsonify({"message": "Theft reported successfully", "vehicle_no": clean_no, "theft_status": "STOLEN"}), 200

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
            "service": "Police CCTNS & RVSF",
            "database": "theft_scrap.db",
            "execution_ms": elapsed,
            "columns": columns,
            "rows": results,
            "row_count": row_count
        })
    except Exception as e:
        elapsed = round((time.time() - start_t) * 1000, 2)
        return jsonify({
            "status": "error",
            "service": "Police CCTNS & RVSF",
            "database": "theft_scrap.db",
            "execution_ms": elapsed,
            "error": str(e)
        }), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT_POLICE", 5004))
    print(f"[*] Starting Police CCTNS Microservice on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
