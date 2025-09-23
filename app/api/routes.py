from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, UploadFile, File, Form
from typing import List, Optional, Dict, Any
import pandas as pd
import io
from pathlib import Path
import uuid
import json
from datetime import datetime

from ..models.schemas import (
    QueryRequest, QueryResponse, HealthResponse,
    # Add these to schemas.py
    FileUploadResponse, DatabaseCredentials, DatabaseTestResponse
)
from ..services.query_processor import QueryProcessor
from ..core.config import get_settings
from ..core.database import test_database_connection, add_dynamic_connection
from ..api.dependencies import get_query_processor, rate_limit
from ..utils.logger import get_logger
from ..utils.exceptions import InvalidFileFormatError, DatabaseConnectionError

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/v1", tags=["queries"])

# Storage for uploaded data (in production, use persistent storage)
uploaded_data_store: Dict[str, Any] = {}

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
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
):
    """Process a natural language query"""
    
    try:
        logger.info(f"Processing query: {request.prompt[:100]}...")
        
        # Process query
        response = await processor.process_query(request)
        
        # Add background task for analytics/logging
        background_tasks.add_task(log_query_analytics, request, response)
        
        return response
        
    except Exception as e:
        logger.error(f"Query processing error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/upload/excel", response_model=FileUploadResponse)
async def upload_excel(
    file: UploadFile = File(...),
    sheet_name: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None)
):
    """
    Upload Excel file for analysis
    
    - **file**: Excel file (.xlsx, .xls) to upload
    - **sheet_name**: Optional specific sheet to load (default: first sheet)
    - **name**: Optional name for the dataset
    - **description**: Optional description of the data
    """
    try:
        # Validate file extension
        if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            raise HTTPException(
                status_code=400,
                detail="File must be an Excel file (.xlsx or .xls)"
            )
        
        # Check file size (limit to 50MB for Excel)
        contents = await file.read()
        file_size = len(contents)
        if file_size > 50 * 1024 * 1024:  # 50MB
            raise HTTPException(
                status_code=413,
                detail="File size exceeds 50MB limit"
            )
        
        # Parse Excel
        try:
            # Read Excel file
            excel_file = pd.ExcelFile(io.BytesIO(contents))
            
            # Get available sheets
            available_sheets = excel_file.sheet_names
            
            # Select sheet
            if sheet_name and sheet_name in available_sheets:
                df = pd.read_excel(excel_file, sheet_name=sheet_name)
                selected_sheet = sheet_name
            else:
                df = pd.read_excel(excel_file, sheet_name=0)
                selected_sheet = available_sheets[0]
                
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid Excel file: {str(e)}"
            )
        
        # Generate unique ID for this dataset
        dataset_id = str(uuid.uuid4())
        dataset_name = name or f"excel_{dataset_id[:8]}"
        
        # Store metadata and data
        uploaded_data_store[dataset_id] = {
            "id": dataset_id,
            "name": dataset_name,
            "type": "excel",
            "description": description,
            "filename": file.filename,
            "sheet_name": selected_sheet,
            "available_sheets": available_sheets,
            "upload_time": datetime.now().isoformat(),
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": df.columns.tolist(),
            "column_types": df.dtypes.astype(str).to_dict(),
            "data": df,  # In production, store in database or file system
            "sample": df.head(5).to_dict(orient='records')
        }
        
        logger.info(f"Excel uploaded successfully: {dataset_id}")
        
        return FileUploadResponse(
            success=True,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            message=f"Excel file uploaded successfully (sheet: {selected_sheet})",
            file_info={
                "filename": file.filename,
                "sheet_name": selected_sheet,
                "available_sheets": available_sheets,
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": df.columns.tolist(),
                "size_bytes": file_size
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Excel upload error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process Excel file: {str(e)}"
        )

@router.post("/upload/database", response_model=DatabaseTestResponse)
async def upload_database_credentials(
    credentials: DatabaseCredentials,
    processor: QueryProcessor = Depends(get_query_processor)
):
    """
    Upload and test database connection credentials
    
    Supports: PostgreSQL, MySQL, SQLite, SQL Server, Oracle
    """
    try:
        # Build connection string based on database type
        if credentials.db_type.lower() == "sqlite":
            connection_string = f"sqlite:///{credentials.database}"
        elif credentials.db_type.lower() == "postgresql":
            connection_string = f"postgresql://{credentials.username}:{credentials.password}@{credentials.host}:{credentials.port}/{credentials.database}"
        elif credentials.db_type.lower() == "mysql":
            connection_string = f"mysql+pymysql://{credentials.username}:{credentials.password}@{credentials.host}:{credentials.port}/{credentials.database}"
        elif credentials.db_type.lower() == "sqlserver":
            connection_string = f"mssql+pyodbc://{credentials.username}:{credentials.password}@{credentials.host}:{credentials.port}/{credentials.database}?driver=ODBC+Driver+17+for+SQL+Server"
        elif credentials.db_type.lower() == "oracle":
            connection_string = f"oracle+cx_oracle://{credentials.username}:{credentials.password}@{credentials.host}:{credentials.port}/{credentials.database}"
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported database type: {credentials.db_type}"
            )
        
        # Test connection
        logger.info(f"Testing database connection: {credentials.db_type}")
        test_result = await test_database_connection(connection_string)
        
        if not test_result["success"]:
            raise HTTPException(
                status_code=400,
                detail=f"Database connection failed: {test_result.get('error', 'Unknown error')}"
            )
        
        # If test successful, store connection
        connection_id = str(uuid.uuid4())
        connection_name = credentials.name or f"db_{connection_id[:8]}"
        
        # Add to dynamic connections
        await add_dynamic_connection(
            connection_id=connection_id,
            connection_name=connection_name,
            connection_string=connection_string,
            metadata={
                "db_type": credentials.db_type,
                "host": credentials.host,
                "port": credentials.port,
                "database": credentials.database,
                "description": credentials.description,
                "upload_time": datetime.now().isoformat()
            }
        )
        
        # Get schema information
        schema_info = test_result.get("schema", {})
        
        logger.info(f"Database connection added successfully: {connection_id}")
        
        return DatabaseTestResponse(
            success=True,
            connection_id=connection_id,
            connection_name=connection_name,
            message="Database connection successful",
            connection_info={
                "db_type": credentials.db_type,
                "host": credentials.host,
                "port": credentials.port,
                "database": credentials.database,
                "tables_count": len(schema_info.get("tables", [])),
                "tables": schema_info.get("tables", [])[:10],  # Return first 10 tables
                "test_query_time": test_result.get("query_time", 0)
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to connect to database: {str(e)}"
        )

@router.get("/datasets")
async def list_datasets():
    """List all uploaded datasets (CSV/Excel files)"""
    datasets = []
    for dataset_id, data in uploaded_data_store.items():
        datasets.append({
            "id": data["id"],
            "name": data["name"],
            "type": data["type"],
            "filename": data["filename"],
            "rows": data["rows"],
            "columns": data["columns"],
            "upload_time": data["upload_time"],
            "description": data.get("description")
        })
    
    return {
        "success": True,
        "count": len(datasets),
        "datasets": datasets
    }

@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str):
    """Delete an uploaded dataset"""
    if dataset_id not in uploaded_data_store:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset {dataset_id} not found"
        )
    
    dataset_name = uploaded_data_store[dataset_id]["name"]
    del uploaded_data_store[dataset_id]
    
    logger.info(f"Dataset deleted: {dataset_id}")
    
    return {
        "success": True,
        "message": f"Dataset '{dataset_name}' deleted successfully"
    }

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
    logger.info(f"Query completed: {response.query_id} - Success: {response.success}")