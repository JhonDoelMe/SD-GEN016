import pytest
import io
import zipfile
import json
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.config import settings


@pytest.mark.asyncio
async def test_backup_system_full_flow(client, superadmin_auth, operator_auth):
    # 1. Unauthenticated access must be rejected with 401
    client.cookies.clear()
    res_unauth = await client.get("/api/v1/backups")
    assert res_unauth.status_code == 401

    # 2. Operator access must be rejected with 403 Forbidden (SuperAdmin only!)
    res_op = await client.get("/api/v1/backups", headers=operator_auth)
    assert res_op.status_code == 403

    # 3. SuperAdmin access allowed
    res = await client.get("/api/v1/backups", headers=superadmin_auth)
    assert res.status_code == 200
    data = res.json()
    assert "backups" in data
    assert "count" in data

    # 4. Create a Full Backup
    res_full = await client.post(
        "/api/v1/backups",
        headers=superadmin_auth,
        json={"backup_type": "full", "notes": "Тестовий повний бекап"}
    )
    assert res_full.status_code == 201
    full_manifest = res_full.json()
    assert full_manifest["backup_type"] == "full"
    assert full_manifest["filename"].endswith(".zip")
    full_filename = full_manifest["filename"]

    # 5. Create a DB-only Backup
    res_db = await client.post(
        "/api/v1/backups",
        headers=superadmin_auth,
        json={"backup_type": "db_only", "notes": "Тестовий швидкий бекап БД"}
    )
    assert res_db.status_code == 201
    db_manifest = res_db.json()
    assert db_manifest["backup_type"] == "db_only"
    db_filename = db_manifest["filename"]

    # 6. List backups should now show both
    res_list = await client.get("/api/v1/backups", headers=superadmin_auth)
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert list_data["count"] >= 2
    filenames = [b["filename"] for b in list_data["backups"]]
    assert full_filename in filenames
    assert db_filename in filenames

    # 7. Download Full Backup and verify zip integrity
    res_dl = await client.get(f"/api/v1/backups/{full_filename}/download", headers=superadmin_auth)
    assert res_dl.status_code == 200
    assert res_dl.headers.get("content-type") == "application/zip"
    assert len(res_dl.content) > 0

    # Inspect zip contents in memory
    zf = zipfile.ZipFile(io.BytesIO(res_dl.content))
    namelist = zf.namelist()
    assert "manifest.json" in namelist
    assert "database_export.json" in namelist
    manifest_in_zip = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest_in_zip["backup_id"] == full_manifest["backup_id"]

    # 8. Get and Update Backup Settings
    res_get_settings = await client.get("/api/v1/backups/settings", headers=superadmin_auth)
    assert res_get_settings.status_code == 200
    s_data = res_get_settings.json()
    assert "backup_schedule_time" in s_data

    res_put_settings = await client.put(
        "/api/v1/backups/settings",
        headers=superadmin_auth,
        json={
            "backup_auto_enabled": True,
            "backup_schedule_time": "04:15",
            "backup_frequency": "weekly",
            "backup_retention_count": 10,
            "backup_default_type": "db_only"
        }
    )
    assert res_put_settings.status_code == 200
    updated_s = res_put_settings.json()
    assert updated_s["backup_auto_enabled"] is True
    assert updated_s["backup_schedule_time"] == "04:15"
    assert updated_s["backup_frequency"] == "weekly"
    assert updated_s["backup_retention_count"] == 10
    assert updated_s["backup_default_type"] == "db_only"

    # 9. Delete Backups
    res_del_full = await client.delete(f"/api/v1/backups/{full_filename}", headers=superadmin_auth)
    assert res_del_full.status_code == 200
    assert res_del_full.json()["status"] == "success"

    res_del_db = await client.delete(f"/api/v1/backups/{db_filename}", headers=superadmin_auth)
    assert res_del_db.status_code == 200

    # 10. Verify deletion: attempting to download deleted file gives 404
    res_dl_deleted = await client.get(f"/api/v1/backups/{full_filename}/download", headers=superadmin_auth)
    assert res_dl_deleted.status_code == 404

    # 11. Path traversal security check
    res_bad = await client.get("/api/v1/backups/..%2F..%2Fpasswd/download", headers=superadmin_auth)
    assert res_bad.status_code in (400, 404)
