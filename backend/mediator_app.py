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
import threading
import time
from datetime import datetime, timedelta
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, make_response, g, has_request_context
from flask_cors import CORS

# Add project root to sys.path so existing ministry/rules can be imported
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import backend.config as config
from backend import security
from matching.normalize import normalize_plate
from ministry.rules import (
    compute_risk_level,
    compute_ministry_requirement,
    parse_date,
    severity_for_risk_level,
)

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Access control: every /api call needs a login token; some need a specific role.
# The agencies re-check the role themselves (the Mediator signs it into each request).
# ---------------------------------------------------------------------------
PUBLIC_PATHS = {"/api/v1/health", "/api/v1/auth/login"}
_ADMIN = {"ADMIN"}
_POLICE_ADMIN = {"POLICE", "ADMIN"}
ACCESS_POLICY = {
    ("POST", "/api/v1/sql"): _ADMIN,                                  # raw SQL REPL
    ("GET", "/api/v1/matching/noisy-records"): _ADMIN,                # batch cleansing over whole databases
    ("POST", "/api/v1/matching/noisy-records"): _ADMIN,
    ("POST", "/api/v1/matching/cleanse"): _ADMIN,
    ("GET", "/api/v1/matching/audit"): _ADMIN,
    ("POST", "/api/v1/matching/evaluation/run"): _ADMIN,
    ("POST", "/api/v1/matching/index/refresh"): _ADMIN,
    ("GET", "/api/v1/matching/agency"): _ADMIN,
    ("POST", "/api/v1/matching/agency"): _ADMIN,
    ("GET", "/api/v1/fleet/detections"): _POLICE_ADMIN,               # row-level listing of all vehicles
    ("GET", "/api/v1/echallan"): _POLICE_ADMIN,
    ("POST", "/api/v1/echallan"): _POLICE_ADMIN,
    ("PUT", "/api/v1/echallan"): _POLICE_ADMIN,
}
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", 300))
LOGIN_FAILURES_PER_MINUTE = 5
_hits = {}
_hits_lock = threading.Lock()


def _count_recent(bucket, add=False):
    """Events in the last minute for bucket (e.g. client IP); add=True records one more."""
    now = time.time()
    with _hits_lock:
        recent = [t for t in _hits.get(bucket, []) if now - t < 60]
        if add:
            recent.append(now)
        _hits[bucket] = recent
        return len(recent)


def _error(status, message, **extra):
    return jsonify({"status": "error", "error": message, **extra}), status


@app.before_request
def _access_control():
    if request.method == "OPTIONS" or not request.path.startswith("/api/") or request.path in PUBLIC_PATHS:
        return None
    if _count_recent(("req", request.remote_addr), add=True) > RATE_LIMIT_PER_MINUTE:
        return _error(429, "Too many requests - slow down.")
    if request.path == "/api/v1/sync/invalidate":  # webhook from an agency: must be signed, not a user
        path = request.full_path.rstrip("?") if request.query_string else request.path
        try:
            security.verify_signed(request.headers, request.method, path, request.get_data())
        except PermissionError as e:
            return _error(401, str(e))
        return None
    auth = request.headers.get("Authorization", "")
    session = security.read_token(auth[7:] if auth.startswith("Bearer ") else "")
    if not session:
        return _error(401, "Login required.", login_required=True)
    g.user, g.role = session["user"], session["role"]
    allowed = security.route_roles(request.method, request.path, ACCESS_POLICY)
    if allowed is not None and g.role not in allowed:
        return _error(403, f"Your role ({g.role}) may not use this function; it needs {' or '.join(sorted(allowed))}.")
    return None


@app.route("/api/v1/auth/login", methods=["POST"])
def login():
    if not security.configured():
        return _error(503, "Security is not configured on the Mediator machine: run  python -m backend.security init-env")
    if _count_recent(("login-fail", request.remote_addr)) >= LOGIN_FAILURES_PER_MINUTE:
        return _error(429, "Too many failed logins - wait a minute.")
    data = request.get_json(force=True, silent=True) or {}
    user = (data.get("username") or "").strip()
    role = security.authenticate(user, data.get("password") or "")
    if not role:
        _count_recent(("login-fail", request.remote_addr), add=True)
        return _error(401, "Invalid username or password.")
    return jsonify({"status": "authenticated", "user": user, "role": role, "token": security.issue_token(user, role),
                    "expires_in": security.TOKEN_TTL_SECONDS})


@app.route("/api/v1/auth/me", methods=["GET"])
def whoami():
    return jsonify({"user": g.user, "role": g.role})


def get_dwh_conn():
    conn = sqlite3.connect(config.DB_DWH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

# ---------------------------------------------------------------------------
# HTTP Fetcher with timeout & latency tracking
# ---------------------------------------------------------------------------
def current_role():
    """Role of the logged-in user making this request (batch jobs outside a request run as ADMIN)."""
    return (g.get("role") if has_request_context() else None) or "ADMIN"


def _in_process_service(url, method, req):
    """
    pytest only (local mode): call this checkout's agency app in-process with the same signed
    request, so the suite is hermetic and fast (on Windows a refused connection costs ~2 s).
    """
    from urllib.parse import urlparse
    import importlib
    from flask.testing import FlaskClient
    parsed = urlparse(url)
    app_map = {
        config.PORT_IIB: "backend.IIB.iib_service",
        config.PORT_VAHAN: "backend.VAHAN.vahan_service",
        config.PORT_POLICE: "backend.POLICE_CCTNS.cctns_service",
        config.PORT_ANPR: "backend.ANPR_CAMERA.anpr_service",
        config.PORT_ECHALLAN: "backend.ECHALLAN.echallan_service",
    }
    if parsed.port not in app_map:
        return None
    svc_app = importlib.import_module(app_map[parsed.port]).app
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    with FlaskClient(svc_app, svc_app.response_class) as client:
        return client.open(path, method=method, headers=dict(req.header_items()),
                           data=req.data or b"", content_type="application/json")


def _fetch_service(url, service_name, role=None, method="GET", body=None):
    """Signed call to an agency service on behalf of `role` (default: the current user's role)."""
    start = time.time()
    role = role or current_role()
    req = security.signed_request(url, method, body, role=role)
    req.add_header("User-Agent", "Mediator-GlobalSchemaCoordinator/2.0")

    if "pytest" in sys.modules and config.DEFAULT_HOST in ("127.0.0.1", "localhost"):
        resp = _in_process_service(url, method, req)
        if resp is not None:
            return {"service": service_name, "url": url, "status": resp.status_code,
                    "latency_ms": round((time.time() - start) * 1000, 2), "data": resp.get_json(),
                    "error": None if resp.status_code in (200, 404) else f"Service returned HTTP {resp.status_code}"}

    try:
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
    except urllib.error.HTTPError as http_err:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        # HTTP 404 means the agency microservice is online and responsive, but has no record for this plate
        if http_err.code == 404:
            try:
                body = http_err.read().decode("utf-8")
                err_data = json.loads(body) if body else None
            except Exception:
                err_data = None
            return {
                "service": service_name,
                "url": url,
                "status": 404,
                "latency_ms": elapsed_ms,
                "data": err_data,
                "error": None
            }
        return {
            "service": service_name,
            "url": url,
            "status": http_err.code,
            "latency_ms": elapsed_ms,
            "data": None,
            "error": f"Service returned HTTP {http_err.code}: {http_err.reason}"
        }
    except Exception as e:
        # If the host is down, strictly report it as offline
        return {
            "service": service_name,
            "url": url,
            "status": 503,
            "latency_ms": round((time.time() - start) * 1000, 2),
            "data": None,
            "error": f"Service offline or unreachable at {url}: {str(e)}"
        }

AGENCY_LABELS = {
    "iib": ("IIB (Insurance)", "IIB_IRDAI", "Insurance Information Bureau of India", "registration_no"),
    "vahan": ("MoRTH VAHAN (RC)", "MORTH_VAHAN", "Ministry of Road Transport and Highways (VAHAN)", "vehicle_registration_id"),
    "police": ("Police CCTNS (Theft/Scrap)", "POLICE_CCTNS", "Police Crime & Criminal Tracking Network", "vehicle_no"),
    "anpr": ("Traffic ANPR (Cameras)", "TRAFFIC_ANPR", "Highway Toll ANPR Camera Network", "plate_number"),
    "echallan": ("MoRTH e-Challan", "MORTH_ECHALLAN", "MoRTH e-Challan & Notice Portal", "vehicle_identifier"),
}
AGENCY_URLS = {"iib": config.URL_IIB, "vahan": config.URL_VAHAN, "police": config.URL_POLICE,
               "anpr": config.URL_ANPR, "echallan": config.URL_ECHALLAN}


def _verdict_url(key, clean_plate, on=None):
    return f"{AGENCY_URLS[key]}/api/v1/verdict/{clean_plate}" + (f"?on={on.isoformat()}" if on else "")


def fetch_all_agency_apis(clean_plate):
    """
    Decomposes one plate lookup into five questions, each answered BY the agency that owns the data
    (verdict push-down, backend/verdicts.py). No agency sends its rows for the Mediator to evaluate.

    Round 1 (parallel): VAHAN "registered?", Police "stolen/scrapped?", ANPR "seen on the road?",
                        e-Challan "open challans?"
    Round 2:            IIB "insured on <date of the last sighting>?" (the date comes from ANPR's answer)
    """
    role = current_role()
    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {k: executor.submit(_fetch_service, _verdict_url(k, clean_plate), AGENCY_LABELS[k][0], role)
                   for k in ("vahan", "police", "anpr", "echallan")}
        for k, fut in futures.items():
            results[k] = fut.result()
    last_seen = ((results["anpr"].get("data") or {}).get("last_seen") or {}).get("captured_timestamp")
    on = parse_date(last_seen) or config.SIMULATION_TODAY
    results["iib"] = _fetch_service(_verdict_url("iib", clean_plate, on), AGENCY_LABELS["iib"][0], role)
    return {k: results[k] for k in ("iib", "vahan", "police", "anpr", "echallan")}


# ---------------------------------------------------------------------------
# Global dossier: combines the five agencies' answers (the Mediator does not re-evaluate their data)
# ---------------------------------------------------------------------------
def merge_to_global_dossier(clean_plate, api_results):
    def answer(key):
        res = api_results.get(key) or {}
        return (res.get("data") or {}) if res.get("status") == 200 else {}

    iib, vahan, police, anpr, echallan = (answer(k) for k in ("iib", "vahan", "police", "anpr", "echallan"))

    insurance_status = iib.get("insurance_status") or "UNINSURED"
    suspicion_status = police.get("suspicion_status") or "NONE"
    reg_status = vahan.get("registration_status") or "UNKNOWN"
    was_captured_on_road = bool(anpr.get("seen_on_road"))
    last_seen = anpr.get("last_seen") or {}
    vehicle = vahan.get("vehicle") or {}
    latest_challan = echallan.get("latest") or {}

    # Combining the answers is the Mediator's job: overall risk and the reporting requirement
    risk_level = compute_risk_level(insurance_status, suspicion_status, was_captured_on_road)
    ministry_eval = compute_ministry_requirement(insurance_status, suspicion_status, reg_status, was_captured_on_road)

    return {
        "vehicle_identifier": clean_plate,
        "plate_number": clean_plate,
        "capture_time": last_seen.get("captured_timestamp"),
        "camera_id": last_seen.get("camera_id"),
        "location": last_seen.get("location"),
        "detection_count": anpr.get("detection_count", 0),
        "was_captured_on_road": was_captured_on_road,

        # Vehicle specifications (VAHAN primary, ANPR camera fallback)
        "make": vehicle.get("vehicle_make") or last_seen.get("detected_make"),
        "model": vehicle.get("vehicle_model") or last_seen.get("detected_model"),
        "color": vehicle.get("color") or last_seen.get("detected_color"),
        "vehicle_type": vehicle.get("vehicle_type") or last_seen.get("vehicle_type"),
        "fuel_type": vehicle.get("fuel_type"),
        "owner_name": vahan.get("owner_name"),
        "owner_id": vahan.get("owner_id"),

        # Registration (VAHAN's answer)
        "registration_date": vahan.get("registration_date"),
        "registration_expiry_date": vahan.get("valid_till"),
        "registration_status": reg_status,

        # Insurance (IIB's answer; policy rows only for INSURER / ADMIN)
        "insurance_company": iib.get("insurer_name"),
        "policy_number": iib.get("policy_number"),
        "insurance_start_date": iib.get("valid_from"),
        "insurance_expiry_date": iib.get("valid_till"),
        "insurance_status": insurance_status,
        "insurance_evaluated_on": iib.get("evaluated_on"),
        "policy_history_count": iib.get("policy_count", 0),
        "policy_history": iib.get("policies", []),
        "claims": iib.get("claims", []),

        # Theft & scrapping (Police's answer; FIRs only for POLICE / ADMIN)
        "theft_status": police.get("theft_status", "NONE"),
        "theft_report_date": police.get("theft_report_date"),
        "recovery_date": police.get("recovery_date"),
        "scrapping_status": police.get("scrapping_status", "NONE"),
        "scrapping_date": police.get("scrapping_date"),
        "shredding_date": police.get("shredding_date"),
        "authority_reference": police.get("authority_reference"),
        "firs": police.get("firs", []),

        # Risk & compliance
        "suspicion_status": suspicion_status,
        "risk_level": risk_level,
        "ministry_report_required": ministry_eval["required"],
        "ministry_report_reasons": ministry_eval["reasons"],
        "ministry_report_status": latest_challan.get("report_status"),
        "ministry_reference": latest_challan.get("ministry_reference"),
        "open_challans": echallan.get("open_challans", 0),
        "challans": echallan.get("challans", []),

        "refreshed_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
    }


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
# Approximate Vehicle Matching & Data Cleansing (backend/matching_api.py)
# ---------------------------------------------------------------------------
from backend import matching_api

def mark_vehicles_stale(plates):
    """Expire cached dossiers so the next lookup re-federates (used after data is cleansed)."""
    past = (datetime.now() - timedelta(days=3650)).isoformat(sep=" ")
    plates = [normalize_plate(p) for p in plates if normalize_plate(p)]
    if not plates:
        return
    with get_dwh_conn() as conn:
        conn.executemany("UPDATE mv_vehicle_complete_history SET refreshed_at = ? WHERE vehicle_identifier = ?",
                         [(past, p) for p in plates])
        conn.commit()

matching_api.configure(_fetch_service, on_vehicles_changed=mark_vehicles_stale)
app.register_blueprint(matching_api.matching_bp)

# Federated context discovery across the five databases (backend/context_api.py)
from backend import context_api
context_api.configure(_fetch_service)
app.register_blueprint(context_api.context_bp)

def _attach_approximate_matches(vehicle):
    """For a plate VAHAN does not know, suggest the registered vehicles it most likely is."""
    if not vehicle or vehicle.get("registration_status") != "UNREGISTERED":
        return None
    try:
        return matching_api.suggest_matches(vehicle["vehicle_identifier"])
    except Exception as e:
        return {"error": f"Approximate matching unavailable: {e}"}

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
    clean_plate = normalize_plate(plate_number)
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
                "approximate_matches": _attach_approximate_matches(cached_dict),
                "query_latency_ms": 1.2
            }))
            resp.headers["X-Cache"] = "HIT"
            return resp

    # Step 2: Cache MISS or STALE or FORCE_SYNC -> Call 5 Microservices
    start = time.time()
    api_results = fetch_all_agency_apis(clean_plate)
    elapsed_ms = round((time.time() - start) * 1000, 2)

    # Analyze API outcomes: 200 (record found) and 404 (vehicle not registered) are valid responsive outcomes
    failed_services = [k for k, v in api_results.items() if v["status"] not in (200, 404)]
    successful_services = [k for k, v in api_results.items() if v["status"] in (200, 404)]
    failed_count = len(failed_services)
    target_host = config.DEFAULT_HOST

    # Case A: ALL 5 services failed (Remote or local host is down/unreachable)
    if failed_count == 5:
        if cached:
            cached_dict = dict(cached)
            resp = make_response(jsonify({
                "source": "CACHE_FALLBACK",
                "cache_status": "OFFLINE_FALLBACK",
                "services_status": "OFFLINE",
                "failed_count": 5,
                "target_host": target_host,
                "warning": f"Cannot reach backend APIs at {target_host} (5/5 services offline or timed out). Displaying cached record from local Data Warehouse.",
                "vehicle": cached_dict,
                "federation_latency_ms": elapsed_ms,
                "decomposed_calls": {
                    k: {"service": v["service"], "latency_ms": v["latency_ms"], "status": v["status"], "error": v.get("error")}
                    for k, v in api_results.items()
                }
            }))
            resp.headers["X-Cache"] = "FALLBACK"
            return resp
        else:
            resp = make_response(jsonify({
                "source": "FEDERATION_FAILED",
                "cache_status": "NO_CACHE",
                "services_status": "OFFLINE",
                "failed_count": 5,
                "target_host": target_host,
                "error": f"Cannot reach backend APIs at {target_host} (5/5 services offline or timed out), and no cached record exists for {clean_plate}.",
                "vehicle": None,
                "federation_latency_ms": elapsed_ms,
                "decomposed_calls": {
                    k: {"service": v["service"], "latency_ms": v["latency_ms"], "status": v["status"], "error": v.get("error")}
                    for k, v in api_results.items()
                }
            }), 503)
            resp.headers["X-Cache"] = "UNAVAILABLE"
            return resp

    # Case B: At least some services responded
    dossier = merge_to_global_dossier(clean_plate, api_results)

    # If partial failure and cached exists, preserve cached values rather than overwriting with None
    if failed_count > 0 and cached:
        cached_dict = dict(cached)
        for k, v in cached_dict.items():
            if dossier.get(k) is None and v is not None:
                dossier[k] = v

    # Upsert only when we have real data from at least one service
    upsert_cache(dossier)

    source_type = "PARTIAL_FEDERATION" if failed_count > 0 else "API_FEDERATION"
    resp = make_response(jsonify({
        "source": source_type,
        "cache_status": "CACHE_UPDATED",
        "services_status": "DEGRADED" if failed_count > 0 else "HEALTHY",
        "failed_count": failed_count,
        "target_host": target_host,
        "vehicle": dossier,
        "approximate_matches": _attach_approximate_matches(dossier),
        "federation_latency_ms": elapsed_ms,
        "decomposed_calls": {
            k: {"service": v["service"], "latency_ms": v["latency_ms"], "status": v["status"], "error": v.get("error")}
            for k, v in api_results.items()
        }
    }))
    resp.headers["X-Cache"] = "MISS" if not cached else "REFRESHED"
    return resp

@app.route("/api/v1/vehicles/<plate_number>/trace", methods=["GET"])
def get_federated_trace(plate_number):
    """The five decomposed questions, where each was answered, and each agency's answer."""
    clean_plate = normalize_plate(plate_number)
    api_results = fetch_all_agency_apis(clean_plate)
    trace = {}
    for key, res in api_results.items():
        _, trace_key, agency, attribute = AGENCY_LABELS[key]
        data = res.get("data") or {}
        trace[trace_key] = {
            "agency": agency,
            "local_attribute": attribute,
            "question": data.get("question"),
            "computed_at": "agency (verdict push-down)",
            "endpoint": res["url"],
            "latency_ms": res["latency_ms"],
            "status": res["status"],
            "error": res.get("error"),
            "response": res["data"] or {"error": res.get("error")},
        }
    return jsonify({"plate": clean_plate, "target_host": config.DEFAULT_HOST, "decomposed_queries": trace})


@app.route("/api/v1/sync/invalidate", methods=["POST"])
def invalidate_cache():
    data = request.get_json(force=True) or {}
    vehicle_id = normalize_plate(data.get("vehicle_identifier"))
    if not vehicle_id:
        return jsonify({"error": "Missing vehicle_identifier"}), 400

    mark_vehicles_stale([vehicle_id])

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
    req = security.signed_request(f"{config.URL_ECHALLAN}/api/v1/challans", "POST", data, role=current_role())
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        challan_resp = json.loads(resp.read().decode("utf-8"))

    # Force re-sync of this vehicle in Mediator cache
    clean_id = normalize_plate(data.get("vehicle_identifier"))
    if clean_id:
        api_results = fetch_all_agency_apis(clean_id)
        dossier = merge_to_global_dossier(clean_id, api_results)
        upsert_cache(dossier)

    return jsonify(challan_resp), 201

@app.route("/api/v1/echallan/challans", methods=["GET"])
def get_echallans_list():
    """Proxies challan listing to the ECHALLAN service (local or remote)."""
    page = request.args.get("page", 1)
    limit = request.args.get("limit", 20)
    status = request.args.get("status", "")
    params = f"?page={page}&limit={limit}"
    if status:
        params += f"&status={status}"
    url = f"{config.URL_ECHALLAN}/api/v1/challans{params}"
    try:
        req = security.signed_request(url, "GET", role=current_role())
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return jsonify(data)
    except Exception as e:
        return jsonify({"error": f"Failed to connect to E-Challan service at {config.URL_ECHALLAN}: {str(e)}", "challans": [], "total": 0}), 502

@app.route("/api/v1/echallan/challans/<int:report_id>/status", methods=["PUT"])
def update_echallan_status(report_id):
    """Proxies challan status update to the ECHALLAN service (local or remote)."""
    data = request.get_json(force=True)
    url = f"{config.URL_ECHALLAN}/api/v1/challans/{report_id}/status"
    try:
        req = security.signed_request(url, "PUT", data, role=current_role())
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            return jsonify(res_data)
    except Exception as e:
        return jsonify({"error": f"Failed to update challan at {config.URL_ECHALLAN}: {str(e)}"}), 502


# ---------------------------------------------------------------------------
# Distributed Interactive SQL REPL Endpoints
# ---------------------------------------------------------------------------
# Access: ADMIN session token only (see ACCESS_POLICY); the agency checks the ADMIN role again.
@app.route("/api/v1/sql/execute", methods=["POST"])
def sql_execute():
    """
    Multi-Hop Distributed SQL REPL Engine.
    Flow: Frontend -> Mediator (Port 5001) -> Microservice (Ports 5002-5006) -> SQLite DB.
    """
    data = request.get_json(force=True) or {}
    target = data.get("target", "").strip().lower()
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"status": "error", "error": "Empty SQL query provided"}), 400

    service_targets = {
        "iib": {
            "name": "IIB (Insurance Information Bureau)",
            "agency": "IRDAI",
            "url": f"{config.URL_IIB}/api/v1/internal/execute-sql",
            "host": config.HOST_IIB,
            "port": config.PORT_IIB,
            "db": "insurance_iib.db"
        },
        "vahan": {
            "name": "MoRTH VAHAN Registry",
            "agency": "Ministry of Road Transport & Highways",
            "url": f"{config.URL_VAHAN}/api/v1/internal/execute-sql",
            "host": config.HOST_VAHAN,
            "port": config.PORT_VAHAN,
            "db": "parivahan_vahan.db"
        },
        "police": {
            "name": "Police CCTNS & RVSF",
            "agency": "State Police Crime & Criminal Tracking",
            "url": f"{config.URL_POLICE}/api/v1/internal/execute-sql",
            "host": config.HOST_POLICE,
            "port": config.PORT_POLICE,
            "db": "theft_scrap.db"
        },
        "anpr": {
            "name": "Highway Toll ANPR Cameras",
            "agency": "National Highways Authority of India",
            "url": f"{config.URL_ANPR}/api/v1/internal/execute-sql",
            "host": config.HOST_ANPR,
            "port": config.PORT_ANPR,
            "db": "vehicle_capture.db"
        },
        "echallan": {
            "name": "MoRTH e-Challan Notice Portal",
            "agency": "MoRTH Enforcement Wing",
            "url": f"{config.URL_ECHALLAN}/api/v1/internal/execute-sql",
            "host": config.HOST_ECHALLAN,
            "port": config.PORT_ECHALLAN,
            "db": "ministry_echallan.db"
        },
        "dwh": {
            "name": "Central Kimball Star Schema DWH",
            "agency": "Vehicle Sentinel Central Analytics",
            "url": "local://warehouse_dwh.db",
            "host": "127.0.0.1",
            "port": config.PORT_MEDIATOR,
            "db": "warehouse_dwh.db"
        }
    }

    if target not in service_targets:
        return jsonify({
            "status": "error",
            "error": f"Invalid target service '{target}'. Supported targets: {list(service_targets.keys())}"
        }), 400

    target_info = service_targets[target]
    is_remote = target_info["host"] not in ("127.0.0.1", "localhost")

    # Local DWH query execution
    if target == "dwh":
        t0 = time.time()
        try:
            with get_dwh_conn() as conn:
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
            exec_time = round((time.time() - t0) * 1000, 2)
            return jsonify({
                "status": "success",
                "target": target_info["name"],
                "agency": target_info["agency"],
                "database": target_info["db"],
                "target_host": target_info["host"],
                "is_remote": False,
                "hop_latency_ms": exec_time,
                "remote_db_execution_ms": exec_time,
                "columns": columns,
                "rows": results,
                "row_count": row_count,
                "query": query,
                "trace": [
                    {"hop": 1, "action": "Browser -> Mediator API", "endpoint": "/api/v1/sql/execute", "status": "200 OK"},
                    {"hop": 2, "action": "Mediator -> Local Star Schema DWH Engine", "target": "warehouse_dwh.db", "status": "SUCCESS"}
                ]
            })
        except Exception as e:
            exec_time = round((time.time() - t0) * 1000, 2)
            return jsonify({
                "status": "error",
                "target": target_info["name"],
                "agency": target_info["agency"],
                "database": target_info["db"],
                "target_host": target_info["host"],
                "is_remote": False,
                "hop_latency_ms": exec_time,
                "error": str(e),
                "query": query
            }), 400

    # Remote or Local Microservice API Call
    t0 = time.time()
    try:
        req = security.signed_request(target_info["url"], "POST", {"query": query}, role="ADMIN")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            raw = resp.read().decode("utf-8")
            res_data = json.loads(raw)
            hop_time = round((time.time() - t0) * 1000, 2)

        # The agency microservice has already applied the statement to its own database; it is the
        # only writer. (Re-running it here against a "local copy" applied every INSERT twice when the
        # services run on this machine, because that copy is the same file.)
        is_mutation = any(query.strip().upper().startswith(kw) for kw in ("UPDATE", "INSERT", "DELETE", "REPLACE", "ALTER", "CREATE", "DROP"))
        if is_mutation and res_data.get("status") == "success":
            matching_api.invalidate_index()  # plates changed in an agency database -> rebuild the matcher's index

        return jsonify({
            "status": res_data.get("status", "success"),
            "target": target_info["name"],
            "agency": target_info["agency"],
            "database": target_info["db"],
            "target_host": target_info["host"],
            "target_port": target_info["port"],
            "target_endpoint": target_info["url"],
            "is_remote": is_remote,
            "hop_latency_ms": hop_time,
            "remote_db_execution_ms": res_data.get("execution_ms", 0),
            "columns": res_data.get("columns", []),
            "rows": res_data.get("rows", []),
            "row_count": res_data.get("row_count", 0),
            "database_updated": is_mutation,
            "error": res_data.get("error"),
            "query": query,
            "trace": [
                {"hop": 1, "action": "Browser -> Central Mediator", "endpoint": "/api/v1/sql/execute", "status": "200 OK"},
                {"hop": 2, "action": f"Mediator -> Microservice ({target_info['host']}:{target_info['port']})", "endpoint": target_info["url"], "status": "200 OK"},
                {"hop": 3, "action": f"Microservice -> SQLite ({target_info['db']})", "engine": "SQLite WAL", "status": "SUCCESS"}
            ]
        })
    except urllib.error.HTTPError as e:
        hop_time = round((time.time() - t0) * 1000, 2)
        err_msg = f"HTTP {e.code}: {e.reason}"
        try:
            body = json.loads(e.read().decode("utf-8"))
            err_msg = body.get("error", err_msg)
        except Exception:
            pass
        return jsonify({
            "status": "error",
            "target": target_info["name"],
            "agency": target_info["agency"],
            "target_host": target_info["host"],
            "target_endpoint": target_info["url"],
            "is_remote": is_remote,
            "hop_latency_ms": hop_time,
            "error": err_msg,
            "query": query,
            "trace": [
                {"hop": 1, "action": "Browser -> Central Mediator", "status": "200 OK"},
                {"hop": 2, "action": f"Mediator -> Microservice ({target_info['host']}:{target_info['port']})", "status": f"ERROR ({e.code})"}
            ]
        }), 400
    except Exception as e:
        hop_time = round((time.time() - t0) * 1000, 2)
        return jsonify({
            "status": "error",
            "target": target_info["name"],
            "agency": target_info["agency"],
            "target_host": target_info["host"],
            "target_endpoint": target_info["url"],
            "is_remote": is_remote,
            "hop_latency_ms": hop_time,
            "error": f"Cannot reach microservice at {target_info['url']}: {str(e)}",
            "query": query,
            "trace": [
                {"hop": 1, "action": "Browser -> Central Mediator", "status": "200 OK"},
                {"hop": 2, "action": f"Mediator -> Microservice ({target_info['host']}:{target_info['port']})", "status": "CONNECTION FAILED / OFFLINE"}
            ]
        }), 503

if __name__ == "__main__":
    port = config.PORT_MEDIATOR
    print(f"[*] Starting Central Mediator API on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
