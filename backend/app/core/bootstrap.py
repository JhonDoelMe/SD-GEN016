"""
Zero-.env bootstrap configuration manager (`data/instance.config.json`).

Stores generated cryptographic bootstrap secrets (`app_secret_key`), optional
dynamic `database_url`, and first-run setup completion state outside `.env`
with restricted file permissions (`0o600` on POSIX).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_INSTANCE_CONFIG_PATH = Path("./data/instance.config.json")

# In-process flag set during startup lifespan when running in clean Setup Wizard mode
_SETUP_REQUIRED: bool = False


def is_setup_required() -> bool:
    """Return True if the application is waiting for initial Web Setup Wizard completion."""
    return _SETUP_REQUIRED


def set_setup_required(required: bool) -> None:
    """Set runtime initial setup gate flag."""
    global _SETUP_REQUIRED
    _SETUP_REQUIRED = bool(required)


def has_env_file() -> bool:
    """Return True if an explicit .env file exists on disk."""
    return Path(".env").is_file() or Path("../.env").is_file()


def get_instance_config_path(override_path: Optional[Path] = None) -> Path:
    """Resolve the active path to instance.config.json."""
    if override_path is not None:
        return Path(override_path)
    env_override = (os.getenv("SDGEN_INSTANCE_CONFIG") or os.getenv("INSTANCE_CONFIG_PATH") or "").strip()
    if env_override:
        return Path(env_override)
    return DEFAULT_INSTANCE_CONFIG_PATH


def generate_instance_secret() -> str:
    """Generate a cryptographically random >=64-char secret key."""
    return secrets.token_urlsafe(48)


def load_instance_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Safely load JSON configuration from instance.config.json if present."""
    path = get_instance_config_path(config_path)
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to read instance config (%s): %s", path.name, type(exc).__name__)
        return {}


def save_instance_config(data: Dict[str, Any], config_path: Optional[Path] = None) -> Path:
    """Atomically write instance.config.json with owner-only permissions (0o600)."""
    path = get_instance_config_path(config_path)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(parent, 0o700)
    except OSError:
        pass

    payload = dict(data)
    payload.setdefault("version", 1)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    fd, tmp_name = tempfile.mkstemp(prefix=".instance_cfg_", suffix=".tmp", dir=str(parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(serialized)
        try:
            os.chmod(tmp_name, 0o600)
        except OSError:
            pass
        os.replace(tmp_name, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def update_instance_config(updates: Dict[str, Any], config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Merge updates into instance.config.json atomically and return resulting dict."""
    current = load_instance_config(config_path)
    current.update(updates)
    save_instance_config(current, config_path)
    return current


def is_setup_completed(config_path: Optional[Path] = None) -> bool:
    """Return True if instance.config.json marks initial CMS setup as completed."""
    cfg = load_instance_config(config_path)
    return bool(cfg.get("setup_completed", False))


def instance_config_exists(config_path: Optional[Path] = None) -> bool:
    """Return True if instance.config.json currently exists on disk."""
    return get_instance_config_path(config_path).is_file()
