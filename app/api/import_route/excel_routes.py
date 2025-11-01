# 📄 api/routes/excel.py - Dedicated Excel Routes
from fastapi import APIRouter, Depends, HTTPException, Header, status, BackgroundTasks, UploadFile, File, Form, Query
from typing import List, Optional, Dict, Any
from datetime import datetime

from ...models.schemas import FileUploadResponse, SchemeExcel, QueryResponse, QueryRequest, ExcelQueryRequest
from ...services.import_services.excel_service import DynamicExcelService  # Jika pakai dynamic tables
from ...api.dependencies import rate_limit, get_current_user  # Jika ada auth
from ...utils.logger import get_logger

from ...services.query_processor import QueryProcessor
from ...api.dependencies import get_query_processor

logger = get_logger(__name__)

# Create router dengan prefix yang jelas
router = APIRouter(
    prefix="/api/v1/excel",
    tags=["excel"],
    responses={404: {"description": "Not found"}}   
)

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

# @router.post(
#     "/dynamic/{dataset_id}/query",
#     summary="Query Dynamic Table",
#     description="Execute SQL query on dynamic table",
#     tags=["dynamic-tables"]
# )
# async def query_dynamic_table(
#     dataset_id: str,
#     sql_query: str = Query(..., description="SQL query to execute"),
#     limit: Optional[int] = Query(1000, le=10000, description="Row limit"),
#     excel_service: DynamicExcelService = Depends(lambda: DynamicExcelService())
# ):
#     """Query data dari dynamic table"""
#     try:
#         # Add LIMIT if not present
#         if limit and "LIMIT" not in sql_query.upper():
#             sql_query += f" LIMIT {limit}"
        
#         result = await excel_service.query_dynamic_table(dataset_id, sql_query)
        
#         if not result["success"]:
#             raise HTTPException(status_code=400, detail=result["error"])
        
#         return result
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Dynamic query error: {str(e)}")
#         raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")
    

# async def log_excel_upload(dataset_id: str, filename: str):
#     """Background task untuk logging upload"""
#     try:
#         logger.info(f"Excel upload completed - Dataset: {dataset_id}, File: {filename}")
#         # Add analytics tracking, email notifications, etc.
#     except Exception as e:
#         logger.error(f"Error in upload logging: {str(e)}")

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
