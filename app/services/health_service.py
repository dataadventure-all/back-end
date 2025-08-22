import asyncio
from typing import Dict, Any, List
from datetime import datetime
import asyncpg
from sqlalchemy import text
from ..core.database import get_db, get_raw_connection
from ..core.config import get_settings
from ..services.llm_service import LLMService
from ..utils.logger import get_logger
import httpx
import redis.asyncio as redis
from supabase import create_client, Client

logger = get_logger(__name__)
settings = get_settings()

class HealthCheckService:
    """Comprehensive health check service"""
    
    def __init__(self):
        self.checks_passed = {}
        self.checks_details = {}
        
    async def check_all(self) -> Dict[str, Any]:
        """Run all health checks"""
        start_time = datetime.now()
        
        # Run checks in parallel
        checks = await asyncio.gather(
            self.check_database(),
            self.check_supabase(),
            self.check_llm(),
            self.check_redis(),
            return_exceptions=True
        )
        
        # Process results
        db_health, supabase_health, llm_health, redis_health = checks
        
        # Calculate overall health
        all_healthy = all([
            isinstance(db_health, dict) and db_health.get('healthy', False),
            isinstance(llm_health, dict) and llm_health.get('healthy', False),
            # Optional services
            isinstance(supabase_health, dict) and supabase_health.get('healthy', False) 
                if settings.SUPABASE_URL else True,
            isinstance(redis_health, dict) and redis_health.get('healthy', False) 
                if settings.REDIS_URL else True,
        ])
        
        execution_time = (datetime.now() - start_time).total_seconds()
        
        return {
            "status": "healthy" if all_healthy else "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "version": settings.APP_VERSION,
            "execution_time_ms": execution_time * 1000,
            "services": {
                "database": db_health if isinstance(db_health, dict) else {"healthy": False, "error": str(db_health)},
                "supabase": supabase_health if isinstance(supabase_health, dict) else {"healthy": False, "error": str(supabase_health)},
                "llm": llm_health if isinstance(llm_health, dict) else {"healthy": False, "error": str(llm_health)},
                "redis": redis_health if isinstance(redis_health, dict) else {"healthy": False, "error": str(redis_health)},
            }
        }
    
    async def check_database(self) -> Dict[str, Any]:
        """Check PostgreSQL database connection"""
        try:
            start = datetime.now()
            
            # Method 1: Check with asyncpg directly
            async with get_raw_connection() as conn:
                # Test query
                result = await conn.fetchval("SELECT 1")
                version = await conn.fetchval("SELECT version()")
                
                # Get database stats
                db_size = await conn.fetchval("""
                    SELECT pg_size_pretty(pg_database_size(current_database()))
                """)
                
                table_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """)
                
            response_time = (datetime.now() - start).total_seconds() * 1000
            
            return {
                "healthy": True,
                "response_time_ms": response_time,
                "version": version.split(' ')[0] if version else "Unknown",
                "database_size": db_size,
                "table_count": table_count,
                "connection_string": self._mask_connection_string(settings.DATABASE_URL)
            }
            
        except Exception as e:
            logger.error(f"Database health check failed: {str(e)}")
            return {
                "healthy": False,
                "error": str(e),
                "connection_string": self._mask_connection_string(settings.DATABASE_URL)
            }
    
    # async def check_supabase(self) -> Dict[str, Any]:
    #     """Check Supabase connection"""
    #     if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
    #         return {
    #             "healthy": False,
    #             "error": "Supabase not configured",
    #             "configured": False
    #         }
        
    #     try:
    #         start = datetime.now()
            
    #         # Initialize Supabase client
    #         supabase: Client = create_client(
    #             settings.SUPABASE_URL,
    #             settings.SUPABASE_KEY
    #         )
            
    #         # Test query - get tables
    #         response = supabase.table("tabbranch").select("*").limit(1).execute()
            
    #         response_time = (datetime.now() - start).total_seconds() * 1000
            
    #         return {
    #             "healthy": True,
    #             "response_time_ms": response_time,
    #             "url": settings.SUPABASE_URL,
    #             "configured": True
    #         }
            
    #     except Exception as e:
    #         logger.error(f"Supabase health check failed: {str(e)}")
    #         return {
    #             "healthy": False,
    #             "error": str(e),
    #             "configured": True
    #         }

    async def check_supabase(self) -> Dict[str, Any]:
        """Check Supabase Connection"""
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            return {
                "healthy": False,
                "error": "Supabase not configured",
                "configured": False
            }
        
        try:
            start = datetime.now()
            
            supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            
            response_time = (datetime.now() - start).total_seconds() * 1000
            
            return {
                "healthy": True,
                "response_time_ms": response_time,
                "configured": True
            }
            
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "configured": True
            }
    
    async def check_llm(self) -> Dict[str, Any]:
        """Check LLM service connection"""
        try:
            start = datetime.now()
            
            # Initialize LLM service
            llm_service = LLMService()
            
            # Test with simple prompt
            test_prompt = "Return 'OK' if you can read this"
            
            if settings.LLM_PROVIDER == "groq":
                result = await self._test_groq()
            elif settings.LLM_PROVIDER == "openai":
                result = await self._test_openai()
            else:
                result = {"error": f"Unknown provider: {settings.LLM_PROVIDER}"}
            
            response_time = (datetime.now() - start).total_seconds() * 1000
            
            # Test token counting
            token_count = llm_service.count_tokens(test_prompt)
            
            return {
                "healthy": result.get("success", False),
                "provider": settings.LLM_PROVIDER,
                "model": result.get("model", "unknown"),
                "response_time_ms": response_time,
                "token_counter_working": token_count > 0,
                "api_key_configured": bool(self._get_api_key()),
                **result
            }
            
        except Exception as e:
            logger.error(f"LLM health check failed: {str(e)}")
            return {
                "healthy": False,
                "provider": settings.LLM_PROVIDER,
                "error": str(e),
                "api_key_configured": bool(self._get_api_key())
            }
    
    async def _test_groq(self) -> Dict[str, Any]:
        """Test Groq API connection"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "mixtral-8x7b-32768",
                        "messages": [{"role": "user", "content": "Say 'OK'"}],
                        "max_tokens": 10,
                        "temperature": 0
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "model": data.get("model", "mixtral-8x7b-32768"),
                        "usage": data.get("usage", {})
                    }
                else:
                    return {
                        "success": False,
                        "error": f"API returned {response.status_code}",
                        "details": response.text
                    }
                    
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _test_openai(self) -> Dict[str, Any]:
        """Test OpenAI API connection"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4-turbo-preview",
                        "messages": [{"role": "user", "content": "Say 'OK'"}],
                        "max_tokens": 10,
                        "temperature": 0
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "model": data.get("model", "gpt-4"),
                        "usage": data.get("usage", {})
                    }
                else:
                    return {
                        "success": False,
                        "error": f"API returned {response.status_code}"
                    }
                    
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def check_redis(self) -> Dict[str, Any]:
        """Check Redis connection"""
        if not settings.REDIS_URL:
            return {
                "healthy": False,
                "error": "Redis not configured",
                "configured": False
            }
        
        try:
            start = datetime.now()
            
            # Connect to Redis
            r = await redis.from_url(settings.REDIS_URL)
            
            # Test operations
            await r.ping()
            await r.set("health_check", "ok", ex=10)
            value = await r.get("health_check")
            
            # Get info
            info = await r.info()
            
            await r.close()
            
            response_time = (datetime.now() - start).total_seconds() * 1000
            
            return {
                "healthy": True,
                "response_time_ms": response_time,
                "version": info.get("redis_version", "unknown"),
                "used_memory": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "configured": True
            }
            
        except Exception as e:
            logger.error(f"Redis health check failed: {str(e)}")
            return {
                "healthy": False,
                "error": str(e),
                "configured": True
            }
    
    def _mask_connection_string(self, conn_str: str) -> str:
        """Mask sensitive parts of connection string"""
        if not conn_str:
            return "Not configured"
        
        # Parse and mask password
        import re
        pattern = r'://([^:]+):([^@]+)@'
        masked = re.sub(pattern, r'://\1:****@', conn_str)
        return masked
    
    def _get_api_key(self) -> str:
        """Get configured API key based on provider"""
        if settings.LLM_PROVIDER == "groq":
            return settings.GROQ_API_KEY
        elif settings.LLM_PROVIDER == "openai":
            return settings.OPENAI_API_KEY
        return None