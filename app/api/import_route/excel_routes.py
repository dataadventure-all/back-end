# 📄 api/routes/excel.py - Dedicated Excel Routes
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, UploadFile, File, Form, Query
from typing import List, Optional, Dict, Any
from datetime import datetime

from ...models.schemas import FileUploadResponse, SchemeExcel
from ...services.import_services.excel_service import DynamicExcelService  # Jika pakai dynamic tables
from ...api.dependencies import rate_limit, get_current_user  # Jika ada auth
from ...utils.logger import get_logger

logger = get_logger(__name__)

# Create router dengan prefix yang jelas
router = APIRouter(
    prefix="/api/v1/excel",
    tags=["excel"],
    responses={404: {"description": "Not found"}}
)

# ==========================================
# BASIC EXCEL ROUTES (JSON Storage)
# ==========================================

# @router.post(
#     "/upload",
#     response_model=FileUploadResponse,
#     summary="Upload Excel File",
#     description="Upload Excel file and store data in database as JSON",
#     dependencies=[Depends(rate_limit)]
# )
# async def upload_excel_basic(
#     background_tasks: BackgroundTasks,
#     file: UploadFile = File(..., description="Excel file (.xlsx or .xls)"),
#     sheet_name: Optional[str] = Form(None, description="Specific sheet to process"),
#     name: Optional[str] = Form(None, description="Custom name for the dataset"),
#     description: Optional[str] = Form(None, description="Description of the dataset"),
#     excel_service: DynamicExcelService = Depends(lambda: DynamicExcelService())
# ):
#     """Upload Excel file dengan JSON storage"""
#     try:
#         # Validate file extension
#         if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
#             raise HTTPException(
#                 status_code=400,
#                 detail="File must be an Excel file (.xlsx or .xls)"
#             )
        
#         # Read and validate file size
#         contents = await file.read()
#         file_size = len(contents)
        
#         if file_size > 50 * 1024 * 1024:  # 50MB limit
#             raise HTTPException(
#                 status_code=413,
#                 detail="File size exceeds 50MB limit"
#             )
        
#         # Process Excel
#         result = await excel_service.process_and_store_excel(
#             file_contents=contents,
#             filename=file.filename,
#             sheet_name=sheet_name,
#             name=name,
#             description=description
#         )
        
#         # Background task untuk cleanup atau analytics
#         background_tasks.add_task(log_excel_upload, result["dataset_id"], file.filename)
        
#         return FileUploadResponse(
#             success=True,
#             dataset_id=result["dataset_id"],
#             dataset_name=result["dataset_name"],
#             message=result["message"],
#             file_info=result["file_info"]
#         )
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Excel upload error: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Failed to process Excel file: {str(e)}"
#         )

# @router.get(
#     "/datasets",
#     summary="List Excel Datasets",
#     description="Get list of all uploaded Excel datasets"
# )
# async def list_excel_datasets(
#     skip: int = Query(0, ge=0, description="Number of records to skip"),
#     limit: int = Query(100, ge=1, le=1000, description="Number of records to return"),
#     search: Optional[str] = Query(None, description="Search datasets by name"),
#     excel_service: ExcelService = Depends(lambda: ExcelService())
# ):
#     """List semua Excel datasets dengan pagination dan search"""
#     try:
#         datasets = await excel_service.list_excel_datasets(
#             skip=skip, 
#             limit=limit, 
#             search=search
#         )
        
#         return {
#             "datasets": datasets,
#             "pagination": {
#                 "skip": skip,
#                 "limit": limit,
#                 "total": len(datasets)  # Implement proper count in service
#             }
#         }
#     except Exception as e:
#         logger.error(f"Error listing datasets: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail="Failed to retrieve datasets"
#         )

# @router.get(
#     "/{dataset_id}",
#     summary="Get Excel Dataset",
#     description="Retrieve specific Excel dataset by ID"
# )
# async def get_excel_dataset(
#     dataset_id: str,
#     include_data: bool = Query(True, description="Include full data in response"),
#     excel_service: ExcelService = Depends(lambda: ExcelService())
# ):
#     """Get specific Excel dataset"""
#     try:
#         dataset = await excel_service.get_excel_data(
#             dataset_id, 
#             include_full_data=include_data
#         )
        
#         if not dataset:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Dataset not found"
#             )
        
#         return dataset
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error retrieving dataset: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail="Failed to retrieve dataset"
#         )

# @router.get(
#     "/{dataset_id}/sample",
#     summary="Get Dataset Sample",
#     description="Get sample data (first 10 rows) from dataset"
# )
# async def get_dataset_sample(
#     dataset_id: str,
#     rows: int = Query(10, ge=1, le=100, description="Number of sample rows"),
#     excel_service: ExcelService = Depends(lambda: ExcelService())
# ):
#     """Get sample data dari dataset"""
#     try:
#         sample = await excel_service.get_dataset_sample(dataset_id, rows)
        
#         if not sample:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Dataset not found"
#             )
        
#         return sample
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error getting sample: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail="Failed to get sample data"
#         )

# @router.put(
#     "/{dataset_id}",
#     summary="Update Dataset Metadata",
#     description="Update dataset name and description"
# )
# async def update_dataset_metadata(
#     dataset_id: str,
#     name: Optional[str] = None,
#     description: Optional[str] = None,
#     excel_service: ExcelService = Depends(lambda: ExcelService())
# ):
#     """Update dataset metadata"""
#     try:
#         success = await excel_service.update_dataset_metadata(
#             dataset_id, name, description
#         )
        
#         if not success:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Dataset not found"
#             )
        
#         return {"message": "Dataset updated successfully"}
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error updating dataset: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail="Failed to update dataset"
#         )

# @router.delete(
#     "/{dataset_id}",
#     summary="Delete Excel Dataset",
#     description="Soft delete Excel dataset"
# )
# async def delete_excel_dataset(
#     dataset_id: str,
#     hard_delete: bool = Query(False, description="Permanently delete (cannot be recovered)"),
#     excel_service: ExcelService = Depends(lambda: ExcelService())
# ):
#     """Delete Excel dataset"""
#     try:
#         success = await excel_service.delete_excel_dataset(
#             dataset_id, 
#             hard_delete=hard_delete
#         )
        
#         if not success:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Dataset not found"
#             )
        
#         delete_type = "permanently deleted" if hard_delete else "deactivated"
#         return {"message": f"Dataset {delete_type} successfully"}
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error deleting dataset: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail="Failed to delete dataset"
#         )

# # ==========================================
# # DYNAMIC TABLE ROUTES (Optional)
# # ==========================================

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
    "/dynamic/{dataset_id}/query",
    summary="Query Dynamic Table",
    description="Execute SQL query on dynamic table",
    tags=["dynamic-tables"]
)
async def query_dynamic_table(
    dataset_id: str,
    sql_query: str = Query(..., description="SQL query to execute"),
    limit: Optional[int] = Query(1000, le=10000, description="Row limit"),
    excel_service: DynamicExcelService = Depends(lambda: DynamicExcelService())
):
    """Query data dari dynamic table"""
    try:
        # Add LIMIT if not present
        if limit and "LIMIT" not in sql_query.upper():
            sql_query += f" LIMIT {limit}"
        
        result = await excel_service.query_dynamic_table(dataset_id, sql_query)
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dynamic query error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")
    

async def log_excel_upload(dataset_id: str, filename: str):
    """Background task untuk logging upload"""
    try:
        logger.info(f"Excel upload completed - Dataset: {dataset_id}, File: {filename}")
        # Add analytics tracking, email notifications, etc.
    except Exception as e:
        logger.error(f"Error in upload logging: {str(e)}")


