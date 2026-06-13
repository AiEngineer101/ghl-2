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

    # Write controls. Default is read-only.
    # writes_enabled MUST be True for any PUT/POST/PATCH to GHL.
    # write_allowed_pipeline_ids is a comma-separated allowlist enforced inside the writer
    # itself (defense in depth). Default: only the Production pipeline.
    writes_enabled: bool = False
    write_allowed_pipeline_ids: str = "88V9uYY6visCrtI9V0NR"

    @property
    def write_allowed_pipeline_id_set(self) -> set[str]:
        return {p.strip() for p in self.write_allowed_pipeline_ids.split(",") if p.strip()}


settings = Settings()
