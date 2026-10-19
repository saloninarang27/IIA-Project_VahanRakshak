"""
Approximate Vehicle Matching & Data Cleansing API (Mediator blueprint, /api/v1/matching).

The reference index of registered vehicles is pulled from the MoRTH VAHAN
microservice (/api/v1/registry/index) through the Mediator's federated fetcher and
cached for CACHE_TTL_SECONDS. If VAHAN is unreachable, the local VAHAN replica file
is used and the response says so.

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
"""
import os
import threading
import time
from datetime import datetime

from flask import Blueprint, jsonify, request

import backend.config as config
from matching import store
from matching.cleansing import assess_record, RULES, CORRECTION_THRESHOLD, OCR_ONLY_CORRECTION_THRESHOLD, AMBIGUITY_MARGIN
from matching.context import CONTEXT_ATTRIBUTES
from matching.evaluation import run_evaluation, evaluate_cleansing
from matching.matcher import METHODS, METHOD_LABELS, DEFAULT_METHOD, DEFAULT_CANDIDATE_THRESHOLD
from matching.normalize import normalize_plate
from matching.ocr import extract_plate_text, available_engines, OCRUnavailable

matching_bp = Blueprint("matching", __name__, url_prefix="/api/v1/matching")

_fetch = None
_index_lock = threading.Lock()
_index_cache = {"vehicles": None, "by_plate": {}, "loaded_at": 0.0, "source": None, "loaded_at_iso": None}
_store_ready = {"path": None}
_evaluation_lock = threading.Lock()


class IndexUnavailable(RuntimeError):
    pass


def configure(fetch_service):
    """Inject the Mediator's federated HTTP fetcher (avoids a circular import)."""
    global _fetch
    _fetch = fetch_service


def invalidate_index():
    with _index_lock:
        _index_cache["loaded_at"] = 0.0


def get_reference_index(force=False):
    with _index_lock:
        fresh = time.time() - _index_cache["loaded_at"] < config.CACHE_TTL_SECONDS
        if _index_cache["vehicles"] is not None and fresh and not force:
            return _index_cache["vehicles"]

        vehicles, source = None, None
        if _fetch is not None:
            res = _fetch(f"{config.URL_VAHAN}/api/v1/registry/index", "MoRTH VAHAN (Registry Index)")
            if res["status"] == 200 and res.get("data"):
                vehicles = store.reference_index_from_rows(res["data"]["vehicles"])
                source = "VAHAN_API"
        if vehicles is None and os.path.exists(config.DB_VAHAN):
            vehicles = store.load_reference_index_from_db(config.DB_VAHAN)
            source = "LOCAL_VAHAN_REPLICA"
        if vehicles is None:
            raise IndexUnavailable("VAHAN registry is unreachable and no local replica exists.")

        _index_cache.update({
            "vehicles": vehicles,
            "by_plate": {v["plate"]: v for v in vehicles},
            "loaded_at": time.time(),
            "loaded_at_iso": datetime.now().isoformat(sep=" ", timespec="seconds"),
            "source": source,
        })
        return vehicles


def _index_meta():
    return {"size": len(_index_cache["vehicles"] or []), "source": _index_cache["source"],
            "loaded_at": _index_cache["loaded_at_iso"]}


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
    """Used by the vehicle lookup: approximate matches for a plate VAHAN does not know."""
    assessment = assess_record({"plate": plate}, get_reference_index())
    return {
        "decision": assessment["decision"],
        "decision_status": assessment["decision_status"],
        "reason": assessment["reason"],
        "corrected_plate": assessment["corrected_plate"],
        "suggested_plate": assessment["suggested_plate"],
        "candidate_count": assessment["candidate_count"],
        "candidates": [{k: c[k] for k in ("rank", "vehicle_id", "plate", "make", "model", "color",
                                          "plate_score", "scores")}
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
            raise ValueError(f"corrected_plate '{plate}' is not a registered vehicle in VAHAN")
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
