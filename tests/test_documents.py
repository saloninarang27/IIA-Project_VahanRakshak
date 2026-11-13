"""
Phase 3, rubric 3: unstructured documents are searched with the federated query context, the method is
chosen by measurement, and the documents are integrated with the structured results.
"""
import sqlite3

from flask import g
from flask.testing import FlaskClient

import backend.config as bconfig
from backend import security
from backend.DOCS.docs_service import app as docs_app
from backend.mediator_app import app as mediator_app
from backend.context_api import integrated_query
from docsearch import text as T
from docsearch.evaluation import run_evaluation


def truth_of(plate):
    conn = sqlite3.connect(bconfig.DB_DOCS)
    try:
        return {r[0] for r in conn.execute("SELECT doc_id FROM ground_truth WHERE plate = ?", (plate,))}
    finally:
        conn.close()


def iq(query, role):
    with mediator_app.test_request_context():
        g.role = role
        return integrated_query(query, role)


def test_plates_ids_places_dates_are_read_from_free_text():
    assert T.plates_in("a white Creta DL 7C D 1939") == ["DL7CD1939"]          # Delhi style, split series
    s = ("FIR No. FIR5004: the blue Tata Nexon DL-01-AB-1004 was stolen near Golf Course Road, Gurugram on "
         "15 Aug 2026. A caller later saw dl 01 ab 1o04 in Chennai (2026-09-02), policy POL100004.")
    e = T.entities(s)
    assert e["plates"] == ["DL01AB1004", "DL01AB1O04"]
    assert e["firs"] == ["FIR5004"] and e["policies"] == ["POL100004"]
    assert e["cities"] == ["Chennai", "Gurugram"] and e["dates"] == ["2026-08-15", "2026-09-02"]
    assert "THEFT" in e["events"]
    assert T.plates_in("INSURANCE CLAIMS 2026 MOT-2026-000003 FIR5004") == []
    assert T.endings_in("a car with registration ending 1004") == ["1004"]


def test_documents_have_no_structured_vehicle_column():
    conn = sqlite3.connect(bconfig.DB_DOCS)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
        assert not cols & {"plate", "vehicle_no", "registration_no", "vehicle_id"}
        n = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert n > 1000
    finally:
        conn.close()


def test_document_store_only_answers_the_mediator_and_respects_roles():
    assert FlaskClient(docs_app, docs_app.response_class).post("/api/v1/search", json={"context": {}}).status_code == 401
    ctx = {"query": "DL01AB1004", "plates": ["DL01AB1004"], "terms": [{"term": "theft", "weight": 1}]}
    ins = security.signed_test_client(docs_app, "INSURER").post("/api/v1/search", json={"context": ctx, "k": 30}).get_json()
    pol = security.signed_test_client(docs_app, "POLICE").post("/api/v1/search", json={"context": ctx, "k": 30}).get_json()
    assert ins["hidden_by_role"] > 0 and pol["hidden_by_role"] > 0
    assert not {"FIR_NARRATIVE", "OFFICER_NOTE"} & {r["doc_type"] for r in ins["results"]}
    assert "SURVEYOR_REPORT" not in {r["doc_type"] for r in pol["results"]}


def test_context_search_ranks_the_vehicles_documents_first():
    d = iq("Is DL01AB1004 stolen? any insurance claim?", "ADMIN")
    relevant = truth_of("DL01AB1004")
    ranked = [r["doc_id"] for r in d["documents"]["results"]]
    assert set(ranked[:len(relevant)]) == relevant          # every document about the car, before any other
    written = {r["breakdown"]["plate_match"]["in_text"] for r in d["documents"]["results"][:len(relevant)]}
    assert "DL01A81004" in written                          # the OCR-slip tip-off is found too


def test_method_is_chosen_by_measurement():
    rep = run_evaluation(n_queries=16, write=False)
    m = rep["methods"]
    assert rep["selected_method"] == "context_entities"
    assert m["context_entities"]["ndcg@10"] > m["bm25_context"]["ndcg@10"] > m["bm25_query"]["ndcg@10"]
    assert m["context_entities"]["decoy_above_relevant"] == 0.0


def test_integration_links_documents_and_flags_new_leads():
    d = iq("DL01AB1004 stolen", "POLICE")
    i = d["integration"]["DL01AB1004"]
    relevant = truth_of("DL01AB1004")
    assert {x["doc_id"] for x in i["documents"]} <= relevant   # no other car's document is attached
    types = {f["type"] for f in i["findings"]}
    assert {"NEW_LEAD", "NOISY_PLATE"} <= types
    assert any(t["origin"] == "document" for t in i["timeline"]) and any(t["origin"] == "database" for t in i["timeline"])
    assert d["structured"]["DL01AB1004"]["suspicion_status"] == "STOLEN"


def test_a_new_tip_off_is_searchable_and_integrated_at_once():
    client = mediator_app.test_client()
    body = ("Tip-off: a blue Nexon with number DL 01 AB 1OO4 has been parked near Banjara Hills, Hyderabad "
            "since 13 Sep 2026; looks like the stolen one.")
    res = client.post("/api/v1/context/documents", json={"doc_type": "TIP_OFF", "body": body})
    assert res.status_code == 201
    doc_id = res.get_json()["doc_id"]
    try:
        d = iq("DL01AB1004 stolen", "POLICE")
        assert doc_id in [r["doc_id"] for r in d["documents"]["results"]]
        leads = [f for f in d["integration"]["DL01AB1004"]["findings"] if f["doc_id"] == doc_id]
        assert {f["type"] for f in leads} >= {"NEW_LEAD", "NOISY_PLATE"}
        assert "after the last ANPR sighting" in next(f["detail"] for f in leads if f["type"] == "NEW_LEAD")
    finally:
        assert client.delete(f"/api/v1/context/documents/{doc_id}").status_code == 200
    d = iq("DL01AB1004 stolen", "POLICE")
    assert doc_id not in [r["doc_id"] for r in d["documents"]["results"]]


def test_insurer_sees_no_police_documents_in_the_integrated_answer():
    d = iq("DL01AB1004 claim", "INSURER")
    assert d["documents"]["hidden_by_role"] > 0
    assert not {"FIR_NARRATIVE", "OFFICER_NOTE"} & {r["doc_type"] for r in d["documents"]["results"]}
    assert "SURVEYOR_REPORT" in {r["doc_type"] for r in d["documents"]["results"]}


def test_a_document_is_linked_to_the_database_entities_it_discusses():
    # EROCS direction: document -> entities, the plate resolved with the phase-2 matcher
    from backend.context_api import link_document
    with mediator_app.test_request_context():
        g.role = "POLICE"
        L = link_document("Tip-off: DL 01 AB 1OO4 seen in Hyderabad on 13 Sep 2026, ref FIR5004")
    assert L["vehicles"] == ["DL01AB1004"] and L["plate_resolution"][0]["rule"] == "R8"
    assert L["firs"] == ["FIR5004"] and L["cities"] == ["Hyderabad"] and L["dates"] == ["2026-09-13"]


def test_a_plate_no_database_knows_gets_no_unrelated_documents():
    # random plate from the internet: no context, so keyword hits ("stolen") are not "related documents"
    res = iq("DL7CD1939 stolen?", "POLICE")
    assert res["facts"] == [] and res["documents"]["no_context"]
    assert res["documents"]["results"] == []
