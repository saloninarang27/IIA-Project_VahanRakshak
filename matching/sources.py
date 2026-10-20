"""
The five agency databases as plate sources for approximate matching.

Each agency microservice exposes the distinct vehicle identifiers it holds (under
its own local column name). The Mediator fetches all five in parallel and merges
them into one reference index keyed by the normalised plate, so a reading is
matched against every plate known to ANY agency, and each candidate records which
databases contain it.

SQL here is only the Mediator's offline fallback (reading a local replica file when
a service is unreachable); the services run the same projection themselves.
"""
import os
import sqlite3

import backend.config as config

# key, label, local identifier column, service path, local replica, fallback SQL
SOURCES = [
    ("VAHAN", "MoRTH VAHAN (registration)", "vehicle_registration_id",
     f"{config.URL_VAHAN}/api/v1/registry/index", config.DB_VAHAN,
     """SELECT registration_id, vehicle_registration_id, vehicle_make, vehicle_model, color,
               vehicle_type, fuel_type, registration_status
        FROM vehicle_registration ORDER BY vehicle_registration_id"""),
    ("IIB", "IIB (insurance)", "registration_no",
     f"{config.URL_IIB}/api/v1/identifiers", config.DB_IIB,
     """SELECT registration_no AS plate, COUNT(*) AS policies, MAX(policy_expiry_date) AS latest_expiry
        FROM insurance_policy GROUP BY registration_no"""),
    ("POLICE", "Police CCTNS (theft / scrap)", "vehicle_no",
     f"{config.URL_POLICE}/api/v1/identifiers", config.DB_POLICE,
     """SELECT vehicle_no AS plate, theft_status, scrapping_status
        FROM theft_scrap_record GROUP BY vehicle_no"""),
    ("ANPR", "ANPR cameras (sightings)", "plate_number",
     f"{config.URL_ANPR}/api/v1/identifiers", config.DB_ANPR,
     """SELECT plate_number AS plate, COUNT(*) AS sightings, MAX(captured_timestamp) AS last_seen,
               detected_make, detected_model, detected_color, vehicle_type
        FROM vehicle_capture GROUP BY plate_number"""),
    ("ECHALLAN", "MoRTH e-Challan", "vehicle_identifier",
     f"{config.URL_ECHALLAN}/api/v1/identifiers", config.DB_ECHALLAN,
     """SELECT vehicle_identifier AS plate, COUNT(*) AS challans
        FROM ministry_report GROUP BY vehicle_identifier"""),
]
SOURCE_KEYS = [s[0] for s in SOURCES]


def _plate(text):
    return "".join(ch for ch in (text or "").upper() if ch.isalnum())


def _read_local(db_path, sql):
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def fetch_source_rows(fetch_service):
    """
    Pull identifier rows from all five services in parallel.
    Returns {key: {"rows": [...] | None, "via": "API" | "LOCAL_REPLICA" | "UNAVAILABLE", "error"}}.
    """
    from concurrent.futures import ThreadPoolExecutor

    def one(source):
        key, label, _, url, db_path, sql = source
        result = {"rows": None, "via": "UNAVAILABLE", "error": None}
        if fetch_service is not None:
            res = fetch_service(url, f"{label} - identifiers")
            data = res.get("data") or {}
            rows = data.get("vehicles") if key == "VAHAN" else data.get("identifiers")
            if res["status"] == 200 and rows is not None:
                return key, {"rows": rows, "via": "API", "error": None}
            result["error"] = res.get("error") or f"HTTP {res['status']}"
        try:
            rows = _read_local(db_path, sql)
        except sqlite3.Error as e:
            rows, result["error"] = None, str(e)
        if rows is not None:
            result.update(rows=rows, via="LOCAL_REPLICA")
        return key, result

    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        return dict(pool.map(one, SOURCES))


def build_reference_index(source_rows):
    """
    Merge the five identifier lists into one matcher index.

    Vehicle attributes (make, model, colour, type) come from VAHAN; for a plate VAHAN
    does not know, the latest ANPR camera detection is used instead. Every entry has
    "sources" (keys of the databases that hold the plate) and "in_vahan".
    """
    merged = {}

    def entry(plate):
        return merged.setdefault(plate, {
            "vehicle_id": None, "plate": plate, "make": None, "model": None, "color": None,
            "vehicle_type": None, "fuel_type": None, "registration_status": None,
            "attribute_source": None, "sources": [], "source_details": {},
        })

    for key in SOURCE_KEYS:
        rows = (source_rows.get(key) or {}).get("rows") or []
        for r in rows:
            plate = _plate(r.get("vehicle_registration_id") if key == "VAHAN" else r.get("plate"))
            if not plate:
                continue
            e = entry(plate)
            if key not in e["sources"]:
                e["sources"].append(key)
            if key == "VAHAN":
                e.update(vehicle_id=r.get("registration_id"), make=r.get("vehicle_make"), model=r.get("vehicle_model"),
                         color=r.get("color"), vehicle_type=r.get("vehicle_type"), fuel_type=r.get("fuel_type"),
                         registration_status=r.get("registration_status"), attribute_source="VAHAN")
            else:
                e["source_details"][key] = {k: v for k, v in r.items() if k != "plate"}
                if key == "ANPR" and e["attribute_source"] is None:
                    e.update(make=r.get("detected_make"), model=r.get("detected_model"),
                             color=r.get("detected_color"), vehicle_type=r.get("vehicle_type"), attribute_source="ANPR")

    index = []
    for e in sorted(merged.values(), key=lambda v: v["plate"]):
        e["in_vahan"] = "VAHAN" in e["sources"]
        e["sources"].sort(key=SOURCE_KEYS.index)
        index.append(e)
    return index


def source_summary(source_rows, index):
    counts = {k: 0 for k in SOURCE_KEYS}
    for v in index:
        for k in v["sources"]:
            counts[k] += 1
    return [{"key": key, "label": label, "identifier_column": column,
             "via": (source_rows.get(key) or {}).get("via", "UNAVAILABLE"),
             "error": (source_rows.get(key) or {}).get("error"),
             "plates": counts[key]}
            for key, label, column, *_ in SOURCES]
