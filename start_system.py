#!/usr/bin/env python3
"""
VahanRakshak: Unified Multi-Service System Launcher.

Starts all components of the distributed architecture simultaneously:
- 5 Independent Agency Microservices (Ports 5002-5006)
- 1 Central Mediator Application & Cache (Port 5001)
- 1 Frontend Presentation Server (Port 3000)

Handles graceful shutdown on Ctrl+C.
"""
import sys
import os
import subprocess
import time
import signal

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

SERVICES = [
    ("IIB Insurance (IRDAI)", [sys.executable, os.path.join(ROOT_DIR, "backend", "IIB", "iib_service.py")], 5002),
    ("MoRTH VAHAN Registry", [sys.executable, os.path.join(ROOT_DIR, "backend", "VAHAN", "vahan_service.py")], 5003),
    ("Police CCTNS & RVSF", [sys.executable, os.path.join(ROOT_DIR, "backend", "POLICE_CCTNS", "cctns_service.py")], 5004),
    ("Traffic ANPR Network", [sys.executable, os.path.join(ROOT_DIR, "backend", "ANPR_CAMERA", "anpr_service.py")], 5005),
    ("MoRTH e-Challan Portal", [sys.executable, os.path.join(ROOT_DIR, "backend", "ECHALLAN", "echallan_service.py")], 5006),
    ("Central Mediator (Global Schema)", [sys.executable, os.path.join(ROOT_DIR, "backend", "mediator_app.py")], 5001),
    ("Frontend Web Application", [sys.executable, os.path.join(ROOT_DIR, "frontend", "server.py")], 3000),
]

processes = []

def cleanup(sig=None, frame=None):
    print("\n[!] Shutting down all VahanRakshak services...")
    for name, proc in processes:
        try:
            proc.terminate()
        except Exception:
            pass
    print("[✓] All services stopped cleanly.")
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def main():
    print("=" * 75)
    print("🛡️  VAHANRAKSHAK: DISTRIBUTED VEHICLE COMPLIANCE SYSTEM")
    print("   Information Integration & Analytics (IIA) Architecture")
    print("=" * 75)

    for name, cmd, port in SERVICES:
        env = os.environ.copy()
        env["PYTHONPATH"] = ROOT_DIR + (os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else "")
        proc = subprocess.Popen(cmd, cwd=ROOT_DIR, env=env)
        processes.append((name, proc))
        print(f"  [+] Started {name:<35} -> http://127.0.0.1:{port}")
        time.sleep(0.35)

    print("\n" + "-" * 75)
    print("🚀 SYSTEM OPERATIONAL & READY")
    print("   👉 Open Web Application:  http://localhost:3000")
    print("   👉 Central Mediator API:  http://localhost:5001/api/v1/health")
    print("   👉 Press Ctrl+C to stop all services")
    print("-" * 75 + "\n")

    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
