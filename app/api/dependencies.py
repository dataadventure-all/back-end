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

settings = get_settings()
security = HTTPBearer(auto_error=False)

# Rate limiting
request_counts = defaultdict(list)
rate_limit_lock = asyncio.Lock()

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