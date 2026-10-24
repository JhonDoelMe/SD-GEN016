import logging
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("config")

DEFAULT_SECRET_KEY = "sd_gen016_default_secret_key_needs_override_32_chars"
DEFAULT_ADMIN_PASSWORD = "SuperAdminPass123!"


class Settings(BaseSettings):
    APP_ENV: str = "production"
    APP_SECRET_KEY: str = DEFAULT_SECRET_KEY
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Initial SuperAdmin credentials (used only for initial db seed)
    INITIAL_ADMIN_LOGIN: str = "superadmin"
    INITIAL_ADMIN_PASSWORD: str = DEFAULT_ADMIN_PASSWORD
    INITIAL_ADMIN_EMAIL: str = "admin@facility.local"
    INITIAL_ADMIN_FULL_NAME: str = "Головний Системний Адміністратор"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./service_desk.db"

    # Timezone of the facility (handles Kyiv DST winter/summer shifts)
    FACILITY_TIMEZONE: str = "Europe/Kyiv"

    # Uploads & Backups
    UPLOAD_DIR: str = "./uploads"
    BACKUP_DIR: str = "./backups"

    # Domain, Host Protection & CORS (Configured via .env)
    PRIMARY_DOMAIN: str = "generator-016.pp.ua"
    ALLOWED_HOSTS: str = ""
    CORS_ORIGINS: str = ""
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_SECONDS: int = 300

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL

    @property
    def has_insecure_defaults(self) -> bool:
        return (
            self.APP_SECRET_KEY in (DEFAULT_SECRET_KEY, "change_this_to_a_secure_random_secret_key_minimum_32_chars")
            or len(self.APP_SECRET_KEY) < 32
            or self.INITIAL_ADMIN_PASSWORD in (DEFAULT_ADMIN_PASSWORD, "SuperAdminSecretPass123!")
        )

    def check_security_warnings(self) -> None:
        if self.APP_SECRET_KEY in (DEFAULT_SECRET_KEY, "change_this_to_a_secure_random_secret_key_minimum_32_chars") or len(self.APP_SECRET_KEY) < 32:
            logger.warning(
                "[SECURITY WARNING] APP_SECRET_KEY uses a default or weak value (<32 chars). "
                "Override APP_SECRET_KEY in .env for production deployment!"
            )
        if self.INITIAL_ADMIN_PASSWORD in (DEFAULT_ADMIN_PASSWORD, "SuperAdminSecretPass123!"):
            logger.warning(
                "[SECURITY WARNING] INITIAL_ADMIN_PASSWORD uses a default value. "
                "Change the SuperAdmin password via POST /api/v1/auth/change-password or override in .env!"
            )

    @property
    def effective_allowed_hosts(self) -> list[str]:
        """
        Dynamically derives trusted hosts list from PRIMARY_DOMAIN and ALLOWED_HOSTS.
        Always includes localhost, loopback, docker service names and test harnesses.
        """
        if self.ALLOWED_HOSTS.strip():
            hosts = [h.strip() for h in self.ALLOWED_HOSTS.split(",") if h.strip()]
        else:
            domain = self.PRIMARY_DOMAIN.strip()
            hosts = [
                domain,
                f"www.{domain}",
                "localhost",
                "127.0.0.1",
            ]
        # Always guarantee system, container, and test runners can resolve
        for def_host in ("testserver", "test", "app", "nginx"):
            if def_host not in hosts:
                hosts.append(def_host)
        return hosts

    @property
    def effective_cors_origins(self) -> list[str]:
        """
        Dynamically derives allowed CORS origins from PRIMARY_DOMAIN and CORS_ORIGINS.
        """
        if self.CORS_ORIGINS.strip():
            return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        domain = self.PRIMARY_DOMAIN.strip()
        return [
            f"https://{domain}",
            f"https://www.{domain}",
            f"http://{domain}",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
