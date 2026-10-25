from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    google_api_key: str
    meeting_processor_url: str = "http://localhost:8000"
    allowed_origin: str = "http://localhost:8001"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
