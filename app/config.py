from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET_KEY: str
    FERNET_KEY: str

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/calendars/google/callback"

    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""
    MICROSOFT_REDIRECT_URI: str = "http://localhost:8000/calendars/outlook/callback"
    MICROSOFT_TENANT_ID: str = "common"

    DATABASE_URL: str = "sqlite:///./calendar_sync.db"

    class Config:
        env_file = ".env"


settings = Settings()
