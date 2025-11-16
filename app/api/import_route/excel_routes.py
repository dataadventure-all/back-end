# 📄 api/routes/excel.py - Dedicated Excel Routes
from fastapi import APIRouter, Depends, HTTPException, Header, status, BackgroundTasks, UploadFile, File, Form, Query
from typing import List, Optional, Dict, Any
from datetime import datetime

from ...models.schemas import FileUploadResponse, SchemeExcel, QueryResponse, QueryRequest, ExcelQueryRequest, QueryExecutionRequest, QueryExecutionResponse
from ...services.import_services.excel_service import DynamicExcelService
from ...api.dependencies import rate_limit, get_current_user  # Jika ada auth
from ...utils.logger import get_logger
from ...core.database import get_raw_connection

from ...services.query_processor import QueryProcessor
from ...api.dependencies import get_query_processor
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import re


logger = get_logger(__name__)

# Create router dengan prefix yang jelas
router = APIRouter(
    prefix="/api/v1/excel",
    tags=["excel"],
    responses={404: {"description": "Not found"}}   
)

def get_excel_service() -> DynamicExcelService:
    """Dependency untuk mendapatkan Excel Service instance"""
    return DynamicExcelService()

# ==========================================
# DYNAMIC TABLE ROUTES (Optional)
# ==========================================

@router.post(
    "/dynamic/upload",
    summary="Upload Excel with Dynamic Table",
    description="Upload Excel and create dynamic database table",
    tags=["dynamic-tables"]
)
async def upload_excel_dynamic_table(
    file: UploadFile = File(...),
    sheet_name: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    create_table: bool = Form(True, description="Create dynamic table in database"),
    excel_service: DynamicExcelService = Depends(lambda: DynamicExcelService())
):
    """Upload Excel dengan dynamic table creation"""
    try:
        # File validation (same as basic upload)
        if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            raise HTTPException(status_code=400, detail="File must be an Excel file")
        
        contents = await file.read()
        if len(contents) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File size exceeds 50MB limit")
        
        # Process with dynamic table
        result = await excel_service.process_excel_dynamic_table(
            file_contents=contents,
            filename=file.filename,
            sheet_name=sheet_name,
            name=name,
            description=description,
            create_table=create_table
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dynamic Excel upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process: {str(e)}")


@router.post(
    "/query",
    response_model=QueryResponse,
    dependencies=[Depends(rate_limit)]
)
async def process_query(
    request: QueryRequest,
    background_tasks: BackgroundTasks,
    dataset_id: str = Header(..., alias="X-Dataset-ID"),
    processor: QueryProcessor = Depends(get_query_processor)
):
    """Process a natural language query"""
    
    try:
        logger.info(f"Processing query: {request.prompt[:100]}... for dataset: {dataset_id}")
        
        # ✅ Sekarang querytype sudah ada di request
        response = await processor.process_query(request, dataset_id=dataset_id)
        
        background_tasks.add_task(log_query_analytics, request, response)
        
        return response
        
    except Exception as e:
        logger.error(f"Query processing error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    

@router.post(
    "/query/execute",
    response_model=QueryExecutionResponse,
    dependencies=[Depends(rate_limit)],
    summary="Execute Generated SQL Query",
    description="Execute SQL query and return results with optional chart generation"
)
async def execute_query(
    request: QueryExecutionRequest,
    background_tasks: BackgroundTasks,
    dataset_id: str = Header(..., alias="X-Dataset-ID"),
    generate_chart: bool = Query(False, description="Generate chart configuration"),
    chart_prompt: Optional[str] = Query(None, description="Natural language description for chart"),
    chart_type: Optional[str] = Query(None, description="Preferred chart type (line, bar, pie, scatter, area, histogram)"),
    color_scheme: Optional[str] = Query("blue", description="Color scheme (blue, green, purple, red, orange, teal, pink)"),
    chart_width: int = Query(800, ge=400, le=2000, description="Chart width in pixels"),
    chart_height: int = Query(400, ge=300, le=1200, description="Chart height in pixels"),
    excel_service: DynamicExcelService = Depends(get_excel_service)
):
    """
    Execute SQL query and return results with optional chart generation
    
    Parameters:
    - **generate_chart**: Set to true to generate chart configuration
    - **chart_prompt**: Describe what you want to visualize (e.g., "show sales trend over time")
    - **chart_type**: Force a specific chart type (optional)
    - **color_scheme**: Choose color palette for the chart
    - **chart_width**: Chart width in pixels (400-2000)
    - **chart_height**: Chart height in pixels (300-1200)
    """
    try:
        logger.info(f"Executing query: {request.query_id} for dataset: {dataset_id}")
        
        # Execute query with optional chart generation
        result = await excel_service.query_dynamic_table(
            sql_query=request.sql_query,
            dataset_id=dataset_id,
            generate_chart=generate_chart,
            chart_prompt=chart_prompt,
            chart_type=chart_type,
            color_scheme=color_scheme,
            chart_width=chart_width,
            chart_height=chart_height
        )
        
        # Check if execution was successful
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        # Prepare response
        response = QueryExecutionResponse(
            query_id=request.query_id,
            success=result["success"],
            data=result["data"],
            row_count=result["row_count"],
            execution_time_seconds=result["execution_time_seconds"],
            columns=result["columns"],
            chart_config=result.get("chart_config")  # ✅ Include chart config if generated
        )
        
        # Background analytics logging
        background_tasks.add_task(
            log_query_analytics,
            request.query_id,
            dataset_id,
            result["row_count"],
            result["execution_time_seconds"],
            generated_chart=generate_chart  # Track if chart was generated
        )
        
        log_message = (
            f"Query executed: {result['row_count']} rows in "
            f"{result['execution_time_seconds']:.3f}s"
        )
        
        if generate_chart and result.get("chart_config"):
            log_message += f" | Chart: {result['chart_config'].get('chart_type', 'unknown')}"
        
        logger.info(log_message)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query execution error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query execution failed: {str(e)}"
        )
    
async def log_query_analytics(request: QueryRequest, response: QueryResponse):
    """Background task to log analytics"""
    logger.info(f"Query completed: {response.query_id} - Success: {response.success}")

@router.post("/test-query")
async def test_query(
    request: QueryRequest,
    dataset_id: str = Header(..., alias="X-Dataset-ID")
):
    return {
        "prompt": request.prompt,
        "mode": request.mode,
        "use_cache": request.use_cache,
        "dataset_id": dataset_id
    }







