"""
Generate the unstructured document corpus (documents.db) from the seeded agency data.

Every document is free text written the way people write: the plate appears spaced, hyphenated,
in lower case, with an OCR slip (O/0, I/1, B/8, S/5, Z/2), or only as "ending 1004". Kinds:

  FIR_NARRATIVE    one per FIR (police)                                 visibility POLICE
  SURVEYOR_REPORT  one per insurance claim                              visibility INSURER
  OFFICER_NOTE     field notes for a sample of challans                 visibility POLICE
  NEWS             thefts, recoveries, accidents reported in the press  visibility ALL
  TIP_OFF          citizen sightings of stolen cars (after the theft)   visibility ALL
  GENERAL          road-safety news about no particular vehicle         visibility ALL
  decoys           news / tips about OTHER real cars whose plate is one or two characters
                   away from a demo vehicle's plate (hard negatives)

ground_truth records which vehicle each document is really about (evaluation only).
Deterministic (own random seed). Run: python -m seed.seed_documents
"""
import random
import sqlite3
from datetime import date, timedelta

import config
import db
from seed.vehicle_master_data import VEHICLES

rng = random.Random(77)
BY_PLATE = {v["plate"]: v for v in VEHICLES}
OCR_SWAPS = {"0": "O", "O": "0", "1": "I", "I": "1", "8": "B", "B": "8", "5": "S", "S": "5", "2": "Z", "Z": "2"}
DEMO = [f"DL01AB{1000 + n}" for n in range(1, 11)]
PLACES = {"Gurugram": ["Cyber Hub", "Sector 29 market", "Golf Course Road", "MG Road metro station"],
          "Delhi": ["Karol Bagh", "Lajpat Nagar market", "Connaught Place", "Rohini Sector 7"],
          "Bengaluru": ["Koramangala", "Indiranagar 100 ft road", "Whitefield", "Jayanagar 4th block"],
          "Mumbai": ["Andheri East", "Bandra Linking Road", "Powai", "Dadar TT circle"],
          "Chennai": ["T Nagar", "Velachery", "Anna Nagar", "Guindy"],
          "Noida": ["Sector 18 market", "Sector 62", "Botanical Garden metro", "Film City"],
          "Hyderabad": ["Banjara Hills", "Gachibowli", "Ameerpet", "Kukatpally"],
          "Kolkata": ["Salt Lake Sector V", "Park Street", "Howrah station", "New Town"]}
CITIES = list(PLACES)
NEWS_SOURCES = ["City Times", "Metro Daily", "The Highway Herald", "NewsLine 24x7", "Local Pulse"]


def _city(location):
    return (location or "Delhi").rsplit(",", 1)[-1].strip()


def home_city(v):
    return _city(v["captures"][0]["location"]) if v and v["captures"] else "Delhi"


def written(plate, style=None):
    """The plate as a person / OCR would write it."""
    style = style or rng.choice(["exact", "exact", "spaced", "spaced", "hyphen", "lower", "ocr", "ocr"])
    if style == "spaced":
        return f"{plate[:2]} {plate[2:4]} {plate[4:6]} {plate[6:]}"
    if style == "hyphen":
        return f"{plate[:2]}-{plate[2:4]}-{plate[4:6]}-{plate[6:]}"
    if style == "lower":
        return plate.lower()
    if style == "ocr":
        idx = [i for i, ch in enumerate(plate) if ch in OCR_SWAPS and i >= 2]
        if idx:
            i = rng.choice(idx)
            return plate[:i] + OCR_SWAPS[plate[i]] + plate[i + 1:]
    return plate


def vehicle_words(v):
    return f"{v['color'].lower()} {v['make']} {v['model']}"


def nice_date(iso):
    d = date.fromisoformat(iso[:10])
    return d.strftime("%d %b %Y").lstrip("0") if rng.random() < 0.5 else d.isoformat()


def _rows(path, sql):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def build_corpus():
    docs = []   # (doc_type, title, body, source, published_on, visibility, [plates])

    def add(doc_type, title, body, source, when, visibility, plates):
        docs.append((doc_type, title, body, source, when, visibility, plates))

    firs = _rows(config.DB_THEFT_SCRAP, """SELECT f.*, s.station_name, s.city AS station_city, r.recovery_date,
                                                 r.recovered_city, r.vehicle_condition
                                          FROM fir f JOIN police_station s USING (station_id)
                                          LEFT JOIN recovery r USING (fir_no) ORDER BY f.fir_no""")
    claims = _rows(config.DB_INSURANCE, """SELECT c.*, p.registration_no, p.policy_number, p.insurer_name
                                          FROM claim c JOIN insurance_policy p USING (policy_id) ORDER BY c.claim_id""")
    challans = _rows(config.DB_MINISTRY, """SELECT r.*, o.mv_act_section, o.fine_amount, e.officer_name, e.city AS officer_city
                                           FROM ministry_report r LEFT JOIN offence_code o USING (offence_code)
                                           LEFT JOIN enforcement_officer e USING (officer_id) ORDER BY r.report_id""")
    thefts = {f["vehicle_no"]: f for f in firs if f["offence_type"] == "VEHICLE_THEFT"}

    # --- FIR narratives (police only) ---------------------------------------------------------
    for f in firs:
        v = BY_PLATE.get(f["vehicle_no"])
        if not v:
            continue
        place = rng.choice(PLACES[f["station_city"]])
        if f["offence_type"] == "VEHICLE_THEFT":
            body = (f"FIR No. {f['fir_no']} was registered at {f['station_name']} on {nice_date(f['fir_date'])}. "
                    f"The complainant stated that the {vehicle_words(v)} bearing registration number "
                    f"{written(v['plate'])} was parked near {place}, {f['station_city']} and was found missing the next "
                    f"morning. The vehicle was reported stolen; the steering lock was broken. "
                    f"Investigating officer: {f['investigating_officer']}. Case status: {f['case_status'].lower()}.")
            if f["recovery_date"]:
                body += (f" Update: the car was recovered on {nice_date(f['recovery_date'])} in {f['recovered_city']}, "
                         f"condition {f['vehicle_condition'].lower().replace('_', ' ')}.")
            title = f"FIR {f['fir_no']} - vehicle theft, {f['station_city']}"
        else:
            kind = "hit-and-run" if f["offence_type"] == "HIT_AND_RUN" else "road accident"
            body = (f"FIR No. {f['fir_no']} registered at {f['station_name']} on {nice_date(f['fir_date'])} regarding a "
                    f"{kind} near {place}, {f['station_city']}. The {vehicle_words(v)} ({written(v['plate'])}) collided "
                    f"with a two-wheeler; one person was injured and taken to hospital. "
                    f"Investigating officer: {f['investigating_officer']}.")
            title = f"FIR {f['fir_no']} - {kind}, {f['station_city']}"
        add("FIR_NARRATIVE", title, body, f["station_name"], f["fir_date"], "POLICE", [v["plate"]])

    # --- surveyor reports (insurer only) --------------------------------------------------------
    descr = {"THEFT": "theft of the insured vehicle", "ACCIDENT": "accidental damage to the front bumper and bonnet",
             "FIRE": "fire damage; the engine bay was gutted", "FLOOD": "flood damage after the car was submerged"}
    for c in claims:
        v = BY_PLATE.get(c["registration_no"])
        if not v:
            continue
        fir = f" Police reference {c['fir_reference']}." if c["fir_reference"] else " No police report was filed."
        verdict = {"SETTLED": "Claim recommended for settlement.", "PENDING": "Assessment pending further documents.",
                   "REJECTED": "Claim not admissible."}[c["claim_status"]]
        if c["incident_type"] == "THEFT" and c["claim_status"] == "REJECTED":
            verdict = "Claim closed: the vehicle was traced and returned to the owner."
        body = (f"Surveyor report for claim {c['claim_no']} under policy {c['policy_number']} ({c['insurer_name']}). "
                f"Insured vehicle {written(v['plate'])}, a {vehicle_words(v)}. Incident on {nice_date(c['incident_date'])} "
                f"in {c['incident_city']}: {descr[c['incident_type']]}.{fir} Assessed loss Rs {int(c['claim_amount']):,}. "
                f"{verdict}")
        add("SURVEYOR_REPORT", f"Survey {c['claim_no']} - {c['incident_type'].lower()} claim",
            body, c["insurer_name"], c["incident_date"], "INSURER", [v["plate"]])

    # --- officer field notes (police only) ------------------------------------------------------
    notes = [c for c in challans if c["report_type"] in ("UNINSURED_VEHICLE", "EXPIRED_INSURANCE", "STOLEN_VEHICLE",
                                                          "SCRAPPED_VEHICLE_DETECTED")]
    picked = {c["report_id"]: c for c in rng.sample(notes, min(180, len(notes)))}
    picked.update({c["report_id"]: c for c in challans if c["vehicle_identifier"] in DEMO})
    for c in sorted(picked.values(), key=lambda c: c["report_id"]):
        v = BY_PLATE.get(c["vehicle_identifier"])
        if not v or not c["officer_name"]:
            continue
        reason = {"UNINSURED_VEHICLE": "the driver could not produce any insurance policy",
                  "EXPIRED_INSURANCE": "the insurance policy shown had expired",
                  "STOLEN_VEHICLE": "the plate matched the stolen-vehicle hotlist; the vehicle was detained",
                  "SCRAPPED_VEHICLE_DETECTED": "the registration belongs to a vehicle certified as scrapped",
                  "EXPIRED_REGISTRATION": "the registration certificate had expired",
                  "MULTIPLE_SUSPICIOUS_EVENTS": "the vehicle has a past theft record; papers were checked and noted",
                  }[c["report_type"]]
        when = (c["detected_at"] or c["submitted_at"])[:10]
        body = (f"Field note by {c['officer_name']}, {c['officer_city']}: on {nice_date(when)} intercepted a "
                f"{vehicle_words(v)} with plate {written(v['plate'])} at a checkpoint; {reason}. "
                f"e-Challan {c['ministry_reference']} issued under {c['mv_act_section']}.")
        add("OFFICER_NOTE", f"Field note - {c['report_type'].replace('_', ' ').lower()}", body,
            c["officer_name"], when, "POLICE", [v["plate"]])

    # --- news: thefts, recoveries, accidents (public) -------------------------------------------
    theft_news = rng.sample(sorted(thefts), min(70, len(thefts)))
    for plate in sorted(set(theft_news) | (set(DEMO) & set(thefts))):
        f, v = thefts[plate], BY_PLATE[plate]
        style = rng.choice(["ending", "noisy", "full"])
        ref = (f"registration ending {plate[-4:]}" if style == "ending" else
               f"registration {written(plate, 'ocr' if style == 'noisy' else rng.choice(['spaced', 'exact']))}")
        body = (f"{f['station_city']}: A {vehicle_words(v)} was stolen from near {rng.choice(PLACES[f['station_city']])} "
                f"on {nice_date(f['fir_date'])}. Police said the car, bearing {ref}, was taken at night and a case has "
                f"been registered. Residents complained of a rise in vehicle thefts in the area.")
        add("NEWS", f"Car stolen in {f['station_city']}", body, rng.choice(NEWS_SOURCES), f["fir_date"], "ALL", [plate])
        if f["recovery_date"] and rng.random() < 0.7:
            body = (f"{f['recovered_city']}: Police recovered a {vehicle_words(v)} ({written(plate)}) that had been "
                    f"reported stolen in {f['station_city']}. The car was found abandoned on {nice_date(f['recovery_date'])}; "
                    f"its condition was {f['vehicle_condition'].lower().replace('_', ' ')}.")
            add("NEWS", f"Stolen car recovered in {f['recovered_city']}", body, rng.choice(NEWS_SOURCES),
                f["recovery_date"], "ALL", [plate])
    for f in [x for x in firs if x["offence_type"] != "VEHICLE_THEFT"]:
        if f["vehicle_no"] not in DEMO and rng.random() > 0.6:
            continue
        v = BY_PLATE[f["vehicle_no"]]
        body = (f"{f['station_city']}: One person was injured when a {vehicle_words(v)} collided with a two-wheeler near "
                f"{rng.choice(PLACES[f['station_city']])} on {nice_date(f['fir_date'])}. Witnesses noted the number as "
                f"{written(v['plate'], 'ocr' if rng.random() < 0.4 else 'spaced')}. Police have registered a case.")
        add("NEWS", f"Accident in {f['station_city']}", body, rng.choice(NEWS_SOURCES), f["fir_date"], "ALL", [v["plate"]])

    # --- citizen tip-offs: sightings of stolen cars AFTER the theft (public) --------------------
    for plate, f in thefts.items():
        v = BY_PLATE[plate]
        if v["theft_scrap"]["theft_status"] != "STOLEN" and plate not in DEMO:
            continue
        for _ in range(2 if plate in DEMO else 1):
            seen_city = rng.choice([c for c in CITIES if c != f["station_city"]])
            when = date.fromisoformat(f["fir_date"]) + timedelta(days=rng.randint(3, 40))
            when = min(when, config.SIMULATION_TODAY).isoformat()
            body = (f"Tip-off received {nice_date(when)}: caller says a {v['color'].lower()} {v['model']} with number "
                    f"{written(plate, rng.choice(['ocr', 'lower', 'spaced']))} has been parked for two days near "
                    f"{rng.choice(PLACES[seen_city])}, {seen_city}. Looks like the car shown in the stolen-vehicle "
                    f"appeal. Number plate appeared to be tampered.")
            add("TIP_OFF", f"Sighting of a possibly stolen {v['model']} in {seen_city}", body,
                "Citizen helpline", when, "ALL", [plate])

    # --- decoys: OTHER real cars whose plates are close to the demo plates (hard negatives) ------
    for plate in DEMO:
        near = [p for p in BY_PLATE if p not in DEMO and sum(a != b for a, b in zip(p, plate)) == 1][:6]
        for other in rng.sample(near, min(4, len(near))):
            v = BY_PLATE[other]
            city = home_city(v)
            body = rng.choice([
                f"{city}: A {vehicle_words(v)} ({written(other, 'exact')}) was involved in a minor collision near "
                f"{rng.choice(PLACES[city])}; no one was hurt.",
                f"Tip-off: caller reports a {v['color'].lower()} {v['model']} {written(other, 'spaced')} parked in a "
                f"no-parking zone near {rng.choice(PLACES[city])}, {city} for several hours.",
            ])
            add("NEWS" if body.startswith(city) else "TIP_OFF", f"{v['model']} incident in {city}", body,
                rng.choice(NEWS_SOURCES), (config.SIMULATION_TODAY - timedelta(days=rng.randint(1, 60))).isoformat(),
                "ALL", [other])

    # --- general road-safety news (no vehicle) --------------------------------------------------
    topics = ["Traffic police launch drive against uninsured vehicles", "FASTag blacklist to cover stolen vehicles",
              "New scrapping policy: owners of old cars get incentives", "Monsoon waterlogging damages hundreds of cars",
              "Insurance claims for vehicle theft rise this year", "ANPR cameras installed at more toll plazas",
              "Helmet and seat-belt checks intensified", "Court clears backlog of traffic challans"]
    for i in range(80):
        city = rng.choice(CITIES)
        t = rng.choice(topics)
        body = (f"{city}: {t}. Officials said the drive will continue through the month, and motorists were asked to "
                f"keep their registration, insurance and pollution certificates up to date. Theft and accident "
                f"figures for the city were shared at a press briefing.")
        add("GENERAL", t, body, rng.choice(NEWS_SOURCES),
            (config.SIMULATION_TODAY - timedelta(days=rng.randint(1, 300))).isoformat(), "ALL", [])
    return docs


def seed(path=None):
    path = path or config.DB_DOCS
    db.run_script(path, config.SCHEMA_FILES[config.DB_DOCS])
    docs = build_corpus()
    conn = sqlite3.connect(path)
    try:
        for doc_type, title, body, source, when, visibility, plates in docs:
            cur = conn.execute("INSERT INTO documents (doc_type, title, body, source, published_on, visibility) "
                               "VALUES (?, ?, ?, ?, ?, ?)", (doc_type, title, body, source, when, visibility))
            conn.executemany("INSERT INTO ground_truth (doc_id, plate) VALUES (?, ?)", [(cur.lastrowid, p) for p in plates])
        conn.commit()
        counts = dict(conn.execute("SELECT doc_type, COUNT(*) FROM documents GROUP BY doc_type").fetchall())
    finally:
        conn.close()
    print(f"[seed_documents] {sum(counts.values())} documents: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return counts


if __name__ == "__main__":
    seed()
