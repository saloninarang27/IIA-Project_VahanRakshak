"""
Populate the related tables of every agency database (phase 3: entity information
distributed over 5-6 tables per database, joined by FK -> PK).

Runs AFTER the five core seeders. It fills the new tables and the new FK columns of
the core tables (vehicle_registration.owner_id/model_id/rto_code, insurance_policy.
insurer_id/holder_id, theft_scrap_record.fir_no/rvsf_id, ministry_report.offence_code/
officer_id). vehicle_capture.camera_id already holds the camera key.

It uses its own random generator (seed 2026), so the phase-1/2 dataset produced by
seed/vehicle_master_data.py is unchanged. The cross-database keys line up on purpose
(fictional story, generated once):
  IIB policyholder.owner_ref  = VAHAN owner.owner_id
  IIB claim.fir_reference     = Police fir.fir_no
  Police fir.complainant_owner_ref = VAHAN owner.owner_id

Run: python -m seed.seed_relations
"""
import random
from datetime import date, datetime, timedelta

import config
import db
from seed.vehicle_master_data import VEHICLES, LOCATIONS, INSURERS, MAKES_MODELS, FIRST_NAMES, LAST_NAMES

rng = random.Random(2026)
TODAY = config.SIMULATION_TODAY

# city of each ANPR location ("NH-8 Toll Plaza, Gurugram" -> "Gurugram")
CITY_STATE = {"Gurugram": "Haryana", "Delhi": "Delhi", "Bengaluru": "Karnataka", "Mumbai": "Maharashtra",
              "Chennai": "Tamil Nadu", "Noida": "Uttar Pradesh", "Hyderabad": "Telangana", "Kolkata": "West Bengal"}
CITIES = list(CITY_STATE)
CITY_CODE = {"Gurugram": "GGN", "Delhi": "DEL", "Bengaluru": "BLR", "Mumbai": "MUM", "Chennai": "CHN",
             "Noida": "NOI", "Hyderabad": "HYD", "Kolkata": "KOL"}
RTO_OFFICES = [("DL-01", "Delhi North (Mall Road)", "Delhi", "Delhi"), ("HR-26", "Gurugram RTO", "Gurugram", "Haryana"),
               ("KA-01", "Bengaluru Central", "Bengaluru", "Karnataka"), ("MH-02", "Mumbai West (Andheri)", "Mumbai", "Maharashtra"),
               ("TN-01", "Chennai Central", "Chennai", "Tamil Nadu"), ("UP-16", "Noida RTO", "Noida", "Uttar Pradesh"),
               ("TS-09", "Hyderabad Central", "Hyderabad", "Telangana"), ("WB-02", "Kolkata Beltala", "Kolkata", "West Bengal")]
STREETS = ["MG Road", "Station Road", "Sector 14", "Lake View Colony", "Nehru Nagar", "Civil Lines", "Park Street",
           "Gandhi Marg", "Green Park", "Shanti Vihar"]
FINANCERS = ["HDFC Bank", "State Bank of India", "ICICI Bank", "Axis Bank", "Mahindra Finance", "Bajaj Finance"]
SEGMENT = {"Kwid": "ENTRY", "Swift": "ENTRY", "i20": "ENTRY", "Polo": "ENTRY", "Magnite": "ENTRY",
           "Corolla": "PREMIUM", "Civic": "PREMIUM", "Innova": "PREMIUM", "Hector": "PREMIUM", "XUV500": "PREMIUM"}
OFFENCES = [("MVA-196", "UNINSURED_VEHICLE", "Section 196", "Driving an uninsured motor vehicle", 2000),
            ("MVA-196E", "EXPIRED_INSURANCE", "Section 196", "Insurance policy expired", 2000),
            ("MVA-39", "EXPIRED_REGISTRATION", "Section 39 / 192", "Driving with expired registration", 5000),
            ("IPC-379", "STOLEN_VEHICLE", "IPC 379 / MV Act 4", "Stolen vehicle detected on road", 0),
            ("MVA-SCRAP", "SCRAPPED_VEHICLE_DETECTED", "Vehicle Scrapping Policy 2021", "Scrapped vehicle on road", 10000),
            ("MVA-SUSP", "MULTIPLE_SUSPICIOUS_EVENTS", "Section 207", "Suspicious vehicle history", 0)]


def _d(text):
    return date.fromisoformat(text[:10]) if text else None


def _city(location):
    return location.rsplit(",", 1)[-1].strip()


def _name():
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def _phone():
    return "9" + "".join(rng.choice("0123456789") for _ in range(9))


def _home_city(v):
    """A vehicle's home city: where it was first seen by a camera (Delhi if never seen)."""
    return _city(v["captures"][0]["location"]) if v["captures"] else "Delhi"


BY_PLATE = {v["plate"]: v for v in VEHICLES}


# ---------------------------------------------------------------------------
# Story shared by several databases, generated once so the cross-database keys agree
# ---------------------------------------------------------------------------
def _accident_firs():
    """Accident FIRs (Police) that IIB claims refer to: ~6% of insured vehicles + demo vehicles 1001/1007."""
    firs = []
    for v in VEHICLES:
        active = [p for p in v["insurance_policies"] if p["insurance_status"] == "ACTIVE"]
        if not active:
            continue
        if v["plate"] in ("DL01AB1001", "DL01AB1007") or rng.random() < 0.06:
            when = TODAY - timedelta(days=rng.randint(5, 150))
            firs.append({"fir_no": f"FIR{70000 + len(firs) + 1}", "plate": v["plate"], "date": when.isoformat(),
                         "city": _home_city(v), "type": rng.choice(["ROAD_ACCIDENT", "ROAD_ACCIDENT", "HIT_AND_RUN"]),
                         "policy": active[-1]["policy_number"]})
    return firs


ACCIDENT_FIRS = _accident_firs()


# ---------------------------------------------------------------------------
def seed_registration():
    conn = db.get_connection(config.DB_REGISTRATION)
    cur = conn.cursor()
    for t in ("hypothecation", "ownership_transfer", "vehicle_model", "owner", "rto_office"):
        cur.execute(f"DELETE FROM {t}")
    cur.executemany("INSERT INTO rto_office VALUES (?, ?, ?, ?)", RTO_OFFICES)
    for make, model in MAKES_MODELS:
        cur.execute("INSERT INTO vehicle_model (make, model, segment) VALUES (?, ?, ?)",
                    (make, model, SEGMENT.get(model, "MID")))
    model_ids = {(r["make"], r["model"]): r["model_id"] for r in cur.execute("SELECT * FROM vehicle_model")}

    regs = cur.execute("SELECT registration_id, vehicle_registration_id, owner_id, owner_name, vehicle_make, "
                       "vehicle_model, registration_date FROM vehicle_registration ORDER BY registration_id").fetchall()
    owners, transfers, hyps = {}, [], []
    for r in regs:
        v = BY_PLATE.get(r["vehicle_registration_id"])
        city = _home_city(v) if v else "Delhi"
        owners.setdefault(r["owner_id"], (r["owner_id"], r["owner_name"],
                                          f"{rng.randint(1, 250)}, {rng.choice(STREETS)}, {city}", city, _phone()))
        chassis = "MA" + "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(15))
        engine = "EN" + "".join(rng.choice("0123456789") for _ in range(9))
        cur.execute("UPDATE vehicle_registration SET model_id = ?, rto_code = ?, chassis_no = ?, engine_no = ? "
                    "WHERE registration_id = ?",
                    (model_ids.get((r["vehicle_make"], r["vehicle_model"])), "DL-01", chassis, engine, r["registration_id"]))
        demo_transfer = r["vehicle_registration_id"] in ("DL01AB1004", "DL01AB1007", "DL01AB1010")
        if demo_transfer or rng.random() < 0.12:
            prev = f"OWN{90000 + len(transfers) + 1}"
            owners[prev] = (prev, _name(), f"{rng.randint(1, 250)}, {rng.choice(STREETS)}, {city}", city, _phone())
            when = _d(r["registration_date"]) + timedelta(days=rng.randint(30, 150))
            transfers.append((r["registration_id"], prev, r["owner_id"], min(when, TODAY).isoformat(),
                              rng.choice(["SALE", "SALE", "SALE", "INHERITANCE"])))
        if rng.random() < 0.3:
            hyps.append((r["registration_id"], rng.choice(FINANCERS), f"LN{rng.randint(10**8, 10**9 - 1)}",
                         r["registration_date"], rng.choice(["ACTIVE", "ACTIVE", "CLOSED"])))
    cur.executemany("INSERT INTO owner VALUES (?, ?, ?, ?, ?)", owners.values())
    cur.executemany("INSERT INTO ownership_transfer (registration_id, from_owner_id, to_owner_id, transfer_date, "
                    "transfer_reason) VALUES (?, ?, ?, ?, ?)", transfers)
    cur.executemany("INSERT INTO hypothecation (registration_id, financer_name, loan_account_no, start_date, status) "
                    "VALUES (?, ?, ?, ?, ?)", hyps)
    conn.commit()
    conn.close()
    return {"rto_office": len(RTO_OFFICES), "owner": len(owners), "vehicle_model": len(model_ids),
            "ownership_transfer": len(transfers), "hypothecation": len(hyps)}


def seed_insurance():
    conn = db.get_connection(config.DB_INSURANCE)
    cur = conn.cursor()
    for t in ("premium_payment", "claim", "policyholder", "insurer"):
        cur.execute(f"DELETE FROM {t}")
    hq = ["Mumbai", "Delhi", "Bengaluru", "Chennai", "Kolkata"]
    for i, name in enumerate(INSURERS):
        cur.execute("INSERT INTO insurer (insurer_name, irdai_reg_no, head_office_city, claims_helpline) VALUES (?, ?, ?, ?)",
                    (name, f"IRDAI-{101 + i}", hq[i % len(hq)], f"1800-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"))
    insurer_ids = {r["insurer_name"]: r["insurer_id"] for r in cur.execute("SELECT * FROM insurer")}

    holder_ids = {}
    for plate in [r[0] for r in cur.execute("SELECT DISTINCT registration_no FROM insurance_policy ORDER BY registration_no")]:
        v = BY_PLATE.get(plate)
        cur.execute("INSERT INTO policyholder (holder_name, owner_ref, city, kyc_status) VALUES (?, ?, ?, ?)",
                    (v["owner_name"] if v else _name(), v["owner_id"] if v else None,
                     _home_city(v) if v else "Delhi", rng.choice(["VERIFIED"] * 9 + ["PENDING"])))
        holder_ids[plate] = cur.lastrowid

    policies = cur.execute("SELECT policy_id, registration_no, insurer_name, policy_number, policy_start_date, "
                           "policy_type FROM insurance_policy ORDER BY policy_id").fetchall()
    by_number = {}
    for p in policies:
        sum_insured = rng.choice([300000, 450000, 600000, 800000, 1200000])
        cur.execute("UPDATE insurance_policy SET insurer_id = ?, holder_id = ?, sum_insured = ? WHERE policy_id = ?",
                    (insurer_ids.get(p["insurer_name"]), holder_ids.get(p["registration_no"]), sum_insured, p["policy_id"]))
        premium = round(sum_insured * (0.035 if p["policy_type"] == "Comprehensive" else 0.012), 2)
        cur.execute("INSERT INTO premium_payment (policy_id, paid_on, amount, payment_mode) VALUES (?, ?, ?, ?)",
                    (p["policy_id"], p["policy_start_date"], premium, rng.choice(["UPI", "CARD", "NETBANKING", "CASH"])))
        by_number[p["policy_number"]] = (p, sum_insured)

    claims = 0

    def add_claim(policy_number, when, kind, city, fir, status):
        nonlocal claims
        p, sum_insured = by_number[policy_number]
        amount = round(sum_insured * (0.9 if kind == "THEFT" else rng.uniform(0.05, 0.4)), 2)
        settled = amount if status == "SETTLED" else None
        claims += 1
        cur.execute("INSERT INTO claim (policy_id, claim_no, incident_date, incident_type, incident_city, fir_reference, "
                    "claim_amount, claim_status, settled_amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (p["policy_id"], f"CLM{800000 + claims}", when, kind, city, fir, amount, status, settled))

    # theft claims: every stolen / recovered / previously-stolen vehicle that holds a policy
    for v in VEHICLES:
        ts = v["theft_scrap"]
        if not ts or ts["theft_status"] == "NONE" or not v["insurance_policies"]:
            continue
        status = {"STOLEN": "PENDING", "RECOVERED": "REJECTED"}[ts["theft_status"]]
        if v["category"] == "SUSPICIOUS":
            status = "SETTLED"
        add_claim(v["insurance_policies"][-1]["policy_number"], ts["theft_report_date"], "THEFT", _home_city(v),
                  ts["authority_reference"], status)
    for f in ACCIDENT_FIRS:  # accident claims, each backed by a police FIR
        add_claim(f["policy"], f["date"], "ACCIDENT", f["city"], f["fir_no"], rng.choice(["PENDING", "SETTLED", "SETTLED"]))
    for p in policies:  # small claims without an FIR (fire / flood / minor damage)
        if rng.random() < 0.03:
            when = _d(p["policy_start_date"]) + timedelta(days=rng.randint(10, 200))
            v = BY_PLATE.get(p["registration_no"])
            add_claim(p["policy_number"], min(when, TODAY).isoformat(), rng.choice(["FIRE", "FLOOD"]),
                      _home_city(v) if v else "Delhi", None, rng.choice(["PENDING", "SETTLED", "REJECTED"]))
    conn.commit()
    conn.close()
    return {"insurer": len(insurer_ids), "policyholder": len(holder_ids), "claim": claims, "premium_payment": len(policies)}


def seed_police():
    conn = db.get_connection(config.DB_THEFT_SCRAP)
    cur = conn.cursor()
    for t in ("recovery", "fir", "rvsf_facility", "police_station"):
        cur.execute(f"DELETE FROM {t}")
    for city in CITIES:
        for k in (1, 2):
            cur.execute("INSERT INTO police_station VALUES (?, ?, ?, ?)",
                        (f"PS-{CITY_CODE[city]}-0{k}", f"{city} {'Central' if k == 1 else 'Highway'} Police Station",
                         city, city))
    rvsf = [(f"RVSF-{CITY_CODE[c]}", f"{c} Authorised Scrapping Facility", c, f"RVSF/LIC/{2021 + i}/{100 + i}")
            for i, c in enumerate(["Delhi", "Gurugram", "Mumbai", "Chennai"])]
    cur.executemany("INSERT INTO rvsf_facility VALUES (?, ?, ?, ?)", rvsf)

    firs, recoveries = 0, 0
    officers = [f"SI {_name()}" for _ in range(12)]
    for r in cur.execute("SELECT record_id, vehicle_no, theft_status, theft_report_date, recovery_date, scrapping_status, "
                         "authority_reference FROM theft_scrap_record ORDER BY record_id").fetchall():
        v = BY_PLATE.get(r["vehicle_no"])
        city = _home_city(v) if v else "Delhi"
        ref = r["authority_reference"] or ""
        fir_no, rvsf_id = None, None
        if ref.startswith("FIR"):
            fir_no = ref
            cur.execute("INSERT INTO fir VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (fir_no, f"PS-{CITY_CODE[city]}-0{rng.randint(1, 2)}", r["theft_report_date"], "VEHICLE_THEFT",
                         r["vehicle_no"], v["owner_name"] if v else None, v["owner_id"] if v else None,
                         rng.choice(officers), "OPEN" if r["theft_status"] == "STOLEN" else "CLOSED"))
            firs += 1
            if r["recovery_date"]:
                cur.execute("INSERT INTO recovery (fir_no, recovery_date, recovered_city, vehicle_condition) VALUES (?, ?, ?, ?)",
                            (fir_no, r["recovery_date"], rng.choice(CITIES), rng.choice(["INTACT", "DAMAGED", "PARTS_MISSING"])))
                recoveries += 1
        if r["scrapping_status"] == "SCRAPPED":
            rvsf_id = rng.choice(rvsf)[0]
        cur.execute("UPDATE theft_scrap_record SET fir_no = ?, rvsf_id = ? WHERE record_id = ?", (fir_no, rvsf_id, r["record_id"]))
    for f in ACCIDENT_FIRS:
        v = BY_PLATE[f["plate"]]
        cur.execute("INSERT INTO fir VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f["fir_no"], f"PS-{CITY_CODE[f['city']]}-02", f["date"], f["type"], f["plate"], v["owner_name"],
                     v["owner_id"], rng.choice(officers), rng.choice(["OPEN", "CHARGESHEETED", "CLOSED"])))
        firs += 1
    conn.commit()
    conn.close()
    return {"police_station": len(CITIES) * 2, "fir": firs, "rvsf_facility": len(rvsf), "recovery": recoveries}


def seed_capture():
    conn = db.get_connection(config.DB_CAPTURE)
    cur = conn.cursor()
    for t in ("toll_transaction", "anpr_alert", "camera", "toll_plaza"):
        cur.execute(f"DELETE FROM {t}")
    highways = ["NH-48", "Ring Road", "NH-75", "Western Express Hwy", "NH-32", "DND Flyway", "ORR", "NH-12"]
    for i, (cam, loc) in enumerate(LOCATIONS):
        plaza = f"TP-{i + 1:02d}"
        city = _city(loc)
        cur.execute("INSERT INTO toll_plaza VALUES (?, ?, ?, ?, ?)", (plaza, loc.split(",")[0], highways[i], city, CITY_STATE[city]))
        cur.execute("INSERT INTO camera VALUES (?, ?, ?, ?, ?)",
                    (cam, plaza, rng.randint(1, 6), rng.choice(["Hikvision ANPR-X5", "Bosch DINION 7100", "Axis Q1700-LE"]),
                     (TODAY - timedelta(days=rng.randint(300, 1500))).isoformat()))
    alerts, txns = 0, 0
    for c in cur.execute("SELECT capture_id, plate_number, captured_timestamp, confidence_score FROM vehicle_capture "
                         "ORDER BY capture_id").fetchall():
        v = BY_PLATE.get(c["plate_number"])
        ts = (v or {}).get("theft_scrap") or {}
        alert = ("HOTLIST_STOLEN" if ts.get("theft_status") == "STOLEN" else
                 "HOTLIST_SCRAPPED" if ts.get("scrapping_status") == "SCRAPPED" else
                 "LOW_CONFIDENCE_READ" if (c["confidence_score"] or 1) < 0.87 else None)
        if alert:
            cur.execute("INSERT INTO anpr_alert (capture_id, alert_type, raised_at, alert_status) VALUES (?, ?, ?, ?)",
                        (c["capture_id"], alert, c["captured_timestamp"], rng.choice(["OPEN", "DISPATCHED", "CLOSED"])))
            alerts += 1
        cur.execute("INSERT INTO toll_transaction (capture_id, fastag_id, amount, txn_status) VALUES (?, ?, ?, ?)",
                    (c["capture_id"], f"FT{rng.randint(10**11, 10**12 - 1)}", rng.choice([65, 95, 120, 155, 210]),
                     "BLACKLISTED_TAG" if alert == "HOTLIST_STOLEN" else rng.choice(["PAID"] * 19 + ["FAILED"])))
        txns += 1
    conn.commit()
    conn.close()
    return {"toll_plaza": len(LOCATIONS), "camera": len(LOCATIONS), "anpr_alert": alerts, "toll_transaction": txns}


def seed_ministry():
    conn = db.get_connection(config.DB_MINISTRY)
    cur = conn.cursor()
    for t in ("court_case", "challan_payment", "enforcement_officer", "offence_code"):
        cur.execute(f"DELETE FROM {t}")
    cur.executemany("INSERT INTO offence_code VALUES (?, ?, ?, ?, ?)", OFFENCES)
    code_of = {o[1]: o[0] for o in OFFENCES}
    fine_of = {o[0]: o[4] for o in OFFENCES}
    officers = []
    for city in CITIES:
        for k in (1, 2):
            officers.append((f"OFF-{CITY_CODE[city]}-0{k}", _name(), rng.choice(["Inspector", "Sub-Inspector", "ASI"]), city))
    cur.executemany("INSERT INTO enforcement_officer VALUES (?, ?, ?, ?)", officers)
    payments, cases = 0, 0
    for r in cur.execute("SELECT report_id, vehicle_identifier, report_type, severity, submitted_at FROM ministry_report "
                         "ORDER BY report_id").fetchall():
        v = BY_PLATE.get(r["vehicle_identifier"])
        city = _home_city(v) if v else "Delhi"
        code = code_of.get(r["report_type"])
        cur.execute("UPDATE ministry_report SET offence_code = ?, officer_id = ? WHERE report_id = ?",
                    (code, f"OFF-{CITY_CODE[city]}-0{rng.randint(1, 2)}", r["report_id"]))
        fine = fine_of.get(code, 0)
        if fine and rng.random() < 0.25:
            cur.execute("INSERT INTO challan_payment (report_id, paid_on, amount, payment_mode) VALUES (?, ?, ?, ?)",
                        (r["report_id"], r["submitted_at"][:10], fine, rng.choice(["UPI", "CARD"])))
            payments += 1
        elif r["severity"] == "CRITICAL" and rng.random() < 0.4:
            cur.execute("INSERT INTO court_case (report_id, court_name, hearing_date, case_status) VALUES (?, ?, ?, ?)",
                        (r["report_id"], f"Virtual Traffic Court, {city}",
                         (TODAY + timedelta(days=rng.randint(7, 90))).isoformat(), rng.choice(["LISTED", "ADJOURNED"])))
            cases += 1
    conn.commit()
    conn.close()
    return {"offence_code": len(OFFENCES), "enforcement_officer": len(officers), "challan_payment": payments,
            "court_case": cases}


def seed():
    counts = {"registration.db": seed_registration(), "insurance.db": seed_insurance(),
              "theft_scrap.db": seed_police(), "vehicle_capture.db": seed_capture(), "ministry.db": seed_ministry()}
    for dbname, tables in counts.items():
        print(f"[seed_relations] {dbname}: " + ", ".join(f"{t}={n}" for t, n in tables.items()))
    return counts


if __name__ == "__main__":
    seed()
