from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid
import hashlib
import json
from ..models.schemas import (
    QueryRequest, QueryResponse, QueryStatus,
    SQLQuery, TokenUsage
)
from ..models.enums import QueryMode
from .llm_service import LLMService
from .sql_service import SQLService
from .redis_service import redis_service  
from ..utils.logger import get_logger
from ..core.config import get_settings

logger = get_logger(__name__)
settings = get_settings()

class QueryProcessor:
    """Simplified query processing orchestrator"""
    
    def __init__(self):
        self.llm_service = LLMService()
        self.sql_service = SQLService()
        self.redis_service = redis_service
        
    async def process_query(self, request: QueryRequest) -> QueryResponse:
        """Process user query and return simplified response"""
        
        try:
            # Check cache first if enabled
            if request.use_cache and settings.ENABLE_QUERY_CACHE:
                cached_result = await self._check_query_cache(request)
                if cached_result:
                    logger.info(f"Cache hit for query")
                    return QueryResponse(**cached_result)
            
            # Determine processing mode
            mode = await self._determine_mode(request)
            
            # Get schema with caching
            logger.info(f"Getting database schema for query")
            schema = await self._get_cached_schema()
            
            # Generate SQL
            logger.info(f"Generating SQL for query")
            sql_query, token_usage = await self.llm_service.generate_sql_query(
                prompt=request.prompt,
                schema_context=schema
            )
            
            # Extract query string from SQLQuery object or handle string response
            query_string = None
            if sql_query:
                if hasattr(sql_query, 'query'):
                    query_string = sql_query.query
                elif isinstance(sql_query, str):
                    query_string = sql_query
                else:
                    query_string = str(sql_query)
            
            # Create response
            response = QueryResponse(
                prompt=request.prompt,
                mode=mode.value,
                query_id=str(uuid.uuid4()),
                query=query_string,
                success=True
            )
            
            # Cache successful results
            if request.use_cache and settings.ENABLE_QUERY_CACHE:
                await self._cache_query_result(request, response)
            
            return response
                
        except Exception as e:
            logger.error(f"Query processing failed: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {repr(e)}")
            
            return QueryResponse(
                prompt=request.prompt,
                mode=QueryMode.SIMPLE.value,
                query=None,
                success=False,
                error=f"{type(e).__name__}: {str(e)}"
            )
    
    # Cache methods
    async def _check_query_cache(self, request: QueryRequest) -> Optional[dict]:
        """Check if query result is cached in Redis"""
        try:
            if not await self.redis_service.is_connected():
                return None
                
            query_hash = self._generate_query_hash(request)
            cached_result = await self.redis_service.get_cached_query(query_hash)
            
            if cached_result:
                logger.info(f"Query cache hit: {query_hash[:12]}...")
                return cached_result
            
            logger.debug(f"Query cache miss: {query_hash[:12]}...")
            return None
            
        except Exception as e:
            logger.error(f"Cache check failed: {e}")
            return None
    
    async def _cache_query_result(self, request: QueryRequest, result: QueryResponse):
        """Cache query result in Redis"""
        try:
            if not await self.redis_service.is_connected():
                return
                
            query_hash = self._generate_query_hash(request)
            
            # Convert result to dict for caching
            result_dict = result.dict()
            
            # Cache for configured TTL
            success = await self.redis_service.cache_query_result(
                query_hash,
                result_dict,
                expire_minutes=settings.QUERY_CACHE_TTL_MINUTES
            )
            
            if success:
                logger.info(f"Query result cached: {query_hash[:12]}...")
            else:
                logger.warning("Failed to cache query result")
            
        except Exception as e:
            logger.error(f"Failed to cache query result: {e}")
    
    async def _get_cached_schema(self) -> dict:
        """Get database schema with Redis caching"""
        try:
            if await self.redis_service.is_connected():
                # Try cache first
                cached_schema = await self.redis_service.get_cache("db_schema")
                
                if cached_schema:
                    logger.debug("Using cached database schema")
                    return cached_schema
            
            # Get fresh schema
            schema = await self.sql_service.get_schema_info()
            
            # Cache schema for 1 hour if Redis is available
            if await self.redis_service.is_connected():
                await self.redis_service.set_cache("db_schema", schema, expire_seconds=3600)
                logger.debug("Database schema fetched and cached")
            
            return schema
            
        except Exception as e:
            logger.error(f"Schema caching failed: {e}")
            # Fallback to direct fetch
            return await self.sql_service.get_schema_info()
    
    def _generate_query_hash(self, request: QueryRequest) -> str:
        """Generate unique hash for query caching"""
        cache_key_data = {
            "prompt": request.prompt.lower().strip(),
            "mode": request.mode.value
        }
        
        cache_string = json.dumps(cache_key_data, sort_keys=True)
        return hashlib.md5(cache_string.encode()).hexdigest()
    
    async def _determine_mode(self, request: QueryRequest) -> QueryMode:
        """Determine processing mode based on request"""
        
        if request.mode != QueryMode.AUTO:
            return request.mode
        
        # Count tokens
        token_count = self.llm_service.count_tokens(request.prompt)
        
        if token_count > settings.USE_ADVANCED_MODE_THRESHOLD:
            logger.info(f"Token count {token_count} exceeds threshold, using advanced mode")
            return QueryMode.ADVANCED
        
        return QueryMode.SIMPLE