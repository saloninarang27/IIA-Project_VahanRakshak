"""
Central Configuration for the Distributed Vehicle Verification Architecture.

Defines ports, URLs, DB paths, and cache TTL settings for:
- 5 Independent Agency Microservices (Local Schemas)
- 1 Central Mediator Application (Global Schema Coordinator & Cache)
- 1 Frontend Presentation Server
"""
import os
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Ports Configuration
# ---------------------------------------------------------------------------
PORT_FRONTEND = int(os.environ.get("PORT_FRONTEND", 3000))
PORT_MEDIATOR = int(os.environ.get("PORT_MEDIATOR", 5001))
PORT_IIB = int(os.environ.get("PORT_IIB", 5002))
PORT_VAHAN = int(os.environ.get("PORT_VAHAN", 5003))
PORT_POLICE = int(os.environ.get("PORT_POLICE", 5004))
PORT_ANPR = int(os.environ.get("PORT_ANPR", 5005))
PORT_ECHALLAN = int(os.environ.get("PORT_ECHALLAN", 5006))

# ---------------------------------------------------------------------------
# Service URLs (for Mediator -> Local Microservice calls)
# ---------------------------------------------------------------------------
URL_IIB = f"http://127.0.0.1:{PORT_IIB}"
URL_VAHAN = f"http://127.0.0.1:{PORT_VAHAN}"
URL_POLICE = f"http://127.0.0.1:{PORT_POLICE}"
URL_ANPR = f"http://127.0.0.1:{PORT_ANPR}"
URL_ECHALLAN = f"http://127.0.0.1:{PORT_ECHALLAN}"
URL_MEDIATOR = f"http://127.0.0.1:{PORT_MEDIATOR}"

# ---------------------------------------------------------------------------
# Database Filepaths (Paired inside each respective service folder)
# ---------------------------------------------------------------------------
DB_IIB = os.path.join(BASE_DIR, "IIB", "insurance_iib.db")
DB_VAHAN = os.path.join(BASE_DIR, "VAHAN", "parivahan_vahan.db")
DB_POLICE = os.path.join(BASE_DIR, "POLICE_CCTNS", "theft_scrap.db")
DB_ANPR = os.path.join(BASE_DIR, "ANPR_CAMERA", "vehicle_capture.db")
DB_ECHALLAN = os.path.join(BASE_DIR, "ECHALLAN", "ministry_echallan.db")
DB_DWH = os.path.join(BASE_DIR, "dwh", "warehouse_dwh.db")

# ---------------------------------------------------------------------------
# Cache & Simulation Settings
# ---------------------------------------------------------------------------
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", 300))  # 5 minutes TTL
SIMULATION_TODAY = date(2026, 9, 14)
