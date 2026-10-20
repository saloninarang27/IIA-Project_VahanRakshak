"""
Approximate matching searches all five agency databases, not just VAHAN.
"""
from backend.mediator_app import app as mediator_app
from backend.IIB.iib_service import app as iib_app
from backend.POLICE_CCTNS.cctns_service import app as police_app
from backend.ANPR_CAMERA.anpr_service import app as anpr_app
from backend.ECHALLAN.echallan_service import app as echallan_app
from backend import matching_api
from matching.cleansing import assess_record
from matching.sources import build_reference_index, fetch_source_rows, SOURCE_KEYS


def test_every_service_exposes_its_identifiers_under_its_own_column():
    expected = {iib_app: "registration_no", police_app: "vehicle_no",
                anpr_app: "plate_number", echallan_app: "vehicle_identifier"}
    for app, column in expected.items():
        data = app.test_client().get("/api/v1/identifiers").get_json()
        assert data["query_key"] == column
        assert data["count"] == len(data["identifiers"]) > 0
        assert all("plate" in r for r in data["identifiers"])


def test_index_merges_all_five_sources():
    rows = fetch_source_rows(None)            # local replica files
    assert all(rows[k]["rows"] for k in SOURCE_KEYS)
    index = build_reference_index(rows)
    by_plate = {v["plate"]: v for v in index}
    # DL01AB1004 is registered, insured, reported stolen, seen by cameras and has a challan
    assert by_plate["DL01AB1004"]["sources"] == ["VAHAN", "IIB", "POLICE", "ANPR", "ECHALLAN"]
    # DL01AB1003 has no insurance policy at all
    assert "IIB" not in by_plate["DL01AB1003"]["sources"]
    assert len(index) == len({v["plate"] for v in index})   # one entry per plate


def _synthetic_rows():
    return {
        "VAHAN": {"rows": [{"registration_id": 1, "vehicle_registration_id": "DL01AB1001", "vehicle_make": "Honda",
                            "vehicle_model": "Civic", "color": "Black", "vehicle_type": "Sedan", "fuel_type": "Petrol",
                            "registration_status": "ACTIVE"}], "via": "API"},
        "IIB": {"rows": [{"plate": "DL01AB1001", "policies": 1}, {"plate": "KA05MX2481", "policies": 1}], "via": "API"},
        "POLICE": {"rows": [], "via": "API"},
        "ANPR": {"rows": [{"plate": "KA05MX2481", "sightings": 3, "detected_make": "Tata", "detected_model": "Nexon",
                           "detected_color": "Red", "vehicle_type": "SUV"}], "via": "API"},
        "ECHALLAN": {"rows": None, "via": "UNAVAILABLE"},
    }


def test_plate_missing_from_vahan_is_still_matchable_with_camera_attributes():
    index = build_reference_index(_synthetic_rows())
    unregistered = next(v for v in index if v["plate"] == "KA05MX2481")
    assert unregistered["sources"] == ["IIB", "ANPR"] and not unregistered["in_vahan"]
    assert (unregistered["make"], unregistered["attribute_source"]) == ("Tata", "ANPR")

    # exact reading: accepted, but flagged as not registered in VAHAN
    a = assess_record({"plate": "KA 05 MX 2481"}, index)
    assert a["decision"] == "ACCEPT" and "NOT_IN_VAHAN" in a["flags"]
    # noisy reading with confirming camera attributes: corrected to the plate VAHAN does not have
    a = assess_record({"plate": "KA05MX248", "make": "Tata", "model": "Nexon", "color": "Red"}, index)
    assert a["decision"] == "CORRECT" and a["corrected_plate"] == "KA05MX2481"
    assert a["candidates"][0]["sources"] == ["IIB", "ANPR"]


def test_noisy_value_stored_by_another_agency_is_still_corrected():
    """A camera stored the misread 'DL01AB1O01'; scanning that reading must not 'accept' the noise."""
    rows = _synthetic_rows()
    rows["ANPR"]["rows"].append({"plate": "DL01AB1O01", "sightings": 1})
    index = build_reference_index(rows)
    a = assess_record({"plate": "DL01AB1O01"}, index)
    assert a["decision"] == "CORRECT" and a["corrected_plate"] == "DL01AB1001"
    assert "NOT_IN_VAHAN" in a["flags"]


def test_api_reports_all_five_sources():
    matching_api.invalidate_index()
    client = mediator_app.test_client()
    sources = client.get("/api/v1/matching/config").get_json()["index"]["sources"]
    assert [s["key"] for s in sources] == SOURCE_KEYS
    assert all(s["plates"] > 0 for s in sources)
    result = client.post("/api/v1/matching/search", json={"plate": "DL01AB1O04"}).get_json()
    top = result["candidates"][0]
    assert top["plate"] == "DL01AB1004" and set(top["sources"]) == set(SOURCE_KEYS)
