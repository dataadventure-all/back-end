import json
import logging
from typing import Optional, Any, Union
from datetime import timedelta
from redis import asyncio as aioredis
from ..core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class RedisService:
    """Redis service for caching and session management"""
    
    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self.connection_pool = None
        
    async def connect(self):
        """Initialize Redis connection"""
        try:
            # Create connection pool
            self.connection_pool = aioredis.ConnectionPool.from_url(
                settings.REDIS_URL,
                max_connections=20,
                retry_on_timeout=True,
                decode_responses=True
            )
            
            # Create Redis client
            self.redis = aioredis.Redis(connection_pool=self.connection_pool)
            
            # Test connection
            await self.redis.ping()
            logger.info("✅ Redis connection established successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            self.redis = None
            raise
    
    async def disconnect(self):
        """Close Redis connection"""
        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed")
    
    async def is_connected(self) -> bool:
        """Check if Redis is connected"""
        if not self.redis:
            return False
        try:
            await self.redis.ping()
            return True
        except:
            return False
    
    # CACHING METHODS
    async def set_cache(
        self, 
        key: str, 
        value: Any, 
        expire_seconds: int = 3600
    ) -> bool:
        """Set cache with expiration"""
        if not self.redis:
            logger.warning("Redis not connected, skipping cache set")
            return False
            
        try:
            # Serialize value
            if isinstance(value, (dict, list)):
                serialized_value = json.dumps(value, default=str)
            else:
                serialized_value = str(value)
            
            # Set with expiration
            result = await self.redis.setex(
                name=key,
                time=expire_seconds,
                value=serialized_value
            )
            
            logger.debug(f"Cache set: {key} (expires in {expire_seconds}s)")
            return result
            
        except Exception as e:
            logger.error(f"Failed to set cache {key}: {e}")
            return False
    
    async def get_cache(self, key: str) -> Optional[Any]:
        """Get cached value"""
        if not self.redis:
            logger.warning("Redis not connected, cache miss")
            return None
            
        try:
            value = await self.redis.get(key)
            
            if value is None:
                logger.debug(f"Cache miss: {key}")
                return None
            
            # Try to deserialize JSON
            try:
                deserialized = json.loads(value)
                logger.debug(f"Cache hit: {key}")
                return deserialized
            except json.JSONDecodeError:
                # Return as string if not JSON
                logger.debug(f"Cache hit (string): {key}")
                return value
                
        except Exception as e:
            logger.error(f"Failed to get cache {key}: {e}")
            return None
    
    async def delete_cache(self, key: str) -> bool:
        """Delete cached value"""
        if not self.redis:
            return False
            
        try:
            result = await self.redis.delete(key)
            logger.debug(f"Cache deleted: {key}")
            return result > 0
        except Exception as e:
            logger.error(f"Failed to delete cache {key}: {e}")
            return False
    
    async def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching pattern"""
        if not self.redis:
            return 0
            
        try:
            keys = await self.redis.keys(pattern)
            if keys:
                result = await self.redis.delete(*keys)
                logger.info(f"Cleared {result} keys matching pattern: {pattern}")
                return result
            return 0
        except Exception as e:
            logger.error(f"Failed to clear pattern {pattern}: {e}")
            return 0
    
    # SPECIALIZED CACHE METHODS
    async def cache_query_result(
        self,
        query_hash: str,
        result: dict,
        expire_minutes: int = 60
    ) -> bool:
        """Cache SQL query result"""
        cache_key = f"query:{query_hash}"
        return await self.set_cache(
            cache_key, 
            result, 
            expire_seconds=expire_minutes * 60
        )
    
    async def get_cached_query(self, query_hash: str) -> Optional[dict]:
        """Get cached query result"""
        cache_key = f"query:{query_hash}"
        return await self.get_cache(cache_key)
    
    async def cache_chart_config(
        self,
        data_hash: str,
        config: dict,
        expire_hours: int = 24
    ) -> bool:
        """Cache chart configuration"""
        cache_key = f"chart:{data_hash}"
        return await self.set_cache(
            cache_key,
            config,
            expire_seconds=expire_hours * 3600
        )
    
    async def get_cached_chart_config(self, data_hash: str) -> Optional[dict]:
        """Get cached chart configuration"""
        cache_key = f"chart:{data_hash}"
        return await self.get_cache(cache_key)
    
    # UTILITY METHODS
    async def get_stats(self) -> dict:
        """Get Redis statistics"""
        if not self.redis:
            return {"connected": False}
            
        try:
            info = await self.redis.info()
            return {
                "connected": True,
                "used_memory": info.get("used_memory_human", "N/A"),
                "connected_clients": info.get("connected_clients", 0),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "hit_rate": self._calculate_hit_rate(info)
            }
        except Exception as e:
            logger.error(f"Failed to get Redis stats: {e}")
            return {"connected": False, "error": str(e)}
    
    def _calculate_hit_rate(self, info: dict) -> float:
        """Calculate cache hit rate percentage"""
        hits = info.get("keyspace_hits", 0)
        misses = info.get("keyspace_misses", 0)
        total = hits + misses
        
        if total == 0:
            return 0.0
        
        return round((hits / total) * 100, 2)

# Global Redis service instance
redis_service = RedisService()