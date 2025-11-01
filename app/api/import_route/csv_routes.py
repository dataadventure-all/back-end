# 📄 api/routes/csv.py - Dedicated CSV Routes
from fastapi import APIRouter, Depends, HTTPException, Header, status, BackgroundTasks, UploadFile, File, Form, Query
from typing import List, Optional, Dict, Any
from datetime import datetime

from ...models.schemas import FileUploadResponse, SchemeExcel, QueryResponse, QueryRequest
from ...services.import_services.csv_service import DynamicCsvService
from ...api.dependencies import rate_limit, get_current_user  # Jika ada auth
from ...utils.logger import get_logger

from ...services.query_processor import QueryProcessor
from ...api.dependencies import get_query_processor

logger = get_logger(__name__)

# Create router dengan prefix yang jelas
router = APIRouter(
    prefix="/api/v1/csv",
    tags=["csv"],
    responses={404: {"description": "Not found"}}   
)

# ==========================================
# CSV DYNAMIC TABLE ROUTES
# ==========================================

@router.post(
    "/dynamic/upload",
    summary="Upload CSV with Dynamic Table",
    description="Upload CSV and create dynamic database table",
    tags=["dynamic-tables", "csv"]
)
async def upload_csv_dynamic_table(
    file: UploadFile = File(...),
    encoding: Optional[str] = Form(None, description="File encoding (utf-8, latin-1, etc.). Auto-detected if not provided."),
    delimiter: Optional[str] = Form(None, description="CSV delimiter (comma, semicolon, tab, etc.). Auto-detected if not provided."),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    create_table: bool = Form(True, description="Create dynamic table in database"),
    csv_service: DynamicCsvService = Depends(lambda: DynamicCsvService())
):
    """Upload CSV dengan dynamic table creation"""
    try:
        # File validation
        if not (file.filename.endswith('.csv') or file.filename.endswith('.txt')):
            raise HTTPException(status_code=400, detail="File must be a CSV file (.csv or .txt)")
        
        contents = await file.read()
        if len(contents) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File size exceeds 50MB limit")
        
        # Process with dynamic table
        result = await csv_service.process_csv_dynamic_table(
            file_contents=contents,
            filename=file.filename,
            encoding=encoding,
            delimiter=delimiter,
            name=name,
            description=description,
            create_table=create_table
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dynamic CSV upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process: {str(e)}")

@router.post(
    "/dynamic/{dataset_id}/query",
    summary="Query CSV Dynamic Table",
    description="Execute SQL query on CSV dynamic table",
    tags=["dynamic-tables", "csv"]
)
async def query_csv_dynamic_table(
    dataset_id: str,
    sql_query: str = Query(..., description="SQL query to execute"),
    limit: Optional[int] = Query(1000, le=10000, description="Row limit"),
    csv_service: DynamicCsvService = Depends(lambda: DynamicCsvService())
):
    """Query data dari CSV dynamic table"""
    try:
        # Add LIMIT if not present
        if limit and "LIMIT" not in sql_query.upper():
            sql_query += f" LIMIT {limit}"
        
        result = await csv_service.query_dynamic_table(dataset_id, sql_query)
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dynamic CSV query error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

@router.delete(
    "/dynamic/table/{dataset_id}",
    summary="Drop CSV Dynamic Table",
    description="Delete CSV dynamic table from database",
    tags=["dynamic-tables", "csv"]
)
async def drop_csv_dynamic_table(
    dataset_id: str,
    csv_service: DynamicCsvService = Depends(lambda: DynamicCsvService())
):
    """Drop CSV dynamic table"""
    try:
        success = await csv_service.drop_dynamic_table(dataset_id)
        if not success:
            raise HTTPException(status_code=404, detail="Dataset not found or table already dropped")
        return {"message": "CSV dynamic table dropped successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dynamic CSV drop error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to drop table: {str(e)}")

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
    """Process a natural language query for CSV dataset"""
    
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

