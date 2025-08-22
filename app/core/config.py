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
    LLM_PROVIDER: str = "groq"  # groq, openai, anthropic
    GROQ_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    
    # Token Limits
    MAX_PROMPT_TOKENS: int = 10000
    MAX_RESPONSE_TOKENS: int = 4000
    USE_ADVANCED_MODE_THRESHOLD: int = 10000  # Switch to graph/vector
    
    # Cache
    REDIS_URL: Optional[str] = "redis://localhost:6379/0"
    CACHE_TTL: int = 3600  # 1 hour
    
    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    
    # Monitoring
    SENTRY_DSN: Optional[str] = None
    LOG_LEVEL: str = "INFO"
    
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