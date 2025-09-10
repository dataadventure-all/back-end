from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from typing import List, Optional
from ..models.schemas import (
    QueryRequest, QueryResponse, HealthResponse
)
from ..services.query_processor import QueryProcessor
from ..core.config import get_settings
from ..api.dependencies import get_query_processor, rate_limit
from ..utils.logger import get_logger
from datetime import datetime
import uuid

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/v1", tags=["queries"])

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    # TODO: Add actual health checks
    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
        database=True,
        llm=True,
        cache=True,
        timestamp=datetime.now()
    )

@router.post(
    "/query",
    response_model=QueryResponse,
    dependencies=[Depends(rate_limit)]
)
async def process_query(
    request: QueryRequest,
    background_tasks: BackgroundTasks,
    processor: QueryProcessor = Depends(get_query_processor)
) -> QueryResponse:
    """Process a natural language query and return simplified response"""
    
    query_id = str(uuid.uuid4())  # generate query_id di awal
    
    try:
        logger.info(f"Processing query: {request.prompt[:100]}...")

        result = await processor.process_query(request)

        # Ambil query dari result jika ada, aman untuk dict atau object
        query_value = None
        if isinstance(result, dict):
            query_value = result.get("query")
        elif hasattr(result, "query"):
            query_value = result.query

        response = QueryResponse(
            query_id=query_id,
            prompt=request.prompt,
            mode=request.mode,
            query=query_value,
            success=True,
            error=None
        )

        # Background task untuk logging/analytics
        background_tasks.add_task(log_query_analytics, request, response)

        return response

    except Exception as e:
        logger.error(f"Query processing error: {str(e)}")

        return QueryResponse(
            query_id=query_id,  # pakai query_id sama dengan di atas
            prompt=request.prompt,
            mode=request.mode,
            success=False,
            error=str(e)
        )

@router.get("/schema")
async def get_schema(
    processor: QueryProcessor = Depends(get_query_processor)
):
    """Get database schema information"""
    try:
        schema = await processor.sql_service.get_schema_info()
        return {"schema": schema}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

async def log_query_analytics(request: QueryRequest, response: QueryResponse):
    """Background task to log analytics"""
    # Implement analytics logging
    logger.info(f"Query completed: {response.query_id} - Success: {response.success}")