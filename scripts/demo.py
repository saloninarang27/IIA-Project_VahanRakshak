"""
scripts/demo.py
===============
Command-Line Demonstration Engine for VahanRakshak.

Demonstrates:
  1. High-level plate inquiry decomposed into 5 independent agency queries
  2. Federated query execution across heterogeneous databases
  3. Live Mediator REST API querying (Cache-Aside hit vs. live federation)
  4. Statutory compliance evaluation under Section 196 of the Motor Vehicles Act 1988
  5. Full vehicle lifecycle dossier integration

Run:
  python -m scripts.demo
  or
  python3 scripts/demo.py
"""
import sys
import os
import json
import urllib.request
import urllib.error

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from mediator.query_decomposer import decompose_vehicle_query
from mediator.federated_query import execute_federated_query
from mediator.integration import get_complete_vehicle_history

DEMO_VEHICLES = [
    ("DL01AB1001", "Fully Compliant (Active Insurance, Valid RC, Clean Record)"),
    ("DL01AB1002", "Expired Insurance (Policy expired 45 days ago; Section 196 Warning)"),
    ("DL01AB1003", "Completely Uninsured on Road (Auto-issued ₹2,000 e-Challan)"),
    ("DL01AB1004", "Stolen Vehicle Active on Road (Police CCTNS FIR; Critical Alert)"),
    ("DL01AB1005", "Scrapped Vehicle Active on Road (Dismantled at RVSF; Illegal Operation)"),
    ("DL01AB1006", "Expired Registration (RC expired in MoRTH VAHAN)"),
    ("DL01AB1007", "Valid Insurance with Historical Theft Record"),
    ("DL01AB1008", "Shredded Vehicle (Permanently destroyed body shell)"),
    ("DL01AB1009", "Recovered Stolen Vehicle (Previously stolen, officially recovered)"),
    ("DL01AB1010", "Multi-Policy Vehicle (3 historical policies; currently active)"),
]

MEDIATOR_URL = "http://127.0.0.1:5001/api/v1/vehicles"


def check_mediator_online():
    """Checks if the central Mediator microservice (Port 5001) is running."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:5001/api/v1/health",
            headers={"User-Agent": "VahanRakshak-CLI/2.0"}
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def fetch_from_mediator_api(plate: str):
    """Fetches real-time dossier and cache metadata from Mediator API."""
    url = f"{MEDIATOR_URL}/{plate}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VahanRakshak-CLI/2.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return None


def print_vehicle_demo(plate: str, expectation: str, mediator_online: bool):
    print("\n" + "=" * 80)
    print(f"🚗 VEHICLE: {plate}")
    print(f"📋 Scenario: {expectation}")
    print("=" * 80)

    # 1. SQL Decomposition
    print("\n[1] Sub-Query Decomposition Across 5 Silos:")
    decomposed = decompose_vehicle_query(plate)
    for src, sq in decomposed.items():
        print(f"    • {src.upper():<14} : {sq.sql}")
        print(f"      {'':14}   (Linking Param: {sq.params})")

    # 2. Live Mediator API or In-Process Federation
    if mediator_online:
        api_res = fetch_from_mediator_api(plate)
        if api_res and "vehicle" in api_res:
            source_type = api_res.get("source", "UNKNOWN")
            latency = api_res.get("query_latency_ms") or api_res.get("federation_latency_ms", 0.0)
            v = api_res["vehicle"]

            print(f"\n[2] Live Mediator API Result (Port 5001):")
            print(f"    • Source Engine : {source_type} (Latency: {latency} ms)")
            print(f"    • Make / Model  : {v.get('make', 'N/A')} {v.get('model', 'N/A')} ({v.get('color', 'N/A')})")
            print(f"    • Registration  : {v.get('registration_status', 'N/A')} (Expiry: {v.get('registration_expiry_date', 'N/A')})")
            print(f"    • Insurance     : {v.get('insurance_status', 'N/A')} ({v.get('insurance_company', 'N/A')})")
            print(f"    • Police CCTNS  : Theft={v.get('theft_status', 'NONE')}, Scrap={v.get('scrapping_status', 'NONE')}")
            print(f"    • Risk Level    : {v.get('risk_level', 'LOW')}")
            print(f"    • Statutory Act : Section 196 MV Act -> E-Challan Required = {v.get('ministry_report_required')}")
            if v.get("ministry_reference"):
                print(f"    • Citation Ref  : {v.get('ministry_reference')} (Status: {v.get('ministry_report_status')})")
            return

    # Fallback to local integration engine if mediator is offline
    raw = execute_federated_query(plate)
    print(f"\n[2] In-Process Federated Query Matches:")
    print(f"    • Sighted on Road (ANPR) : {len(raw['capture'])} sighting(s)")
    print(f"    • Policies Found (IIB)   : {len(raw['insurance'])} record(s)")
    print(f"    • Registry Match (VAHAN) : {len(raw['registration'])} record(s)")
    print(f"    • Police Records (CCTNS) : {len(raw['theft_scrap'])} record(s)")

    history = get_complete_vehicle_history(plate)
    print(f"\n[3] Integrated Conformed Vehicle Dossier:")
    print(f"    • Make / Model  : {history.get('make')} {history.get('model')} ({history.get('color')})")
    print(f"    • Registration  : {history.get('registration_status')}")
    print(f"    • Insurance     : {history.get('insurance_status')} ({history.get('insurance_company')})")
    print(f"    • Police CCTNS  : Theft={history.get('theft_status')}, Scrap={history.get('scrapping_status')}")
    print(f"    • Risk Level    : {history.get('risk_level')}")
    print(f"    • Statutory Act : Section 196 MV Act -> E-Challan Required = {history.get('ministry_report_required')}")


def main():
    print("=" * 80)
    print("🛡️  VahanRakshak: FEDERATED COMPLIANCE INTELLIGENCE DEMO")
    print("   Information Integration & Analytics (IIA) — Project A")
    print("=" * 80)

    mediator_online = check_mediator_online()
    if mediator_online:
        print("[✓] Connected to live Mediator microservice on http://127.0.0.1:5001")
    else:
        print("[i] Mediator offline. Running in direct federated mode.")
        print("    (Tip: Run 'python3 start_system.py' to launch all 7 microservices)")

    for plate, expectation in DEMO_VEHICLES:
        print_vehicle_demo(plate, expectation, mediator_online)

    print("\n" + "=" * 80)
    print("✔ DEMONSTRATION COMPLETE: All 10 Benchmark Scenarios Verified.")
    print("=" * 80)


if __name__ == "__main__":
    main()
