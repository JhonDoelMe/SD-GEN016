"""Avatar image validation, resizing, and safe storage service."""

from __future__ import annotations

import asyncio
import io
import time
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.app.config import settings

MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB
AVATAR_SIZE = (256, 256)
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}


def _process_and_write_avatar_sync(raw_bytes: bytes, user_id: int) -> str:
    """Validate raster image bytes, crop to 256x256 WebP, and write under UPLOAD_DIR/avatars."""
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            if (img.format or "").upper() not in ALLOWED_IMAGE_FORMATS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Непідтримуваний формат зображення. Дозволено JPEG, PNG, WebP або GIF.",
                )
            transposed = ImageOps.exif_transpose(img)
            if transposed.mode not in ("RGB", "RGBA"):
                transposed = transposed.convert("RGBA" if "A" in transposed.getbands() else "RGB")
            fitted = ImageOps.fit(transposed, AVATAR_SIZE, method=Image.Resampling.LANCZOS)

            uploads_root = Path(settings.UPLOAD_DIR).resolve()
            avatars_dir = uploads_root / "avatars"
            avatars_dir.mkdir(parents=True, exist_ok=True)

            filename = f"user_{user_id}_{int(time.time() * 1000)}.webp"
            target_path = (avatars_dir / filename).resolve()
            if not target_path.is_relative_to(uploads_root):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Некоректний шлях збереження аватара.",
                )

            fitted.save(target_path, format="WEBP", quality=85, method=4)
            return f"avatars/{filename}"
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не вдалося обробити зображення. Завантажте коректний файл JPEG, PNG або WebP.",
        ) from exc


def delete_avatar_file(avatar_path: Optional[str]) -> None:
    """Safely remove an existing avatar file under UPLOAD_DIR if present."""
    if not avatar_path:
        return
    try:
        uploads_root = Path(settings.UPLOAD_DIR).resolve()
        candidate = (uploads_root / avatar_path).resolve()
        if candidate.is_relative_to(uploads_root) and candidate.is_file():
            candidate.unlink()
    except OSError:
        pass


async def save_user_avatar(upload: UploadFile, user_id: int) -> str:
    """Read UploadFile safely up to 5 MB and persist normalized 256x256 WebP avatar."""
    raw_bytes = await upload.read(MAX_AVATAR_BYTES + 1)
    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл аватара порожній.",
        )
    if len(raw_bytes) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Розмір файлу перевищує ліміт 5 МБ.",
        )
    return await asyncio.to_thread(_process_and_write_avatar_sync, raw_bytes, user_id)
