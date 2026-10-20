"""
The five agency databases - the single description of where each one keeps its
vehicle identifier.

Every agency names the same vehicle differently (vehicle_registration_id,
registration_no, vehicle_no, plate_number, vehicle_identifier). SOURCES records, per
agency: table, identifier column, primary key, the columns that describe the vehicle
(used as matching context) and the microservice URLs. The approximate matcher, the
agency-data cleanser and the legacy in-process mediator (mediator/identifier_mapper.py)
all read this one map.

Each agency microservice exposes the distinct identifiers it holds. The Mediator
fetches all five in parallel and merges them into one reference index keyed by the
normalised plate, so a reading is matched against every plate known to ANY agency,
and each candidate records which databases contain it.

The SQL here is only the Mediator's offline fallback (reading a local replica file when
a service is unreachable); the services run the same projection themselves.
"""
import os
import sqlite3

import backend.config as config

SOURCES = [
    {
        "key": "VAHAN", "label": "MoRTH VAHAN (registration)", "legacy_key": "registration",
        "table": "vehicle_registration", "id_column": "vehicle_registration_id", "pk_column": "registration_id",
        "context_columns": {"make": "vehicle_make", "model": "vehicle_model", "color": "color", "vehicle_type": "vehicle_type"},
        "base_url": config.URL_VAHAN, "identifiers_path": "/api/v1/registry/index", "local_db": config.DB_VAHAN,
        "fallback_sql": """SELECT registration_id, vehicle_registration_id, vehicle_make, vehicle_model, color,
                                  vehicle_type, fuel_type, registration_status
                           FROM vehicle_registration ORDER BY vehicle_registration_id""",
    },
    {
        "key": "IIB", "label": "IIB (insurance)", "legacy_key": "insurance",
        "table": "insurance_policy", "id_column": "registration_no", "pk_column": "policy_id",
        "context_columns": {},
        "base_url": config.URL_IIB, "identifiers_path": "/api/v1/identifiers", "local_db": config.DB_IIB,
        "fallback_sql": """SELECT registration_no AS plate, COUNT(*) AS policies, MAX(policy_expiry_date) AS latest_expiry
                           FROM insurance_policy GROUP BY registration_no""",
    },
    {
        "key": "POLICE", "label": "Police CCTNS (theft / scrap)", "legacy_key": "theft_scrap",
        "table": "theft_scrap_record", "id_column": "vehicle_no", "pk_column": "record_id",
        "context_columns": {},
        "base_url": config.URL_POLICE, "identifiers_path": "/api/v1/identifiers", "local_db": config.DB_POLICE,
        "fallback_sql": """SELECT vehicle_no AS plate, theft_status, scrapping_status
                           FROM theft_scrap_record GROUP BY vehicle_no""",
    },
    {
        "key": "ANPR", "label": "ANPR cameras (sightings)", "legacy_key": "capture",
        "table": "vehicle_capture", "id_column": "plate_number", "pk_column": "capture_id",
        "context_columns": {"make": "detected_make", "model": "detected_model", "color": "detected_color",
                            "vehicle_type": "vehicle_type"},
        "base_url": config.URL_ANPR, "identifiers_path": "/api/v1/identifiers", "local_db": config.DB_ANPR,
        "fallback_sql": """SELECT plate_number AS plate, COUNT(*) AS sightings, MAX(captured_timestamp) AS last_seen,
                                  detected_make, detected_model, detected_color, vehicle_type
                           FROM vehicle_capture GROUP BY plate_number""",
    },
    {
        "key": "ECHALLAN", "label": "MoRTH e-Challan", "legacy_key": "ministry",
        "table": "ministry_report", "id_column": "vehicle_identifier", "pk_column": "report_id",
        "context_columns": {},
        "base_url": config.URL_ECHALLAN, "identifiers_path": "/api/v1/identifiers", "local_db": config.DB_ECHALLAN,
        "fallback_sql": """SELECT vehicle_identifier AS plate, COUNT(*) AS challans
                           FROM ministry_report GROUP BY vehicle_identifier""",
    },
]
SOURCE_KEYS = [s["key"] for s in SOURCES]
SOURCES_BY_KEY = {s["key"]: s for s in SOURCES}


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
        key = source["key"]
        result = {"rows": None, "via": "UNAVAILABLE", "error": None}
        if fetch_service is not None:
            res = fetch_service(source["base_url"] + source["identifiers_path"], f"{source['label']} - identifiers")
            data = res.get("data") or {}
            rows = data.get("vehicles") if key == "VAHAN" else data.get("identifiers")
            if res["status"] == 200 and rows is not None:
                return key, {"rows": rows, "via": "API", "error": None}
            result["error"] = res.get("error") or f"HTTP {res['status']}"
        try:
            rows = _read_local(source["local_db"], source["fallback_sql"])
        except sqlite3.Error as e:
            rows, result["error"] = None, str(e)
        if rows is not None:
            result.update(rows=rows, via="LOCAL_REPLICA")
        return key, result

    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        return dict(pool.map(one, SOURCES))


def build_reference_index(source_rows, only=None):
    """
    Merge the five identifier lists into one matcher index.

    Vehicle attributes (make, model, colour, type) come from VAHAN; for a plate VAHAN
    does not know, the latest ANPR camera detection is used instead. Every entry has
    "sources" (keys of the databases that hold the plate) and "in_vahan".
    only: optional list of source keys to restrict the index to (e.g. ["VAHAN"]).
    """
    merged = {}

    def entry(plate):
        return merged.setdefault(plate, {
            "vehicle_id": None, "plate": plate, "make": None, "model": None, "color": None,
            "vehicle_type": None, "fuel_type": None, "registration_status": None,
            "attribute_source": None, "sources": [], "source_details": {},
        })

    for key in SOURCE_KEYS:
        if only and key not in only:
            continue
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
    return [{"key": s["key"], "label": s["label"], "identifier_column": s["id_column"],
             "via": (source_rows.get(s["key"]) or {}).get("via", "UNAVAILABLE"),
             "error": (source_rows.get(s["key"]) or {}).get("error"),
             "plates": counts[s["key"]]}
            for s in SOURCES]
