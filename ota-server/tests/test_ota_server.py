"""Unit and API tests for standalone SD-GEN016 OTA service."""

from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

OTA_DIR = Path(__file__).resolve().parents[1]
if str(OTA_DIR) not in sys.path:
    sys.path.insert(0, str(OTA_DIR))

from app import create_ota_app  # noqa: E402


def _fake_apk(content: bytes = b"dummy-apk-payload") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("AndroidManifest.xml", content * 120)
        zf.writestr("classes.dex", b"dex\n035\x00" + content * 80)
    return buf.getvalue()


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


def test_upload_rejects_zip_without_android_manifest(ota_client: TestClient) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("readme.txt", b"not-an-apk" * 200)
    bad = ota_client.post(
        "/ota/api/releases",
        headers={"X-OTA-Admin-Token": "test-ota-admin-token-1234567890"},
        files={"file": ("fake.apk", io.BytesIO(buf.getvalue()), "application/vnd.android.package-archive")},
        data={"version_code": "10", "version_name": "5.7.4"},
    )
    assert bad.status_code == 400
    assert "AndroidManifest.xml" in bad.json()["detail"]


def test_admin_auth_rate_limiting(ota_client: TestClient) -> None:
    for _ in range(10):
        res = ota_client.get("/ota/api/releases", headers={"X-OTA-Admin-Token": "wrong-token"})
        assert res.status_code == 401
    blocked = ota_client.get("/ota/api/releases", headers={"X-OTA-Admin-Token": "wrong-token"})
    assert blocked.status_code == 429


def _fake_web_bundle(content: str = "<h1>SD-GEN016</h1>") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("index.html", f"<!doctype html><html><body>{content}</body></html>" * 10)
        zf.writestr("frontend/js/ota-updater.js", "// ota" * 20)
    return buf.getvalue()


def test_web_bundle_ota_lifecycle_and_compatibility(ota_client: TestClient) -> None:
    headers = {"X-OTA-Admin-Token": "test-ota-admin-token-1234567890"}

    # Upload base APK v5.8.0 (build 27)
    apk27 = _fake_apk(b"release-27-")
    assert ota_client.post(
        "/ota/api/releases",
        headers=headers,
        files={"file": ("sdgen-v5.8.0.apk", io.BytesIO(apk27), "application/vnd.android.package-archive")},
        data={"version_code": "27", "version_name": "5.8.0", "min_supported_version_code": "27"},
    ).status_code == 201

    # Upload Web-OTA bundle build 28 requiring min_native_version_code=27
    zip28 = _fake_web_bundle("v5.8.1-web")
    sha28 = hashlib.sha256(zip28).hexdigest()
    r28 = ota_client.post(
        "/ota/api/web/releases",
        headers=headers,
        files={"file": ("web-5.8.1.zip", io.BytesIO(zip28), "application/zip")},
        data={
            "web_build": "28",
            "version_name": "5.8.1",
            "min_native_version_code": "27",
            "changelog": "Швидкий веб-фікс",
            "is_mandatory": "false",
        },
    )
    assert r28.status_code == 201
    b28 = r28.json()
    assert b28["web_build"] == 28
    assert b28["sha256"] == sha28
    assert b28["download_url"] == "https://sdgen.pp.ua/ota/download/web/latest.zip"

    # APK 27 with embedded web 27 -> eligible for web update 28 without APK reinstall
    c27 = ota_client.get("/ota/api/web/latest?current_native_code=27&current_web_build=27").json()
    assert c27["web_update_available"] is True
    assert c27["native_update_required"] is False

    # Already on web 28 -> no web update
    c28 = ota_client.get("/ota/api/web/latest?current_native_code=27&current_web_build=28").json()
    assert c28["web_update_available"] is False

    # Newer APK 29 (embedded 29 > bundle 28) -> never downgrades to bundle 28
    c29 = ota_client.get("/ota/api/web/latest?current_native_code=29&current_web_build=29").json()
    assert c29["web_update_available"] is False

    # Very old APK 26 (< min_supported 27) -> native_update_required=True, skips web bundle
    c26 = ota_client.get("/ota/api/web/latest?current_native_code=26&current_web_build=26").json()
    assert c26["native_update_required"] is True
    assert c26["web_update_available"] is False
    assert c26["native"]["force_update"] is True

    # Download ZIP & verify SHA header
    dl = ota_client.get("/ota/download/web/latest.zip")
    assert dl.status_code == 200
    assert dl.content == zip28
    assert dl.headers["x-ota-sha256"] == sha28

    # Reject ZIP missing index.html or path traversal
    bad_buf = io.BytesIO()
    with zipfile.ZipFile(bad_buf, "w") as zf:
        zf.writestr("index.html", "ok" * 80)
        zf.writestr("../evil.js", "alert(1)")
    bad_zip = ota_client.post(
        "/ota/api/web/releases",
        headers=headers,
        files={"file": ("evil.zip", io.BytesIO(bad_buf.getvalue()), "application/zip")},
        data={"web_build": "29", "version_name": "5.8.2"},
    )
    assert bad_zip.status_code == 400

    # Publish web 29 then rollback to 28
    zip29 = _fake_web_bundle("v5.8.2-web")
    assert ota_client.post(
        "/ota/api/web/releases",
        headers=headers,
        files={"file": ("web-5.8.2.zip", io.BytesIO(zip29), "application/zip")},
        data={"web_build": "29", "version_name": "5.8.2", "min_native_version_code": "27"},
    ).status_code == 201

    rb = ota_client.patch("/ota/api/web/policy", headers=headers, json={"active_web_build": 28})
    assert rb.status_code == 200
    assert rb.json()["web_build"] == 28
    assert ota_client.get("/ota/download/web/latest.zip").content == zip28
