"""
Verdict push-down: each agency computes the answer to the Mediator's question itself, the
answers equal what the Mediator used to compute centrally from the raw rows, and each role
receives only the details it needs.
"""
from flask import g

from backend import security
from backend.mediator_app import app as mediator_app, fetch_all_agency_apis, merge_to_global_dossier
from backend.IIB.iib_service import app as iib_app
from backend.VAHAN.vahan_service import app as vahan_app
from backend.POLICE_CCTNS.cctns_service import app as police_app
from backend.ANPR_CAMERA.anpr_service import app as anpr_app
from backend.ECHALLAN.echallan_service import app as echallan_app
import backend.config as config
from ministry.rules import (compute_insurance_status, compute_suspicion_status, compute_risk_level,
                            compute_ministry_requirement, parse_date)

PLATES = [f"DL01AB{1000 + n}" for n in list(range(1, 11)) + list(range(20, 2001, 25))] + ["MH12ZZ9999"]


def _old_central_dossier(plate):
    """What the Mediator used to do: fetch the raw rows and evaluate them itself."""
    admin = {app: security.signed_test_client(app, "ADMIN") for app in (iib_app, vahan_app, police_app, anpr_app)}
    policies = admin[iib_app].get(f"/api/v1/policies/{plate}").get_json().get("policies", [])
    vres = admin[vahan_app].get(f"/api/v1/rc/{plate}")
    rc = vres.get_json().get("rc_details")
    record = admin[police_app].get(f"/api/v1/records/{plate}").get_json().get("record")
    captures = admin[anpr_app].get(f"/api/v1/captures/{plate}").get_json().get("captures", [])
    on = parse_date(captures[0]["captured_timestamp"]) if captures else config.SIMULATION_TODAY
    ins = compute_insurance_status(policies, on)["status"]
    sus = compute_suspicion_status(record)
    if rc:
        reg = rc["registration_status"]
        exp = parse_date(rc["registration_expiry_date"])
        if exp and exp < config.SIMULATION_TODAY:
            reg = "EXPIRED"
    else:
        reg = "UNREGISTERED"
    seen = bool(captures)
    return {"insurance_status": ins, "suspicion_status": sus, "registration_status": reg,
            "risk_level": compute_risk_level(ins, sus, seen),
            "ministry_report_reasons": compute_ministry_requirement(ins, sus, reg, seen)["reasons"],
            "make": (rc or {}).get("vehicle_make") or (captures[0]["detected_make"] if captures else None),
            "capture_time": captures[0]["captured_timestamp"] if captures else None}


def _new_dossier(plate, role="ADMIN"):
    with mediator_app.test_request_context():
        g.role = role
        results = fetch_all_agency_apis(plate)
        return results, merge_to_global_dossier(plate, results)


def test_agency_answers_equal_the_old_central_evaluation():
    for plate in PLATES:
        _, new = _new_dossier(plate)
        old = _old_central_dossier(plate)
        assert {k: new[k] for k in old} == old, plate


def test_mediator_asks_questions_not_for_rows():
    results, dossier = _new_dossier("DL01AB1004", role="POLICE")
    for key, res in results.items():
        assert "/api/v1/verdict/" in res["url"] and res["status"] == 200, key
        assert "question" in res["data"]
    assert "?on=" in results["iib"]["url"]            # IIB evaluates on the date ANPR last saw the car
    assert dossier["insurance_status"] == "INSURED" and dossier["suspicion_status"] == "STOLEN"
    assert dossier["risk_level"] == "CRITICAL"


def test_each_role_gets_only_what_it_needs():
    police = security.signed_test_client(iib_app, "POLICE").get("/api/v1/verdict/DL01AB1010").get_json()
    insurer = security.signed_test_client(iib_app, "INSURER").get("/api/v1/verdict/DL01AB1010").get_json()
    assert police["insurance_status"] == insurer["insurance_status"] == "INSURED"
    assert "policies" not in police and "policy_number" not in police and "claims" not in police
    assert len(insurer["policies"]) == 3 and insurer["policy_number"]

    fir_for_insurer = security.signed_test_client(police_app, "INSURER").get("/api/v1/verdict/DL01AB1004").get_json()
    fir_for_police = security.signed_test_client(police_app, "POLICE").get("/api/v1/verdict/DL01AB1004").get_json()
    assert fir_for_insurer["suspicion_status"] == "STOLEN" and "firs" not in fir_for_insurer
    assert fir_for_police["firs"][0]["fir_no"] == "FIR5004"

    anpr = security.signed_test_client(anpr_app, "INSURER").get("/api/v1/verdict/DL01AB1004").get_json()
    assert anpr["seen_on_road"] and "captures" not in anpr
    challan = security.signed_test_client(echallan_app, "INSURER").get("/api/v1/verdict/DL01AB1004").get_json()
    assert "challans" not in challan and challan["challan_count"] >= 1


def test_raw_rows_are_need_to_know():
    assert security.signed_test_client(iib_app, "POLICE").get("/api/v1/policies/DL01AB1001").status_code == 403
    assert security.signed_test_client(police_app, "INSURER").get("/api/v1/records/DL01AB1004").status_code == 403
    assert security.signed_test_client(anpr_app, "INSURER").get("/api/v1/captures/DL01AB1004").status_code == 403
    assert security.signed_test_client(echallan_app, "INSURER").get("/api/v1/challans/DL01AB1004").status_code == 403
    assert security.signed_test_client(anpr_app, "POLICE").get("/api/v1/captures").status_code == 403   # full list
    assert security.signed_test_client(iib_app, "INSURER").get("/api/v1/policies/DL01AB1001").status_code == 200


def test_unregistered_plate_is_an_answer_not_an_error():
    res = security.signed_test_client(vahan_app, "INSURER").get("/api/v1/verdict/MH12ZZ9999")
    assert res.status_code == 200 and res.get_json()["registration_status"] == "UNREGISTERED"
