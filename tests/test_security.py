"""
Need-to-know security (phase-2 feedback): nobody but the Mediator can call an agency, roles are
enforced by the agency itself, personal data is masked, every access is audited append-only, and
a plate search never moves a whole agency plate list.
"""
import json
import sqlite3

from flask.testing import FlaskClient

from backend import security
from backend.mediator_app import app as mediator_app
from backend.VAHAN.vahan_service import app as vahan_app, DB_PATH as VAHAN_DB
from backend.IIB.iib_service import app as iib_app
from backend.matching_api import candidate_index
from matching.cleansing import assess_record
from matching.sources import fetch_source_rows, build_reference_index
from matching.similarity import ocr_similarity
from tests.conftest import TEST_PASSWORDS


def plain(app):
    return FlaskClient(app, app.response_class)


def last_audit(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT role, path, status, outcome FROM access_audit ORDER BY audit_id DESC LIMIT 1").fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------------------- agency side
def test_unsigned_request_to_agency_is_rejected_and_audited():
    res = plain(vahan_app).get("/api/v1/rc/DL01AB1001")
    assert res.status_code == 401
    role, path, status, outcome = last_audit(VAHAN_DB)
    assert status == 401 and outcome.startswith("DENIED") and path == "/api/v1/rc/DL01AB1001"


def test_health_stays_public():
    assert plain(vahan_app).get("/api/v1/health").status_code == 200


def test_tampered_and_replayed_requests_are_rejected():
    body = json.dumps({"query": "SELECT 1"}).encode()
    headers = security.signed_headers("POST", "/api/v1/internal/execute-sql", body, "ADMIN")
    client = plain(iib_app)
    tampered = json.dumps({"query": "DELETE FROM insurance_policy"}).encode()
    assert client.post("/api/v1/internal/execute-sql", data=tampered, headers=headers,
                       content_type="application/json").status_code == 401
    # a signature over a role the caller does not have cannot be produced without the secret
    forged = dict(headers, **{"X-Fed-Role": "ADMIN", "X-Fed-Caller": "attacker"})
    assert client.post("/api/v1/internal/execute-sql", data=body, headers=forged,
                       content_type="application/json").status_code == 401
    fresh = security.signed_headers("POST", "/api/v1/internal/execute-sql", body, "ADMIN")
    assert client.post("/api/v1/internal/execute-sql", data=body, headers=fresh,
                       content_type="application/json").status_code == 200
    assert client.post("/api/v1/internal/execute-sql", data=body, headers=fresh,
                       content_type="application/json").status_code == 401   # replay


def test_bulk_endpoints_and_raw_sql_need_admin():
    for role in ("POLICE", "INSURER"):
        client = security.signed_test_client(vahan_app, role)
        assert client.get("/api/v1/registry/index").status_code == 403
        assert client.post("/api/v1/internal/execute-sql", json={"query": "SELECT 1"}).status_code == 403
    assert security.signed_test_client(vahan_app, "ADMIN").get("/api/v1/registry/index").status_code == 200


def test_personal_data_is_masked_unless_police_or_admin():
    insurer = security.signed_test_client(vahan_app, "INSURER").get("/api/v1/rc/DL01AB1001").get_json()
    police = security.signed_test_client(vahan_app, "POLICE").get("/api/v1/rc/DL01AB1001").get_json()
    real = police["rc_details"]["owner_name"]
    masked = insurer["rc_details"]["owner_name"]
    assert "*" not in real and masked != real and "*" in masked
    assert masked.split()[0][0] == real.split()[0][0]


def test_access_audit_is_append_only_and_hidden_from_raw_sql():
    security.signed_test_client(vahan_app, "POLICE").get("/api/v1/rc/DL01AB1001")
    conn = sqlite3.connect(VAHAN_DB)
    try:
        for stmt in ("DELETE FROM access_audit", "UPDATE access_audit SET role = 'X'"):
            try:
                conn.execute(stmt)
                raise AssertionError(f"{stmt} should be blocked")
            except sqlite3.DatabaseError as e:
                assert "append-only" in str(e)
    finally:
        conn.close()
    res = security.signed_test_client(vahan_app, "ADMIN").post(
        "/api/v1/internal/execute-sql", json={"query": "DROP TRIGGER access_audit_no_delete"})
    assert res.status_code == 403


def test_match_endpoint_returns_only_candidates():
    client = security.signed_test_client(vahan_app, "INSURER")
    data = client.post("/api/v1/match", json={"plate": "DL01AB1O04", "threshold": 0.01}).get_json()
    assert data["threshold"] == 0.75                      # floor: cannot be lowered to dump the registry
    assert 0 < data["count"] <= 300
    assert all(ocr_similarity("DL01AB1O04", v["vehicle_registration_id"]) >= 0.75 for v in data["vehicles"])
    total = security.signed_test_client(vahan_app, "ADMIN").get("/api/v1/health").get_json()["records_count"]
    assert data["count"] < total / 4


# ---------------------------------------------------------------------------- mediator side
def test_mediator_requires_login():
    client = plain(mediator_app)
    assert client.get("/api/v1/health").status_code == 200
    res = client.get("/api/v1/vehicles/DL01AB1001")
    assert res.status_code == 401 and res.get_json()["login_required"]


def test_login_and_role_gates():
    client = plain(mediator_app)
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    res = client.post("/api/v1/auth/login", json={"username": "insurer", "password": TEST_PASSWORDS["insurer"]})
    assert res.status_code == 200 and res.get_json()["role"] == "INSURER"
    token = res.get_json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/me", headers=auth).get_json() == {"user": "insurer", "role": "INSURER"}
    assert client.post("/api/v1/sql/execute", json={"target": "vahan", "query": "SELECT 1"}, headers=auth).status_code == 403
    assert client.get("/api/v1/fleet/detections", headers=auth).status_code == 403
    assert client.get("/api/v1/matching/agency/scan", headers=auth).status_code == 403
    assert client.get("/api/v1/fleet/kpis", headers=auth).status_code == 200


def test_forged_token_is_rejected():
    token = security.issue_token("insurer", "INSURER")
    payload, sig = token.split(".")
    data = json.loads(security._unb64(payload))
    data["r"] = "ADMIN"
    forged = security._b64(json.dumps(data).encode()) + "." + sig
    assert security.read_token(forged) is None
    res = plain(mediator_app).get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401


def test_invalidate_webhook_must_be_signed():
    client = plain(mediator_app)
    assert client.post("/api/v1/sync/invalidate", json={"vehicle_identifier": "DL01AB1001"}).status_code == 401
    body = json.dumps({"vehicle_identifier": "DL01AB1001"}).encode()
    headers = security.signed_headers("POST", "/api/v1/sync/invalidate", body, "ADMIN", "echallan")
    assert client.post("/api/v1/sync/invalidate", data=body, headers=headers,
                       content_type="application/json").status_code == 200


def test_push_down_search_gives_the_same_decision_as_the_full_index():
    full = build_reference_index(fetch_source_rows(None))
    with mediator_app.test_request_context():
        from flask import g
        g.role = "INSURER"
        for noisy in ("DL01AB1O04", "DL01A81004", "DL0IAB1007", "DL01AB10", "MH12ZZ9999"):
            small, meta = candidate_index(noisy)
            assert len(small) < len(full) / 4
            a, b = assess_record({"plate": noisy}, small), assess_record({"plate": noisy}, full)
            assert (a["decision"], a["corrected_plate"], a["candidate_count"]) == \
                   (b["decision"], b["corrected_plate"], b["candidate_count"]), noisy
