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

    # 5. Create a Partial Backup (дамп бази, конфігурація, .env)
    res_db = await client.post(
        "/api/v1/backups",
        headers=superadmin_auth,
        json={"backup_type": "partial", "notes": "Тестовий частковий бекап"}
    )
    assert res_db.status_code == 201
    db_manifest = res_db.json()
    assert db_manifest["backup_type"] in ("partial", "db_only")
    db_filename = db_manifest["filename"]

    # 6. List backups should now show both
    res_list = await client.get("/api/v1/backups", headers=superadmin_auth)
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert list_data["count"] >= 2
    filenames = [b["filename"] for b in list_data["backups"]]
    assert full_filename in filenames
    assert db_filename in filenames

    # 7. Download Full Backup and verify zip integrity & server files presence
    res_dl = await client.get(f"/api/v1/backups/{full_filename}/download", headers=superadmin_auth)
    assert res_dl.status_code == 200
    assert res_dl.headers.get("content-type") == "application/zip"
    assert len(res_dl.content) > 0

    zf = zipfile.ZipFile(io.BytesIO(res_dl.content))
    namelist = zf.namelist()
    assert "manifest.json" in namelist
    assert "database_export.json" in namelist
    assert any(n.startswith("server_files/") for n in namelist)
    manifest_in_zip = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest_in_zip["backup_id"] == full_manifest["backup_id"]

    # Download Partial Backup and verify it has config/ but NOT server_files/
    res_dl_db = await client.get(f"/api/v1/backups/{db_filename}/download", headers=superadmin_auth)
    assert res_dl_db.status_code == 200
    zf_db = zipfile.ZipFile(io.BytesIO(res_dl_db.content))
    db_namelist = zf_db.namelist()
    assert "manifest.json" in db_namelist
    assert "database_export.json" in db_namelist
    assert any(n.startswith("config/") for n in db_namelist)
    assert not any(n.startswith("server_files/") for n in db_namelist)

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
            "backup_default_type": "partial"
        }
    )
    assert res_put_settings.status_code == 200
    updated_s = res_put_settings.json()
    assert updated_s["backup_auto_enabled"] is True
    assert updated_s["backup_schedule_time"] == "04:15"
    assert updated_s["backup_frequency"] == "weekly"
    assert updated_s["backup_retention_count"] == 10
    assert updated_s["backup_default_type"] in ("partial", "db_only")

    # 9. Inspect Backup Metadata
    res_inspect = await client.get(f"/api/v1/backups/{full_filename}/inspect", headers=superadmin_auth)
    assert res_inspect.status_code == 200
    inspect_data = res_inspect.json()
    assert inspect_data["manifest"]["backup_id"] == full_manifest["backup_id"]
    assert inspect_data["has_database_export"] is True

    # 10. Test Restore Validation (rejection on wrong confirmation)
    res_bad_confirm = await client.post(
        f"/api/v1/backups/{full_filename}/restore",
        headers=superadmin_auth,
        json={"confirmation": "WRONG_WORD", "restore_files": True}
    )
    assert res_bad_confirm.status_code == 400

    # 11. Test Restore from existing backup (with proper confirmation 'ВІДНОВИТИ')
    res_restore = await client.post(
        f"/api/v1/backups/{full_filename}/restore",
        headers=superadmin_auth,
        json={"confirmation": "ВІДНОВИТИ", "restore_files": True}
    )
    assert res_restore.status_code == 200
    restore_data = res_restore.json()
    assert restore_data["status"] == "success"
    assert restore_data["records_restored"] > 0
    assert "safety_backup_filename" in restore_data
    safety_filename = restore_data["safety_backup_filename"]

    # 12. Test Upload and Restore (Multipart/Form-Data)
    res_upload_restore = await client.post(
        "/api/v1/backups/upload-restore",
        headers=superadmin_auth,
        data={"confirmation": "ВІДНОВИТИ", "restore_files": "true"},
        files={"file": ("test_upload_backup.zip", res_dl.content, "application/zip")}
    )
    assert res_upload_restore.status_code == 200
    up_restore_data = res_upload_restore.json()
    assert up_restore_data["status"] == "success"
    assert up_restore_data["records_restored"] > 0

    # 13. Delete Backups (including safety backup)
    res_del_full = await client.delete(f"/api/v1/backups/{full_filename}", headers=superadmin_auth)
    assert res_del_full.status_code == 200
    assert res_del_full.json()["status"] == "success"

    res_del_db = await client.delete(f"/api/v1/backups/{db_filename}", headers=superadmin_auth)
    assert res_del_db.status_code == 200

    if safety_filename:
        await client.delete(f"/api/v1/backups/{safety_filename}", headers=superadmin_auth)

    # 14. Verify deletion: attempting to download deleted file gives 404
    res_dl_deleted = await client.get(f"/api/v1/backups/{full_filename}/download", headers=superadmin_auth)
    assert res_dl_deleted.status_code == 404

    # 15. Path traversal security check
    res_bad = await client.get("/api/v1/backups/..%2F..%2Fpasswd/download", headers=superadmin_auth)
    assert res_bad.status_code in (400, 404)
