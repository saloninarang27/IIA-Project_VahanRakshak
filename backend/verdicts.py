"""
Verdict push-down: each agency answers the Mediator's question itself.

Instead of sending its rows for a vehicle and letting the Mediator decide, every agency
service exposes GET /api/v1/verdict/<plate>, computes the answer on its own machine from
its own tables, and returns the answer (plus only the details the caller's role needs):

  IIB       "is it insured on <date>?"         INSURED / EXPIRED / UNINSURED, valid till, insurer
  VAHAN     "is it registered and valid?"       ACTIVE / EXPIRED / UNREGISTERED, vehicle description
  Police    "is it stolen / scrapped?"          NONE / STOLEN / SCRAPPED / SHREDDED / RECOVERED_HISTORY
  ANPR      "has it been seen on the road?"     seen_on_road, sightings, last sighting
  e-Challan "does it have open challans?"       open count, latest challan

Detail rows (policy history, FIR, every sighting, every challan) are added only for the
roles that need them; personal fields are masked by security.protect_service as before.
The Mediator only combines the five answers into the dossier and the risk level.

The rules are the same pure functions as before (ministry/rules.py); they now run at the
agency instead of at the Mediator.
"""
from datetime import date

from flask import g, jsonify

import backend.config as config
from ministry.rules import compute_insurance_status, compute_suspicion_status, parse_date


def _plate(text):
    return "".join(ch for ch in (text or "").upper() if ch.isalnum())


def _role():
    return g.get("fed_role")


def insurance_verdict(conn, plate, on, role):
    policies = [dict(r) for r in conn.execute(
        """SELECT p.policy_id, p.registration_no, p.insurer_name, p.policy_number, p.policy_start_date,
                  p.policy_expiry_date, p.insurance_status, p.policy_type
           FROM insurance_policy p WHERE p.registration_no = ? ORDER BY p.policy_expiry_date DESC""", (plate,))]
    result = compute_insurance_status(policies, on)
    policy = result["policy"] or {}
    verdict = {
        "agency": "IIB_IRDAI", "question": f"Is {plate} insured on {on.isoformat()}?", "plate": plate,
        "evaluated_on": on.isoformat(),
        "insurance_status": result["status"],
        "insured": result["status"] == "INSURED",
        "insurer_name": policy.get("insurer_name"),
        "valid_from": policy.get("policy_start_date"),
        "valid_till": policy.get("policy_expiry_date"),
        "policy_count": len(policies),
    }
    if role in ("INSURER", "ADMIN"):
        verdict["policy_number"] = policy.get("policy_number")
        verdict["policies"] = policies
        verdict["claims"] = [dict(r) for r in conn.execute(
            """SELECT c.claim_no, c.incident_date, c.incident_type, c.incident_city, c.fir_reference,
                      c.claim_amount, c.claim_status
               FROM claim c JOIN insurance_policy p ON p.policy_id = c.policy_id
               WHERE p.registration_no = ? ORDER BY c.incident_date DESC""", (plate,))]
    return verdict


def registration_verdict(conn, plate, on, role):
    row = conn.execute(
        """SELECT r.registration_id, r.vehicle_registration_id, r.owner_id, r.owner_name, r.registration_date,
                  r.registration_expiry_date, r.vehicle_make, r.vehicle_model, r.vehicle_type, r.fuel_type,
                  r.color, r.registration_status, r.rto_code
           FROM vehicle_registration r WHERE r.vehicle_registration_id = ?""", (plate,)).fetchone()
    verdict = {"agency": "MORTH_VAHAN", "question": f"Is {plate} registered and valid?", "plate": plate,
               "evaluated_on": on.isoformat(), "registered": row is not None}
    if row is None:
        verdict["registration_status"] = "UNREGISTERED"
        return verdict
    rc = dict(row)
    status = rc["registration_status"]
    expiry = parse_date(rc["registration_expiry_date"])
    if expiry and expiry < on:
        status = "EXPIRED"
    verdict.update(registration_status=status, valid_till=rc["registration_expiry_date"],
                   registration_date=rc["registration_date"],
                   vehicle={k: rc[k] for k in ("vehicle_make", "vehicle_model", "vehicle_type", "fuel_type", "color")},
                   owner_id=rc["owner_id"], owner_name=rc["owner_name"])  # owner_name masked unless POLICE/ADMIN
    return verdict


def police_verdict(conn, plate, on, role):
    row = conn.execute(
        """SELECT record_id, vehicle_no, theft_status, theft_report_date, recovery_date, scrapping_status,
                  scrapping_date, shredding_date, authority_reference, remarks, fir_no
           FROM theft_scrap_record WHERE vehicle_no = ? ORDER BY record_id DESC LIMIT 1""", (plate,)).fetchone()
    rec = dict(row) if row else None
    suspicion = compute_suspicion_status(rec)
    verdict = {"agency": "POLICE_CCTNS", "question": f"Is {plate} stolen or scrapped?", "plate": plate,
               "suspicion_status": suspicion, "has_record": rec is not None,
               "theft_status": (rec or {}).get("theft_status") or "NONE",
               "scrapping_status": (rec or {}).get("scrapping_status") or "NONE",
               "theft_report_date": (rec or {}).get("theft_report_date"),
               "recovery_date": (rec or {}).get("recovery_date"),
               "scrapping_date": (rec or {}).get("scrapping_date"),
               "shredding_date": (rec or {}).get("shredding_date")}
    if role in ("POLICE", "ADMIN"):
        verdict["authority_reference"] = (rec or {}).get("authority_reference")
        verdict["firs"] = [dict(r) for r in conn.execute(
            """SELECT f.fir_no, f.fir_date, f.offence_type, f.case_status, s.station_name, f.complainant_name
               FROM fir f JOIN police_station s ON s.station_id = f.station_id
               WHERE f.vehicle_no = ? ORDER BY f.fir_date DESC""", (plate,))]
    return verdict


def anpr_verdict(conn, plate, on, role):
    rows = [dict(r) for r in conn.execute(
        """SELECT capture_id, plate_number, captured_timestamp, camera_id, location, vehicle_type,
                  detected_make, detected_model, detected_color, confidence_score
           FROM vehicle_capture WHERE plate_number = ? ORDER BY captured_timestamp DESC""", (plate,))]
    last = rows[0] if rows else None
    verdict = {"agency": "TRAFFIC_ANPR", "question": f"Has {plate} been seen on the road?", "plate": plate,
               "seen_on_road": bool(rows), "detection_count": len(rows),
               "last_seen": {k: last[k] for k in ("captured_timestamp", "camera_id", "location", "vehicle_type",
                                                   "detected_make", "detected_model", "detected_color")} if last else None}
    if role in ("POLICE", "ADMIN"):
        verdict["captures"] = rows
    return verdict


def challan_verdict(conn, plate, on, role):
    rows = [dict(r) for r in conn.execute(
        """SELECT report_id, vehicle_identifier, report_type, report_reason, detected_at, severity, report_status,
                  submitted_at, ministry_reference, offence_code
           FROM ministry_report WHERE vehicle_identifier = ? ORDER BY submitted_at DESC, report_id DESC""", (plate,))]
    open_rows = [r for r in rows if r["report_status"] not in ("CLOSED", "RESOLVED")]
    latest = rows[0] if rows else None
    verdict = {"agency": "MORTH_ECHALLAN", "question": f"Does {plate} have open challans?", "plate": plate,
               "challan_count": len(rows), "open_challans": len(open_rows),
               "latest": {k: latest[k] for k in ("report_type", "report_status", "ministry_reference", "severity")}
               if latest else None}
    if role in ("POLICE", "ADMIN"):
        verdict["challans"] = rows
    return verdict


VERDICTS = {"IIB": insurance_verdict, "VAHAN": registration_verdict, "POLICE": police_verdict,
            "ANPR": anpr_verdict, "ECHALLAN": challan_verdict}


def register_verdict_endpoint(app, key, get_db):
    """Add GET /api/v1/verdict/<plate>[?on=YYYY-MM-DD] to an agency service."""
    from flask import request
    compute = VERDICTS[key]

    @app.route("/api/v1/verdict/<plate>", methods=["GET"])
    def verdict(plate):
        on = parse_date(request.args.get("on")) or config.SIMULATION_TODAY
        with get_db() as conn:
            return jsonify(compute(conn, _plate(plate), on, _role()))
