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

    # Uploads
    UPLOAD_DIR: str = "./uploads"

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
