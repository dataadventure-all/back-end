from typing import Generator, Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from ..core.database import get_db
from ..services.query_processor import QueryProcessor
from ..core.config import get_settings
import time
from collections import defaultdict
import asyncio
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import time
from collections import defaultdict

from ..services.query_processor import QueryProcessor
from ..core.config import get_settings
from ..utils.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)
security = HTTPBearer(auto_error=False)

# Rate limiting
request_counts = defaultdict(list)
rate_limit_lock = asyncio.Lock()
rate_limit_storage = defaultdict(list)

async def rate_limit(request: Request):
    """Simple rate limiting"""
    client_ip = request.client.host
    current_time = time.time()
    
    async with rate_limit_lock:
        # Clean old requests
        request_counts[client_ip] = [
            req_time for req_time in request_counts[client_ip]
            if current_time - req_time < 60
        ]
        
        # Check rate limit
        if len(request_counts[client_ip]) >= settings.RATE_LIMIT_PER_MINUTE:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded"
            )
        
        # Add current request
        request_counts[client_ip].append(current_time)

def get_query_processor() -> QueryProcessor:
    """Get query processor instance"""
    return QueryProcessor() 

# Optional: Auth dependency (for future)
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Optional[dict]:
    """Get current user from JWT token"""
    if not credentials:
        return None
    
    # TODO: Implement JWT validation
    # token = credentials.credentials
    # user = validate_jwt(token)
    
    return {"user_id": "anonymous"}

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB for CSV
MAX_EXCEL_SIZE = 50 * 1024 * 1024  # 50MB for Excel
ALLOWED_CSV_EXTENSIONS = {'.csv', '.tsv'}
ALLOWED_EXCEL_EXTENSIONS = {'.xlsx', '.xls'}

# Singleton instance of QueryProcessor
_query_processor_instance: Optional[QueryProcessor] = None

async def get_query_processor() -> QueryProcessor:
    """
    Get or create QueryProcessor instance (singleton pattern)
    """
    global _query_processor_instance
    
    if _query_processor_instance is None:
        _query_processor_instance = QueryProcessor()
        await _query_processor_instance.initialize()
        
    return _query_processor_instance

async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> bool:
    """
    Verify API key if authentication is enabled
    """
    if not settings.REQUIRE_API_KEY:
        return True
        
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify the API key
    if credentials.credentials != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return True

async def rate_limit(request: Request) -> bool:
    """
    Simple rate limiting based on IP address
    """
    if not settings.RATE_LIMIT_ENABLED:
        return True
    
    client_ip = request.client.host
    current_time = time.time()
    
    # Clean old entries (older than 1 minute)
    rate_limit_storage[client_ip] = [
        t for t in rate_limit_storage[client_ip] 
        if current_time - t < 60
    ]
    
    # Check rate limit (default: 30 requests per minute)
    if len(rate_limit_storage[client_ip]) >= settings.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later."
        )
    
    # Add current request
    rate_limit_storage[client_ip].append(current_time)
    
    return True

def validate_file_extension(filename: str, file_type: str) -> bool:
    """
    Validate file extension based on file type
    """
    if file_type == "csv":
        return any(filename.lower().endswith(ext) for ext in ALLOWED_CSV_EXTENSIONS)
    elif file_type == "excel":
        return any(filename.lower().endswith(ext) for ext in ALLOWED_EXCEL_EXTENSIONS)
    return False

def validate_file_size(file_size: int, file_type: str) -> bool:
    """
    Validate file size based on file type
    """
    if file_type == "csv":
        return file_size <= MAX_FILE_SIZE
    elif file_type == "excel":
        return file_size <= MAX_EXCEL_SIZE
    return False

# Cleanup function for application shutdown
async def cleanup_resources():
    """
    Cleanup resources on application shutdown
    """
    global _query_processor_instance
    
    if _query_processor_instance:
        logger.info("Cleaning up QueryProcessor resources...")
        # Add cleanup logic here
        _query_processor_instance = None
    
    # Clear rate limit storage
    rate_limit_storage.clear()
    
    logger.info("Resources cleaned up successfully")