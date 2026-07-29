from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    ludos_api_base_url: str = "https://api.ludos.pro/api3"
    ludos_api_key: str

    sync_interval_hours: float = 6.0
    ludos_min_request_interval_seconds: float = 1.5
    ludos_max_retries: int = 3

    frontend_origin: str = "*"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
