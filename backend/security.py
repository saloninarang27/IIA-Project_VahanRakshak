"""
Security layer shared by the Mediator and the five agency services (need-to-know federation).

Threat addressed (phase-2 feedback): any user could make the Mediator pull and return whole agency
databases, and every agency endpoint (including raw SQL) was open to anyone on the network.

  1. Users log in at the Mediator and get a signed, expiring session token carrying their role
     (POLICE / INSURER / ADMIN). Passwords are stored only as PBKDF2 hashes in .env.
  2. Agencies trust nobody but the Mediator: every request must carry an HMAC-SHA256 signature over
     timestamp, nonce, method, path, caller, role and body hash, made with FEDERATION_SECRET.
     Unsigned, tampered, stale (>60 s) or replayed requests get 401. The secret never leaves .env.
  3. The agency itself enforces the role: bulk endpoints (full identifier lists, raw SQL) are ADMIN
     only, writes need the right role, and personal fields (owner name, address, phone ...) are
     masked unless the role is POLICE or ADMIN.
  4. Every request an agency answers is written to its own append-only access_audit table
     (UPDATE / DELETE are blocked by triggers, and raw SQL cannot touch the table).

CLI:
  python -m backend.security init-env        write .env with a random secret and passwords (prints them once)
  python -m backend.security hash <password> print a PBKDF2 hash for AUTH_USERS
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import backend.config  # noqa: E402,F401  (loads .env into os.environ)

ROLES = ("POLICE", "INSURER", "ADMIN")
PII_ROLES = {"POLICE", "ADMIN"}
PII_FIELDS = {"owner_name", "holder_name", "complainant_name", "address", "phone", "email"}
SIGNATURE_WINDOW_SECONDS = 60
TOKEN_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", 8 * 3600))
PBKDF2_ROUNDS = 200_000


def _secret() -> bytes:
    value = os.environ.get("FEDERATION_SECRET", "")
    return value.encode() if len(value) >= 16 else b""


def configured() -> bool:
    return bool(_secret())


# ---------------------------------------------------------------------------
# Passwords and session tokens (Mediator <-> browser)
# ---------------------------------------------------------------------------
def hash_password(password: str, salt: str = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS).hex()
    return f"{salt}${digest}"


def _users() -> dict:
    """AUTH_USERS="admin:ADMIN:salt$hash,police:POLICE:salt$hash,..." -> {user: (role, hash)}"""
    users = {}
    for item in os.environ.get("AUTH_USERS", "").split(","):
        parts = item.strip().split(":")
        if len(parts) == 3 and parts[1].upper() in ROLES:
            users[parts[0]] = (parts[1].upper(), parts[2])
    return users


def authenticate(username: str, password: str):
    """Role of the user if the password is right, else None."""
    entry = _users().get((username or "").strip())
    if not entry or "$" not in entry[1]:
        hash_password(password or "")  # same cost either way: no user-enumeration by timing
        return None
    role, stored = entry
    salt = stored.split("$", 1)[0]
    return role if hmac.compare_digest(hash_password(password or "", salt), stored) else None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _token_key() -> bytes:
    return hmac.new(_secret(), b"session-token", hashlib.sha256).digest()


def issue_token(username: str, role: str) -> str:
    payload = _b64(json.dumps({"u": username, "r": role, "exp": int(time.time()) + TOKEN_TTL_SECONDS}).encode())
    return payload + "." + _b64(hmac.new(_token_key(), payload.encode(), hashlib.sha256).digest())


def read_token(token: str):
    """{"user", "role"} for a valid, unexpired token, else None."""
    if not configured() or not token or token.count(".") != 1:
        return None
    payload, sig = token.split(".")
    expected = _b64(hmac.new(_token_key(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except ValueError:
        return None
    if data.get("exp", 0) < time.time() or data.get("r") not in ROLES:
        return None
    return {"user": data.get("u"), "role": data["r"]}


# ---------------------------------------------------------------------------
# Signed service-to-service requests (Mediator -> agency, agency -> Mediator webhook)
# ---------------------------------------------------------------------------
def _canonical(ts, nonce, method, path, caller, role, body: bytes) -> bytes:
    return "\n".join([str(ts), nonce, method.upper(), path, caller, role,
                      hashlib.sha256(body or b"").hexdigest()]).encode()


def signed_headers(method: str, path: str, body: bytes = b"", role: str = "ADMIN", caller: str = "mediator") -> dict:
    """Headers that authenticate one request. path must include the query string."""
    ts, nonce = str(int(time.time())), secrets.token_hex(12)
    sig = hmac.new(_secret(), _canonical(ts, nonce, method, path, caller, role, body), hashlib.sha256).hexdigest()
    return {"X-Fed-Caller": caller, "X-Fed-Role": role, "X-Fed-Timestamp": ts,
            "X-Fed-Nonce": nonce, "X-Fed-Signature": sig}


_seen_nonces = {}
_nonce_lock = threading.Lock()


def verify_signed(headers, method: str, path: str, body: bytes):
    """(caller, role) for a valid signed request; raises PermissionError otherwise."""
    if not configured():
        raise PermissionError("FEDERATION_SECRET is not configured on this machine (run: python -m backend.security init-env)")
    try:
        caller, role = headers["X-Fed-Caller"], headers["X-Fed-Role"]
        ts, nonce, sig = headers["X-Fed-Timestamp"], headers["X-Fed-Nonce"], headers["X-Fed-Signature"]
        age = abs(time.time() - int(ts))
    except (KeyError, ValueError):
        raise PermissionError("unsigned request: only the Mediator may call agency services")
    if age > SIGNATURE_WINDOW_SECONDS:
        raise PermissionError("request signature expired (check the clocks of both machines)")
    expected = hmac.new(_secret(), _canonical(ts, nonce, method, path, caller, role, body), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise PermissionError("bad request signature (is FEDERATION_SECRET in .env the same on every laptop?)")
    if role not in ROLES:
        raise PermissionError(f"unknown role {role}")
    now = time.time()
    with _nonce_lock:
        if nonce in _seen_nonces:
            raise PermissionError("replayed request")
        _seen_nonces[nonce] = now
        if len(_seen_nonces) > 10000:
            for n, t in list(_seen_nonces.items()):
                if now - t > SIGNATURE_WINDOW_SECONDS * 2:
                    del _seen_nonces[n]
    return caller, role


def signed_request(url: str, method: str = "GET", payload=None, role: str = "ADMIN", caller: str = "mediator"):
    """urllib Request for an agency (or Mediator webhook) URL, signed."""
    import urllib.request
    from urllib.parse import urlsplit
    body = json.dumps(payload).encode() if payload is not None else b""
    parts = urlsplit(url)
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    headers = signed_headers(method, path, body, role, caller)
    if payload is not None:
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=body if payload is not None else None, headers=headers, method=method)


# ---------------------------------------------------------------------------
# Field masking
# ---------------------------------------------------------------------------
def mask_value(value):
    if not isinstance(value, str) or not value:
        return value
    return " ".join(w[0] + "*" * (len(w) - 1) if len(w) > 1 else w for w in value.split())


def mask_pii(data):
    if isinstance(data, dict):
        return {k: (mask_value(v) if k in PII_FIELDS else mask_pii(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [mask_pii(v) for v in data]
    return data


# ---------------------------------------------------------------------------
# Agency side: install on a Flask service
# ---------------------------------------------------------------------------
AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS access_audit (
    audit_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    accessed_at    TEXT NOT NULL,
    caller         TEXT,
    role           TEXT,
    method         TEXT NOT NULL,
    path           TEXT NOT NULL,
    status         INTEGER NOT NULL,
    response_bytes INTEGER,
    remote_addr    TEXT,
    outcome        TEXT NOT NULL            -- ALLOWED / DENIED: <reason>
);
CREATE TRIGGER IF NOT EXISTS access_audit_no_update BEFORE UPDATE ON access_audit
BEGIN SELECT RAISE(ABORT, 'access_audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS access_audit_no_delete BEFORE DELETE ON access_audit
BEGIN SELECT RAISE(ABORT, 'access_audit is append-only'); END;
"""


def route_roles(method: str, path: str, policy: dict):
    """
    Roles allowed for (method, path); None = any authenticated role. Policy keys are
    (METHOD, path_prefix); a prefix ending in "$" matches that exact path only.
    The longest matching prefix wins; an exact rule beats a prefix rule for the same path.
    """
    best, allowed = -1, None
    for (m, prefix), roles in policy.items():
        exact = prefix.endswith("$")
        p = prefix.rstrip("$")
        hit = path == p if exact else (path == p or path.startswith(p.rstrip("/") + "/"))
        weight = len(p) + (0.5 if exact else 0)   # an exact rule beats a prefix rule of the same path
        if m == method and hit and weight > best:
            best, allowed = weight, roles
    return allowed


def protect_service(app, db_path: str, policy: dict, public_paths=("/api/v1/health",)):
    """
    Require a signed Mediator request on every endpoint except public_paths, enforce the
    per-route role policy {(METHOD, path_prefix): {roles}}, mask PII for roles that may not
    see it, and append every request to access_audit in the service's own database.
    """
    from flask import g, request

    def _audit(status, size, outcome):
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            try:
                conn.executescript(AUDIT_DDL)
                conn.execute(
                    "INSERT INTO access_audit (accessed_at, caller, role, method, path, status, response_bytes, remote_addr, outcome)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (datetime.now().isoformat(sep=" ", timespec="seconds"), g.get("fed_caller"), g.get("fed_role"),
                     request.method, request.full_path.rstrip("?"), status, size, request.remote_addr, outcome))
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error:
            pass  # auditing must never take the service down

    def _deny(status, reason):
        from flask import jsonify
        _audit(status, 0, f"DENIED: {reason}")
        g.fed_audited = True
        return jsonify({"status": "error", "error": reason}), status

    @app.before_request
    def _check():
        if request.method == "OPTIONS" or request.path in public_paths:
            return None
        path = request.full_path.rstrip("?") if request.query_string else request.path
        try:
            g.fed_caller, g.fed_role = verify_signed(request.headers, request.method, path, request.get_data())
        except PermissionError as e:
            return _deny(401, str(e))
        allowed = route_roles(request.method, request.path, policy)
        if allowed is not None and g.fed_role not in allowed:
            return _deny(403, f"role {g.fed_role} may not {request.method} {request.path} (need {'/'.join(sorted(allowed))})")
        if request.path.endswith("/internal/execute-sql"):
            query = ((request.get_json(silent=True) or {}).get("query") or "").lower()
            if "access_audit" in query:
                return _deny(403, "the access audit log cannot be queried or changed through raw SQL")
        return None

    @app.after_request
    def _finish(response):
        if request.method == "OPTIONS" or request.path in public_paths or g.get("fed_audited"):
            return response
        if g.get("fed_role") not in PII_ROLES and response.is_json:
            response.set_data(json.dumps(mask_pii(response.get_json())))
        _audit(response.status_code, response.calculate_content_length() or 0, "ALLOWED")
        return response


# ---------------------------------------------------------------------------
# Test helper: a Flask test client that signs (agency) or authenticates (Mediator) every request
# ---------------------------------------------------------------------------
def signed_client_class(role="ADMIN", caller="mediator", bearer=False):
    """FlaskClient subclass that signs (agency) or carries a login token (bearer=True, Mediator)."""
    from flask.testing import FlaskClient

    class _Client(FlaskClient):
        def open(self, *args, **kwargs):
            path = args[0] if args and isinstance(args[0], str) else kwargs.get("path", "/")
            method = kwargs.get("method", "GET")
            headers = dict(kwargs.pop("headers", None) or {})
            if bearer:
                headers.setdefault("Authorization", f"Bearer {issue_token('test-' + role.lower(), role)}")
            else:
                body = kwargs.get("data") or b""
                if "json" in kwargs:
                    body = json.dumps(kwargs.pop("json")).encode()
                    kwargs["data"] = body
                    kwargs["content_type"] = "application/json"
                if isinstance(body, str):
                    body = body.encode()
                headers.update(signed_headers(method, path, body if isinstance(body, bytes) else b"", role, caller))
            return super().open(*args, headers=headers, **kwargs)

    return _Client


def signed_test_client(app, role="ADMIN", caller="mediator", bearer=False):
    return signed_client_class(role, caller, bearer)(app, app.response_class, use_cookies=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def init_env(path=os.path.join(PROJECT_ROOT, ".env")):
    """Create .env from .env.example with a fresh secret and random passwords (printed once)."""
    if os.path.exists(path):
        print(f"[security] {path} already exists - not touched.")
        return None
    example = os.path.join(PROJECT_ROOT, ".env.example")
    text = open(example, encoding="utf-8").read() if os.path.exists(example) else ""
    passwords = {u: secrets.token_urlsafe(9) for u in ("admin", "police", "insurer")}
    users = ",".join(f"{u}:{r}:{hash_password(passwords[u])}"
                     for u, r in (("admin", "ADMIN"), ("police", "POLICE"), ("insurer", "INSURER")))
    lines = [ln for ln in text.splitlines() if not ln.startswith(("FEDERATION_SECRET=", "AUTH_USERS="))]
    lines += ["", f"FEDERATION_SECRET={secrets.token_hex(32)}", f"AUTH_USERS={users}", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[security] wrote {path}. Copy this SAME file to every laptop. Login passwords (shown only now):")
    for u, p in passwords.items():
        print(f"    {u:<8} {p}")
    return passwords


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "init-env":
        init_env()
    elif len(sys.argv) == 3 and sys.argv[1] == "hash":
        print(hash_password(sys.argv[2]))
    else:
        print(__doc__)
