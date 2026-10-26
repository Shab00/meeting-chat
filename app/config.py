from dotenv import load_dotenv

# Explicit path: under uvicorn/FastAPI lifespan the default search can miss
# the repo's .env. Must run before anything reads env vars (e.g. the OpenAI
# clients, which read OPENAI_API_KEY directly from the environment).
load_dotenv(dotenv_path=".env")

from pydantic_settings import BaseSettings, SettingsConfigDict  # noqa: E402


class Settings(BaseSettings):
    google_api_key: str = ""  # unused since the switch to OpenAI; kept for compat
    openai_api_key: str
    meeting_processor_url: str = "http://localhost:8000"
    allowed_origin: str = "http://localhost:8001"
    vector_db_url: str = "postgresql+psycopg://postgres:postgres@localhost:5433/vectordb"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
