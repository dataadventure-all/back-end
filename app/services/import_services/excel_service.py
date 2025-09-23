# services/dynamic_excel_service.py
import pandas as pd
import io
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, Column, Integer, String, DateTime, Text, JSON, Boolean, Float, Date
from sqlalchemy.sql import func
from datetime import datetime
import uuid
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor

from ...core.database import AsyncSessionLocal, engine, Base
from ...models.schemas import SchemeExcel
from ...utils.logger import get_logger
from ...utils.exceptions import InvalidFileFormatError, DatabaseConnectionError

logger = get_logger(__name__)

class DynamicExcelService:
    """Service untuk menangani Excel dengan dynamic table creation"""
    
    def __init__(self):
        self.max_file_size = 50 * 1024 * 1024  # 50MB
        self.max_rows = 100000  # Limit rows untuk performa
        self.executor = ThreadPoolExecutor(max_workers=1)
    
    def _sanitize_table_name(self, name: str) -> str:
        """Sanitize nama untuk dijadikan table name"""
        # Remove special characters, keep alphanumeric and underscore
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name.lower())
        # Ensure starts with letter
        if not sanitized[0].isalpha():
            sanitized = 'tbl_' + sanitized
        # Limit length
        return sanitized[:50]
    
    def _sanitize_column_name(self, name: str) -> str:
        """Sanitize nama kolom untuk database"""
        # Remove special characters
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', str(name).lower())
        # Ensure starts with letter
        if not sanitized or not sanitized[0].isalpha():
            sanitized = 'col_' + sanitized
        # Handle reserved keywords
        reserved_words = ['id', 'index', 'order', 'group', 'select', 'from', 'where']
        if sanitized in reserved_words:
            sanitized = sanitized + '_col'
        return sanitized[:50]
    
    def _infer_sql_type(self, dtype, sample_values) -> str:
        """Infer SQL column type from pandas dtype"""
        dtype_str = str(dtype).lower()
        
        # Check sample values untuk lebih akurat
        non_null_values = [v for v in sample_values if pd.notna(v)]
        
        if 'int' in dtype_str:
            return 'INTEGER'
        elif 'float' in dtype_str:
            return 'FLOAT'
        elif 'bool' in dtype_str:
            return 'BOOLEAN'
        elif 'datetime' in dtype_str:
            return 'TIMESTAMP'
        elif 'date' in dtype_str:
            return 'DATE'
        else:
            # String type - determine length
            if non_null_values:
                max_length = max(len(str(v)) for v in non_null_values[:100])  # Sample first 100
                if max_length > 255:
                    return 'TEXT'
                else:
                    return f'VARCHAR({min(max_length * 2, 255)})'  # Double for safety
            return 'VARCHAR(255)'
    
    async def process_excel_dynamic_table(
        self,
        file_contents: bytes,
        filename: str,
        sheet_name: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        create_table: bool = True
    ) -> Dict[str, Any]:
        """
        Process Excel dan buat dynamic table
        """
        try:
            # Parse Excel
            excel_data = self._parse_excel(file_contents, sheet_name)
            df = excel_data["dataframe"]
            
            # Generate IDs
            dataset_id = str(uuid.uuid4())
            dataset_name = name or f"excel_{dataset_id[:8]}"
            table_name = self._sanitize_table_name(dataset_name)
            
            # Create dynamic table jika diminta
            if create_table:
                await self._create_dynamic_table(df, table_name, dataset_id)
                
                # Insert data ke dynamic table
                await self._insert_data_to_dynamic_table(df, table_name)
            
            # Save metadata ke scheme_excel
            excel_record = SchemeExcel(
                dataset_id=dataset_id,
                dataset_name=dataset_name,
                filename=filename,
                sheet_name=excel_data["selected_sheet"],
                description=description,
                rows_count=excel_data["rows"],
                columns_count=excel_data["columns"],
                column_names=excel_data["column_names"],
                column_types=excel_data["column_types"],
                available_sheets=excel_data["available_sheets"],
                file_size_bytes=len(file_contents),
                sample_data=excel_data["sample"],
                # Store table name instead of full data
                full_data={"dynamic_table": table_name, "created": create_table},
                processed=True
            )
            
            async with AsyncSessionLocal() as session:
                session.add(excel_record)
                await session.commit()
                await session.refresh(excel_record)
            
            logger.info(f"Excel processed with dynamic table: {table_name}")
            
            return {
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "table_name": table_name,
                "dynamic_table_created": create_table,
                "message": f"Excel processed {'with dynamic table' if create_table else 'as JSON'}",
                "file_info": {
                    "filename": filename,
                    "sheet_name": excel_data["selected_sheet"],
                    "available_sheets": excel_data["available_sheets"],
                    "rows": excel_data["rows"],
                    "columns": excel_data["columns"],
                    "column_names": excel_data["column_names"],
                    "size_bytes": len(file_contents)
                }
            }
            
        except Exception as e:
            logger.error(f"Error processing Excel with dynamic table: {str(e)}")
            raise Exception(f"Failed to process Excel file: {str(e)}")
    
    async def _create_dynamic_table(self, df: pd.DataFrame, table_name: str, dataset_id: str):
        """Create dynamic table based on DataFrame structure"""
        
        # Generate column definitions
        column_definitions = [
            "id SERIAL PRIMARY KEY",
            f"dataset_id VARCHAR(50) DEFAULT '{dataset_id}'",
            "created_at TIMESTAMP DEFAULT NOW()"
        ]
        
        # Add columns based on DataFrame
        for col_name in df.columns:
            sanitized_name = self._sanitize_column_name(col_name)
            sql_type = self._infer_sql_type(df[col_name].dtype, df[col_name].head(10))
            column_definitions.append(f'"{sanitized_name}" {sql_type}')
        
        # Create table SQL
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            {', '.join(column_definitions)}
        )
        """
        
        # Execute table creation
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._execute_sync_ddl,
            create_table_sql
        )
        
        logger.info(f"Created dynamic table: {table_name}")
    
    def _execute_sync_ddl(self, sql: str):
        """Execute DDL synchronously (required for table creation)"""
        from sqlalchemy import create_engine
        sync_engine = create_engine(
            str(engine.url).replace("+asyncpg", ""),
            echo=False
        )
        with sync_engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
        sync_engine.dispose()
    
    async def _insert_data_to_dynamic_table(self, df: pd.DataFrame, table_name: str):
        """Insert DataFrame data ke dynamic table"""
        
        # Sanitize column names
        sanitized_columns = {col: self._sanitize_column_name(col) for col in df.columns}
        
        # Prepare data
        df_clean = df.copy()
        df_clean = df_clean.fillna(None)  # Replace NaN with None
        
        # Convert data types for PostgreSQL compatibility
        for col in df_clean.columns:
            if df_clean[col].dtype == 'datetime64[ns]':
                df_clean[col] = df_clean[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            elif df_clean[col].dtype == 'bool':
                df_clean[col] = df_clean[col].astype(bool)
        
        # Rename columns to sanitized names
        df_clean.columns = [sanitized_columns[col] for col in df_clean.columns]
        
        # Insert data in batches
        batch_size = 1000
        total_rows = len(df_clean)
        
        loop = asyncio.get_event_loop()
        
        for i in range(0, total_rows, batch_size):
            batch = df_clean.iloc[i:i+batch_size]
            await loop.run_in_executor(
                self.executor,
                self._insert_batch_sync,
                batch,
                table_name
            )
        
        logger.info(f"Inserted {total_rows} rows into {table_name}")
    
    def _insert_batch_sync(self, batch_df: pd.DataFrame, table_name: str):
        """Insert batch data synchronously"""
        from sqlalchemy import create_engine
        sync_engine = create_engine(
            str(engine.url).replace("+asyncpg", ""),
            echo=False
        )
        
        batch_df.to_sql(
            table_name,
            sync_engine,
            if_exists='append',
            index=False,
            method='multi'
        )
        sync_engine.dispose()
    
    def _parse_excel(self, file_contents: bytes, sheet_name: Optional[str] = None) -> Dict[str, Any]:
        """Parse Excel file dan extract data"""
        try:
            # Read Excel file
            excel_file = pd.ExcelFile(io.BytesIO(file_contents))
            available_sheets = excel_file.sheet_names
            
            # Select sheet
            if sheet_name and sheet_name in available_sheets:
                df = pd.read_excel(excel_file, sheet_name=sheet_name)
                selected_sheet = sheet_name
            else:
                df = pd.read_excel(excel_file, sheet_name=0)
                selected_sheet = available_sheets[0]
            
            # Check limits
            if len(df) > self.max_rows:
                logger.warning(f"Excel file has {len(df)} rows, truncating to {self.max_rows}")
                df = df.head(self.max_rows)
            
            # Clean column names
            df.columns = [str(col).strip() for col in df.columns]
            
            # Sample data for JSON storage (first 5 rows)
            df_sample = df.head(5).fillna("")
            sample_data = df_sample.to_dict(orient='records')
            
            return {
                "dataframe": df,
                "selected_sheet": selected_sheet,
                "available_sheets": available_sheets,
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": df.columns.tolist(),
                "column_types": df.dtypes.astype(str).to_dict(),
                "sample": sample_data
            }
            
        except Exception as e:
            raise InvalidFileFormatError(f"Invalid Excel file: {str(e)}")
    
    async def query_dynamic_table(self, dataset_id: str, query: str) -> Dict[str, Any]:
        """Query data dari dynamic table"""
        try:
            # Get dataset info
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(SchemeExcel).where(SchemeExcel.dataset_id == dataset_id)
                )
                excel_record = result.scalar_one_or_none()
                
                if not excel_record or not excel_record.full_data.get("dynamic_table"):
                    raise ValueError("Dataset not found or no dynamic table created")
                
                table_name = excel_record.full_data["dynamic_table"]
            
            # Execute query on dynamic table
            async with AsyncSessionLocal() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                columns = list(result.keys())
                
                # Convert to list of dicts
                data = [dict(zip(columns, row)) for row in rows]
                
                return {
                    "success": True,
                    "data": data,
                    "columns": columns,
                    "row_count": len(data),
                    "table_name": table_name
                }
                
        except Exception as e:
            logger.error(f"Error querying dynamic table: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def drop_dynamic_table(self, dataset_id: str) -> bool:
        """Drop dynamic table"""
        try:
            # Get table name
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(SchemeExcel).where(SchemeExcel.dataset_id == dataset_id)
                )
                excel_record = result.scalar_one_or_none()
                
                if not excel_record or not excel_record.full_data.get("dynamic_table"):
                    return False
                
                table_name = excel_record.full_data["dynamic_table"]
            
            # Drop table
            drop_sql = f'DROP TABLE IF EXISTS "{table_name}"'
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.executor,
                self._execute_sync_ddl,
                drop_sql
            )
            
            # Update metadata
            async with AsyncSessionLocal() as session:
                excel_record.full_data = {"dynamic_table": None, "created": False}
                excel_record.is_active = False
                await session.commit()
            
            logger.info(f"Dropped dynamic table: {table_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error dropping dynamic table: {str(e)}")
            return False

# Updated routes dengan opsi dynamic table
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query

router = APIRouter(prefix="/api/v1/dynamic", tags=["dynamic-excel"])

@router.post("/upload/excel")
async def upload_excel_dynamic(
    file: UploadFile = File(...),
    sheet_name: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    create_table: bool = Form(True),  # Option to create dynamic table
    excel_service: DynamicExcelService = Depends(lambda: DynamicExcelService())
):
    """Upload Excel dengan opsi dynamic table creation"""
    try:
        # Validate file
        if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            raise HTTPException(
                status_code=400,
                detail="File must be an Excel file (.xlsx or .xls)"
            )
        
        contents = await file.read()
        if len(contents) > 50 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail="File size exceeds 50MB limit"
            )
        
        # Process Excel
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
        logger.error(f"Excel upload error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process Excel file: {str(e)}"
        )

@router.post("/query/{dataset_id}")
async def query_excel_data(
    dataset_id: str,
    query: str = Query(..., description="SQL query to execute"),
    excel_service: DynamicExcelService = Depends(lambda: DynamicExcelService())
):
    """Query data dari dynamic table"""
    try:
        result = await excel_service.query_dynamic_table(dataset_id, query)
        
        if not result["success"]:
            raise HTTPException(
                status_code=400,
                detail=result["error"]
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Query execution failed: {str(e)}"
        )

@router.delete("/table/{dataset_id}")
async def drop_dynamic_table(
    dataset_id: str,
    excel_service: DynamicExcelService = Depends(lambda: DynamicExcelService())
):
    """Drop dynamic table"""
    try:
        success = await excel_service.drop_dynamic_table(dataset_id)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail="Dataset not found or table already dropped"
            )
        
        return {"message": "Dynamic table dropped successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Drop table error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to drop table: {str(e)}"
        )