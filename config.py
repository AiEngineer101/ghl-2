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

    # Opp-scoped write allowlist (comma-separated opp IDs). Lets specific TEST opportunities
    # in non-allowlisted pipelines (e.g. a Sales sandbox job) receive active writes WITHOUT
    # opening writes to every opp in that pipeline. Other opps stay protected.
    # TEMPORARY: contains the current Sales test opps — remove when Sales testing is done.
    write_allowed_opp_ids: str = "U970gIvE6Q31JKTCGVNw,HCkgP9gfjEJmTbN74ORq,YlKKKJ1WM6UaG5kIDh1h"

    # Per-handler write allowlist (comma-separated HANDLER_IDs). A handler listed here may write
    # to ANY opp it acts on — and since each mover self-scopes to its own pipeline+stage in
    # evaluate(), this is effectively "this ONE move is live for the whole pipeline". It is the
    # migration cutover knob: turn Sales movers live ONE stage at a time for real deals by adding
    # their HANDLER_ID here (then Draft the matching GHL workflow). Empty default = nothing extra
    # is live; only the pipeline/opp allowlists apply.
    write_live_handlers: str = ""

    @property
    def write_allowed_pipeline_id_set(self) -> set[str]:
        return {p.strip() for p in self.write_allowed_pipeline_ids.split(",") if p.strip()}

    @property
    def write_allowed_opp_id_set(self) -> set[str]:
        return {o.strip() for o in self.write_allowed_opp_ids.split(",") if o.strip()}

    @property
    def write_live_handler_set(self) -> set[str]:
        return {h.strip() for h in self.write_live_handlers.split(",") if h.strip()}


settings = Settings()
