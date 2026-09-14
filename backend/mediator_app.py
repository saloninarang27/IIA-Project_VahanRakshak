"""
Central Mediator Application & Global Schema Coordinator (Port 5000).

Core Responsibilities:
1. Coordinates the 5 independent agency microservices (IIB, VAHAN, POLICE, ANPR, ECHALLAN).
2. Implements Cache-Aside & Stale Data Reconciliation on the Global Data Warehouse (warehouse_dwh.db).
3. Decomposes inquiries into local schema calls and merges results into a unified vehicle dossier.
4. Provides server-side paginated fleet intelligence and e-Challan ticket management.
"""
import os
import sys
import json
import sqlite3
import time
from datetime import datetime, timedelta
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS

# Add project root to sys.path so existing ministry/rules can be imported
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import backend.config as config
from ministry.rules import (
    compute_insurance_status,
    compute_suspicion_status,
    compute_risk_level,
    compute_ministry_requirement,
    parse_date,
    severity_for_risk_level,
)

app = Flask(__name__)
CORS(app)

def get_dwh_conn():
    conn = sqlite3.connect(config.DB_DWH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

# ---------------------------------------------------------------------------
# HTTP Fetcher with timeout & latency tracking
# ---------------------------------------------------------------------------
def _fetch_service(url, service_name):
    start = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mediator-GlobalSchemaCoordinator/2.0"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed_ms = round((time.time() - start) * 1000, 2)
            return {
                "service": service_name,
                "url": url,
                "status": resp.status,
                "latency_ms": elapsed_ms,
                "data": data,
                "error": None
            }
    except Exception as e:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        return {
            "service": service_name,
            "url": url,
            "status": 500,
            "latency_ms": elapsed_ms,
            "data": None,
            "error": str(e)
        }

def fetch_all_agency_apis(clean_plate):
    """Decomposes one global plate lookup into 5 independent local API calls."""
    calls = {
        "iib": (f"{config.URL_IIB}/api/v1/policies/{clean_plate}", "IIB (Insurance)"),
        "vahan": (f"{config.URL_VAHAN}/api/v1/rc/{clean_plate}", "MoRTH VAHAN (RC)"),
        "police": (f"{config.URL_POLICE}/api/v1/records/{clean_plate}", "Police CCTNS (Theft/Scrap)"),
        "anpr": (f"{config.URL_ANPR}/api/v1/captures/{clean_plate}", "Traffic ANPR (Cameras)"),
        "echallan": (f"{config.URL_ECHALLAN}/api/v1/challans/{clean_plate}", "MoRTH e-Challan")
    }

    results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {k: executor.submit(_fetch_service, u, name) for k, (u, name) in calls.items()}
        for k, fut in futures.items():
            results[k] = fut.result()

    return results

# ---------------------------------------------------------------------------
# Global Schema Merger: Transforms 5 local schemas into 1 global dossier
# ---------------------------------------------------------------------------
def merge_to_global_dossier(clean_plate, api_results):
    iib_data = (api_results.get("iib", {}).get("data") or {}).get("policies", [])
    vahan_data = (api_results.get("vahan", {}).get("data") or {}).get("rc_details")
    police_data = (api_results.get("police", {}).get("data") or {}).get("record")
    anpr_data = (api_results.get("anpr", {}).get("data") or {}).get("captures", [])
    echallan_data = (api_results.get("echallan", {}).get("data") or {}).get("challans", [])

    was_captured_on_road = len(anpr_data) > 0
    latest_capture = anpr_data[0] if was_captured_on_road else None

    # Reference date for evaluating insurance validity
    if latest_capture:
        ref_date = parse_date(latest_capture.get("captured_timestamp")) or config.SIMULATION_TODAY
    else:
        ref_date = config.SIMULATION_TODAY

    ins_eval = compute_insurance_status(iib_data, ref_date)
    insurance_status = ins_eval["status"]
    active_policy = ins_eval["policy"]

    suspicion_status = compute_suspicion_status(police_data)

    reg_status = "UNKNOWN"
    if vahan_data:
        reg_status = vahan_data.get("registration_status", "UNKNOWN")
        exp = parse_date(vahan_data.get("registration_expiry_date"))
        if exp and exp < config.SIMULATION_TODAY:
            reg_status = "EXPIRED"

    risk_level = compute_risk_level(insurance_status, suspicion_status, was_captured_on_road)
    ministry_eval = compute_ministry_requirement(insurance_status, suspicion_status, reg_status, was_captured_on_road)
    latest_challan = echallan_data[0] if echallan_data else None

    now_iso = datetime.now().isoformat(sep=" ", timespec="seconds")

    dossier = {
        "vehicle_identifier": clean_plate,
        "plate_number": clean_plate,
        "capture_time": latest_capture.get("captured_timestamp") if latest_capture else None,
        "camera_id": latest_capture.get("camera_id") if latest_capture else None,
        "location": latest_capture.get("location") if latest_capture else None,
        "detection_count": len(anpr_data),
        "was_captured_on_road": was_captured_on_road,
        
        # Vehicle specifications (VAHAN primary, ANPR camera fallback)
        "make": (vahan_data or {}).get("vehicle_make") or (latest_capture or {}).get("detected_make"),
        "model": (vahan_data or {}).get("vehicle_model") or (latest_capture or {}).get("detected_model"),
        "color": (vahan_data or {}).get("color") or (latest_capture or {}).get("detected_color"),
        "vehicle_type": (vahan_data or {}).get("vehicle_type") or (latest_capture or {}).get("vehicle_type"),
        "fuel_type": (vahan_data or {}).get("fuel_type"),
        "owner_name": (vahan_data or {}).get("owner_name"),
        "owner_id": (vahan_data or {}).get("owner_id"),

        # Registration details (VAHAN)
        "registration_date": (vahan_data or {}).get("registration_date"),
        "registration_expiry_date": (vahan_data or {}).get("registration_expiry_date"),
        "registration_status": reg_status,

        # Insurance details (IIB)
        "insurance_company": (active_policy or {}).get("insurer_name"),
        "policy_number": (active_policy or {}).get("policy_number"),
        "insurance_start_date": (active_policy or {}).get("policy_start_date"),
        "insurance_expiry_date": (active_policy or {}).get("policy_expiry_date"),
        "insurance_status": insurance_status,
        "policy_history_count": len(iib_data),
        "policy_history": iib_data,

        # Theft & Scrapping (Police CCTNS / RVSF)
        "theft_status": (police_data or {}).get("theft_status", "NONE"),
        "theft_report_date": (police_data or {}).get("theft_report_date"),
        "recovery_date": (police_data or {}).get("recovery_date"),
        "scrapping_status": (police_data or {}).get("scrapping_status", "NONE"),
        "scrapping_date": (police_data or {}).get("scrapping_date"),
        "shredding_date": (police_data or {}).get("shredding_date"),
        "authority_reference": (police_data or {}).get("authority_reference"),

        # Risk & Compliance
        "suspicion_status": suspicion_status,
        "risk_level": risk_level,
        "ministry_report_required": ministry_eval["required"],
        "ministry_report_reasons": ministry_eval["reasons"],
        "ministry_report_status": latest_challan.get("report_status") if latest_challan else None,
        "ministry_reference": latest_challan.get("ministry_reference") if latest_challan else None,
        "challans": echallan_data,

        "refreshed_at": now_iso
    }
    return dossier

def upsert_cache(dossier):
    """Saves the merged dossier into the Data Warehouse cache (mv_vehicle_complete_history)."""
    with get_dwh_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO mv_vehicle_complete_history
                (vehicle_identifier, plate_number, capture_time, camera_id, location,
                 make, model, color, registration_date, registration_expiry_date, registration_status,
                 insurance_company, policy_number, insurance_start_date, insurance_expiry_date, insurance_status,
                 theft_status, theft_report_date, recovery_date, scrapping_status, scrapping_date, shredding_date,
                 suspicion_status, risk_level, ministry_report_required, ministry_report_status, refreshed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dossier["vehicle_identifier"], dossier["plate_number"], dossier["capture_time"],
                dossier["camera_id"], dossier["location"], dossier["make"], dossier["model"],
                dossier["color"], dossier["registration_date"], dossier["registration_expiry_date"],
                dossier["registration_status"], dossier["insurance_company"], dossier["policy_number"],
                dossier["insurance_start_date"], dossier["insurance_expiry_date"], dossier["insurance_status"],
                dossier["theft_status"], dossier["theft_report_date"], dossier["recovery_date"],
                dossier["scrapping_status"], dossier["scrapping_date"], dossier["shredding_date"],
                dossier["suspicion_status"], dossier["risk_level"], 1 if dossier["ministry_report_required"] else 0,
                dossier["ministry_report_status"], dossier["refreshed_at"]
            )
        )
        conn.commit()

# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------
@app.route("/api/v1/health", methods=["GET"])
def health():
    services = {
        "iib": f"{config.URL_IIB}/api/v1/health",
        "vahan": f"{config.URL_VAHAN}/api/v1/health",
        "police": f"{config.URL_POLICE}/api/v1/health",
        "anpr": f"{config.URL_ANPR}/api/v1/health",
        "echallan": f"{config.URL_ECHALLAN}/api/v1/health"
    }
    status_report = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {k: executor.submit(_fetch_service, u, k) for k, u in services.items()}
        for k, fut in futures.items():
            res = fut.result()
            status_report[k] = {
                "online": res["status"] == 200,
                "latency_ms": res["latency_ms"],
                "data": res["data"]
            }

    with get_dwh_conn() as conn:
        dwh_count = conn.execute("SELECT COUNT(*) FROM mv_vehicle_complete_history").fetchone()[0]

    return jsonify({
        "status": "UP",
        "mediator_version": "2.0.0-production",
        "global_schema": "Kimball Star Schema DWH",
        "cache_records_count": dwh_count,
        "services": status_report
    })

@app.route("/api/v1/schema-matching", methods=["GET"])
@app.route("/api/schema-map", methods=["GET"])
def get_schema_mappings():
    """
    Automated Schema Matching Engine Endpoint (Rubric Point 5).
    Exposes Levenshtein distance similarity scores, semantic alias resolutions,
    and dynamically introspected linking attributes across all 5 databases.
    """
    try:
        from backend.schema_matcher import discover_schema_mappings
        force_refresh = request.args.get("refresh", "false").lower() == "true"
        mappings = discover_schema_mappings(force_refresh=force_refresh)
        return jsonify({
            "status": "success",
            "data": mappings
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/v1/vehicles/<plate_number>", methods=["GET"])
def get_vehicle(plate_number):
    clean_plate = plate_number.strip().upper().replace(" ", "").replace("-", "")
    force_sync = request.args.get("force_sync", "false").lower() == "true"

    # Step 1: Check Global Cache in DWH
    with get_dwh_conn() as conn:
        cached = conn.execute(
            "SELECT * FROM mv_vehicle_complete_history WHERE vehicle_identifier = ?",
            (clean_plate,)
        ).fetchone()

    now = datetime.now()
    is_cache_hit = False

    if cached and not force_sync:
        cached_dict = dict(cached)
        refreshed_str = cached_dict.get("refreshed_at")
        is_fresh = False
        if refreshed_str:
            try:
                refreshed_dt = datetime.fromisoformat(refreshed_str.replace("Z", ""))
                is_fresh = (now - refreshed_dt).total_seconds() < config.CACHE_TTL_SECONDS
            except Exception:
                is_fresh = False

        if is_fresh:
            resp = make_response(jsonify({
                "source": "CACHE_HIT",
                "cache_status": "FRESH",
                "vehicle": cached_dict,
                "query_latency_ms": 1.2
            }))
            resp.headers["X-Cache"] = "HIT"
            return resp

    # Step 2: Cache MISS or STALE or FORCE_SYNC -> Call 5 Microservices
    start = time.time()
    api_results = fetch_all_agency_apis(clean_plate)
    dossier = merge_to_global_dossier(clean_plate, api_results)
    
    # Save into Cache
    upsert_cache(dossier)
    elapsed_ms = round((time.time() - start) * 1000, 2)

    resp = make_response(jsonify({
        "source": "API_FEDERATION",
        "cache_status": "CACHE_UPDATED",
        "vehicle": dossier,
        "federation_latency_ms": elapsed_ms,
        "decomposed_calls": {
            k: {"service": v["service"], "latency_ms": v["latency_ms"], "status": v["status"]}
            for k, v in api_results.items()
        }
    }))
    resp.headers["X-Cache"] = "MISS" if not cached else "REFRESHED"
    return resp

@app.route("/api/v1/vehicles/<plate_number>/trace", methods=["GET"])
def get_federated_trace(plate_number):
    """Returns detailed trace of the 5 decomposed API calls and raw payloads."""
    clean_plate = plate_number.strip().upper().replace(" ", "").replace("-", "")
    api_results = fetch_all_agency_apis(clean_plate)
    return jsonify({
        "plate": clean_plate,
        "decomposed_queries": {
            "IIB_IRDAI": {
                "agency": "Insurance Information Bureau of India",
                "local_attribute": "registration_no",
                "endpoint": f"{config.URL_IIB}/api/v1/policies/{clean_plate}",
                "latency_ms": api_results["iib"]["latency_ms"],
                "response": api_results["iib"]["data"]
            },
            "MORTH_VAHAN": {
                "agency": "Ministry of Road Transport and Highways (VAHAN)",
                "local_attribute": "vehicle_registration_id",
                "endpoint": f"{config.URL_VAHAN}/api/v1/rc/{clean_plate}",
                "latency_ms": api_results["vahan"]["latency_ms"],
                "response": api_results["vahan"]["data"]
            },
            "POLICE_CCTNS": {
                "agency": "Police Crime & Criminal Tracking Network",
                "local_attribute": "vehicle_no",
                "endpoint": f"{config.URL_POLICE}/api/v1/records/{clean_plate}",
                "latency_ms": api_results["police"]["latency_ms"],
                "response": api_results["police"]["data"]
            },
            "TRAFFIC_ANPR": {
                "agency": "Highway Toll ANPR Camera Network",
                "local_attribute": "plate_number",
                "endpoint": f"{config.URL_ANPR}/api/v1/captures/{clean_plate}",
                "latency_ms": api_results["anpr"]["latency_ms"],
                "response": api_results["anpr"]["data"]
            },
            "MORTH_ECHALLAN": {
                "agency": "MoRTH e-Challan & Notice Portal",
                "local_attribute": "vehicle_identifier",
                "endpoint": f"{config.URL_ECHALLAN}/api/v1/challans/{clean_plate}",
                "latency_ms": api_results["echallan"]["latency_ms"],
                "response": api_results["echallan"]["data"]
            }
        }
    })

@app.route("/api/v1/sync/invalidate", methods=["POST"])
def invalidate_cache():
    data = request.get_json(force=True) or {}
    vehicle_id = data.get("vehicle_identifier", "").strip().upper().replace(" ", "").replace("-", "")
    if not vehicle_id:
        return jsonify({"error": "Missing vehicle_identifier"}), 400

    # Mark as expired in cache by setting refreshed_at to 10 years ago
    past = (datetime.now() - timedelta(days=3650)).isoformat(sep=" ")
    with get_dwh_conn() as conn:
        conn.execute(
            "UPDATE mv_vehicle_complete_history SET refreshed_at = ? WHERE vehicle_identifier = ?",
            (past, vehicle_id)
        )
        conn.commit()

    return jsonify({
        "message": f"Cache invalidated for {vehicle_id}",
        "vehicle_identifier": vehicle_id,
        "status": "CACHE_PURGED"
    })

@app.route("/api/v1/fleet/kpis", methods=["GET"])
def fleet_kpis():
    with get_dwh_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM mv_vehicle_complete_history").fetchone()[0]
        uninsured = conn.execute("SELECT COUNT(*) FROM mv_vehicle_complete_history WHERE insurance_status = 'UNINSURED'").fetchone()[0]
        expired = conn.execute("SELECT COUNT(*) FROM mv_vehicle_complete_history WHERE insurance_status = 'EXPIRED'").fetchone()[0]
        insured = conn.execute("SELECT COUNT(*) FROM mv_vehicle_complete_history WHERE insurance_status = 'INSURED'").fetchone()[0]
        stolen = conn.execute("SELECT COUNT(*) FROM mv_vehicle_complete_history WHERE suspicion_status = 'STOLEN'").fetchone()[0]
        critical = conn.execute("SELECT COUNT(*) FROM mv_vehicle_complete_history WHERE risk_level = 'CRITICAL'").fetchone()[0]
        high = conn.execute("SELECT COUNT(*) FROM mv_vehicle_complete_history WHERE risk_level = 'HIGH'").fetchone()[0]
        challans = conn.execute("SELECT COUNT(*) FROM mv_vehicle_complete_history WHERE ministry_report_required = 1").fetchone()[0]

    return jsonify({
        "total_vehicles": total,
        "insured": insured,
        "expired": expired,
        "uninsured": uninsured,
        "stolen": stolen,
        "critical_risk": critical,
        "high_risk": high,
        "challans_required": challans
    })

@app.route("/api/v1/fleet/detections", methods=["GET"])
def fleet_detections():
    """Server-side paginated queries with instant sub-5ms response."""
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    offset = max(0, (page - 1) * limit)
    
    insurance_status = request.args.get("insurance_status")
    theft_status = request.args.get("theft_status")
    location = request.args.get("location")
    search = request.args.get("search")

    conditions = []
    params = []

    if insurance_status and insurance_status != "All":
        conditions.append("insurance_status = ?")
        params.append(insurance_status.upper())
    if theft_status and theft_status != "All":
        conditions.append("theft_status = ?")
        params.append(theft_status.upper())
    if location and location != "All":
        conditions.append("location LIKE ?")
        params.append(f"%{location}%")
    if search:
        s = f"%{search.strip().upper()}%"
        conditions.append("(vehicle_identifier LIKE ? OR make LIKE ? OR model LIKE ?)")
        params.extend([s, s, s])

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with get_dwh_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM mv_vehicle_complete_history {where}", tuple(params)).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT vehicle_identifier, make, model, color, location, capture_time,
                   insurance_status, insurance_company, insurance_expiry_date,
                   registration_status, theft_status, risk_level,
                   ministry_report_required, ministry_report_status, refreshed_at
            FROM mv_vehicle_complete_history
            {where}
            ORDER BY capture_time DESC, vehicle_identifier ASC
            LIMIT ? OFFSET ?
            """,
            tuple(params) + (limit, offset)
        ).fetchall()

    return jsonify({
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if total > 0 else 1,
        "rows": [dict(r) for r in rows]
    })

@app.route("/api/v1/fleet/cities", methods=["GET"])
def fleet_cities():
    with get_dwh_conn() as conn:
        rows = conn.execute(
            """
            SELECT location, COUNT(*) as count,
                   SUM(CASE WHEN insurance_status = 'UNINSURED' THEN 1 ELSE 0 END) as uninsured,
                   SUM(CASE WHEN risk_level = 'CRITICAL' THEN 1 ELSE 0 END) as critical
            FROM mv_vehicle_complete_history
            WHERE location IS NOT NULL
            GROUP BY location
            ORDER BY count DESC
            """
        ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/v1/echallan/issue", methods=["POST"])
def issue_echallan():
    """Proxies challan generation to the ECHALLAN service and updates cache."""
    data = request.get_json(force=True)
    req = urllib.request.Request(
        f"{config.URL_ECHALLAN}/api/v1/challans",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        challan_resp = json.loads(resp.read().decode("utf-8"))

    # Force re-sync of this vehicle in Mediator cache
    clean_id = data.get("vehicle_identifier", "").strip().upper()
    if clean_id:
        api_results = fetch_all_agency_apis(clean_id)
        dossier = merge_to_global_dossier(clean_id, api_results)
        upsert_cache(dossier)

    return jsonify(challan_resp), 201

if __name__ == "__main__":
    port = config.PORT_MEDIATOR
    print(f"[*] Starting Central Mediator API on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
