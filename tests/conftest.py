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
