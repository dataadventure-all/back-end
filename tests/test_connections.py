import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from app.services.health_service import HealthCheckService
from app.core.config import get_settings

@pytest.fixture
def health_service():
    return HealthCheckService()

@pytest.mark.asyncio
async def test_database_connection(health_service):
    """Test database connection check"""
    result = await health_service.check_database()
    
    assert "healthy" in result
    assert "response_time_ms" in result or "error" in result
    
    if result["healthy"]:
        assert result["response_time_ms"] > 0
        assert "version" in result

@pytest.mark.asyncio
async def test_llm_connection(health_service):
    """Test LLM service connection check"""
    result = await health_service.check_llm()
    
    assert "healthy" in result
    assert "provider" in result
    assert "api_key_configured" in result
    
    if result["healthy"]:
        assert "model" in result
        assert "response_time_ms" in result

@pytest.mark.asyncio
async def test_complete_health_check(health_service):
    """Test complete health check"""
    result = await health_service.check_all()
    
    assert "status" in result
    assert result["status"] in ["healthy", "unhealthy"]
    assert "services" in result
    assert "database" in result["services"]
    assert "llm" in result["services"]

@pytest.mark.asyncio
async def test_connection_with_invalid_database():
    """Test with invalid database URL"""
    with patch('app.core.config.get_settings') as mock_settings:
        mock_settings.return_value.DATABASE_URL = "postgresql://invalid:invalid@localhost:5432/invalid"
        
        health_service = HealthCheckService()
        result = await health_service.check_database()
        
        assert result["healthy"] is False
        assert "error" in result

@pytest.mark.asyncio
async def test_connection_with_invalid_llm_key():
    """Test with invalid LLM API key"""
    with patch('app.core.config.get_settings') as mock_settings:
        mock_settings.return_value.GROQ_API_KEY = "invalid_key"
        mock_settings.return_value.LLM_PROVIDER = "groq"
        
        health_service = HealthCheckService()
        result = await health_service.check_llm()
        
        assert result["healthy"] is False
        assert "error" in result