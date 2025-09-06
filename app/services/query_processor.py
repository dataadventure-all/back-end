from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid
from ..models.schemas import (
    QueryRequest, QueryResponse, QueryStatus,
    SQLQuery, ChartConfig, TokenUsage
)
from ..models.enums import QueryMode, OutputFormat
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
                return await self._process_simple_query(request, query_id, start_time, mode)
                
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
        start_time: datetime,
        mode: QueryMode
    ) -> QueryResponse:
        """Process simple query with enhanced chart generation support"""
        
        chart_generation_start = None
        chart_config = None
        chart_fallback_used = False
        
        try:
            # Get schema
            logger.info(f"Getting database schema for query: {query_id}")
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
            if request.output_format == OutputFormat.CHART and data:
                try:
                    chart_generation_start = datetime.now()
                    logger.info(f"Generating chart configuration for query: {query_id}")
                    
                    config_dict = await self.llm_service.generate_chart_config(
                        data=data,
                        user_prompt=request.prompt,
                        preferred_chart_type=getattr(request, 'preferred_chart_type', None),
                        color_scheme=getattr(request, 'color_scheme', None),
                        width=getattr(request, 'chart_width', 800),
                        height=getattr(request, 'chart_height', 400)
                    )
                    
                    # Validate that config_dict has required fields
                    required_fields = ['chart_type', 'x_axis', 'y_axis', 'title']
                    if not all(field in config_dict for field in required_fields):
                        logger.warning(f"Chart config missing required fields: {query_id}")
                        raise ValueError("Chart config incomplete")
                    
                    chart_config = ChartConfig(**config_dict)
                    logger.info(f"Successfully generated {chart_config.chart_type} chart for query: {query_id}")
                    
                except Exception as chart_error:
                    logger.error(f"Chart generation failed for query {query_id}: {str(chart_error)}")
                    chart_fallback_used = True
                    
                    # Create fallback chart config
                    try:
                        fallback_config = self._create_emergency_chart_fallback(data, request.prompt)
                        chart_config = ChartConfig(**fallback_config)
                        logger.info(f"Using fallback chart config for query: {query_id}")
                    except Exception as fallback_error:
                        logger.error(f"Fallback chart generation also failed: {str(fallback_error)}")
                        # Continue without chart config
                        chart_config = None
            
            elif request.output_format == OutputFormat.CHART and not data:
                logger.warning(f"Chart requested but no data returned for query: {query_id}")
            
            # Calculate execution times
            execution_time = (datetime.now() - start_time).total_seconds()
            chart_generation_time = None
            if chart_generation_start:
                chart_generation_time = (datetime.now() - chart_generation_start).total_seconds()
            
            # Create metadata with enhanced information
            metadata = {
                "mode": mode.value,
                "row_count": len(data) if data else 0,
                "column_count": len(data[0].keys()) if data else 0,
                "processing_time_ms": execution_time * 1000,
                "chart_requested": request.output_format == OutputFormat.CHART,
                "chart_generated": chart_config is not None,
                "chart_fallback_used": chart_fallback_used
            }
            
            if chart_generation_time:
                metadata["chart_generation_time_ms"] = chart_generation_time * 1000
            
            # Add data summary if we have data
            if data:
                metadata.update({
                    "first_row_sample": {k: v for k, v in list(data[0].items())[:3]} if data else {},
                    "column_names": list(data[0].keys()) if data else []
                })
            
            return QueryResponse(
                success=True,
                query_id=query_id,
                status=QueryStatus.SUCCESS,
                sql_query=sql_info,
                data=data,
                chart_config=chart_config,
                metadata=metadata,
                execution_time=execution_time,
                token_usage=token_usage.dict() if token_usage else None,
                chart_generation_time=chart_generation_time,
                chart_fallback_used=chart_fallback_used
            )
            
        except Exception as e:
            logger.error(f"Query processing failed for {query_id}: {str(e)}")
            execution_time = (datetime.now() - start_time).total_seconds()
            
            # Return error response
            return QueryResponse(
                success=False,
                query_id=query_id,
                status=QueryStatus.FAILED,
                sql_query=None,
                data=None,
                chart_config=None,
                metadata={
                    "mode": mode.value,
                    "processing_time_ms": execution_time * 1000,
                    "error_type": type(e).__name__
                },
                error=str(e),
                execution_time=execution_time,
                token_usage=None
            )

    def _create_emergency_chart_fallback(self, data: List[Dict], user_prompt: str) -> Dict:
        """Emergency fallback when both LLM and regular fallback fail"""
        if not data:
            return {
                "chart_type": "bar",
                "x_axis": "category", 
                "y_axis": "value",
                "title": "No Data Available",
                "colors": ["#8884d8", "#82ca9d", "#ffc658"],
                "color_scheme": "blue",
                "width": 800,
                "height": 400,
                "show_legend": True,
                "show_grid": True,
                "show_tooltip": True,
                "animate": True,
                "additional_config": {}
            }
        
        columns = list(data[0].keys())
        
        # Very simple logic - first column as x, second as y (or first if only one)
        x_axis = columns[0]
        y_axis = columns[1] if len(columns) > 1 else columns[0]
        
        # Detect if we should use bar or line based on column names
        chart_type = "bar"
        if any(word in user_prompt.lower() for word in ["trend", "over time", "timeline", "progression"]):
            chart_type = "line"
        elif any(word in user_prompt.lower() for word in ["distribution", "spread"]):
            chart_type = "histogram"
        
        return {
            "chart_type": chart_type,
            "x_axis": x_axis,
            "y_axis": y_axis, 
            "title": f"Emergency Chart: {user_prompt[:30]}..." if user_prompt else "Data Visualization",
            "colors": ["#8884d8", "#82ca9d", "#ffc658", "#ff7300", "#00ff00"],
            "color_scheme": "blue",
            "width": 800,
            "height": 400,
            "show_legend": True,
            "show_grid": True,
            "show_tooltip": True,
            "animate": True,
            "aggregate_function": None,
            "group_by": None,
            "additional_config": {}
        }
    
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