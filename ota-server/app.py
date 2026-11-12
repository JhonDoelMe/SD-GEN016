"""Standalone FastAPI OTA server for SD-GEN016 Android APK distribution."""

from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from storage import (
    OtaConflictError,
    OtaNotFoundError,
    OtaStorage,
    OtaValidationError,
)
from templates import render_admin_page, render_landing_page

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


class PolicyUpdateRequest(BaseModel):
    min_supported_version_code: Optional[int] = Field(default=None, ge=0)
    active_version_code: Optional[int] = Field(default=None, ge=1)
    is_mandatory: Optional[bool] = None
    changelog: Optional[str] = Field(default=None, max_length=4000)


def _parse_cors_origins(raw: str) -> list[str]:
    defaults = [
        "https://sdgen.pp.ua",
        "https://www.sdgen.pp.ua",
        "https://localhost",
        "http://localhost",
        "capacitor://localhost",
    ]
    extra = [item.strip() for item in raw.split(",") if item.strip()]
    seen: list[str] = []
    for origin in defaults + extra:
        if origin not in seen:
            seen.append(origin)
    return seen


def create_ota_app(
    data_dir: Optional[str] = None,
    admin_token: Optional[str] = None,
    public_base_url: Optional[str] = None,
    app_id: Optional[str] = None,
    app_name: Optional[str] = None,
    max_releases: Optional[int] = None,
) -> FastAPI:
    """Create configured FastAPI OTA application instance."""
    resolved_data_dir = data_dir or os.getenv("OTA_DATA_DIR", "/data")
    resolved_token = (admin_token if admin_token is not None else os.getenv("OTA_ADMIN_TOKEN", "")).strip()
    resolved_base_url = (public_base_url or os.getenv("OTA_PUBLIC_BASE_URL", "https://sdgen.pp.ua/ota")).rstrip("/")
    resolved_app_id = app_id or os.getenv("OTA_APP_ID", "ua.pp.sdgen.app")
    resolved_app_name = app_name or os.getenv("OTA_APP_NAME", "SD-GEN016")
    resolved_max = max_releases if max_releases is not None else int(os.getenv("OTA_MAX_RELEASES", "15"))

    storage = OtaStorage(
        data_dir=resolved_data_dir,
        public_base_url=resolved_base_url,
        app_id=resolved_app_id,
        app_name=resolved_app_name,
        max_releases=resolved_max,
    )

    app = FastAPI(
        title="SD-GEN016 OTA Service",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
    )
    app.state.storage = storage

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_parse_cors_origins(os.getenv("OTA_CORS_ORIGINS", "")),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-OTA-Admin-Token", "Accept"],
    )

    def require_admin(
        x_ota_admin_token: Optional[str] = Header(default=None),
        authorization: Optional[str] = Header(default=None),
    ) -> None:
        if not resolved_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OTA_ADMIN_TOKEN не налаштований на сервері.",
            )
        candidate = (x_ota_admin_token or "").strip()
        if not candidate and authorization and authorization.lower().startswith("bearer "):
            candidate = authorization[7:].strip()
        if not candidate or not hmac.compare_digest(candidate, resolved_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Невірний або відсутній токен адміністратора OTA.",
            )

    @app.get("/ota/health")
    def ota_health() -> JSONResponse:
        manifest = storage.get_latest_manifest()
        return JSONResponse(
            content={
                "status": "healthy",
                "service": "sdgen-ota",
                "app_id": manifest["app_id"],
                "has_release": manifest["has_release"],
                "latest_version_code": manifest["version_code"],
                "latest_version_name": manifest["version_name"],
            },
            headers=NO_CACHE_HEADERS,
        )

    @app.get("/ota", include_in_schema=False)
    def ota_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ota/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    @app.get("/ota/", response_class=HTMLResponse)
    def ota_landing() -> HTMLResponse:
        manifest = storage.get_latest_manifest()
        return HTMLResponse(content=render_landing_page(manifest), headers=NO_CACHE_HEADERS)

    @app.get("/ota/admin", response_class=HTMLResponse)
    def ota_admin() -> HTMLResponse:
        return HTMLResponse(content=render_admin_page(resolved_base_url), headers=NO_CACHE_HEADERS)

    @app.get("/ota/api/latest")
    def ota_latest(current_code: Optional[int] = Query(default=None, ge=0)) -> JSONResponse:
        manifest = storage.get_latest_manifest(current_code=current_code)
        return JSONResponse(content=manifest, headers=NO_CACHE_HEADERS)

    @app.get("/ota/download/latest.apk")
    def ota_download_latest() -> FileResponse:
        try:
            apk_path, meta = storage.get_release_for_download(version_code=None)
        except OtaNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        headers = {
            **NO_CACHE_HEADERS,
            "Content-Disposition": f'attachment; filename="{meta["file_name"]}"',
            "X-OTA-Version-Code": str(meta["version_code"]),
            "X-OTA-Version-Name": str(meta["version_name"]),
            "X-OTA-SHA256": str(meta["sha256"]),
        }
        return FileResponse(
            path=apk_path,
            media_type="application/vnd.android.package-archive",
            filename=meta["file_name"],
            headers=headers,
        )

    @app.get("/ota/download/{version_code}.apk")
    def ota_download_version(version_code: int) -> FileResponse:
        try:
            apk_path, meta = storage.get_release_for_download(version_code=version_code)
        except OtaNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        headers = {
            **NO_CACHE_HEADERS,
            "Content-Disposition": f'attachment; filename="{meta["file_name"]}"',
            "X-OTA-Version-Code": str(meta["version_code"]),
            "X-OTA-Version-Name": str(meta["version_name"]),
            "X-OTA-SHA256": str(meta["sha256"]),
        }
        return FileResponse(
            path=apk_path,
            media_type="application/vnd.android.package-archive",
            filename=meta["file_name"],
            headers=headers,
        )

    @app.get("/ota/api/releases", dependencies=[Depends(require_admin)])
    def ota_list_releases() -> JSONResponse:
        return JSONResponse(content=storage.list_releases(), headers=NO_CACHE_HEADERS)

    @app.post("/ota/api/releases", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
    def ota_upload_release(
        file: UploadFile = File(...),
        version_code: int = Form(...),
        version_name: str = Form(...),
        changelog: str = Form(default=""),
        is_mandatory: bool = Form(default=False),
        min_supported_version_code: Optional[int] = Form(default=None),
        replace: bool = Form(default=False),
    ) -> JSONResponse:
        filename = (file.filename or "").lower()
        if filename and not filename.endswith(".apk"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Дозволено завантажувати лише файли .apk.",
            )
        try:
            release = storage.save_release(
                file_stream=file.file,
                version_code=version_code,
                version_name=version_name,
                changelog=changelog,
                is_mandatory=is_mandatory,
                min_supported_version_code=min_supported_version_code,
                replace=replace,
            )
        except OtaValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except OtaConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        finally:
            file.file.close()
        return JSONResponse(content=release, status_code=status.HTTP_201_CREATED, headers=NO_CACHE_HEADERS)

    @app.patch("/ota/api/policy", dependencies=[Depends(require_admin)])
    def ota_update_policy(payload: PolicyUpdateRequest) -> JSONResponse:
        try:
            manifest = storage.update_policy(
                min_supported_version_code=payload.min_supported_version_code,
                active_version_code=payload.active_version_code,
                is_mandatory=payload.is_mandatory,
                changelog=payload.changelog,
            )
        except OtaValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except OtaNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return JSONResponse(content=manifest, headers=NO_CACHE_HEADERS)

    @app.delete("/ota/api/releases/{version_code}", dependencies=[Depends(require_admin)])
    def ota_delete_release(version_code: int) -> JSONResponse:
        try:
            storage.delete_release(version_code=version_code)
        except OtaNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except OtaConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return JSONResponse(content={"deleted": version_code}, headers=NO_CACHE_HEADERS)

    return app


app = create_ota_app()
