from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List
from functools import lru_cache
import os

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "AI Dashboard API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 4
    
    # Database
    DATABASE_URL: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40
    
    # LLM Configuration
    LLM_PROVIDER: str = "deepseek"  
    GROQ_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    
    # Token Limits
    MAX_PROMPT_TOKENS: int = 10000
    MAX_RESPONSE_TOKENS: int = 4000
    USE_ADVANCED_MODE_THRESHOLD: int = 1000  # Token threshold
    
    # Cache
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: Optional[str] = None
    REDIS_MAX_CONNECTIONS: int = 20
    ENABLE_QUERY_CACHE: bool = True
    QUERY_CACHE_TTL_MINUTES: int = 60
    CHART_CACHE_TTL_HOURS: int = 24
    
    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REQUIRE_API_KEY: bool = False
    API_KEY: Optional[str] = None
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:5173"]
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60
    
    # Monitoring
    SENTRY_DSN: Optional[str] = None
    LOG_LEVEL: str = "INFO"
    
    # File Upload Settings
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 100
    ALLOWED_EXTENSIONS: list = [".csv", ".xlsx", ".xls", ".tsv"]
    TEMP_FILE_CLEANUP_HOURS: int = 24
    
    # Database Connection Pool
    MAX_DYNAMIC_CONNECTIONS: int = 10
    CONNECTION_POOL_SIZE: int = 5
    CONNECTION_POOL_OVERFLOW: int = 10
    CONNECTION_TIMEOUT_SECONDS: int = 30
    
    # Data Processing
    MAX_ROWS_IN_MEMORY: int = 1000000  # 1 million rows
    CHUNK_SIZE: int = 10000
    PANDAS_MAX_COLUMNS: int = 1000
    
    # Supported Database Types
    SUPPORTED_DATABASES: list = [
        "postgresql",
        "mysql", 
        "sqlite",
        "sqlserver",
        "oracle"
    ]
    
    # Cache Settings (for uploaded data)
    CACHE_UPLOADED_DATA: bool = True
    CACHE_TTL_HOURS: int = 24
    MAX_CACHED_DATASETS: int = 100
    
    # Pydantic v2 config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow"
    )

    @property
    def is_production(self) -> bool:
        return not self.DEBUG
    
    @property
    def should_use_advanced_mode(self) -> bool:
        """Determine if we should use graph/vector for large queries"""
        return self.USE_ADVANCED_MODE_THRESHOLD > 0


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance"""
    return Settings()


# Create upload directory if it doesn't exist
def ensure_upload_dir():
    """Ensure upload directory exists"""
    settings = get_settings()
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(f"{settings.UPLOAD_DIR}/csv", exist_ok=True)
    os.makedirs(f"{settings.UPLOAD_DIR}/excel", exist_ok=True)
    os.makedirs(f"{settings.UPLOAD_DIR}/temp", exist_ok=True)
