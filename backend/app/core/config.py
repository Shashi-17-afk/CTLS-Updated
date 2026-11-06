import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    APP_NAME: str = "Logistics OCR Service"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0" if os.environ.get("SERVER_PORT") else "127.0.0.1"
    PORT: int = int(os.environ.get("SERVER_PORT", os.environ.get("PORT", "8000")))
    LOG_LEVEL: str = "INFO"

    # Ingestion & Validation Limits
    MAX_FILE_SIZE_BYTES: int = 25 * 1024 * 1024  # 25 MB
    MIN_FILE_SIZE_BYTES: int = 16  # Bytes
    MAX_PDF_PAGES: int = 50
    MIN_TEXT_CHARS_PER_PAGE: int = 40
    MAX_IMAGE_DIMENSION_PX: int = 10000
    ALLOWED_EXTENSIONS: list[str] = ["pdf", "png", "jpg", "jpeg"]

    # Local OCR Configuration
    OCR_ENABLED: bool = True
    OCR_ENGINE: str = "rapidocr"  # "rapidocr" | "mock"
    OCR_DPI: int = 300
    OCR_MAX_IMAGE_SIDE_PX: int = 4000
    ENABLE_DESKEW: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
