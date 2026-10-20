"""
Approximate Vehicle Matching & Data Cleansing API (Mediator blueprint, /api/v1/matching).

The reference index is federated from ALL FIVE agency microservices (VAHAN, IIB,
Police, ANPR, e-Challan), fetched in parallel through the Mediator's fetcher, merged
by normalised plate (matching/sources.py) and cached for CACHE_TTL_SECONDS. Each
candidate records which databases hold it. A service that is unreachable falls back
to its local replica file, or is reported as unavailable.

Endpoints:
    GET  /config                       methods, thresholds, decision rules, OCR engines
    POST /ocr                          plate image -> raw OCR text (server engine if installed)
    POST /search                       plate (+ optional context) -> ranked candidates + decision
    GET  /noisy-records                staged noisy records with their current decision
    GET  /noisy-records/<id>           one record, fresh candidate analysis and audit history
    POST /noisy-records/<id>/review    reviewer decision (appended to the audit trail)
    POST /cleanse                      run the rule engine over staged records
    GET  /audit                        append-only correction audit trail
    GET  /evaluation                   latest algorithm comparison (P / R / F1)
    POST /evaluation/run               re-run the comparison
    POST /index/refresh                rebuild the five-database plate list now

  Cleansing of the live agency databases (matching/agency_cleansing.py):
    GET  /agency/scan                  find noisy identifiers in all five agency tables + proposed fix
    POST /agency/cleanse               apply: UPDATE corrected rows in the agency DBs, flag the rest
    POST /agency/review                reviewer decision for one flagged agency row (may UPDATE it)
    GET  /agency/changes               append-only log of agency-data decisions (original values kept)
"""
import os
import threading
import time
from datetime import datetime

from flask import Blueprint, jsonify, request

import backend.config as config
from matching import store, agency_cleansing
from matching.sources import fetch_source_rows, build_reference_index, source_summary
from matching.cleansing import assess_record, RULES, CORRECTION_THRESHOLD, OCR_ONLY_CORRECTION_THRESHOLD, AMBIGUITY_MARGIN
from matching.context import CONTEXT_ATTRIBUTES
from matching.evaluation import run_evaluation, evaluate_cleansing
from matching.matcher import METHODS, METHOD_LABELS, DEFAULT_METHOD, DEFAULT_CANDIDATE_THRESHOLD
from matching.normalize import normalize_plate
from matching.ocr import extract_plate_text, available_engines, OCRUnavailable

matching_bp = Blueprint("matching", __name__, url_prefix="/api/v1/matching")

_fetch = None
_on_vehicles_changed = None
_sql_runner = agency_cleansing.http_sql_runner   # replaced in tests
_index_lock = threading.Lock()
_index_cache = {"vehicles": None, "by_plate": {}, "loaded_at": 0.0, "source": None, "loaded_at_iso": None}
_store_ready = {"path": None}
_evaluation_lock = threading.Lock()


class IndexUnavailable(RuntimeError):
    pass


def configure(fetch_service, on_vehicles_changed=None):
    """
    Inject the Mediator's federated HTTP fetcher and its dossier-cache invalidation
    (avoids a circular import).
    """
    global _fetch, _on_vehicles_changed
    _fetch = fetch_service
    _on_vehicles_changed = on_vehicles_changed


def invalidate_index():
    with _index_lock:
        _index_cache["loaded_at"] = 0.0


def get_reference_index(force=False):
    with _index_lock:
        fresh = time.time() - _index_cache["loaded_at"] < config.MATCHING_INDEX_TTL_SECONDS
        if _index_cache["vehicles"] is not None and fresh and not force:
            return _index_cache["vehicles"]

        source_rows = fetch_source_rows(_fetch)
        vehicles = build_reference_index(source_rows)
        if not vehicles:
            raise IndexUnavailable("None of the five agency databases is reachable, and no local replica exists.")
        sources = source_summary(source_rows, vehicles)
        live = sum(1 for s in sources if s["via"] == "API")
        source = "ALL_SOURCES_API" if live == len(sources) else f"PARTIAL ({live}/{len(sources)} live)"

        _index_cache.update({
            "vehicles": vehicles,
            "by_plate": {v["plate"]: v for v in vehicles},
            "loaded_at": time.time(),
            "loaded_at_iso": datetime.now().isoformat(sep=" ", timespec="seconds"),
            "source": source,
            "sources": sources,
        })
        return vehicles


def _vahan_index():
    """Registered vehicles only: the reference for cleansing agency data."""
    return [v for v in get_reference_index() if v.get("in_vahan")]


def _store_conn():
    return store.connect(_db())


def _data_changed(plates):
    invalidate_index()
    if _on_vehicles_changed and plates:
        _on_vehicles_changed(plates)


def _index_meta():
    return {"size": len(_index_cache["vehicles"] or []), "source": _index_cache["source"],
            "sources": _index_cache.get("sources") or [], "loaded_at": _index_cache["loaded_at_iso"]}


def _db():
    path = config.DB_DATA_QUALITY
    if _store_ready["path"] != path:
        store.init_store(path)
        store.seed_noisy_records(path, get_reference_index())
        _store_ready["path"] = path
    return path


def _method_arg(value):
    method = (value or DEFAULT_METHOD).strip().lower()
    if method not in METHODS:
        raise ValueError(f"Unknown method '{method}'. Choose from {list(METHODS)}")
    return method


def _record_input(record):
    return {"plate": record.get("raw_plate"), "make": record.get("make"), "model": record.get("model"),
            "color": record.get("color"), "vehicle_type": record.get("vehicle_type")}


def suggest_matches(plate, limit=5):
    """Used by the vehicle lookup: approximate matches for a plate VAHAN does not know (all five databases searched)."""
    assessment = assess_record({"plate": plate}, get_reference_index())
    return {
        "decision": assessment["decision"],
        "decision_status": assessment["decision_status"],
        "reason": assessment["reason"],
        "corrected_plate": assessment["corrected_plate"],
        "suggested_plate": assessment["suggested_plate"],
        "candidate_count": assessment["candidate_count"],
        "candidates": [{k: c.get(k) for k in ("rank", "vehicle_id", "plate", "make", "model", "color",
                                              "plate_score", "scores", "sources")}
                       for c in assessment["candidates"][:limit]],
    }


@matching_bp.errorhandler(IndexUnavailable)
def _index_unavailable(e):
    return jsonify({"status": "error", "error": str(e)}), 503


@matching_bp.errorhandler(ValueError)
def _bad_request(e):
    return jsonify({"status": "error", "error": str(e)}), 400


# ---------------------------------------------------------------------------
@matching_bp.route("/config", methods=["GET"])
def matching_config():
    get_reference_index()
    return jsonify({
        "default_method": DEFAULT_METHOD,
        "methods": [{"key": k, "label": METHOD_LABELS[k]} for k in METHODS],
        "thresholds": {
            "candidate": DEFAULT_CANDIDATE_THRESHOLD,
            "correction": CORRECTION_THRESHOLD,
            "ocr_only_correction": OCR_ONLY_CORRECTION_THRESHOLD,
            "ambiguity_margin": AMBIGUITY_MARGIN,
        },
        "context_attributes": [{"attribute": a, "weight": w} for a, w in CONTEXT_ATTRIBUTES],
        "rules": RULES,
        "ocr_engines": available_engines(),
        "index": _index_meta(),
    })


@matching_bp.route("/ocr", methods=["POST"])
def ocr_upload():
    upload = request.files.get("image")
    if upload is None:
        return jsonify({"status": "error", "error": "Send the plate image as multipart field 'image'."}), 400
    data = upload.read()
    if not data:
        return jsonify({"status": "error", "error": "Uploaded image is empty."}), 400
    try:
        result = extract_plate_text(data)
    except OCRUnavailable as e:
        return jsonify({"status": "unavailable", "error": str(e), "fallback": "browser"}), 501
    except Exception as e:
        return jsonify({"status": "error", "error": f"Could not read image: {e}"}), 400
    return jsonify({"status": "success", **result, "normalized_plate": normalize_plate(result["raw_text"])})


@matching_bp.route("/search", methods=["POST"])
def search():
    body = request.get_json(force=True, silent=True) or {}
    method = _method_arg(body.get("method"))
    threshold = float(body.get("threshold") or DEFAULT_CANDIDATE_THRESHOLD)
    if not 0.0 < threshold <= 1.0:
        raise ValueError("threshold must be in (0, 1]")
    limit = max(1, min(int(body.get("limit") or 25), 200))

    started = time.time()
    record = {"plate": body.get("plate"), **{a: (body.get(a) or None) for a, _ in CONTEXT_ATTRIBUTES}}
    assessment = assess_record(record, get_reference_index(), method, threshold=threshold, max_candidates=limit)
    assessment["latency_ms"] = round((time.time() - started) * 1000, 1)
    assessment["index"] = _index_meta()
    if body.get("ocr"):
        assessment["ocr"] = body["ocr"]

    if body.get("log"):
        source = (body.get("source_system") or "MANUAL_SCAN").upper()[:40]
        assessment["audit_id"] = store.record_decision(_db(), assessment, source)
    return jsonify(assessment)


@matching_bp.route("/noisy-records", methods=["GET"])
def noisy_records():
    db = _db()
    records = store.list_noisy_records(db, decision_status=request.args.get("status") or None,
                                       source_system=request.args.get("source") or None)
    return jsonify({"records": records, "summary": store.decision_summary(db)})


@matching_bp.route("/noisy-records/<int:record_id>", methods=["GET"])
def noisy_record_detail(record_id):
    db = _db()
    record = store.get_noisy_record(db, record_id)
    if not record:
        return jsonify({"status": "error", "error": f"Record {record_id} not found"}), 404
    method = _method_arg(request.args.get("method"))
    analysis = assess_record(_record_input(record), get_reference_index(), method)
    return jsonify({
        "record": record,
        "current_decision": store.current_decision(db, record_id),
        "analysis": analysis,
        "audit": store.list_audit(db, record_id=record_id)["entries"],
    })


@matching_bp.route("/noisy-records/<int:record_id>/review", methods=["POST"])
def review_record(record_id):
    body = request.get_json(force=True, silent=True) or {}
    action = (body.get("action") or "").upper()
    reviewer = (body.get("reviewer") or "").strip()
    if not reviewer:
        raise ValueError("reviewer is required for the audit trail")
    matched = None
    if action == "CORRECT":
        plate = normalize_plate(body.get("corrected_plate"))
        get_reference_index()
        matched = _index_cache["by_plate"].get(plate)
        if not matched:
            raise ValueError(f"corrected_plate '{plate}' is not held by any of the five agency databases")
    try:
        audit_id = store.record_review(_db(), record_id, action, reviewer[:60], body.get("note"),
                                       matched_vehicle=matched)
    except LookupError as e:
        return jsonify({"status": "error", "error": str(e)}), 404
    return jsonify({"status": "success", "audit_id": audit_id,
                    "current_decision": store.current_decision(_db(), record_id)})


@matching_bp.route("/cleanse", methods=["POST"])
def cleanse():
    """
    Run the rule engine over staged records. By default only unprocessed records are
    assessed; reprocess=true re-assesses records whose current decision came from the
    rule engine (human review decisions are never overwritten).
    """
    body = request.get_json(force=True, silent=True) or {}
    method = _method_arg(body.get("method"))
    reprocess = bool(body.get("reprocess"))
    only_ids = set(body.get("record_ids") or [])
    db = _db()
    index = get_reference_index()

    started = time.time()
    processed, skipped_reviewed, outcome = 0, 0, {}
    for rec in store.list_noisy_records(db):
        if only_ids and rec["record_id"] not in only_ids:
            continue
        if rec["audit_id"] is not None:
            if rec["decided_by"] != "RULE_ENGINE":
                skipped_reviewed += 1
                continue
            if not reprocess and not only_ids:
                continue
        assessment = assess_record(_record_input(rec), index, method)
        store.record_decision(db, assessment, rec["source_system"], record_id=rec["record_id"],
                              supersedes_audit_id=rec["audit_id"])
        processed += 1
        outcome[assessment["decision_status"]] = outcome.get(assessment["decision_status"], 0) + 1

    return jsonify({
        "status": "success",
        "method": method,
        "processed": processed,
        "skipped_human_reviewed": skipped_reviewed,
        "outcome": outcome,
        "duration_ms": round((time.time() - started) * 1000, 1),
        "summary": store.decision_summary(db),
    })


@matching_bp.route("/audit", methods=["GET"])
def audit():
    record_id = request.args.get("record_id", type=int)
    limit = max(1, min(request.args.get("limit", 50, type=int), 500))
    offset = max(0, request.args.get("offset", 0, type=int))
    return jsonify(store.list_audit(_db(), record_id=record_id, limit=limit, offset=offset))


def _run_and_store_evaluation():
    index = get_reference_index()
    db = _db()
    report = run_evaluation([v["plate"] for v in index])
    records = store.list_noisy_records(db)
    report["cleansing"] = evaluate_cleansing(records, index)
    run_id = store.save_evaluation(db, report)
    return store.latest_evaluation(db) if run_id else report


@matching_bp.route("/evaluation", methods=["GET"])
def evaluation():
    report = store.latest_evaluation(_db())
    if not report:
        return jsonify({"status": "not_run",
                        "error": "No evaluation run stored yet. POST /api/v1/matching/evaluation/run (~30s)."}), 404
    return jsonify(report)


@matching_bp.route("/evaluation/run", methods=["POST"])
def evaluation_run():
    if not _evaluation_lock.acquire(blocking=False):
        return jsonify({"status": "busy", "error": "An evaluation run is already in progress."}), 409
    try:
        return jsonify(_run_and_store_evaluation())
    finally:
        _evaluation_lock.release()


@matching_bp.route("/index/refresh", methods=["POST"])
def index_refresh():
    get_reference_index(force=True)
    return jsonify({"status": "success", "index": _index_meta()})


# ---------------------------------------------------------------------------
# Cleansing the live agency databases
# ---------------------------------------------------------------------------
def _annotate(anomalies):
    """Attach each row's latest logged decision; reviewer-resolved rows are marked resolved."""
    for a in anomalies:
        latest = agency_cleansing.latest_decision(_store_conn, a["source"], a["row_id"], a["original_value"])
        a["latest"] = ({k: latest[k] for k in ("change_id", "decision_status", "decided_by", "created_at", "reason")}
                       if latest else None)
        a["resolved"] = bool(latest and latest["decided_by"] != "RULE_ENGINE")
    return anomalies


def _scan_summary(anomalies):
    by_action = {}
    for a in anomalies:
        if not a["resolved"]:
            by_action[a["action"]] = by_action.get(a["action"], 0) + 1
    return {"anomalies": len(anomalies), "open": sum(1 for a in anomalies if not a["resolved"]),
            "resolved_by_reviewer": sum(1 for a in anomalies if a["resolved"]), "by_action": by_action}


@matching_bp.route("/agency/scan", methods=["GET"])
def agency_scan():
    started = time.time()
    method = _method_arg(request.args.get("method"))
    result = agency_cleansing.scan(_vahan_index(), _sql_runner, method)
    anomalies = _annotate(result["anomalies"])
    return jsonify({"anomalies": anomalies, "sources": result["sources"], "summary": _scan_summary(anomalies),
                    "registered_vehicles": len(_vahan_index()), "method": method,
                    "duration_ms": round((time.time() - started) * 1000, 1)})


@matching_bp.route("/agency/cleanse", methods=["POST"])
def agency_cleanse():
    body = request.get_json(force=True, silent=True) or {}
    method = _method_arg(body.get("method"))
    started = time.time()
    result = agency_cleansing.scan(_vahan_index(), _sql_runner, method)
    applied = agency_cleansing.apply(result["anomalies"], _store_conn, _sql_runner)
    touched = applied["changed_plates"] + [a["original_value"] for a in result["anomalies"] if a["action"] == "UPDATE"]
    _data_changed(touched)
    return jsonify({"status": "success", "method": method, **applied,
                    "scanned_sources": result["sources"],
                    "duration_ms": round((time.time() - started) * 1000, 1)})


@matching_bp.route("/agency/review", methods=["POST"])
def agency_review():
    body = request.get_json(force=True, silent=True) or {}
    action = (body.get("action") or "").upper()
    reviewer = (body.get("reviewer") or "").strip()
    if not reviewer:
        raise ValueError("reviewer is required for the audit trail")
    if body.get("row_id") is None:
        raise ValueError("row_id is required")
    matched = None
    if action == "CORRECT":
        plate = normalize_plate(body.get("corrected_plate"))
        matched = next((v for v in _vahan_index() if v["plate"] == plate), None)
        if not matched:
            raise ValueError(f"corrected_plate '{plate}' is not a registered (VAHAN) vehicle")
    try:
        result = agency_cleansing.review(_store_conn, (body.get("source") or "").upper(), int(body["row_id"]),
                                         body.get("original_value"), action, reviewer[:60], body.get("note"),
                                         matched_vehicle=matched, sql_runner=_sql_runner)
    except LookupError as e:
        return jsonify({"status": "error", "error": str(e)}), 409
    if result["applied"]:
        _data_changed([result["new_value"], body.get("original_value")])
    return jsonify({"status": "success", **result})


@matching_bp.route("/agency/changes", methods=["GET"])
def agency_changes():
    limit = max(1, min(request.args.get("limit", 50, type=int), 500))
    offset = max(0, request.args.get("offset", 0, type=int))
    return jsonify(agency_cleansing.list_changes(_store_conn, limit=limit, offset=offset))
