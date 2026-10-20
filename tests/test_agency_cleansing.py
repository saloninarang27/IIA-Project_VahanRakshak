"""
Cleansing the live recorded data in the five agency databases.

Each test works on temporary copies of the agency databases and inserts the kind of
noisy records an evaluator would add (misread plates, typos, formatting, unregistered
plates, a suspicious registry entry), then checks what the cleanser writes back.
"""
import shutil
import sqlite3

import pytest

import backend.config as bconfig
from backend import matching_api
from backend.mediator_app import app as mediator_app
from matching import agency_cleansing as ac
from matching import store
from matching.sources import SOURCES, build_reference_index, _read_local

DB_FILES = {"VAHAN": bconfig.DB_VAHAN, "IIB": bconfig.DB_IIB, "POLICE": bconfig.DB_POLICE,
            "ANPR": bconfig.DB_ANPR, "ECHALLAN": bconfig.DB_ECHALLAN}


@pytest.fixture
def env(tmp_path):
    copies = {}
    for key, path in DB_FILES.items():
        copies[key] = str(tmp_path / f"{key}.db")
        shutil.copy(path, copies[key])

    def runner(key, query):
        conn = sqlite3.connect(copies[key])
        try:
            cur = conn.execute(query)
            if cur.description:
                return {"columns": [c[0] for c in cur.description], "rows": [list(r) for r in cur.fetchall()]}
            conn.commit()
            return {"columns": ["affected_rows"], "rows": [[cur.rowcount]]}
        finally:
            conn.close()

    def sql(key, query, *params):
        conn = sqlite3.connect(copies[key])
        try:
            rows = conn.execute(query, params).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    def vahan_index():
        rows = {s["key"]: {"rows": _read_local(copies[s["key"]], s["fallback_sql"])} for s in SOURCES}
        return [v for v in build_reference_index(rows) if v["in_vahan"]]

    dq = str(tmp_path / "dq.db")
    store.init_store(dq)
    return {"runner": runner, "sql": sql, "vahan_index": vahan_index, "conn": lambda: store.connect(dq), "dq": dq}


def _vehicle(env, plate):
    return env["sql"]("VAHAN", "SELECT vehicle_make, vehicle_model, color, vehicle_type FROM vehicle_registration "
                               "WHERE vehicle_registration_id = ?", plate)[0]


def _insert_policy(env, plate, ref):
    env["sql"]("IIB", "INSERT INTO insurance_policy (registration_no, insurer_name, policy_number, policy_start_date, "
                      "policy_expiry_date, insurance_status, policy_type) VALUES (?, 'Test Insurer', ?, '2026-01-01', "
                      "'2027-01-01', 'ACTIVE', 'Comprehensive')", plate, ref)
    return env["sql"]("IIB", "SELECT policy_id FROM insurance_policy WHERE policy_number = ?", ref)[0][0]


def _insert_sighting(env, plate, make=None, model=None, color=None, vtype=None):
    env["sql"]("ANPR", "INSERT INTO vehicle_capture (plate_number, captured_timestamp, camera_id, location, vehicle_type, "
                       "detected_make, detected_model, detected_color, confidence_score) "
                       "VALUES (?, '2026-09-14 10:00:00', 'Camera-01', 'TEST', ?, ?, ?, ?, 0.9)",
               plate, vtype, make, model, color)
    return env["sql"]("ANPR", "SELECT MAX(capture_id) FROM vehicle_capture")[0][0]


def _by_row(scan, source, row_id):
    return next(a for a in scan["anomalies"] if a["source"] == source and a["row_id"] == row_id)


def test_clean_databases_have_no_anomalies(env):
    assert ac.scan(env["vahan_index"](), env["runner"])["anomalies"] == []


def test_ocr_misread_in_insurance_is_corrected_in_place(env):
    row = _insert_policy(env, "DL01AB1O01", "POL-T1")
    scan = ac.scan(env["vahan_index"](), env["runner"])
    a = _by_row(scan, "IIB", row)
    assert (a["kind"], a["action"], a["new_value"]) == ("UNREGISTERED_PLATE", "UPDATE", "DL01AB1001")

    result = ac.apply(scan["anomalies"], env["conn"], env["runner"])
    assert result["outcome"] == {"CORRECTED": 1} and not result["errors"]
    assert env["sql"]("IIB", "SELECT registration_no FROM insurance_policy WHERE policy_id = ?", row)[0][0] == "DL01AB1001"
    log = ac.list_changes(env["conn"])["entries"][0]
    assert (log["original_value"], log["new_value"], log["applied"]) == ("DL01AB1O01", "DL01AB1001", 1)
    # nothing left to cleanse, and re-running changes nothing
    assert ac.scan(env["vahan_index"](), env["runner"])["anomalies"] == []


def test_camera_row_corrected_using_its_own_make_model_colour(env):
    make, model, color, vtype = _vehicle(env, "DL01AB1234")
    row = _insert_sighting(env, "DL01AB124", make, model, color, vtype)   # digit lost
    a = _by_row(ac.scan(env["vahan_index"](), env["runner"]), "ANPR", row)
    assert a["action"] == "UPDATE" and a["new_value"] == "DL01AB1234"
    assert a["context_from"] == "ANPR row" and a["assessment"]["rule"] == "R7"


def test_insurance_row_borrows_context_from_camera_sighting_of_same_reading(env):
    make, model, color, vtype = _vehicle(env, "DL01AB1234")
    _insert_sighting(env, "DL01AB124", make, model, color, vtype)
    row = _insert_policy(env, "DL01AB124", "POL-T2")
    a = _by_row(ac.scan(env["vahan_index"](), env["runner"]), "IIB", row)
    assert a["context_from"] == "ANPR sighting of the same reading"
    assert a["action"] == "UPDATE" and a["new_value"] == "DL01AB1234"


def test_typo_without_any_context_is_flagged_not_changed(env):
    row = _insert_policy(env, "DL01AB124", "POL-T3")
    scan = ac.scan(env["vahan_index"](), env["runner"])
    a = _by_row(scan, "IIB", row)
    assert a["action"] == "REVIEW" and a["new_value"] is None
    ac.apply(scan["anomalies"], env["conn"], env["runner"])
    assert env["sql"]("IIB", "SELECT registration_no FROM insurance_policy WHERE policy_id = ?", row)[0][0] == "DL01AB124"
    # flagging twice logs once
    ac.apply(ac.scan(env["vahan_index"](), env["runner"])["anomalies"], env["conn"], env["runner"])
    assert ac.list_changes(env["conn"])["total"] == 1


def test_reviewer_correction_writes_back_and_is_audited(env):
    row = _insert_policy(env, "DL01AB124", "POL-T4")
    ac.apply(ac.scan(env["vahan_index"](), env["runner"])["anomalies"], env["conn"], env["runner"])
    target = next(v for v in env["vahan_index"]() if v["plate"] == "DL01AB1234")
    result = ac.review(env["conn"], "IIB", row, "DL01AB124", "CORRECT", "officer.k", "checked RC copy",
                       matched_vehicle=target, sql_runner=env["runner"])
    assert result["applied"]
    assert env["sql"]("IIB", "SELECT registration_no FROM insurance_policy WHERE policy_id = ?", row)[0][0] == "DL01AB1234"
    entries = ac.list_changes(env["conn"])["entries"]
    assert [e["decision_status"] for e in entries] == ["REVIEWED_CORRECTED", "PENDING_REVIEW"]
    assert entries[0]["supersedes_change_id"] == entries[1]["change_id"]


def test_reviewer_accepting_original_stops_further_flagging(env):
    row = _insert_policy(env, "DL01AB124", "POL-T5")
    ac.apply(ac.scan(env["vahan_index"](), env["runner"])["anomalies"], env["conn"], env["runner"])
    ac.review(env["conn"], "IIB", row, "DL01AB124", "ACCEPT_ORIGINAL", "officer.k", sql_runner=env["runner"])
    result = ac.apply(ac.scan(env["vahan_index"](), env["runner"])["anomalies"], env["conn"], env["runner"])
    assert result["skipped_reviewed"] == 1 and result["outcome"] == {}


def test_unregistered_plate_is_flagged_never_deleted(env):
    env["sql"]("ECHALLAN", "INSERT INTO ministry_report (vehicle_identifier, report_type, report_reason, severity, "
                           "report_status, submitted_at, ministry_reference) VALUES ('MH12XY4821', 'TEST', 'test', "
                           "'HIGH', 'SUBMITTED', '2026-09-14', 'MOT-TEST-1')")
    scan = ac.scan(env["vahan_index"](), env["runner"])
    a = next(x for x in scan["anomalies"] if x["original_value"] == "MH12XY4821")
    assert a["action"] == "REJECT"
    assert ac.apply(scan["anomalies"], env["conn"], env["runner"])["outcome"] == {"FLAGGED_REJECTED": 1}
    assert env["sql"]("ECHALLAN", "SELECT COUNT(*) FROM ministry_report WHERE vehicle_identifier = 'MH12XY4821'")[0][0] == 1


def test_formatting_noise_is_standardised(env):
    env["sql"]("POLICE", "UPDATE theft_scrap_record SET vehicle_no = 'dl 01-ab 1004' WHERE vehicle_no = 'DL01AB1004'")
    scan = ac.scan(env["vahan_index"](), env["runner"])
    a = next(x for x in scan["anomalies"] if x["source"] == "POLICE")
    assert (a["kind"], a["new_value"]) == ("NON_CANONICAL_FORMAT", "DL01AB1004")
    assert ac.apply(scan["anomalies"], env["conn"], env["runner"])["outcome"] == {"STANDARDIZED": 1}
    assert env["sql"]("POLICE", "SELECT COUNT(*) FROM theft_scrap_record WHERE vehicle_no = 'DL01AB1004'")[0][0] == 1


def test_suspicious_registry_entry_is_flagged_but_never_auto_changed(env):
    make, model, color, vtype = _vehicle(env, "DL01AB1005")
    env["sql"]("VAHAN", "INSERT INTO vehicle_registration (vehicle_registration_id, owner_id, owner_name, registration_date, "
                        "registration_expiry_date, vehicle_make, vehicle_model, vehicle_type, color, registration_status) "
                        "VALUES ('DL01AB1O05', 'OWN9', 'Test Owner', '2026-01-01', '2030-01-01', ?, ?, ?, ?, 'ACTIVE')",
               make, model, vtype, color)
    scan = ac.scan(env["vahan_index"](), env["runner"])
    a = next(x for x in scan["anomalies"] if x["source"] == "VAHAN")
    assert a["kind"] == "SUSPECT_REGISTRATION" and a["action"] == "REVIEW"
    assert a["assessment"]["matched_plate"] == "DL01AB1005"
    ac.apply(scan["anomalies"], env["conn"], env["runner"])
    assert env["sql"]("VAHAN", "SELECT COUNT(*) FROM vehicle_registration WHERE vehicle_registration_id = 'DL01AB1O05'")[0][0] == 1


def test_deleted_registration_turns_dependent_records_into_anomalies(env):
    env["sql"]("VAHAN", "DELETE FROM vehicle_registration WHERE vehicle_registration_id = 'DL01AB1003'")
    sources = {a["source"] for a in ac.scan(env["vahan_index"](), env["runner"])["anomalies"]
               if a["original_value"] == "DL01AB1003"}
    assert "ANPR" in sources        # the camera still has sightings of a now-unregistered plate


def test_api_scan_cleanse_review_flow(env, monkeypatch):
    monkeypatch.setattr(matching_api, "_sql_runner", env["runner"])
    monkeypatch.setattr(matching_api, "_vahan_index", env["vahan_index"])
    monkeypatch.setattr(bconfig, "DB_DATA_QUALITY", env["dq"])
    monkeypatch.setattr(matching_api, "_store_ready", {"path": None})
    stale = []
    monkeypatch.setattr(matching_api, "_on_vehicles_changed", stale.extend)
    api = mediator_app.test_client()

    fix_row = _insert_policy(env, "DL01AB1O01", "POL-T6")
    review_row = _insert_policy(env, "DL01AB124", "POL-T7")
    scan = api.get("/api/v1/matching/agency/scan").get_json()
    assert scan["summary"]["by_action"] == {"UPDATE": 1, "REVIEW": 1}

    done = api.post("/api/v1/matching/agency/cleanse", json={}).get_json()
    assert done["outcome"] == {"CORRECTED": 1, "PENDING_REVIEW": 1}
    assert "DL01AB1001" in stale     # corrected vehicle's cached dossier expired

    res = api.post("/api/v1/matching/agency/review", json={
        "source": "IIB", "row_id": review_row, "original_value": "DL01AB124", "action": "CORRECT",
        "corrected_plate": "DL01AB1234", "reviewer": "officer.k"})
    assert res.status_code == 200 and res.get_json()["applied"]
    bad = api.post("/api/v1/matching/agency/review", json={
        "source": "IIB", "row_id": review_row, "original_value": "DL01AB124", "action": "CORRECT",
        "corrected_plate": "ZZ00ZZ0000", "reviewer": "officer.k"})
    assert bad.status_code == 400
    assert api.get("/api/v1/matching/agency/scan").get_json()["summary"]["anomalies"] == 0
    assert api.get("/api/v1/matching/agency/changes").get_json()["total"] == 3
    assert env["sql"]("IIB", "SELECT registration_no FROM insurance_policy WHERE policy_id = ?", fix_row)[0][0] == "DL01AB1001"
