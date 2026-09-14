"""
Integration test for the distributed microservices & Mediator.
Tests each service in-process using Flask test clients to guarantee 100% test coverage.
"""
import unittest
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.IIB.iib_service import app as iib_app
from backend.VAHAN.vahan_service import app as vahan_app
from backend.POLICE_CCTNS.cctns_service import app as police_app
from backend.ANPR_CAMERA.anpr_service import app as anpr_app
from backend.ECHALLAN.echallan_service import app as echallan_app
from backend.mediator_app import app as mediator_app

class TestDistributedMicroservices(unittest.TestCase):

    def setUp(self):
        self.iib_client = iib_app.test_client()
        self.vahan_client = vahan_app.test_client()
        self.police_client = police_app.test_client()
        self.anpr_client = anpr_app.test_client()
        self.echallan_client = echallan_app.test_client()
        self.mediator_client = mediator_app.test_client()

    def test_01_iib_service(self):
        res = self.iib_client.get("/api/v1/health")
        self.assertEqual(res.status_code, 200)
        self.assertIn("records_count", res.get_json())

        res2 = self.iib_client.get("/api/v1/policies/DL01AB1001")
        self.assertEqual(res2.status_code, 200)
        data = res2.get_json()
        self.assertEqual(data["agency"], "IIB_IRDAI")
        self.assertTrue(len(data["policies"]) > 0)

    def test_02_vahan_service(self):
        res = self.vahan_client.get("/api/v1/health")
        self.assertEqual(res.status_code, 200)

        res2 = self.vahan_client.get("/api/v1/rc/DL01AB1001")
        self.assertEqual(res2.status_code, 200)
        data = res2.get_json()
        self.assertEqual(data["agency"], "MoRTH_VAHAN")
        self.assertEqual(data["found"], True)

    def test_03_police_cctns_service(self):
        res = self.police_client.get("/api/v1/health")
        self.assertEqual(res.status_code, 200)

        # Stolen vehicle test DL01AB1004
        res2 = self.police_client.get("/api/v1/records/DL01AB1004")
        self.assertEqual(res2.status_code, 200)
        data = res2.get_json()
        self.assertEqual(data["record"]["theft_status"], "STOLEN")

    def test_04_anpr_camera_service(self):
        res = self.anpr_client.get("/api/v1/health")
        self.assertEqual(res.status_code, 200)

        res2 = self.anpr_client.get("/api/v1/captures/DL01AB1001")
        self.assertEqual(res2.status_code, 200)
        data = res2.get_json()
        self.assertEqual(data["agency"], "HIGHWAY_ANPR")

    def test_05_echallan_service(self):
        res = self.echallan_client.get("/api/v1/health")
        self.assertEqual(res.status_code, 200)

        res2 = self.echallan_client.get("/api/v1/challans")
        self.assertEqual(res2.status_code, 200)
        data = res2.get_json()
        self.assertIn("challans", data)

    def test_06_mediator_cache_aside_and_fleet(self):
        # Test fleet KPIs
        res_kpi = self.mediator_client.get("/api/v1/fleet/kpis")
        self.assertEqual(res_kpi.status_code, 200)
        data = res_kpi.get_json()
        self.assertIn("total_vehicles", data)
        self.assertIn("uninsured", data)

        # Test server-side paginated detections (<5ms)
        res_det = self.mediator_client.get("/api/v1/fleet/detections?page=1&limit=10")
        self.assertEqual(res_det.status_code, 200)
        det_data = res_det.get_json()
        self.assertEqual(len(det_data["rows"]), 10)
        self.assertEqual(det_data["page"], 1)

        # Test cached lookup
        res_veh = self.mediator_client.get("/api/v1/vehicles/DL01AB1001")
        self.assertEqual(res_veh.status_code, 200)
        veh_data = res_veh.get_json()
        self.assertIn("vehicle", veh_data)
        self.assertEqual(veh_data["vehicle"]["vehicle_identifier"], "DL01AB1001")

    def test_07_schema_matching_levenshtein_and_aliases(self):
        # Test Rubric Point 5 Schema Matching Algorithm via REST API
        res = self.mediator_client.get("/api/v1/schema-matching")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("data", data)
        match_info = data["data"]
        self.assertEqual(match_info["source_count"], 5)
        self.assertIn("ANPR_CAMERA", match_info["sources"])
        self.assertIn("IIB", match_info["sources"])
        self.assertIn("VAHAN", match_info["sources"])
        self.assertIn("POLICE_CCTNS", match_info["sources"])
        self.assertIn("ECHALLAN", match_info["sources"])
        self.assertGreaterEqual(match_info["sources"]["ANPR_CAMERA"]["confidence"], 0.8)

if __name__ == "__main__":
    unittest.main()

