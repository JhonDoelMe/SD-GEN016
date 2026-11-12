"""SQLite and filesystem storage layer for the standalone SD-GEN016 OTA service."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

APK_ZIP_MAGIC = b"PK\x03\x04"
MAX_APK_BYTES = 150 * 1024 * 1024  # 150 MiB hard ceiling
VERSION_NAME_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:-[A-Za-z0-9._-]+)?$")


class OtaValidationError(ValueError):
    """Raised when uploaded APK metadata or content violates validation rules."""


class OtaConflictError(RuntimeError):
    """Raised when version_code conflicts with an existing release."""


class OtaNotFoundError(LookupError):
    """Raised when requested release does not exist."""


class OtaStorage:
    """Thread-safe SQLite + local disk storage for APK releases and update policy."""

    def __init__(
        self,
        data_dir: str | Path,
        public_base_url: str = "https://sdgen.pp.ua/ota",
        app_id: str = "ua.pp.sdgen.app",
        app_name: str = "SD-GEN016",
        max_releases: int = 15,
    ) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.apks_dir = self.data_dir / "apks"
        self.db_path = self.data_dir / "ota.db"
        self.public_base_url = public_base_url.rstrip("/")
        self.app_id = app_id
        self.app_name = app_name
        self.max_releases = max(1, int(max_releases))

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.apks_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS releases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_code INTEGER NOT NULL UNIQUE,
                    version_name TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    changelog TEXT NOT NULL DEFAULT '',
                    is_mandatory INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    download_count INTEGER NOT NULL DEFAULT 0,
                    published_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS policy (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    min_supported_version_code INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                """
            )
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO policy (id, min_supported_version_code, updated_at)
                VALUES (1, 0, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (now_iso,),
            )

    def _get_min_supported(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT min_supported_version_code FROM policy WHERE id = 1"
        ).fetchone()
        return int(row["min_supported_version_code"]) if row else 0

    def _row_to_dict(self, row: sqlite3.Row, min_supported: int) -> dict[str, Any]:
        version_code = int(row["version_code"])
        version_name = str(row["version_name"])
        return {
            "app_id": self.app_id,
            "app_name": self.app_name,
            "has_release": True,
            "version_code": version_code,
            "version_name": version_name,
            "min_supported_version_code": min_supported,
            "is_mandatory": bool(row["is_mandatory"]),
            "is_active": bool(row["is_active"]),
            "file_name": str(row["file_name"]),
            "file_size": int(row["file_size"]),
            "sha256": str(row["sha256"]),
            "changelog": str(row["changelog"] or ""),
            "download_count": int(row["download_count"] or 0),
            "published_at": str(row["published_at"]),
            "download_url": f"{self.public_base_url}/download/latest.apk",
            "version_download_url": f"{self.public_base_url}/download/{version_code}.apk",
            "landing_url": f"{self.public_base_url}/",
        }

    def get_latest_manifest(self, current_code: int | None = None) -> dict[str, Any]:
        """Return latest active release metadata and update flags for the given client build."""
        with self._connect() as conn:
            min_supported = self._get_min_supported(conn)
            row = conn.execute(
                "SELECT * FROM releases WHERE is_active = 1 ORDER BY version_code DESC LIMIT 1"
            ).fetchone()
            if row is None:
                manifest: dict[str, Any] = {
                    "app_id": self.app_id,
                    "app_name": self.app_name,
                    "has_release": False,
                    "version_code": 0,
                    "version_name": "",
                    "min_supported_version_code": min_supported,
                    "is_mandatory": False,
                    "file_name": "",
                    "file_size": 0,
                    "sha256": "",
                    "changelog": "",
                    "download_url": f"{self.public_base_url}/download/latest.apk",
                    "landing_url": f"{self.public_base_url}/",
                    "published_at": None,
                }
                if current_code is not None:
                    manifest["update_available"] = False
                    manifest["force_update"] = False
                return manifest

            manifest = self._row_to_dict(row, min_supported)
            if current_code is not None:
                update_available = current_code < manifest["version_code"]
                force_update = update_available and (
                    current_code < min_supported or manifest["is_mandatory"]
                )
                manifest["update_available"] = update_available
                manifest["force_update"] = force_update
            return manifest

    def list_releases(self) -> dict[str, Any]:
        """List all releases ordered newest-first alongside current policy."""
        with self._connect() as conn:
            min_supported = self._get_min_supported(conn)
            rows = conn.execute(
                "SELECT * FROM releases ORDER BY version_code DESC"
            ).fetchall()
            return {
                "min_supported_version_code": min_supported,
                "releases": [self._row_to_dict(r, min_supported) for r in rows],
            }

    def save_release(
        self,
        file_stream: BinaryIO,
        version_code: int,
        version_name: str,
        changelog: str = "",
        is_mandatory: bool = False,
        min_supported_version_code: int | None = None,
        replace: bool = False,
    ) -> dict[str, Any]:
        """Validate, stream to disk, hash, store metadata, and prune old releases."""
        if version_code < 1:
            raise OtaValidationError("version_code має бути цілим числом >= 1.")
        clean_ver = (version_name or "").strip()
        if not VERSION_NAME_RE.match(clean_ver):
            raise OtaValidationError("Некоректний формат version_name (очікується напр. 5.6.3).")
        if min_supported_version_code is not None and min_supported_version_code < 0:
            raise OtaValidationError("min_supported_version_code не може бути від'ємним.")

        stored_name = f"sd-gen016-v{clean_ver}-b{version_code}.apk"
        public_file_name = f"sd-gen016-v{clean_ver}.apk"
        final_path = (self.apks_dir / stored_name).resolve()
        if final_path.parent != self.apks_dir:
            raise OtaValidationError("Неприпустиме ім'я файлу.")
        tmp_path = self.apks_dir / f".upload-{os.getpid()}-{version_code}.tmp"

        hasher = hashlib.sha256()
        total_bytes = 0
        first_chunk = True
        try:
            with open(tmp_path, "wb") as out_fp:
                while True:
                    chunk = file_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    if first_chunk:
                        first_chunk = False
                        if len(chunk) < 4 or chunk[:4] != APK_ZIP_MAGIC:
                            raise OtaValidationError(
                                "Файл не є валідним APK/ZIP-архівом (відсутня сигнатура PK)."
                            )
                    total_bytes += len(chunk)
                    if total_bytes > MAX_APK_BYTES:
                        raise OtaValidationError(
                            f"Файл перевищує максимальний розмір {MAX_APK_BYTES // (1024 * 1024)} МБ."
                        )
                    hasher.update(chunk)
                    out_fp.write(chunk)

            if total_bytes < 1024:
                raise OtaValidationError("APK файл занадто малий або порожній.")

            sha256_hex = hasher.hexdigest()
            now_iso = datetime.now(timezone.utc).isoformat()

            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT version_code, stored_name FROM releases WHERE version_code = ?",
                    (version_code,),
                ).fetchone()
                max_row = conn.execute(
                    "SELECT COALESCE(MAX(version_code), 0) AS max_code FROM releases"
                ).fetchone()
                max_code = int(max_row["max_code"]) if max_row else 0

                if not replace and version_code <= max_code:
                    raise OtaConflictError(
                        f"version_code={version_code} має бути строго більшим за поточний максимум ({max_code})."
                    )

                old_stored_to_remove: str | None = None
                if existing and existing["stored_name"] != stored_name:
                    old_stored_to_remove = str(existing["stored_name"])

                os.replace(tmp_path, final_path)

                conn.execute("UPDATE releases SET is_active = 0")
                if existing:
                    conn.execute(
                        """
                        UPDATE releases
                        SET version_name = ?, file_name = ?, stored_name = ?,
                            file_size = ?, sha256 = ?, changelog = ?,
                            is_mandatory = ?, is_active = 1, published_at = ?
                        WHERE version_code = ?
                        """,
                        (
                            clean_ver,
                            public_file_name,
                            stored_name,
                            total_bytes,
                            sha256_hex,
                            (changelog or "").strip(),
                            1 if is_mandatory else 0,
                            now_iso,
                            version_code,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO releases (
                            version_code, version_name, file_name, stored_name,
                            file_size, sha256, changelog, is_mandatory,
                            is_active, download_count, published_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?)
                        """,
                        (
                            version_code,
                            clean_ver,
                            public_file_name,
                            stored_name,
                            total_bytes,
                            sha256_hex,
                            (changelog or "").strip(),
                            1 if is_mandatory else 0,
                            now_iso,
                        ),
                    )

                if min_supported_version_code is not None:
                    conn.execute(
                        "UPDATE policy SET min_supported_version_code = ?, updated_at = ? WHERE id = 1",
                        (int(min_supported_version_code), now_iso),
                    )

                self._prune_old_releases(conn)
                min_supported = self._get_min_supported(conn)
                saved = conn.execute(
                    "SELECT * FROM releases WHERE version_code = ?",
                    (version_code,),
                ).fetchone()

            if old_stored_to_remove:
                self._safe_unlink(self.apks_dir / old_stored_to_remove)

            return self._row_to_dict(saved, min_supported)
        except Exception:
            self._safe_unlink(tmp_path)
            raise

    def _prune_old_releases(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT version_code, stored_name, is_active FROM releases ORDER BY version_code DESC"
        ).fetchall()
        if len(rows) <= self.max_releases:
            return
        for row in rows[self.max_releases :]:
            if int(row["is_active"]) == 1:
                continue
            conn.execute(
                "DELETE FROM releases WHERE version_code = ?",
                (int(row["version_code"]),),
            )
            self._safe_unlink(self.apks_dir / str(row["stored_name"]))

    def _safe_unlink(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            if resolved.parent == self.apks_dir and resolved.exists():
                resolved.unlink()
        except OSError:
            pass

    def get_release_for_download(self, version_code: int | None = None) -> tuple[Path, dict[str, Any]]:
        """Resolve APK file path on disk for active release or explicit version_code."""
        with self._connect() as conn:
            min_supported = self._get_min_supported(conn)
            if version_code is None:
                row = conn.execute(
                    "SELECT * FROM releases WHERE is_active = 1 ORDER BY version_code DESC LIMIT 1"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM releases WHERE version_code = ?",
                    (version_code,),
                ).fetchone()
            if row is None:
                raise OtaNotFoundError("Реліз APK не знайдено.")
            apk_path = (self.apks_dir / os.path.basename(str(row["stored_name"]))).resolve()
            if apk_path.parent != self.apks_dir or not apk_path.is_file():
                raise OtaNotFoundError("Файл APK відсутній на диску сервера.")
            conn.execute(
                "UPDATE releases SET download_count = download_count + 1 WHERE version_code = ?",
                (int(row["version_code"]),),
            )
            return apk_path, self._row_to_dict(row, min_supported)

    def update_policy(
        self,
        min_supported_version_code: int | None = None,
        active_version_code: int | None = None,
        is_mandatory: bool | None = None,
        changelog: str | None = None,
    ) -> dict[str, Any]:
        """Update minimum supported build version, switch active release (rollback), or update flags."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            if active_version_code is not None:
                target = conn.execute(
                    "SELECT version_code FROM releases WHERE version_code = ?",
                    (active_version_code,),
                ).fetchone()
                if target is None:
                    raise OtaNotFoundError(f"Реліз build {active_version_code} не знайдено.")
                conn.execute("UPDATE releases SET is_active = 0")
                conn.execute(
                    "UPDATE releases SET is_active = 1 WHERE version_code = ?",
                    (active_version_code,),
                )

            if min_supported_version_code is not None:
                if min_supported_version_code < 0:
                    raise OtaValidationError("min_supported_version_code не може бути від'ємним.")
                conn.execute(
                    "UPDATE policy SET min_supported_version_code = ?, updated_at = ? WHERE id = 1",
                    (int(min_supported_version_code), now_iso),
                )

            if is_mandatory is not None or changelog is not None:
                active = conn.execute(
                    "SELECT version_code FROM releases WHERE is_active = 1 LIMIT 1"
                ).fetchone()
                if active is not None:
                    if is_mandatory is not None:
                        conn.execute(
                            "UPDATE releases SET is_mandatory = ? WHERE version_code = ?",
                            (1 if is_mandatory else 0, int(active["version_code"])),
                        )
                    if changelog is not None:
                        conn.execute(
                            "UPDATE releases SET changelog = ? WHERE version_code = ?",
                            (changelog.strip(), int(active["version_code"])),
                        )

        return self.get_latest_manifest()

    def delete_release(self, version_code: int) -> None:
        """Delete a release by version_code (refuses deleting active release when others exist)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT stored_name, is_active FROM releases WHERE version_code = ?",
                (version_code,),
            ).fetchone()
            if row is None:
                raise OtaNotFoundError(f"Реліз build {version_code} не знайдено.")
            total = conn.execute("SELECT COUNT(*) AS cnt FROM releases").fetchone()["cnt"]
            if int(row["is_active"]) == 1 and int(total) > 1:
                raise OtaConflictError(
                    "Спочатку активуйте інший реліз (rollback), перш ніж видаляти поточний активний."
                )
            conn.execute("DELETE FROM releases WHERE version_code = ?", (version_code,))
            stored_name = str(row["stored_name"])
        self._safe_unlink(self.apks_dir / stored_name)
