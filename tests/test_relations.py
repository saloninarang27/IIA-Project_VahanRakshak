"""
Phase 3, rubric 1: every agency database has 4-6 tables joined by FK -> PK, the seeded
data satisfies every foreign key, the cross-database keys line up, and the services
enforce the foreign keys on live writes (SQL console).
"""
import sqlite3

import pytest

import config
from backend import security
from backend.VAHAN.vahan_service import app as vahan_app
from backend.IIB.iib_service import app as iib_app

DATABASES = {
    config.DB_REGISTRATION: {"owner", "rto_office", "vehicle_model", "vehicle_registration", "ownership_transfer", "hypothecation"},
    config.DB_INSURANCE: {"insurer", "policyholder", "insurance_policy", "claim", "premium_payment"},
    config.DB_THEFT_SCRAP: {"police_station", "fir", "rvsf_facility", "theft_scrap_record", "recovery"},
    config.DB_CAPTURE: {"toll_plaza", "camera", "vehicle_capture", "anpr_alert", "toll_transaction"},
    config.DB_MINISTRY: {"offence_code", "enforcement_officer", "ministry_report", "challan_payment", "court_case"},
}


def _conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.mark.parametrize("path", DATABASES)
def test_each_database_has_related_tables_joined_by_foreign_keys(path):
    conn = _conn(path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert DATABASES[path] <= tables and 4 <= len(DATABASES[path]) <= 6
        fks = [(t, dict(fk)) for t in DATABASES[path] for fk in conn.execute(f"PRAGMA foreign_key_list({t})")]
        assert len(fks) >= len(DATABASES[path]) - 1           # every table is connected to the graph
        connected = {t for t, _ in fks} | {fk["table"] for _, fk in fks}
        assert connected == DATABASES[path]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        for t in DATABASES[path]:
            assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] > 0, f"{t} is empty"
    finally:
        conn.close()


def test_cross_database_keys_line_up():
    ins, pol, reg = _conn(config.DB_INSURANCE), _conn(config.DB_THEFT_SCRAP), _conn(config.DB_REGISTRATION)
    try:
        firs = {r[0] for r in pol.execute("SELECT fir_no FROM fir")}
        refs = [r[0] for r in ins.execute("SELECT fir_reference FROM claim WHERE fir_reference IS NOT NULL")]
        assert refs and all(r in firs for r in refs)
        owners = {r[0] for r in reg.execute("SELECT owner_id FROM owner")}
        assert all(r[0] in owners for r in ins.execute("SELECT owner_ref FROM policyholder WHERE owner_ref IS NOT NULL"))
        assert all(r[0] in owners for r in pol.execute("SELECT complainant_owner_ref FROM fir"))
        # demo vehicle DL01AB1004 (stolen): VAHAN owner -> IIB theft claim -> Police FIR
        owner = reg.execute("SELECT owner_id FROM vehicle_registration WHERE vehicle_registration_id='DL01AB1004'").fetchone()[0]
        claim = ins.execute("""SELECT h.owner_ref, c.incident_type, c.fir_reference FROM insurance_policy p
                               JOIN policyholder h USING (holder_id) JOIN claim c USING (policy_id)
                               WHERE p.registration_no = 'DL01AB1004'""").fetchone()
        assert claim["owner_ref"] == owner and claim["incident_type"] == "THEFT"
        fir = pol.execute("SELECT vehicle_no, offence_type FROM fir WHERE fir_no = ?", (claim["fir_reference"],)).fetchone()
        assert tuple(fir) == ("DL01AB1004", "VEHICLE_THEFT")
    finally:
        for c in (ins, pol, reg):
            c.close()


def _sql(app, query):
    res = security.signed_test_client(app, "ADMIN").post("/api/v1/internal/execute-sql", json={"query": query})
    return res.status_code, res.get_json()


def test_services_enforce_foreign_keys_on_live_writes():
    status, body = _sql(iib_app, "INSERT INTO claim (policy_id, claim_no, incident_date, incident_type, claim_amount, "
                                 "claim_status) VALUES (999999, 'CLM-BAD', '2026-09-01', 'ACCIDENT', 1000, 'PENDING')")
    assert status == 400 and "FOREIGN KEY" in body["error"].upper()
    status, body = _sql(vahan_app, "DELETE FROM owner WHERE owner_id = 'OWN2001'")   # still referenced by a registration
    assert status == 400 and "FOREIGN KEY" in body["error"].upper()


def test_cascade_delete_removes_dependent_rows():
    """Deleting a policy deletes its claims and premium payments (ON DELETE CASCADE), on a scratch copy of the schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(open(config.SCHEMA_FILES[config.DB_INSURANCE], encoding="utf-8").read())
    conn.execute("INSERT INTO insurance_policy (policy_id, registration_no, insurer_name, policy_number, policy_start_date, "
                 "policy_expiry_date, insurance_status) VALUES (1, 'X', 'Y', 'P1', '2026-01-01', '2027-01-01', 'ACTIVE')")
    conn.execute("INSERT INTO claim (policy_id, claim_no, incident_date, incident_type, claim_amount, claim_status) "
                 "VALUES (1, 'C1', '2026-02-01', 'THEFT', 10, 'PENDING')")
    conn.execute("DELETE FROM insurance_policy WHERE policy_id = 1")
    assert conn.execute("SELECT COUNT(*) FROM claim").fetchone()[0] == 0
