"""
Phase 3, rubric 2: the query is federated to the five databases, each database discovers the context
by following its own FK -> PK relationships, keys found in one database lead the next round into the
others, and the accumulated context stays about the query.
"""
import sqlite3

from flask import g

from backend import security
from backend.context_api import parse_query, discover_context, MIN_FACT_SCORE
from backend.context_engine import discover
from backend.mediator_app import app as mediator_app
from backend.IIB.iib_service import app as iib_app
import backend.config as bconfig


def ctx(query, role="ADMIN"):
    with mediator_app.test_request_context():
        g.role = role
        return discover_context(query, role)


def test_query_parsing_finds_keys_and_tolerates_noise():
    assert parse_query("Is DL01AB1004 stolen?")["seeds"] == {"plate": ["DL01AB1004"]}
    assert parse_query("dl 01 ab 1004")["seeds"] == {"plate": ["DL01AB1004"]}
    assert parse_query("DL01A81004 theft claim")["seeds"] == {"plate": ["DL01A81004"]}
    assert parse_query("claim for FIR5004 and owner OWN2004")["seeds"] == {"fir_no": ["FIR5004"], "owner_id": ["OWN2004"]}
    assert parse_query("INSURANCE CLAIMS 2026")["seeds"] == {}
    assert "theft" in parse_query("was it stolen")["terms"]


def test_each_database_walks_only_its_own_fk_graph_around_the_seed():
    conn = sqlite3.connect(bconfig.DB_VAHAN)
    conn.row_factory = sqlite3.Row
    try:
        d = discover(conn, "VAHAN", {"plate": ["DL01AB1004"]}, ["stolen"], "ADMIN")
    finally:
        conn.close()
    assert {"vehicle_registration", "owner", "vehicle_model", "rto_office", "ownership_transfer"} <= set(d["stats"]["tables_reached"])
    # shared parents (RTO office, model) must not lead down to other vehicles
    assert [k["value"] for k in d["keys"]["plate"]] == ["DL01AB1004"]
    assert all("->" in f["via"] or "<-" in f["via"] or f["via"].startswith("seed") for f in d["facts"])


def test_restricted_tables_return_keys_only():
    res = security.signed_test_client(iib_app, "POLICE").post(
        "/api/v1/context", json={"seeds": {"plate": ["DL01AB1004"]}, "terms": ["theft"]}).get_json()
    claim = next(f for f in res["facts"] if f["table"] == "claim")
    assert claim["redacted"] and claim["row"] == {"fir_reference": "FIR5004"}
    full = security.signed_test_client(iib_app, "INSURER").post(
        "/api/v1/context", json={"seeds": {"plate": ["DL01AB1004"]}, "terms": ["theft"]}).get_json()
    claim = next(f for f in full["facts"] if f["table"] == "claim")
    assert not claim["redacted"] and claim["row"]["incident_type"] == "THEFT"


def test_seed_values_are_capped():
    conn = sqlite3.connect(bconfig.DB_VAHAN)
    conn.row_factory = sqlite3.Row
    try:
        d = discover(conn, "VAHAN", {"plate": [f"DL01AB{1000 + n}" for n in range(1, 200)]}, [], "ADMIN", max_hops=0)
    finally:
        conn.close()
    assert d["stats"]["seed_rows"] == 20


def test_keys_from_one_database_lead_the_next_round_into_the_others():
    d = ctx("accident claim FIR70001", "POLICE")
    assert d["parsed"]["seeds"] == {"fir_no": ["FIR70001"]}
    r1 = {a["agency"]: a for a in d["rounds"][0]["agencies"]}
    assert r1["IIB"]["facts"] and r1["POLICE"]["facts"] and not r1["VAHAN"]["facts"]   # only IIB/Police know FIRs
    r2 = {a["agency"]: a for a in d["rounds"][1]["agencies"]}
    assert r2["VAHAN"]["seeds_sent"]["plate"] == ["DL01AB1001"] and r2["ANPR"]["facts"]
    assert set(d["facts_by_agency"]) >= {"IIB", "POLICE", "VAHAN", "ANPR"}
    assert [e["value"] for e in d["entities"]["vehicles"]] == ["DL01AB1001"]


def test_context_is_about_the_query():
    d = ctx("Is DL01AB1004 stolen? any insurance claim?")
    assert [e["value"] for e in d["entities"]["vehicles"]] == ["DL01AB1004"]
    assert all(f["score"] >= MIN_FACT_SCORE for f in d["facts"])
    assert [f["score"] for f in d["facts"]] == sorted((f["score"] for f in d["facts"]), reverse=True)
    top = {(f["agency"], f["table"]) for f in d["facts"][:4]}
    assert ("POLICE", "fir") in top and ("POLICE", "theft_scrap_record") in top   # 'stolen' ranks theft facts first
    assert {"FIR5004"} <= {e["value"] for e in d["entities"]["firs"]}


def test_noisy_plate_in_the_query_is_resolved_first():
    d = ctx("DL01A81004 theft claim", "INSURER")
    assert d["parsed"]["seeds"]["plate"] == ["DL01AB1004"]
    assert d["parsed"]["plate_resolution"][0]["resolved_to"] == "DL01AB1004"


def test_text_query_focuses_on_vehicles_covering_all_words():
    d = ctx("stolen Nexon Gurugram", "POLICE")
    assert d["mode"] == "text" and d["text_focus"]["chosen_plates"]
    veh = sqlite3.connect(bconfig.DB_VAHAN)
    pol = sqlite3.connect(bconfig.DB_POLICE)
    try:
        for plate in d["text_focus"]["chosen_plates"]:
            assert veh.execute("SELECT vehicle_model FROM vehicle_registration WHERE vehicle_registration_id=?",
                               (plate,)).fetchone()[0] == "Nexon"
            assert pol.execute("SELECT theft_status FROM theft_scrap_record WHERE vehicle_no=?", (plate,)).fetchone()[0] == "STOLEN"
    finally:
        veh.close()
        pol.close()
    assert {e["value"] for e in d["entities"]["vehicles"]} == set(d["text_focus"]["chosen_plates"])


def test_a_record_inserted_live_appears_in_the_context():
    sql = security.signed_test_client(iib_app, "ADMIN")
    policy_id = sql.post("/api/v1/internal/execute-sql", json={
        "query": "SELECT policy_id FROM insurance_policy WHERE registration_no='DL01AB1004'"}).get_json()["rows"][0][0]
    sql.post("/api/v1/internal/execute-sql", json={"query":
             f"INSERT INTO claim (policy_id, claim_no, incident_date, incident_type, incident_city, claim_amount, "
             f"claim_status) VALUES ({policy_id}, 'CLM-LIVE-1', '2026-09-13', 'FIRE', 'Gurugram', 50000, 'PENDING')"})
    try:
        d = ctx("DL01AB1004 fire claim", "INSURER")
        assert "CLM-LIVE-1" in {e["value"] for e in d["entities"]["policies_claims"]}
        assert any(f["row"].get("claim_no") == "CLM-LIVE-1" and "fire" in f["matched_terms"] for f in d["facts"])
    finally:
        sql.post("/api/v1/internal/execute-sql", json={"query": "DELETE FROM claim WHERE claim_no='CLM-LIVE-1'"})
    d = ctx("DL01AB1004 fire claim", "INSURER")
    assert "CLM-LIVE-1" not in {e["value"] for e in d["entities"].get("policies_claims", [])}


def test_mediator_endpoint_requires_login_and_runs():
    from flask.testing import FlaskClient
    assert FlaskClient(mediator_app, mediator_app.response_class).post(
        "/api/v1/context/query", json={"query": "DL01AB1004"}).status_code == 401
    res = mediator_app.test_client().post("/api/v1/context/query", json={"query": "DL01AB1004 stolen"})
    assert res.status_code == 200 and res.get_json()["facts"]
