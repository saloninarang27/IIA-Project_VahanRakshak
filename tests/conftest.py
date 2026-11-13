"""
Test session bootstrap.

`pytest` must work standalone (Section 16), so this session-scoped, autouse
fixture rebuilds every database from scratch — schemas, all five seeded
sources, the ETL load, and the materialized-view refresh — exactly once
before any test runs. This also means the test suite doubles as an
end-to-end pipeline smoke test.
"""
import sys
import os

# The suite always tests this checkout's own services in-process. A .env pointing at
# another laptop (REMOTE_HOST / HOST_*) must not leak in, or the tests would depend on
# that machine being reachable. Empty values win over .env (it never overrides set vars).
for _var in ("SERVICES_HOST", "REMOTE_HOST", "HOST_IIB", "HOST_VAHAN", "HOST_POLICE", "HOST_ANPR",
             "HOST_ECHALLAN", "URL_IIB", "URL_VAHAN", "URL_POLICE", "URL_ANPR", "URL_ECHALLAN"):
    os.environ[_var] = ""

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test-only credentials (never the .env of a real machine).
os.environ["FEDERATION_SECRET"] = "test-federation-secret-0123456789abcdef"
from backend import security  # noqa: E402
TEST_PASSWORDS = {"admin": "admin-pw", "police": "police-pw", "insurer": "insurer-pw"}
os.environ["AUTH_USERS"] = ",".join(
    f"{u}:{u.upper()}:{security.hash_password(p, salt='testsalt')}" for u, p in TEST_PASSWORDS.items())

# Existing tests call the services and the Mediator directly: give their test clients an ADMIN
# identity (signed requests for agencies, a login token for the Mediator). Tests that check access
# control build their own unsigned / lower-role clients (tests/test_security.py).
from backend.mediator_app import app as _mediator_app  # noqa: E402
from backend.IIB.iib_service import app as _iib  # noqa: E402
from backend.VAHAN.vahan_service import app as _vahan  # noqa: E402
from backend.POLICE_CCTNS.cctns_service import app as _police  # noqa: E402
from backend.ANPR_CAMERA.anpr_service import app as _anpr  # noqa: E402
from backend.ECHALLAN.echallan_service import app as _echallan  # noqa: E402
for _svc in (_iib, _vahan, _police, _anpr, _echallan):
    _svc.test_client_class = security.signed_client_class("ADMIN")
_mediator_app.test_client_class = security.signed_client_class("ADMIN", bearer=True)

import pytest

import db
from seed import seed_capture, seed_insurance, seed_registration, seed_theft_scrap, seed_ministry
from etl.pipeline import run_pipeline
from dwh.refresh_views import refresh_all_views


@pytest.fixture(scope="session", autouse=True)
def bootstrap_full_dataset():
    db.init_all_schemas()
    seed_capture.seed()
    seed_insurance.seed()
    seed_registration.seed()
    seed_theft_scrap.seed()
    seed_ministry.seed()
    run_pipeline()
    refresh_all_views()
    yield
