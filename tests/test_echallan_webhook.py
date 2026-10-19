"""
The e-Challan service must send its cache-invalidation webhook to the Mediator that
called it - not a hard-coded 127.0.0.1, which breaks when the Mediator runs on
another machine (REMOTE_HOST mode).
"""
import shutil

import pytest

from backend.ECHALLAN import echallan_service


@pytest.fixture()
def captured(monkeypatch, tmp_path):
    # Work on a copy so the demo e-Challan data is left untouched
    db_copy = tmp_path / "ministry_echallan.db"
    shutil.copy(echallan_service.DB_PATH, db_copy)
    monkeypatch.setattr(echallan_service, "DB_PATH", str(db_copy))

    urls = []

    def fake_urlopen(req, timeout=None):
        urls.append(req.full_url)

    monkeypatch.setattr(echallan_service.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.delenv("URL_MEDIATOR", raising=False)
    monkeypatch.delenv("HOST_MEDIATOR", raising=False)
    monkeypatch.delenv("PORT_MEDIATOR", raising=False)
    return urls


def _update_status(remote_addr):
    client = echallan_service.app.test_client()
    report_id = client.get("/api/v1/challans?limit=1").get_json()["challans"][0]["report_id"]
    res = client.put(f"/api/v1/challans/{report_id}/status", json={"status": "UNDER_REVIEW"},
                     environ_base={"REMOTE_ADDR": remote_addr})
    assert res.status_code == 200


def test_webhook_targets_calling_mediator_host(captured):
    _update_status("192.168.1.20")
    assert captured == ["http://192.168.1.20:5001/api/v1/sync/invalidate"]


def test_webhook_local_default(captured):
    _update_status("127.0.0.1")
    assert captured == ["http://127.0.0.1:5001/api/v1/sync/invalidate"]


def test_webhook_explicit_override_wins(captured, monkeypatch):
    monkeypatch.setenv("HOST_MEDIATOR", "10.0.0.5")
    monkeypatch.setenv("PORT_MEDIATOR", "6001")
    _update_status("192.168.1.20")
    assert captured == ["http://10.0.0.5:6001/api/v1/sync/invalidate"]

    captured.clear()
    monkeypatch.setenv("URL_MEDIATOR", "http://mediator.lan:5001/")
    _update_status("192.168.1.20")
    assert captured == ["http://mediator.lan:5001/api/v1/sync/invalidate"]


def test_issuing_challan_notifies_mediator(captured):
    client = echallan_service.app.test_client()
    res = client.post("/api/v1/challans", json={"vehicle_identifier": "DL01AB1003",
                                                "report_type": "UNINSURED_ON_ROAD",
                                                "report_reason": "test", "severity": "HIGH"},
                      environ_base={"REMOTE_ADDR": "192.168.1.20"})
    assert res.status_code == 201
    assert captured == ["http://192.168.1.20:5001/api/v1/sync/invalidate"]
