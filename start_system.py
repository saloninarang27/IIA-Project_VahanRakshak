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

import backend.config as b_config

# If REMOTE_HOST is configured, we only need to launch Mediator (5001) & Frontend (3000)
# because the 5 database microservices are already running on the remote laptop!
is_remote = b_config.DEFAULT_HOST not in ("127.0.0.1", "localhost")

if is_remote:
    SERVICES = [
        ("Central Mediator (Global Schema)", [sys.executable, os.path.join(ROOT_DIR, "backend", "mediator_app.py")], 5001),
        ("Frontend Web Application", [sys.executable, os.path.join(ROOT_DIR, "frontend", "server.py")], 3000),
    ]
else:
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

def free_ports():
    """Automatically terminates any lingering/orphaned processes holding our ports."""
    ports = [port for _, _, port in SERVICES]
    killed_any = False
    for port in ports:
        try:
            out = subprocess.check_output(["lsof", "-ti", f":{port}"], stderr=subprocess.DEVNULL).decode().strip()
            if out:
                for pid_str in out.split():
                    try:
                        pid = int(pid_str)
                        if pid != os.getpid():
                            os.kill(pid, signal.SIGKILL)
                            killed_any = True
                    except Exception:
                        pass
        except Exception:
            pass
    if killed_any:
        time.sleep(0.5)

def ports_in_use():
    """Ports from SERVICES that already accept connections on this machine."""
    import socket
    busy = []
    for _, _, port in SERVICES:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                busy.append(port)
    return busy

def cleanup(sig=None, frame=None):
    print("\n[!] Shutting down all VahanRakshak services...")
    for name, proc in processes:
        try:
            proc.terminate()
        except Exception:
            pass
    time.sleep(0.5)
    for name, proc in processes:
        try:
            proc.kill()
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
    if is_remote:
        print(f"  🌐 REMOTE DATABASE MODE ACTIVE -> Host: http://{b_config.DEFAULT_HOST}")
        print("     Federating 5 database microservices over LAN!")
        print("=" * 75)

    # Pre-flight check: ensure ports are free
    free_ports()
    busy = ports_in_use()
    if busy:
        # On Windows a second Flask server can bind the same port and requests keep going to the OLD
        # instance, so a duplicate start would silently keep serving stale code. Refuse instead.
        print("\n[!] These ports are already in use - an earlier VahanRakshak instance is probably still running:")
        for port in busy:
            print(f"      port {port}")
        print("    Stop it first (Ctrl+C in its terminal, or close that terminal), then run start_system.py again.")
        if os.name == "nt":
            print("    To find it:  netstat -ano | findstr :5001   then   taskkill /PID <pid> /T /F")
        sys.exit(1)

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
