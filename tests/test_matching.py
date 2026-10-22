"""
Approximate vehicle matching & data cleansing.

Covers: plate normalisation, Jaro-Winkler / Levenshtein / OCR-weighted similarity,
candidate ranking, OCR confusion cases, the precision/recall/F1 algorithm
comparison, the ACCEPT / CORRECT / REJECT / REVIEW rule engine across the brief's
test scenarios (missing information, incorrect plates, conflicting details,
multiple matches), the append-only audit trail, and the Mediator API integration.
"""
import sqlite3

import pytest

import backend.config as bconfig
from matching import store
from matching.normalize import normalize_plate, is_valid_plate_format
from matching.similarity import (
    jaro, jaro_winkler, levenshtein_distance, levenshtein_similarity,
    ocr_weighted_distance, ocr_similarity, explain_edits,
)
from matching.matcher import find_candidates, DEFAULT_METHOD, METHODS
from matching.context import compare_attribute, compare_context
from matching.cleansing import assess_record
from matching.evaluation import run_evaluation, evaluate_cleansing
from matching.noisy_records import generate_noisy_records, SCENARIOS


@pytest.fixture(scope="module")
def index():
    return store.load_reference_index_from_db(bconfig.DB_VAHAN)


@pytest.fixture(scope="module")
def by_plate(index):
    return {v["plate"]: v for v in index}


@pytest.fixture(scope="module")
def evaluation_report(index):
    return run_evaluation([v["plate"] for v in index])


def _ctx(v, **overrides):
    rec = {"make": v["make"], "model": v["model"], "color": v["color"], "vehicle_type": v["vehicle_type"]}
    rec.update(overrides)
    return rec


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def test_normalize_uppercases_and_strips_separators():
    assert normalize_plate(" dl 01-ab.1001 ") == "DL01AB1001"
    assert normalize_plate("DL/01|AB_1001") == "DL01AB1001"
    assert normalize_plate(None) == ""
    assert normalize_plate(" - ") == ""


def test_plate_format_validation():
    assert is_valid_plate_format("DL01AB1001")
    assert is_valid_plate_format("MH12XY4821")
    assert is_valid_plate_format("22BH1234AA")
    assert not is_valid_plate_format("DL01AB1O01")   # letter in the number block
    assert not is_valid_plate_format("1234")


# ---------------------------------------------------------------------------
# Similarity algorithms
# ---------------------------------------------------------------------------
def test_jaro_winkler_reference_values():
    assert round(jaro("MARTHA", "MARHTA"), 4) == 0.9444
    assert round(jaro_winkler("MARTHA", "MARHTA"), 4) == 0.9611
    assert round(jaro_winkler("DWAYNE", "DUANE"), 4) == 0.84
    assert round(jaro_winkler("DIXON", "DICKSONX"), 4) == 0.8133
    assert jaro_winkler("ABC", "ABC") == 1.0
    assert jaro_winkler("ABC", "") == 0.0


def test_levenshtein_reference_values():
    assert levenshtein_distance("KITTEN", "SITTING") == 3
    assert levenshtein_distance("", "ABC") == 3
    assert levenshtein_distance("DL01AB1001", "DL01AB1001") == 0
    assert levenshtein_similarity("DL01AB1001", "DL01AB1002") == pytest.approx(0.9)


def test_ocr_weighted_distance_makes_glyph_confusions_cheap():
    assert ocr_weighted_distance("DL01AB1O01", "DL01AB1001") == 0.25   # O vs 0
    assert ocr_weighted_distance("DL0IAB1001", "DL01AB1001") == 0.25   # I vs 1
    assert ocr_weighted_distance("DL01AB1201", "DL01AB1001") == 1.0    # real substitution
    assert ocr_weighted_distance("DL01AB1010", "DL01AB1001") == 1.0    # adjacent transposition
    # Plain Levenshtein cannot tell a glyph confusion from a genuine error
    assert levenshtein_distance("DL01AB1O01", "DL01AB1001") == levenshtein_distance("DL01AB1O01", "DL01AB1101")
    assert ocr_similarity("DL01AB1O01", "DL01AB1001") > ocr_similarity("DL01AB1O01", "DL01AB1101")


def test_explain_edits_marks_ocr_confusions():
    edits = explain_edits("DL01A81OO4", "DL01AB1004")
    assert [(e["from"], e["to"]) for e in edits] == [("8", "B"), ("O", "0"), ("O", "0")]
    assert all(e["ocr_confusable"] for e in edits)


# ---------------------------------------------------------------------------
# Candidate search & ranking
# ---------------------------------------------------------------------------
def test_search_returns_all_plausible_candidates_ranked(index):
    cands = find_candidates("DL01AB1O01", index)
    assert len(cands) > 1, "approximate search must return more than the single best match"
    assert cands[0]["plate"] == "DL01AB1001" and cands[0]["rank"] == 1
    scores = [c["plate_score"] for c in cands]
    assert scores == sorted(scores, reverse=True)
    for c in cands:
        assert set(c["scores"]) == set(METHODS)
        assert c["plate_score"] >= 0.80


def test_search_threshold_and_exact_match(index):
    exact = find_candidates("dl-01-ab-1001", index, threshold=0.99)
    assert [c["plate"] for c in exact] == ["DL01AB1001"]
    assert exact[0]["exact"] is True
    assert find_candidates("MH12XY4821", index) == []


def test_ocr_confusion_cases_resolved_only_by_ocr_weighted(evaluation_report):
    cases = evaluation_report["ocr_confusion_cases"]
    assert all(c["methods"]["ocr_weighted"]["resolved"] for c in cases)
    o_vs_0 = next(c for c in cases if c["raw"] == "DL01AB1O01")
    assert not o_vs_0["methods"]["levenshtein"]["resolved"]
    assert o_vs_0["methods"]["levenshtein"]["tied_at_top"] > 1


# ---------------------------------------------------------------------------
# Algorithm comparison (precision / recall / F1)
# ---------------------------------------------------------------------------
def test_evaluation_metrics_are_consistent(evaluation_report):
    for m in evaluation_report["methods"].values():
        tp, fp, fn = m["tp"], m["fp"], m["fn"]
        assert m["precision"] == pytest.approx(tp / (tp + fp), abs=1e-4)
        assert m["recall"] == pytest.approx(tp / (tp + fn), abs=1e-4)
        assert m["f1"] == pytest.approx(2 * m["precision"] * m["recall"] / (m["precision"] + m["recall"]), abs=1e-3)
        assert len(m["curve"]) == 51


def test_selected_method_is_best_f1_and_is_the_default(evaluation_report):
    methods = evaluation_report["methods"]
    assert evaluation_report["selected_method"] == DEFAULT_METHOD
    assert methods["ocr_weighted"]["f1"] > methods["levenshtein"]["f1"]
    assert methods["ocr_weighted"]["f1"] > methods["jaro_winkler"]["f1"]
    assert methods["ocr_weighted"]["by_noise_type"]["ocr_1"] == 1.0
    assert methods["ocr_weighted"]["by_noise_type"]["ocr_2"] == 1.0


# ---------------------------------------------------------------------------
# Contextual evidence
# ---------------------------------------------------------------------------
def test_attribute_comparison_handles_synonyms_and_missing():
    assert compare_attribute("Gray", "Grey")["status"] == "MATCH"
    assert compare_attribute("Maruti", "Maruti Suzuki")["status"] == "MATCH"
    assert compare_attribute("TOYOTA", "Toyota")["status"] == "MATCH"
    assert compare_attribute("Honda", "Hyundai")["status"] == "MISMATCH"
    assert compare_attribute(None, "Toyota")["status"] == "MISSING"


def test_context_score_ignores_missing_attributes():
    ctx = compare_context({"make": "Kia", "model": None, "color": "Blue"},
                          {"make": "Kia", "model": "Seltos", "color": "Red", "vehicle_type": "SUV"})
    assert (ctx["matches"], ctx["mismatches"], ctx["missing"]) == (1, 1, 2)
    assert ctx["score"] == pytest.approx(0.30 / 0.50)


# ---------------------------------------------------------------------------
# Rule engine: the brief's test scenarios
# ---------------------------------------------------------------------------
def test_missing_plate_is_rejected(index):
    for raw in ("", None, " - "):
        a = assess_record({"plate": raw, "make": "Toyota"}, index)
        assert a["decision"] == "REJECT" and a["reason_code"] == "MISSING_PLATE"
    assert assess_record({"plate": "DL0"}, index)["reason_code"] == "UNREADABLE_PLATE"


def test_exact_plate_is_accepted(index, by_plate):
    v = by_plate["DL01AB1001"]
    a = assess_record({"plate": "dl 01 ab 1001", **_ctx(v)}, index)
    assert a["decision"] == "ACCEPT" and a["matched_vehicle_id"] == v["vehicle_id"]
    assert a["original_plate"] == "dl 01 ab 1001" and a["normalized_plate"] == "DL01AB1001"


def test_incorrect_plate_corrected_with_context(index, by_plate):
    v = by_plate["DL01AB1234"]
    a = assess_record({"plate": "DL01AB12340", **_ctx(v)}, index)
    assert a["decision"] == "CORRECT" and a["rule"] == "R7"
    assert a["corrected_plate"] == "DL01AB1234" and a["matched_vehicle_id"] == v["vehicle_id"]
    assert a["similarity_score"] >= 0.85 and a["reason"]


def test_ocr_only_correction_without_context(index):
    a = assess_record({"plate": "DL01AB1OO1"}, index)
    assert a["decision"] == "CORRECT" and a["rule"] == "R8" and a["corrected_plate"] == "DL01AB1001"
    a = assess_record({"plate": "DL0IAB1OO4"}, index)   # three glyph swaps, still unambiguous
    assert a["decision"] == "CORRECT" and a["corrected_plate"] == "DL01AB1004"
    # a glyph swap plus a dropped character is not a pure OCR confusion
    a = assess_record({"plate": "DL01AB1O0"}, index)
    assert a["decision"] == "REVIEW" and a["corrected_plate"] is None


def test_typo_without_context_is_not_auto_corrected(index):
    a = assess_record({"plate": "DL01AB12340"}, index)
    assert a["decision"] == "REVIEW" and a["corrected_plate"] is None
    assert "MISSING_CONTEXT" in a["flags"]


def test_conflicting_details_flagged(index, by_plate):
    real, other = by_plate["DL01AB1001"], by_plate["DL01AB1002"]
    a = assess_record({"plate": "DL01AB1001", **_ctx(other)}, index)
    assert a["decision"] == "REVIEW" and a["reason_code"] == "CONFLICTING_ATTRIBUTES"
    assert "CONFLICT" in a["flags"] and a["corrected_plate"] is None
    assert real["make"] != other["make"]


def test_misread_into_another_registered_plate_suggests_true_vehicle(index, by_plate):
    true_vehicle = by_plate["DL01AB1234"]
    a = assess_record({"plate": "DL01AB1235", **_ctx(true_vehicle)}, index)
    assert a["decision"] == "REVIEW" and a["rule"] == "R3"
    assert a["suggested_plate"] == "DL01AB1234"


def test_multiple_possible_matches_flagged_ambiguous(index, by_plate):
    a = assess_record({"plate": "DL01AB123"}, index)
    assert a["decision"] == "REVIEW" and a["reason_code"] == "AMBIGUOUS_MATCH"
    assert "AMBIGUOUS" in a["flags"] and a["candidate_count"] > 1

    # Ambiguous even with full context: two registered vehicles one edit from the
    # reading share make, model, colour and type.
    v1, v2 = by_plate["DL01AB2070"], by_plate["DL01AB2670"]
    assert _ctx(v1) == _ctx(v2)
    a = assess_record({"plate": "DL01AB270", **_ctx(v1)}, index)
    assert a["decision"] == "REVIEW" and a["reason_code"] == "AMBIGUOUS_MATCH"
    assert {"DL01AB2070", "DL01AB2670"} <= {c["plate"] for c in a["candidates"][:3]}


def test_single_attribute_is_not_enough_to_correct(index, by_plate):
    v = by_plate["DL01AB1234"]
    a = assess_record({"plate": "DL01AB123", "color": v["color"]}, index)
    assert a["decision"] == "REVIEW" and a["reason_code"] == "INSUFFICIENT_EVIDENCE"
    assert a["suggested_plate"] == "DL01AB1234" and a["corrected_plate"] is None


def test_unregistered_plate_rejected(index):
    a = assess_record({"plate": "MH12XY4821", "make": "Toyota"}, index)
    assert a["decision"] == "REJECT" and a["reason_code"] == "NO_PLAUSIBLE_MATCH"


def test_rule_engine_agrees_with_every_labelled_scenario(index):
    records = generate_noisy_records(index)
    assert len(records) == sum(c for _, c, _, _ in SCENARIOS)
    result = evaluate_cleansing(records, index)
    assert result["decision_agreement"] == 1.0, result["by_scenario"]
    assert result["correction_precision"] == 1.0   # never "corrects" to the wrong vehicle


# ---------------------------------------------------------------------------
# Audit trail & original-data preservation
# ---------------------------------------------------------------------------
@pytest.fixture()
def dq_db(tmp_path, index):
    path = str(tmp_path / "dq.db")
    store.init_store(path)
    store.seed_noisy_records(path, index)
    return path


def test_original_records_and_audit_trail_are_immutable(dq_db, index):
    rec = store.list_noisy_records(dq_db)[0]
    a = assess_record({"plate": rec["raw_plate"]}, index)
    store.record_decision(dq_db, a, rec["source_system"], record_id=rec["record_id"])
    with sqlite3.connect(dq_db) as conn:
        for sql in ("UPDATE dq_noisy_records SET raw_plate = 'X'",
                    "DELETE FROM dq_noisy_records",
                    "UPDATE dq_plate_corrections SET decision = 'ACCEPT'",
                    "DELETE FROM dq_plate_corrections"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(sql)


def test_review_appends_superseding_entry_and_keeps_original(dq_db, index):
    rec = next(r for r in store.list_noisy_records(dq_db) if r["scenario"] == "TYPO_MISSING_CONTEXT")
    a = assess_record({"plate": rec["raw_plate"]}, index)
    first = store.record_decision(dq_db, a, rec["source_system"], record_id=rec["record_id"])
    truth = next(v for v in index if v["plate"] == rec["ground_truth_plate"])
    second = store.record_review(dq_db, rec["record_id"], "CORRECT", "officer.k", "checked RC", matched_vehicle=truth)

    history = store.list_audit(dq_db, record_id=rec["record_id"])["entries"]
    assert [h["audit_id"] for h in history] == [second, first]
    assert history[0]["supersedes_audit_id"] == first
    assert history[0]["decided_by"] == "officer.k"
    assert history[0]["decision_status"] == "REVIEWED_CORRECTED"
    assert history[0]["matched_vehicle_id"] == truth["vehicle_id"]

    with store.connect(dq_db) as conn:
        row = conn.execute("SELECT * FROM v_dq_cleansed_records WHERE record_id = ?", (rec["record_id"],)).fetchone()
    assert row["original_plate"] == rec["raw_plate"]
    assert row["effective_plate"] == rec["ground_truth_plate"]


# ---------------------------------------------------------------------------
# Mediator API integration
# ---------------------------------------------------------------------------
@pytest.fixture()
def api(dq_db, monkeypatch, evaluation_report):
    from backend import matching_api
    from backend.mediator_app import app
    monkeypatch.setattr(bconfig, "DB_DATA_QUALITY", dq_db)
    monkeypatch.setattr(matching_api, "run_evaluation", lambda plates: dict(evaluation_report))
    monkeypatch.setattr(matching_api, "evaluate_cleansing", lambda records, index: {"records": len(records)})
    matching_api._store_ready["path"] = None
    matching_api.invalidate_index()
    yield app.test_client()
    matching_api._store_ready["path"] = None


def test_vahan_registry_index_endpoint():
    from backend.VAHAN.vahan_service import app as vahan_app
    data = vahan_app.test_client().get("/api/v1/registry/index").get_json()
    assert data["count"] == len(data["vehicles"]) > 0
    assert {"registration_id", "vehicle_registration_id", "vehicle_make", "color"} <= set(data["vehicles"][0])


def test_api_config_and_search(api):
    cfg = api.get("/api/v1/matching/config").get_json()
    assert cfg["default_method"] == DEFAULT_METHOD and cfg["index"]["size"] > 0
    assert len(cfg["rules"]) == 9

    res = api.post("/api/v1/matching/search", json={"plate": "DL01AB1O01", "log": True, "source_system": "ANPR_UPLOAD"})
    body = res.get_json()
    assert res.status_code == 200
    assert body["decision"] == "CORRECT" and body["corrected_plate"] == "DL01AB1001"
    assert body["candidates"][0]["scores"]["ocr_weighted"] == 0.975
    audit = api.get("/api/v1/matching/audit").get_json()
    assert audit["entries"][0]["audit_id"] == body["audit_id"]
    assert audit["entries"][0]["original_plate"] == "DL01AB1O01"
    assert audit["entries"][0]["source_system"] == "ANPR_UPLOAD"

    assert api.post("/api/v1/matching/search", json={"plate": "DL01AB1001", "method": "nope"}).status_code == 400


def test_api_cleanse_review_flow(api):
    res = api.post("/api/v1/matching/cleanse", json={}).get_json()
    assert res["processed"] == res["summary"]["staged_records"]
    assert set(res["outcome"]) == {"ACCEPTED", "CORRECTED", "REJECTED", "PENDING_REVIEW"}

    pending = api.get("/api/v1/matching/noisy-records?status=PENDING_REVIEW").get_json()["records"]
    target = next(r for r in pending if r["ground_truth_plate"])
    bad = api.post(f"/api/v1/matching/noisy-records/{target['record_id']}/review",
                   json={"action": "CORRECT", "reviewer": "officer.k", "corrected_plate": "ZZ99ZZ9999"})
    assert bad.status_code == 400
    ok = api.post(f"/api/v1/matching/noisy-records/{target['record_id']}/review",
                  json={"action": "CORRECT", "reviewer": "officer.k", "corrected_plate": target["ground_truth_plate"]})
    assert ok.get_json()["current_decision"]["decision_status"] == "REVIEWED_CORRECTED"

    other = next(r for r in pending if r["record_id"] != target["record_id"])
    again = api.post("/api/v1/matching/cleanse",
                     json={"reprocess": True, "record_ids": [target["record_id"], other["record_id"]]}).get_json()
    assert again["processed"] == 1 and again["skipped_human_reviewed"] == 1
    detail = api.get(f"/api/v1/matching/noisy-records/{target['record_id']}").get_json()
    assert detail["current_decision"]["decided_by"] == "officer.k"
    assert detail["record"]["raw_plate"] == target["raw_plate"]


def test_api_evaluation_run_and_fetch(api):
    assert api.get("/api/v1/matching/evaluation").status_code == 404
    run = api.post("/api/v1/matching/evaluation/run").get_json()
    assert run["selected_method"] == DEFAULT_METHOD
    assert run["cleansing"]["records"] > 0
    assert api.get("/api/v1/matching/evaluation").get_json()["run_id"] == run["run_id"]


def test_vehicle_lookup_suggests_matches_for_unregistered_plate(api):
    body = api.get("/api/v1/vehicles/DL01AB1O04?force_sync=true").get_json()
    assert body["vehicle"]["registration_status"] == "UNREGISTERED"
    suggestions = body["approximate_matches"]
    assert suggestions["candidates"][0]["plate"] == "DL01AB1004"
    assert suggestions["corrected_plate"] == "DL01AB1004"

    registered = api.get("/api/v1/vehicles/DL01AB1001?force_sync=true").get_json()
    assert registered["approximate_matches"] is None


def test_candidate_threshold_is_inclusive(index):
    # DL01AB2346 is exactly two edits from the reading (similarity 0.80): it must be listed
    plates = {c["plate"] for c in find_candidates("DL1AB2345", index, threshold=0.80)}
    assert {"DL01AB2345", "DL01AB2346"} <= plates
    assert ocr_similarity("DL1AB2345", "DL01AB2346", 0.80) == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# Score breakdown shown in the UI ("How the combined score was calculated")
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("record", [
    {"plate": "DL 1A B2345"},
    {"plate": "DL 1A B2345", "make": "Volkswagen", "model": "Polo", "color": "Black"},
    {"plate": "DLO1A8I0O4"},
    {"plate": "DL01AB1010", "make": "Toyota"},
    {"plate": "DL01AB12340", "color": "Silver"},
    {"plate": "DL01AB1001"},
])
def test_score_breakdown_agrees_with_the_scores(index, record):
    from matching.similarity import ocr_weighted_distance
    a = assess_record(record, index)
    assert a["score_breakdown"] is not None
    for c in a["candidates"]:
        b = c["breakdown"]
        edits = b["methods"]["ocr_weighted"]["edits"]
        assert sum(e["cost"] for e in edits) == pytest.approx(ocr_weighted_distance(a["normalized_plate"], c["plate"]))
        for method in METHODS:
            assert b["methods"][method]["value"] == pytest.approx(c["scores"][method], abs=1e-3)
        assert b["plate_similarity"]["value"] == c["plate_score"]
        if b["context"]:
            expected = 0.65 * c["plate_score"] + 0.35 * b["context"]["value"]
        else:
            expected = c["plate_score"]
        assert b["combined"]["value"] == pytest.approx(expected, abs=1e-3) == pytest.approx(c["combined_score"], abs=1e-3)


def test_score_breakdown_explains_the_dl1ab2345_example(index):
    b = assess_record({"plate": "DL 1A B2345"}, index)["score_breakdown"]
    edits = b["plate_similarity"]["edits"]
    assert [(e["to"], e["kind"], e["cost"]) for e in edits] == [("0", "missing character", 1.0)]
    assert b["plate_similarity"]["formula"] == "1 − 1 ÷ 10 = 0.900"
    assert b["context"] is None and "combined = plate similarity = 0.900" in b["combined"]["formula"]
    assert "2 × 0.1" in b["methods"]["jaro_winkler"]["formula"] and b["methods"]["jaro_winkler"]["value"] == 0.9733
