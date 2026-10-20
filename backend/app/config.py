from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str = "production"
    APP_SECRET_KEY: str = "sd_gen016_default_secret_key_needs_override_32_chars"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Initial SuperAdmin credentials (used only for initial db seed)
    INITIAL_ADMIN_LOGIN: str = "superadmin"
    INITIAL_ADMIN_PASSWORD: str = "SuperAdminPass123!"
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
