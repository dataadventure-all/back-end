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
    """Comprehensive health check service with debug logging"""
    
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
    
    async def check_supabase(self) -> Dict[str, Any]:
        """Check Supabase connection"""
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            return {
                "healthy": False,
                "error": "Supabase not configured",
                "configured": False
            }
        
        try:
            start = datetime.now()
            
            # Initialize Supabase client
            supabase: Client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_KEY
            )
            
            # Test query - get tables
            response = supabase.table("tabbranch").select("*").limit(1).execute()
            
            response_time = (datetime.now() - start).total_seconds() * 1000
            
            return {
                "healthy": True,
                "response_time_ms": response_time,
                "url": settings.SUPABASE_URL,
                "configured": True
            }
            
        except Exception as e:
            logger.error(f"Supabase health check failed: {str(e)}")
            return {
                "healthy": False,
                "error": str(e),
                "configured": True
            }
    
    def _debug_provider_info(self, provider) -> Dict[str, Any]:
        """Debug function to get detailed provider information"""
        debug_info = {
            "raw_value": repr(provider),
            "type": str(type(provider)),
            "str_value": str(provider),
            "has_value_attr": hasattr(provider, 'value'),
            "has_name_attr": hasattr(provider, 'name'),
            "dir_attrs": [attr for attr in dir(provider) if not attr.startswith('_')]
        }
        
        if hasattr(provider, 'value'):
            debug_info["value_attr"] = repr(provider.value)
        
        if hasattr(provider, 'name'):
            debug_info["name_attr"] = repr(provider.name)
            
        return debug_info
    
    def _get_provider_string(self, provider) -> str:
        """Safely extract provider string from enum or string with extensive debugging"""
        try:
            # Debug logging
            debug_info = self._debug_provider_info(provider)
            logger.info(f"Provider debug info: {debug_info}")
            
            # If it's already a string, just clean it up
            if isinstance(provider, str):
                provider_str = provider.lower().strip()
                logger.info(f"Provider is string: '{provider_str}'")
                return provider_str
                
            # If it's an enum with value attribute
            elif hasattr(provider, 'value'):
                provider_str = str(provider.value).lower().strip()
                logger.info(f"Provider has value attr: '{provider_str}'")
                return provider_str
                
            # If it's an enum with name attribute
            elif hasattr(provider, 'name'):
                provider_str = str(provider.name).lower().strip()
                logger.info(f"Provider has name attr: '{provider_str}'")
                return provider_str
                
            else:
                # Convert to string and handle enum format
                provider_str = str(provider).lower().strip()
                logger.info(f"Provider str conversion: '{provider_str}'")
                
                # Clean up any enum prefix (e.g., "llmprovider.deepseek" -> "deepseek")
                if "." in provider_str:
                    original = provider_str
                    provider_str = provider_str.split(".")[-1]
                    logger.info(f"Provider after dot split: '{original}' -> '{provider_str}'")
                
                return provider_str
            
        except Exception as e:
            logger.error(f"Error converting provider {provider}: {str(e)}")
            return "unknown"
    
    async def check_llm(self) -> Dict[str, Any]:
        """Check LLM service connection with hotfix"""
        try:
            start = datetime.now()
            
            # Debug settings
            logger.info(f"Settings LLM_PROVIDER raw: {repr(settings.LLM_PROVIDER)}")
            logger.info(f"Settings LLM_PROVIDER type: {type(settings.LLM_PROVIDER)}")
            
            # Initialize LLM service
            llm_service = LLMService()
            
            # Test with simple prompt
            test_prompt = "Return 'OK' if you can read this"
            
            # Get provider string with debug
            provider_str = self._get_provider_string(settings.LLM_PROVIDER)
            
            logger.info(f"Final provider string: '{provider_str}'")
            
            # HOTFIX: Handle the specific case where provider_str might still contain enum format
            if "." in provider_str:
                provider_str = provider_str.split(".")[-1].lower()
                logger.info(f"After dot split hotfix: '{provider_str}'")
            
            # Additional cleanup
            provider_str = provider_str.replace("llmprovider", "").replace(".", "").strip()
            logger.info(f"After cleanup hotfix: '{provider_str}'")
            
            # Test all possible conditions
            logger.info(f"Testing conditions:")
            logger.info(f"  provider_str == 'groq': {provider_str == 'groq'}")
            logger.info(f"  provider_str == 'openai': {provider_str == 'openai'}")
            logger.info(f"  provider_str == 'deepseek': {provider_str == 'deepseek'}")
            logger.info(f"  provider_str == 'anthropic': {provider_str == 'anthropic'}")
            
            # HOTFIX: More flexible matching
            result = None
            
            if provider_str in ["groq"]:
                logger.info("Testing Groq provider")
                result = await self._test_groq()
            elif provider_str in ["openai"]:
                logger.info("Testing OpenAI provider")
                result = await self._test_openai()
            elif provider_str in ["deepseek"]:
                logger.info("Testing DeepSeek provider")
                result = await self._test_deepseek()
            elif provider_str in ["anthropic", "claude"]:
                logger.info("Testing Anthropic provider")
                result = await self._test_anthropic()
            else:
                # HOTFIX: Try to extract provider from any remaining enum-like string
                clean_provider = provider_str.lower()
                for pattern in ["groq", "openai", "deepseek", "anthropic"]:
                    if pattern in clean_provider:
                        logger.info(f"Found pattern '{pattern}' in '{clean_provider}'")
                        if pattern == "groq":
                            result = await self._test_groq()
                        elif pattern == "openai":
                            result = await self._test_openai()
                        elif pattern == "deepseek":
                            result = await self._test_deepseek()
                        elif pattern == "anthropic":
                            result = await self._test_anthropic()
                        break
                
                if result is None:
                    logger.error(f"No matching provider found for: '{provider_str}' (original: {settings.LLM_PROVIDER})")
                    result = {
                        "success": False,
                        "error": f"Unsupported provider: {provider_str}",
                        "debug_info": self._debug_provider_info(settings.LLM_PROVIDER),
                        "original_provider": repr(settings.LLM_PROVIDER),
                        "cleaned_provider": clean_provider
                    }
            
            response_time = (datetime.now() - start).total_seconds() * 1000
            
            # Test token counting
            try:
                token_count = llm_service.count_tokens(test_prompt)
                token_counter_working = token_count > 0
            except Exception as e:
                logger.error(f"Token counting failed: {str(e)}")
                token_counter_working = False
                token_count = 0
            
            return {
                "healthy": result.get("success", False),
                "provider": provider_str,
                "model": result.get("model", "unknown"),
                "response_time_ms": response_time,
                "token_counter_working": token_counter_working,
                "token_count": token_count,
                "api_key_configured": bool(self._get_api_key()),
                "debug_provider_info": self._debug_provider_info(settings.LLM_PROVIDER),
                **{k: v for k, v in result.items() if k not in ['success']}
            }
            
        except Exception as e:
            logger.error(f"LLM health check failed: {str(e)}", exc_info=True)
            return {
                "healthy": False,
                "provider": self._get_provider_string(settings.LLM_PROVIDER),
                "error": str(e),
                "api_key_configured": bool(self._get_api_key()),
                "debug_provider_info": self._debug_provider_info(settings.LLM_PROVIDER)
            }
    
    async def _test_deepseek(self) -> Dict[str, Any]:
        """Test DeepSeek via OpenRouter API"""
        try:
            # Untuk deepseek, kita gunakan ANTHROPIC_API_KEY sebagai OpenRouter key
            api_key = settings.ANTHROPIC_API_KEY
            if not api_key:
                return {
                    "success": False,
                    "error": "ANTHROPIC_API_KEY (OpenRouter) not configured"
                }
                
            logger.info("Making request to OpenRouter for DeepSeek...")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "http://localhost:8000",
                        "X-Title": "AI Dashboard Health Check"
                    },
                    json={
                        "model": "deepseek/deepseek-r1-0528-qwen3-8b:free",
                        "messages": [
                            {"role": "user", "content": "Say 'OK'"}
                        ],            
                        "max_tokens": 10,
                        "temperature": 0
                    },
                    timeout=30.0
                )
                
                logger.info(f"OpenRouter response status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"OpenRouter response data: {data}")
                    return {
                        "success": True,
                        "model": data.get("model", "deepseek-r1"),
                        "usage": data.get("usage", {}),
                        "response_content": data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    }
                else:
                    error_text = response.text[:200] if response.text else "No error details"
                    logger.error(f"OpenRouter API error: {response.status_code} - {error_text}")
                    return {
                        "success": False,
                        "error": f"OpenRouter API returned {response.status_code}",
                        "details": error_text
                    }
                    
        except httpx.TimeoutException:
            logger.error("OpenRouter request timeout")
            return {
                "success": False,
                "error": "Request timeout (30s)"
            }
        except Exception as e:
            logger.error(f"OpenRouter connection error: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": f"Connection error: {str(e)}"
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
    
    async def _test_anthropic(self) -> Dict[str, Any]:
        """Test Anthropic API connection"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "Authorization": f"Bearer {settings.ANTHROPIC_API_KEY}",
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01"
                    },
                    json={
                        "model": "claude-3-haiku-20240307",
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": "Say 'OK'"}]
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "model": data.get("model", "claude-3-haiku"),
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
        provider_str = self._get_provider_string(settings.LLM_PROVIDER)
        
        if provider_str == "groq":
            return settings.GROQ_API_KEY
        elif provider_str == "openai":
            return settings.OPENAI_API_KEY
        elif provider_str in ["anthropic", "deepseek"]:  # deepseek uses OpenRouter with anthropic key
            return settings.ANTHROPIC_API_KEY
        return None