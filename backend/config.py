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
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# ---------------------------------------------------------------------------
# Load .env file if present
# ---------------------------------------------------------------------------
def _load_env():
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(env_path):
        return
    try:
        import dotenv
        dotenv.load_dotenv(env_path)
    except Exception:
        # Native fallback parser if python-dotenv is not available
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass

_load_env()

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
# Host & Service URLs Configuration
# ---------------------------------------------------------------------------
# If REMOTE_HOST or SERVICES_HOST is specified in .env, all microservices point to that IP.
# Individual HOST_* or URL_* variables can also be set for fine-grained overrides.
# If commented out, empty, or missing, defaults to 127.0.0.1 (local).
DEFAULT_HOST = os.environ.get("SERVICES_HOST") or os.environ.get("REMOTE_HOST") or "127.0.0.1"

HOST_IIB = os.environ.get("HOST_IIB") or DEFAULT_HOST
HOST_VAHAN = os.environ.get("HOST_VAHAN") or DEFAULT_HOST
HOST_POLICE = os.environ.get("HOST_POLICE") or DEFAULT_HOST
HOST_ANPR = os.environ.get("HOST_ANPR") or DEFAULT_HOST
HOST_ECHALLAN = os.environ.get("HOST_ECHALLAN") or DEFAULT_HOST
HOST_MEDIATOR = os.environ.get("HOST_MEDIATOR") or "127.0.0.1"

URL_IIB = os.environ.get("URL_IIB") or f"http://{HOST_IIB}:{PORT_IIB}"
URL_VAHAN = os.environ.get("URL_VAHAN") or f"http://{HOST_VAHAN}:{PORT_VAHAN}"
URL_POLICE = os.environ.get("URL_POLICE") or f"http://{HOST_POLICE}:{PORT_POLICE}"
URL_ANPR = os.environ.get("URL_ANPR") or f"http://{HOST_ANPR}:{PORT_ANPR}"
URL_ECHALLAN = os.environ.get("URL_ECHALLAN") or f"http://{HOST_ECHALLAN}:{PORT_ECHALLAN}"
URL_MEDIATOR = os.environ.get("URL_MEDIATOR") or f"http://{HOST_MEDIATOR}:{PORT_MEDIATOR}"

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
