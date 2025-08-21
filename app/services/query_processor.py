from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid
from ..models.schemas import (
    QueryRequest, QueryResponse, QueryStatus,
    SQLQuery, ChartConfig, TokenUsage
)
from ..models.enums import QueryMode
from .llm_service import LLMService
from .sql_service import SQLService
from ..utils.logger import get_logger
from ..core.config import get_settings
import asyncio

logger = get_logger(__name__)
settings = get_settings()

class QueryProcessor:
    """Main query processing orchestrator"""
    
    def __init__(self):
        self.llm_service = LLMService()
        self.sql_service = SQLService()
        
    async def process_query(self, request: QueryRequest) -> QueryResponse:
        """Process user query end-to-end"""
        
        query_id = str(uuid.uuid4())
        start_time = datetime.now()
        
        try:
            # Step 1: Determine processing mode
            mode = await self._determine_mode(request)
            
            if mode == QueryMode.ADVANCED:
                # Future: Use graph/vector processing
                return await self._process_advanced_query(request, query_id)
            else:
                # Current: Simple processing
                return await self._process_simple_query(request, query_id, start_time)
                
        except Exception as e:
            logger.error(f"Query processing failed: {str(e)}")
            return QueryResponse(
                success=False,
                query_id=query_id,
                status=QueryStatus.FAILED,
                error=str(e),
                execution_time=(datetime.now() - start_time).total_seconds()
            )
    
    async def _process_simple_query(
        self, 
        request: QueryRequest, 
        query_id: str,
        start_time: datetime
    ) -> QueryResponse:
        """Process simple query (current implementation)"""
        
        try:
            # Get schema
            schema = await self.sql_service.get_schema_info()
            
            # Generate SQL
            logger.info(f"Generating SQL for query: {query_id}")
            sql_query, token_usage = await self.llm_service.generate_sql_query(
                prompt=request.prompt,
                schema_context=schema
            )
            
            # Execute SQL
            logger.info(f"Executing SQL for query: {query_id}")
            data, sql_info = await self.sql_service.execute_query(sql_query)
            
            # Generate chart config if needed
            chart_config = None
            if request.output_format == "chart" and data:
                config_dict = await self.llm_service.generate_chart_config(
                    data=data,
                    user_prompt=request.prompt
                )
                chart_config = ChartConfig(**config_dict)
            
            execution_time = (datetime.now() - start_time).total_seconds()
            
            return QueryResponse(
                success=True,
                query_id=query_id,
                status=QueryStatus.SUCCESS,
                sql_query=sql_info,
                data=data,
                chart_config=chart_config,
                metadata={
                    "mode": mode.value,
                    "row_count": len(data),
                    "processing_time_ms": execution_time * 1000
                },
                execution_time=execution_time,
                token_usage=token_usage.dict()
            )
            
        except Exception as e:
            raise
    
    async def _process_advanced_query(
        self, 
        request: QueryRequest, 
        query_id: str
    ) -> QueryResponse:
        """Process advanced query with graph/vector (placeholder)"""
        
        # This will be implemented when adding graph/vector support
        logger.info(f"Advanced mode triggered for query: {query_id}")
        
        # For now, fallback to simple
        return await self._process_simple_query(
            request, 
            query_id, 
            datetime.now()
        )
    
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