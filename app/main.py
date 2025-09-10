from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time
from .api.routes import router
from .api.health_routes import router as health_router
from .services.redis_service import redis_service
from .core.config import get_settings
from .utils.logger import setup_logging, get_logger
from .core.database import engine

settings = get_settings()
logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager with Redis integration"""
    
    # Startup
    logger.info(f"🚀 Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    
    # Initialize database
    # async with engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)
    
    # NEW: Initialize Redis connection
    redis_connected = False
    try:
        if hasattr(settings, 'REDIS_URL') and settings.REDIS_URL:
            await redis_service.connect()
            redis_connected = await redis_service.is_connected()
            
            if redis_connected:
                logger.info("✅ Redis connected successfully")
                
                # Log Redis stats
                stats = await redis_service.get_stats()
                logger.info(f"📊 Redis stats: {stats.get('used_memory', 'N/A')} memory, "
                          f"{stats.get('connected_clients', 0)} clients")
                
                # Test cache functionality
                await redis_service.set_cache("startup_test", {"timestamp": time.time()}, 60)
                test_value = await redis_service.get_cache("startup_test")
                
                if test_value:
                    logger.info("✅ Redis cache test successful")
                    await redis_service.delete_cache("startup_test")
                else:
                    logger.warning("⚠️  Redis cache test failed")
            else:
                logger.error("❌ Redis connection failed")
        else:
            logger.info("⚠️  Redis URL not configured, running without cache")
            
    except Exception as e:
        logger.error(f"❌ Redis initialization error: {e}")
        logger.warning("⚠️  Application will continue without Redis caching")
        redis_connected = False
    
    # Store Redis connection status for health checks
    app.state.redis_connected = redis_connected
    app.state.cache_enabled = redis_connected and getattr(settings, 'ENABLE_QUERY_CACHE', True)
    
    logger.info(f"🎯 Cache status: {'Enabled' if app.state.cache_enabled else 'Disabled'}")
    logger.info(f"✨ {settings.APP_NAME} startup complete!")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down application...")
    
    # Cleanup Redis connection
    try:
        if redis_connected:
            await redis_service.disconnect()
            logger.info("✅ Redis disconnected successfully")
    except Exception as e:
        logger.error(f"❌ Redis disconnect error: {e}")
    
    # Cleanup database
    try:
        await engine.dispose()
        logger.info("✅ Database connections closed")
    except Exception as e:
        logger.error(f"❌ Database cleanup error: {e}")
    
    logger.info("👋 Application shutdown complete")

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    description="SQL Query Processing API with Redis Caching Support"  # NEW: Updated description
)

# Setup logging
setup_logging(settings.LOG_LEVEL)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Trusted host middleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"] if settings.DEBUG else settings.CORS_ORIGINS
)

# NEW: Enhanced request timing middleware with cache info
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    
    # Log request (optional, for debugging)
    if settings.DEBUG:
        logger.debug(f"📥 {request.method} {request.url.path}")
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(round(process_time, 4))
    
    # NEW: Add cache status headers
    if hasattr(app.state, 'cache_enabled'):
        response.headers["X-Cache-Enabled"] = str(app.state.cache_enabled).lower()
    
    if hasattr(app.state, 'redis_connected'):
        response.headers["X-Redis-Status"] = "connected" if app.state.redis_connected else "disconnected"
    
    # Log slow requests
    if process_time > 1.0:  # Log requests taking more than 1 second
        logger.warning(f"🐌 Slow request: {request.method} {request.url.path} took {process_time:.2f}s")
    
    return response

# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"💥 Global exception on {request.method} {request.url.path}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "timestamp": time.time(),
            "path": str(request.url.path)
        }
    )

# Include routers
app.include_router(router)
app.include_router(health_router)

# NEW: Enhanced root endpoint with system status
@app.get("/")
async def root():
    """Root endpoint with system information"""
    
    # Get Redis status
    redis_status = "unknown"
    cache_stats = {}
    
    try:
        if hasattr(app.state, 'redis_connected') and app.state.redis_connected:
            redis_connected = await redis_service.is_connected()
            if redis_connected:
                redis_status = "connected"
                cache_stats = await redis_service.get_stats()
            else:
                redis_status = "disconnected"
        else:
            redis_status = "not_configured"
    except Exception as e:
        logger.error(f"Error checking Redis status: {e}")
        redis_status = "error"
    
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "timestamp": time.time(),
        "system": {
            "debug_mode": settings.DEBUG,
            "cache_enabled": getattr(app.state, 'cache_enabled', False),
            "redis_status": redis_status,
            "redis_stats": {
                "connected": cache_stats.get("connected", False),
                "memory_used": cache_stats.get("used_memory", "N/A"),
                "hit_rate": f"{cache_stats.get('hit_rate', 0)}%" if cache_stats.get('hit_rate') is not None else "N/A"
            }
        },
        "endpoints": {
            "health": "/health",
            "docs": "/docs" if settings.DEBUG else "disabled",
            "cache_stats": "/cache/stats",
            "api": "/api/v1/"
        }
    }

# NEW: Cache management endpoints
@app.get("/cache/stats")
async def get_cache_stats():
    """Get detailed cache statistics"""
    try:
        if not hasattr(app.state, 'redis_connected') or not app.state.redis_connected:
            return {
                "error": "Redis not connected",
                "cache_enabled": False
            }
        
        stats = await redis_service.get_stats()
        return {
            "cache_enabled": True,
            "redis_stats": stats,
            "settings": {
                "query_cache_ttl_minutes": getattr(settings, 'QUERY_CACHE_TTL_MINUTES', 60),
                "chart_cache_ttl_hours": getattr(settings, 'CHART_CACHE_TTL_HOURS', 24),
                "enable_query_cache": getattr(settings, 'ENABLE_QUERY_CACHE', True)
            }
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return {
            "error": str(e),
            "cache_enabled": False
        }

@app.delete("/cache/clear")
async def clear_cache(pattern: str = "*"):
    """Clear cache entries by pattern (admin endpoint)"""
    try:
        if not hasattr(app.state, 'redis_connected') or not app.state.redis_connected:
            return {
                "success": False,
                "error": "Redis not connected"
            }
        
        # Security: Only allow specific patterns in production
        if not settings.DEBUG:
            allowed_patterns = ["query:*", "chart:*", "sql_result:*", "db_schema"]
            if pattern not in allowed_patterns:
                return {
                    "success": False,
                    "error": f"Pattern not allowed. Use one of: {allowed_patterns}"
                }
        
        cleared_count = await redis_service.clear_pattern(pattern)
        logger.info(f"🧹 Cache cleared: {cleared_count} keys matching '{pattern}'")
        
        return {
            "success": True,
            "cleared_keys": cleared_count,
            "pattern": pattern,
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/cache/warm")
async def warm_cache():
    """Warm up cache with common queries (admin endpoint)"""
    try:
        if not hasattr(app.state, 'redis_connected') or not app.state.redis_connected:
            return {
                "success": False,
                "error": "Redis not connected"
            }
        
        # This is a placeholder - implement based on your common queries
        warmed_items = 0
        
        # Example: Pre-cache database schema
        # schema = await sql_service.get_schema_info()
        # await redis_service.set_cache("db_schema", schema, 3600)
        # warmed_items += 1
        
        logger.info(f"🔥 Cache warmed: {warmed_items} items")
        
        return {
            "success": True,
            "warmed_items": warmed_items,
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error warming cache: {e}")
        return {
            "success": False,
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=1 if settings.DEBUG else settings.WORKERS
    )