#!/usr/bin/env python3
"""
Build a clean, Zero-.env ready-to-install distribution ZIP archive (`dist/sd-gen016-v<version>-install.zip`)
plus SHA-256 checksum file (`*.sha256`), strictly excluding secrets, local DBs, build caches, and git metadata.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent

EXCLUDED_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build-apk",
    "data",
    "htmlcov",
    ".gradle",
    "captures",
}

EXCLUDED_PATH_PREFIXES = (
    "android/build/",
    "android/.gradle/",
    "android/app/build/",
    "ota-server/data/",
    "uploads/",
    "backups/",
    "docker/ssl/",
    "docker/ssl-fallback/",
    "docker/firebase/",
)

KEEP_PLACEHOLDERS = {
    "uploads/.gitkeep",
    "backups/.gitkeep",
    "docker/ssl/.gitkeep",
    "docker/ssl-fallback/.gitkeep",
}

EXCLUDED_FILENAMES = {
    ".env",
    ".ota.env",
    "local.properties",
    "keystore.properties",
    "google-services.json",
    "firebase-service-account.json",
    "Thumbs.db",
    ".DS_Store",
}

EXCLUDED_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".apk",
    ".jks",
    ".keystore",
    ".pem",
    ".key",
    ".log",
)


def should_include(rel_posix: str) -> bool:
    if rel_posix in KEEP_PLACEHOLDERS:
        return True

    parts = rel_posix.split("/")
    if any(part in EXCLUDED_DIRS for part in parts):
        return False

    name = parts[-1]
    if name in EXCLUDED_FILENAMES or name.startswith("local_") or name.startswith("deploy_local."):
        return False
    if rel_posix.startswith("scripts/local_"):
        return False
    if "firebase-adminsdk" in name.lower() and name.endswith(".json"):
        return False
    if any(rel_posix.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES):
        return False
    if rel_posix.startswith("ota-server/") and name == ".env":
        return False
    if name.lower().endswith(EXCLUDED_SUFFIXES):
        return False
    return True


def build_zip() -> Path:
    version_data = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    version_name = version_data["versionName"]

    dist_dir = ROOT / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dist_dir / f"sd-gen016-v{version_name}-install.zip"
    sha_path = dist_dir / f"sd-gen016-v{version_name}-install.zip.sha256"

    root_folder = f"sd-gen016-v{version_name}"
    file_count = 0

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file():
                continue
            rel_posix = path.relative_to(ROOT).as_posix()
            if not should_include(rel_posix):
                continue
            zf.write(path, arcname=f"{root_folder}/{rel_posix}")
            file_count += 1

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    sha_path.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    print(f"Built {zip_path.relative_to(ROOT)} ({file_count} files, {zip_path.stat().st_size} bytes)")
    print(f"SHA-256: {digest}")
    return zip_path


if __name__ == "__main__":
    build_zip()
