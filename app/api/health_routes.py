from fastapi import APIRouter, Depends
from ..services.health_service import HealthCheckService
from ..utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/health", tags=["health"])

@router.get("/")
async def health_check():
    """Basic health check"""
    return {"status": "ok"}

@router.get("/detailed")
async def detailed_health_check():
    """Detailed health check of all services"""
    health_service = HealthCheckService()
    return await health_service.check_all()

@router.get("/database")
async def database_health():
    """Check only database health"""
    health_service = HealthCheckService()
    return await health_service.check_database()
    

@router.get("/llm")
async def llm_health():
    """Check only LLM service health"""
    health_service = HealthCheckService()
    return await health_service.check_llm()

@router.get("/redis")
async def redis_health():
    """Check only Redis health"""
    health_service = HealthCheckService()
    return await health_service.check_redis()

@router.get("/supabase")
async def supabase_health():
    """Check only Supabase health"""
    health_service = HealthCheckService()
    return await health_service.check_supabase()