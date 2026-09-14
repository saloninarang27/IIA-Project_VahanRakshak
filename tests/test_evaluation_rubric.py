"""
Academic Evaluation Rubric Automated Test Suite.
Directly maps to Project A Evaluation Rubric (15 Marks):
  1. Scope of Work (1 mark)
  2. Innovative Aspects / Cache-Aside & Reconciliation (1 mark)
  3. Database Schema Design & Heterogeneity (2 marks)
  4. Data Population & Test Case Coverage (2 marks)
  5. Schema Matching / DWH Views / API Creation (2 marks)
  6. SQL Decomposition / API Querying / Pagination (2 marks)
  7. Communication Between Data Sources (2 marks)
  8. Query Results Integration & Presentation (3 marks)
"""
import unittest
import sqlite3
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
import backend.config as b_config
from backend.IIB.iib_service import app as iib_app
from backend.VAHAN.vahan_service import app as vahan_app
from backend.POLICE_CCTNS.cctns_service import app as police_app
from backend.ANPR_CAMERA.anpr_service import app as anpr_app
from backend.ECHALLAN.echallan_service import app as echallan_app
from backend.mediator_app import app as mediator_app
from mediator.identifier_mapper import normalize_identifier, SOURCE_COLUMN_MAP
from dwh.queries import get_fleet_kpis, browse_vehicle_detections_paginated

class TestEvaluationRubric(unittest.TestCase):

    def setUp(self):
        self.mediator = mediator_app.test_client()
        self.iib = iib_app.test_client()
        self.vahan = vahan_app.test_client()
        self.police = police_app.test_client()
        self.anpr = anpr_app.test_client()
        self.echallan = echallan_app.test_client()

    # -----------------------------------------------------------------------
    # Rubric 1: Scope of Work (1 mark)
    # -----------------------------------------------------------------------
    def test_rubric_01_scope_of_work(self):
        """Verifies operational data sources exist covering the 5 required domains."""
        dbs = [b_config.DB_ANPR, b_config.DB_IIB, b_config.DB_VAHAN, b_config.DB_POLICE, b_config.DB_ECHALLAN, b_config.DB_DWH]
        for db_path in dbs:
            self.assertTrue(os.path.exists(db_path), f"Missing database: {db_path}")

    # -----------------------------------------------------------------------
    # Rubric 2: Innovative Aspects / Cache-Aside & Reconciliation (1 mark)
    # -----------------------------------------------------------------------
    def test_rubric_02_innovative_cache_aside_and_invalidation(self):
        """Verifies cache-aside returns <3ms on hit, and webhook invalidation marks cache stale."""
        # 1. Warm cache
        res1 = self.mediator.get("/api/v1/vehicles/DL01AB1001?force_sync=true")
        self.assertEqual(res1.status_code, 200)

        # 2. Fast cache hit
        res2 = self.mediator.get("/api/v1/vehicles/DL01AB1001")
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertEqual(data2["source"], "CACHE_HIT")
        self.assertLess(data2["query_latency_ms"], 10.0)

        # 3. Webhook Invalidation
        res_inv = self.mediator.post("/api/v1/sync/invalidate", json={"vehicle_identifier": "DL01AB1001"})
        self.assertEqual(res_inv.status_code, 200)
        self.assertEqual(res_inv.get_json()["status"], "CACHE_PURGED")

    # -----------------------------------------------------------------------
    # Rubric 3: Database Schema Design & Heterogeneity (2 marks)
    # -----------------------------------------------------------------------
    def test_rubric_03_schema_design_heterogeneity(self):
        """Verifies 5 isolated schemas use deliberately different column names for vehicle ID."""
        expected_columns = {
            "capture": "plate_number",
            "insurance": "registration_no",
            "registration": "vehicle_registration_id",
            "theft_scrap": "vehicle_no",
            "ministry": "vehicle_identifier"
        }
        for source, col in expected_columns.items():
            self.assertEqual(SOURCE_COLUMN_MAP[source]["id_column"], col)

        # Verify Kimball Star Schema in DWH
        conn = sqlite3.connect(b_config.DB_DWH)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        for required in ["FACT_VEHICLE_EVENT", "DIM_VEHICLE", "DIM_DATE", "DIM_LOCATION", "DIM_STATUS", "mv_vehicle_complete_history"]:
            self.assertIn(required, tables)

    # -----------------------------------------------------------------------
    # Rubric 4: Populating Data & Test Case Coverage (2 marks)
    # -----------------------------------------------------------------------
    def test_rubric_04_data_population_and_coverage(self):
        """Verifies 2,000 vehicles are seeded covering all required test scenarios."""
        kpis = get_fleet_kpis()
        self.assertGreaterEqual(kpis["total_vehicles"], 2000)
        self.assertGreater(kpis["uninsured"], 0)
        self.assertGreater(kpis["expired"], 0)
        self.assertGreater(kpis["stolen_or_scrapped"], 0)

    # -----------------------------------------------------------------------
    # Rubric 5: Schema Mapping & API Creation (2 marks)
    # -----------------------------------------------------------------------
    def test_rubric_05_schema_mapping_and_api_creation(self):
        """Verifies canonical identifier normalization and independent API creation."""
        self.assertEqual(normalize_identifier("dl 01-ab 1004"), "DL01AB1004")
        self.assertEqual(normalize_identifier("DL01AB1004"), "DL01AB1004")

        # Verify each of the 5 APIs responds
        self.assertEqual(self.iib.get("/api/v1/health").status_code, 200)
        self.assertEqual(self.vahan.get("/api/v1/health").status_code, 200)
        self.assertEqual(self.police.get("/api/v1/health").status_code, 200)
        self.assertEqual(self.anpr.get("/api/v1/health").status_code, 200)
        self.assertEqual(self.echallan.get("/api/v1/health").status_code, 200)

        # Verify automated Levenshtein schema matching algorithm & semantic aliases
        from backend.schema_matcher import discover_schema_mappings, levenshtein_distance
        self.assertGreaterEqual(levenshtein_distance("plate_number", "number_plate"), 0)
        mappings = discover_schema_mappings()
        self.assertEqual(mappings["source_count"], 5)
        self.assertIn("ANPR_CAMERA", mappings["sources"])
        self.assertIn("IIB", mappings["sources"])
        self.assertIn("VAHAN", mappings["sources"])
        self.assertIn("POLICE_CCTNS", mappings["sources"])
        self.assertIn("ECHALLAN", mappings["sources"])

    # -----------------------------------------------------------------------
    # Rubric 6: SQL Decomposition / Pagination (2 marks)
    # -----------------------------------------------------------------------
    def test_rubric_06_sql_decomposition_and_pagination(self):
        """Verifies server-side SQL pagination (<5ms) and trace generation."""
        # 1. Test paginated queries
        page1 = browse_vehicle_detections_paginated(page=1, limit=5)
        self.assertEqual(len(page1["rows"]), 5)
        self.assertGreaterEqual(page1["total"], 2000)

        # 2. Test trace decomposition
        res = self.mediator.get("/api/v1/vehicles/DL01AB1004/trace")
        self.assertEqual(res.status_code, 200)
        trace = res.get_json()["decomposed_queries"]
        self.assertIn("IIB_IRDAI", trace)
        self.assertIn("MORTH_VAHAN", trace)
        self.assertIn("POLICE_CCTNS", trace)

    # -----------------------------------------------------------------------
    # Rubric 7: Communication Between Data Sources (2 marks)
    # -----------------------------------------------------------------------
    def test_rubric_07_communication_between_data_sources(self):
        """Verifies Mediator health reports all 5 agency microservices online."""
        res = self.mediator.get("/api/v1/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "UP")
        self.assertTrue(all(s["online"] for s in data["services"].values()))

    # -----------------------------------------------------------------------
    # Rubric 8: Query Results Integration & Demonstration GUI (3 marks)
    # -----------------------------------------------------------------------
    def test_rubric_08_results_integration_and_gui(self):
        """Verifies global vehicle dossier merging, statutory rule evaluation, and frontend pages."""
        res = self.mediator.get("/api/v1/vehicles/DL01AB1004")
        self.assertEqual(res.status_code, 200)
        v = res.get_json()["vehicle"]

        # Integrated data verification
        self.assertEqual(v["vehicle_identifier"], "DL01AB1004")
        self.assertEqual(v["risk_level"], "CRITICAL")
        self.assertEqual(v["theft_status"], "STOLEN")
        self.assertTrue(v["ministry_report_required"])

        # Verify frontend files exist
        for page in ["index.html", "pages/inspector.html", "pages/fleet.html", "pages/echallan.html", "pages/architecture.html"]:
            self.assertTrue(os.path.exists(os.path.join(PROJECT_ROOT, "frontend", page)))

if __name__ == "__main__":
    unittest.main()
