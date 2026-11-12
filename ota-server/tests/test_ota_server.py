"""Unit and API tests for standalone SD-GEN016 OTA service."""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

OTA_DIR = Path(__file__).resolve().parents[1]
if str(OTA_DIR) not in sys.path:
    sys.path.insert(0, str(OTA_DIR))

from app import create_ota_app  # noqa: E402


def _fake_apk(content: bytes = b"dummy-apk-payload") -> bytes:
    # Minimal PK\x03\x04 ZIP magic prefix + >= 1024 bytes
    return b"PK\x03\x04" + (content * 200)


@pytest.fixture()
def ota_client(tmp_path: Path) -> TestClient:
    app = create_ota_app(
        data_dir=str(tmp_path),
        admin_token="test-ota-admin-token-1234567890",
        public_base_url="https://sdgen.pp.ua/ota",
        max_releases=3,
    )
    return TestClient(app)


def test_health_and_empty_manifest(ota_client: TestClient) -> None:
    res = ota_client.get("/ota/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "healthy"
    assert body["has_release"] is False

    latest = ota_client.get("/ota/api/latest?current_code=2")
    assert latest.status_code == 200
    assert latest.headers["cache-control"].startswith("no-store")
    m = latest.json()
    assert m["has_release"] is False
    assert m["update_available"] is False
    assert m["force_update"] is False

    landing = ota_client.get("/ota/")
    assert landing.status_code == 200
    assert "SD-GEN016" in landing.text


def test_upload_auth_and_validation(ota_client: TestClient) -> None:
    apk_bytes = _fake_apk()
    # Missing token
    no_auth = ota_client.post(
        "/ota/api/releases",
        files={"file": ("app.apk", io.BytesIO(apk_bytes), "application/vnd.android.package-archive")},
        data={"version_code": "3", "version_name": "5.6.3"},
    )
    assert no_auth.status_code == 401

    # Invalid file header
    bad_file = ota_client.post(
        "/ota/api/releases",
        headers={"X-OTA-Admin-Token": "test-ota-admin-token-1234567890"},
        files={"file": ("app.apk", io.BytesIO(b"NOT_A_ZIP" * 200), "application/vnd.android.package-archive")},
        data={"version_code": "3", "version_name": "5.6.3"},
    )
    assert bad_file.status_code == 400


def test_upload_manifest_download_policy_and_rollback(ota_client: TestClient) -> None:
    headers = {"X-OTA-Admin-Token": "test-ota-admin-token-1234567890"}
    apk3 = _fake_apk(b"release-3-")
    sha3 = hashlib.sha256(apk3).hexdigest()

    r3 = ota_client.post(
        "/ota/api/releases",
        headers=headers,
        files={"file": ("sdgen-v5.6.3.apk", io.BytesIO(apk3), "application/vnd.android.package-archive")},
        data={
            "version_code": "3",
            "version_name": "5.6.3",
            "changelog": "Додано автоматичне OTA-оновлення",
            "min_supported_version_code": "3",
        },
    )
    assert r3.status_code == 201
    rel3 = r3.json()
    assert rel3["version_code"] == 3
    assert rel3["sha256"] == sha3
    assert rel3["download_url"] == "https://sdgen.pp.ua/ota/download/latest.apk"

    # Reject lower/equal version_code without replace=true
    dup = ota_client.post(
        "/ota/api/releases",
        headers=headers,
        files={"file": ("sdgen-v5.6.3.apk", io.BytesIO(apk3), "application/vnd.android.package-archive")},
        data={"version_code": "3", "version_name": "5.6.3"},
    )
    assert dup.status_code == 409

    # Old client (code 2 < min_supported 3) gets force_update=True
    check_old = ota_client.get("/ota/api/latest?current_code=2").json()
    assert check_old["update_available"] is True
    assert check_old["force_update"] is True

    # Current client (code 3) gets update_available=False
    check_cur = ota_client.get("/ota/api/latest?current_code=3").json()
    assert check_cur["update_available"] is False
    assert check_cur["force_update"] is False

    # Fixed latest download serves bytes and increments download_count
    dl = ota_client.get("/ota/download/latest.apk")
    assert dl.status_code == 200
    assert dl.content == apk3
    assert dl.headers["x-ota-sha256"] == sha3
    assert "no-store" in dl.headers["cache-control"]

    # Landing page renders QR SVG & changelog
    landing = ota_client.get("/ota/")
    assert landing.status_code == 200
    assert "v5.6.3" in landing.text
    assert "<svg" in landing.text

    # Upload build 4 as optional (non-mandatory), min_supported stays 3
    apk4 = _fake_apk(b"release-4-")
    r4 = ota_client.post(
        "/ota/api/releases",
        headers=headers,
        files={"file": ("sdgen-v5.6.4.apk", io.BytesIO(apk4), "application/vnd.android.package-archive")},
        data={"version_code": "4", "version_name": "5.6.4", "changelog": "Покращення UX"},
    )
    assert r4.status_code == 201

    check_3_to_4 = ota_client.get("/ota/api/latest?current_code=3").json()
    assert check_3_to_4["update_available"] is True
    assert check_3_to_4["force_update"] is False

    # Rollback to build 3 via policy PATCH
    rb = ota_client.patch(
        "/ota/api/policy",
        headers=headers,
        json={"active_version_code": 3},
    )
    assert rb.status_code == 200
    assert rb.json()["version_code"] == 3
    assert ota_client.get("/ota/download/latest.apk").content == apk3
