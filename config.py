from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ghl_pit: str = ""
    ghl_location_id: str = "8aQHgJUX2bFYBHZ4Qizg"
    ghl_api_base: str = "https://services.leadconnectorhq.com"
    ghl_api_version: str = "2021-07-28"

    database_url: str = "sqlite:///./shadow.db"

    mode: str = "shadow"
    log_level: str = "INFO"
    webhook_secret: str = ""


settings = Settings()
