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

ALL_SERVICES = {
    "iib": ("IIB Insurance (IRDAI)", [sys.executable, os.path.join(ROOT_DIR, "backend", "IIB", "iib_service.py")], b_config.PORT_IIB),
    "vahan": ("MoRTH VAHAN Registry", [sys.executable, os.path.join(ROOT_DIR, "backend", "VAHAN", "vahan_service.py")], b_config.PORT_VAHAN),
    "police": ("Police CCTNS & RVSF", [sys.executable, os.path.join(ROOT_DIR, "backend", "POLICE_CCTNS", "cctns_service.py")], b_config.PORT_POLICE),
    "anpr": ("Traffic ANPR Network", [sys.executable, os.path.join(ROOT_DIR, "backend", "ANPR_CAMERA", "anpr_service.py")], b_config.PORT_ANPR),
    "echallan": ("MoRTH e-Challan Portal", [sys.executable, os.path.join(ROOT_DIR, "backend", "ECHALLAN", "echallan_service.py")], b_config.PORT_ECHALLAN),
    "mediator": ("Central Mediator (Global Schema)", [sys.executable, os.path.join(ROOT_DIR, "backend", "mediator_app.py")], b_config.PORT_MEDIATOR),
    "frontend": ("Frontend Web Application", [sys.executable, os.path.join(ROOT_DIR, "frontend", "server.py")], b_config.PORT_FRONTEND),
}

# Which services run on THIS laptop:
#   python start_system.py                              everything (one laptop)
#   python start_system.py --services vahan,iib         only these (e.g. the agency laptops of the 4-laptop demo)
# Without --services and with REMOTE_HOST set, only the Mediator and the frontend start (old two-laptop mode).
_args = sys.argv[1:]
if "--services" in _args and _args.index("--services") + 1 < len(_args):
    _wanted = [x.strip().lower() for x in _args[_args.index("--services") + 1].split(",") if x.strip()]
    _unknown = [x for x in _wanted if x not in ALL_SERVICES]
    if _unknown:
        print(f"Unknown service(s): {', '.join(_unknown)}. Choose from: {', '.join(ALL_SERVICES)}")
        sys.exit(2)
elif b_config.DEFAULT_HOST not in ("127.0.0.1", "localhost"):
    _wanted = ["mediator", "frontend"]
else:
    _wanted = list(ALL_SERVICES)
is_remote = "mediator" in _wanted and not all(k in _wanted for k in ("iib", "vahan", "police", "anpr", "echallan"))
SERVICES = [ALL_SERVICES[k] for k in ALL_SERVICES if k in _wanted]

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
    print(f"  Services on this laptop: {', '.join(_wanted)}")
    if is_remote:
        print("  Agency databases are reached over the LAN:")
        for key, url in (("iib", b_config.URL_IIB), ("vahan", b_config.URL_VAHAN), ("police", b_config.URL_POLICE),
                         ("anpr", b_config.URL_ANPR), ("echallan", b_config.URL_ECHALLAN)):
            print(f"     {key:<9} {url}{'   (this laptop)' if key in _wanted else ''}")
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
