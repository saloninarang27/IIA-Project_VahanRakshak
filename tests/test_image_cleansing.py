"""
Cleansing recorded agency data with a scanned plate image as evidence (rubric 2:
"cleanse the recorded data w.r.t. the image data and other contextual information").

The scan (OCR reading + make / model / colour / type seen in the photo) must resolve to
one registered vehicle; the noisy rows that refer to it are then corrected only when the
photo supplies the missing evidence, and never against a row's own contradicting evidence.
"""
from backend import matching_api
from backend.mediator_app import app as mediator_app
import backend.config as bconfig
from matching import agency_cleansing as ac

from tests.test_agency_cleansing import env, _vehicle, _insert_policy, _insert_sighting  # noqa: F401 (fixture)


def _photo(env, plate, reading=None):
    make, model, color, vtype = _vehicle(env, plate)
    return {"plate": reading or plate, "make": make, "model": model, "color": color, "vehicle_type": vtype}


def _related(result, source, row_id):
    return next(a for a in result["related"] if a["source"] == source and a["row_id"] == row_id)


def test_photo_attributes_resolve_a_typo_the_row_alone_cannot(env):
    row = _insert_policy(env, "DL01AB12340", "POL-I1")
    alone = ac.scan(env["vahan_index"](), env["runner"])
    assert next(a for a in alone["anomalies"] if a["row_id"] == row and a["source"] == "IIB")["action"] == "REVIEW"

    result = ac.scan_with_image(_photo(env, "DL01AB1234"), env["vahan_index"](), env["runner"], image_name="car.jpg")
    assert result["vehicle"] == "DL01AB1234"
    a = _related(result, "IIB", row)
    assert a["action"] == "UPDATE" and a["new_value"] == "DL01AB1234"
    assert a["assessment"]["rule"].startswith("IMG2") and a["context_from"] == "scanned image car.jpg"

    applied = ac.apply(result["related"], env["conn"], env["runner"])
    assert applied["outcome"] == {"CORRECTED": 1}
    assert env["sql"]("IIB", "SELECT registration_no FROM insurance_policy WHERE policy_id = ?", row)[0][0] == "DL01AB1234"
    log = ac.list_changes(env["conn"])["entries"][0]
    assert (log["original_value"], log["new_value"], log["context_from"]) == ("DL01AB12340", "DL01AB1234", "scanned image car.jpg")


def test_row_with_the_same_misreading_as_the_photo_is_corrected(env):
    row = _insert_policy(env, "DL01AB123", "POL-I2")
    result = ac.scan_with_image(_photo(env, "DL01AB1234", reading="DL01AB123"), env["vahan_index"](), env["runner"])
    assert result["scan"]["decision"] == "CORRECT" and result["vehicle"] == "DL01AB1234"
    a = _related(result, "IIB", row)
    assert a["action"] == "UPDATE" and a["new_value"] == "DL01AB1234" and a["assessment"]["rule"] == "IMG1"


def test_noisy_rows_about_other_vehicles_are_left_alone(env):
    mine = _insert_policy(env, "DL01AB1O01", "POL-I3")
    other = _insert_policy(env, "DL01AB2O07", "POL-I4")
    result = ac.scan_with_image(_photo(env, "DL01AB1001"), env["vahan_index"](), env["runner"])
    rows = {(a["source"], a["row_id"]) for a in result["related"]}
    assert ("IIB", mine) in rows and ("IIB", other) not in rows


def test_row_own_contradicting_evidence_beats_the_photo(env):
    # A camera saw reading DL01AB123 on a car that is NOT the photographed DL01AB1234
    other = _vehicle(env, "DL01AB1002")
    cap = _insert_sighting(env, "DL01AB123", *other)
    result = ac.scan_with_image(_photo(env, "DL01AB1234", reading="DL01AB123"), env["vahan_index"](), env["runner"])
    a = _related(result, "ANPR", cap)
    assert a["action"] != "UPDATE" and a["image_evidence"].startswith("kept: the row has its own evidence")


def test_unresolved_scan_changes_nothing(env):
    _insert_policy(env, "DL01AB123", "POL-I5")
    result = ac.scan_with_image({"plate": "DL01AB123"}, env["vahan_index"](), env["runner"])
    assert result["vehicle"] is None and result["related"] == []
    assert result["scan"]["decision"] == "REVIEW"


def test_api_previews_then_applies(env, monkeypatch):
    monkeypatch.setattr(matching_api, "_sql_runner", env["runner"])
    monkeypatch.setattr(matching_api, "_vahan_index", env["vahan_index"])
    monkeypatch.setattr(bconfig, "DB_DATA_QUALITY", env["dq"])
    monkeypatch.setattr(matching_api, "_store_ready", {"path": None})
    stale = []
    monkeypatch.setattr(matching_api, "_on_vehicles_changed", stale.extend)
    api = mediator_app.test_client()
    row = _insert_policy(env, "DL01AB12340", "POL-I6")
    body = {**_photo(env, "DL01AB1234"), "image_name": "car.jpg"}

    preview = api.post("/api/v1/matching/agency/image-cleanse", json=body).get_json()
    assert preview["vehicle"] == "DL01AB1234" and preview["applied"] is None
    assert env["sql"]("IIB", "SELECT registration_no FROM insurance_policy WHERE policy_id = ?", row)[0][0] == "DL01AB12340"

    done = api.post("/api/v1/matching/agency/image-cleanse", json={**body, "apply": True}).get_json()
    assert done["applied"]["outcome"] == {"CORRECTED": 1}
    assert env["sql"]("IIB", "SELECT registration_no FROM insurance_policy WHERE policy_id = ?", row)[0][0] == "DL01AB1234"
    assert "DL01AB1234" in stale
