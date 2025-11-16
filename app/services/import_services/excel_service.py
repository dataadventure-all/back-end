# services/dynamic_excel_service.py
import pandas as pd
import io
import uuid
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, List
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.sql import func

from ...core.database import AsyncSessionLocal, engine, Base
from ...core.config import get_settings
from ...models.schemas import SchemeExcel
from ...utils.logger import get_logger
from ...utils.exceptions import InvalidFileFormatError
import time
from ...core.database import get_raw_connection
from ...services.llm_service import LLMService

logger = get_logger(__name__)

class DynamicExcelService:
    """Service untuk menangani Excel dengan dynamic table creation"""

    def __init__(self):
        self.max_file_size = 50 * 1024 * 1024  # 50MB
        self.max_rows = 100_000
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.settings = get_settings()
        self.llm_service = LLMService()

    # ---------------------- Sanitization ----------------------
    def _sanitize_table_name(self, name: str) -> str:
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name.lower())
        if not sanitized[0].isalpha():
            sanitized = "tbl_" + sanitized
        return sanitized[:50]

    def _sanitize_column_name(self, name: str) -> str:
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', str(name).lower())
        if not sanitized or not sanitized[0].isalpha():
            sanitized = "col_" + sanitized
        reserved = ['id', 'index', 'order', 'group', 'select', 'from', 'where']
        if sanitized in reserved:
            sanitized += "_col"
        return sanitized[:50]

    # ---------------------- Type Inference ----------------------
    def _infer_sql_type(self, dtype, sample_values) -> str:
        dtype_str = str(dtype).lower()
        non_null = [v for v in sample_values if pd.notna(v)]
        if 'int' in dtype_str:
            return "BIGINT"
        elif 'float' in dtype_str:
            return "DOUBLE PRECISION"
        elif 'bool' in dtype_str:
            return "BOOLEAN"
        elif 'datetime' in dtype_str:
            return "TIMESTAMP"
        elif 'date' in dtype_str:
            return "DATE"
        else:
            return "TEXT"

    # ---------------------- Excel Parsing ----------------------
    def _parse_excel(self, file_contents: bytes, sheet_name: Optional[str] = None) -> Dict[str, Any]:
        try:
            excel_file = pd.ExcelFile(io.BytesIO(file_contents))
            available_sheets = excel_file.sheet_names
            if sheet_name and sheet_name in available_sheets:
                df = pd.read_excel(excel_file, sheet_name=sheet_name)
                selected_sheet = sheet_name
            else:
                df = pd.read_excel(excel_file, sheet_name=0)
                selected_sheet = available_sheets[0]

            if len(df) > self.max_rows:
                logger.warning(f"Excel has {len(df)} rows, truncating to {self.max_rows}")
                df = df.head(self.max_rows)

            df.columns = [str(col).strip() for col in df.columns]
            sample_data = df.head(5).fillna("").to_dict(orient="records")

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

    # ---------------------- Dynamic Table Creation ----------------------

    async def _create_dynamic_table(self, df: pd.DataFrame, table_name: str, dataset_id: str):
        schema_name = 'schema_excel'
        column_defs = [
            "id SERIAL PRIMARY KEY",
            f"dataset_id VARCHAR(50) DEFAULT '{dataset_id}'",
            "created_at TIMESTAMP DEFAULT NOW()"
        ]
        
        # 🔹 1. Generate definisi kolom dari DataFrame
        for col in df.columns:
            col_name = self._sanitize_column_name(col)
            col_type = self._infer_sql_type(df[col].dtype, df[col].dropna())
            column_defs.append(f'"{col_name}" {col_type}')

        # 🔹 2. Query CREATE TABLE dinamis
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS "{schema_name}"."{table_name}" (
            {', '.join(column_defs)}
        )
        """

        # 🔹 3. Jalankan CREATE TABLE di thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, self._execute_sync_ddl, create_sql)

        # 🔹 4. Setelah tabel berhasil dibuat → daftarkan ke tabel metadata
        try:
            await self._register_dataset_metadata(
                dataset_id=dataset_id,
                table_name=table_name,
                df=df,
                original_filename="unknown.xlsx",  # bisa diisi dari request.file.filename
                created_by="system"                # atau dari user login
            )
            logger.info(f"Registered metadata for dataset {dataset_id}")
        except Exception as e:
            logger.error(f"Failed to register dataset metadata: {e}")

        # 🔹 5. Logging final
        logger.info(f"Created dynamic table: {table_name}")

    def _execute_sync_ddl(self, sql: str):
        from sqlalchemy import create_engine
        sync_url = self.settings.DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
        engine = create_engine(sync_url, echo=False)
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
        engine.dispose()

    # ---------------------- Insert Data ----------------------
    async def _insert_data_to_dynamic_table(self, df: pd.DataFrame, table_name: str):
        sanitized_columns = {c: self._sanitize_column_name(c) for c in df.columns}
        df_clean = df.copy()

        # Convert datetime
        for col in df_clean.columns:
            if df_clean[col].dtype == 'datetime64[ns]':
                mask = df_clean[col].notna()
                df_clean.loc[mask, col] = df_clean.loc[mask, col].dt.strftime("%Y-%m-%d %H:%M:%S")
                df_clean.loc[~mask, col] = None
            elif df_clean[col].dtype == 'bool':
                df_clean[col] = df_clean[col].astype('object')

        df_clean = df_clean.where(pd.notna(df_clean), None)
        df_clean.columns = [sanitized_columns[c] for c in df_clean.columns]

        batch_size = 1000
        loop = asyncio.get_event_loop()
        for i in range(0, len(df_clean), batch_size):
            batch = df_clean.iloc[i:i + batch_size]
            await loop.run_in_executor(self.executor, self._insert_batch_sync, batch, table_name)
        logger.info(f"Inserted {len(df_clean)} rows into {table_name}")

    def _insert_batch_sync(self, batch_df: pd.DataFrame, table_name: str):
        from sqlalchemy import create_engine
        sync_url = self.settings.DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
        engine = create_engine(sync_url, echo=False)
        # Schema None = default public
        batch_df.to_sql(table_name, engine, schema='schema_excel', if_exists="append", index=False, method="multi")
        engine.dispose()


    async def _register_dataset_metadata(
        self,
        dataset_id: str,
        table_name: str,
        df: pd.DataFrame,
        original_filename: str,
        created_by: str = None
    ):
        """Register dataset info ke tabel metadata"""
        schema_name = "schema_excel"
        column_names = list(df.columns)
        row_count = len(df)
        column_count = len(df.columns)

        insert_sql = f"""
        INSERT INTO "{schema_name}".datasets_metadata 
        (dataset_id, schema_name, table_name, original_filename, created_by, row_count, column_count, column_names)
        VALUES (:dataset_id, :schema_name, :table_name, :original_filename, :created_by, :row_count, :column_count, :column_names)
        ON CONFLICT (dataset_id) DO NOTHING;
        """

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor,
            self._execute_sync_metadata_insert,
            insert_sql,
            {
                "dataset_id": dataset_id,
                "schema_name": schema_name,
                "table_name": table_name,
                "original_filename": original_filename,
                "created_by": created_by,
                "row_count": row_count,
                "column_count": column_count,
                "column_names": json.dumps(column_names),
            },
        )
        logger.info(f"Registered metadata for dataset {dataset_id}")

    def _execute_sync_metadata_insert(self, sql: str, params: dict):
        from sqlalchemy import create_engine, text
        sync_url = self.settings.DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
        engine = create_engine(sync_url, echo=False)
        with engine.connect() as conn:
            conn.execute(text(sql), params)
            conn.commit()
            engine.dispose()

    


    # ---------------------- Main Excel Processing ----------------------
    async def process_excel_dynamic_table(
        self,
        file_contents: bytes,
        filename: str,
        sheet_name: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        create_table: bool = True
    ) -> Dict[str, Any]:

        excel_data = self._parse_excel(file_contents, sheet_name)
        df = excel_data["dataframe"]

        dataset_id = uuid.uuid4()
        dataset_name = name or f"excel_{str(dataset_id)[:8]}"
        table_name = self._sanitize_table_name(dataset_name)

        if create_table:
            await self._create_dynamic_table(df, table_name, dataset_id)
            await self._insert_data_to_dynamic_table(df, table_name)

        # Save metadata
        record = SchemeExcel(
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
            full_data={"dynamic_table": table_name, "created": create_table},
            processed=True
        )

        async with AsyncSessionLocal() as session:
            session.add(record)
            await session.commit()
            await session.refresh(record)

        return {
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
            "table_name": table_name,
            "dynamic_table_created": create_table,
            "file_info": {
                "filename": filename,
                "sheet_name": excel_data["selected_sheet"],
                "rows": excel_data["rows"],
                "columns": excel_data["columns"],
                "column_names": excel_data["column_names"],
            }
        }


    async def query_dynamic_table(
            self, 
            sql_query: str,
            dataset_id: str,
            generate_chart: bool = False,
            chart_prompt: Optional[str] = None,
            chart_type: Optional[str] = None,
            color_scheme: Optional[str] = None,
            chart_width: int = 800,
            chart_height: int = 400
        ) -> Dict[str, Any]:
        """
        Execute SQL query on dynamic table in schema_excel
        
        Args:
            sql_query: SQL query to execute
            dataset_id: Dataset identifier
            generate_chart: Whether to generate chart configuration
            chart_prompt: Natural language description for chart (e.g., "show sales trend over time")
            chart_type: Preferred chart type (optional: "line", "bar", "pie", etc.)
            color_scheme: Color scheme (optional: "blue", "green", "purple", etc.)
            chart_width: Chart width in pixels
            chart_height: Chart height in pixels
        
        Returns:
            Dict containing query results and optional chart configuration
        """
        
        start_time = time.time()
        
        try:
            async with get_raw_connection() as conn:
                # ✅ 1. Get table metadata from schema_excel.datasets_metadata
                meta_sql = """
                    SELECT schema_name, table_name
                    FROM schema_excel.datasets_metadata
                    WHERE dataset_id = $1
                    LIMIT 1
                """
                meta_row = await conn.fetchrow(meta_sql, dataset_id)
                
                if not meta_row:
                    return {
                        "success": False, 
                        "error": f"Dataset {dataset_id} not found in metadata",
                        "data": [],
                        "row_count": 0,
                        "execution_time_seconds": 0,
                        "columns": [],
                        "chart_config": None
                    }
                
                schema_name = meta_row["schema_name"]  # "schema_excel"
                table_name = meta_row["table_name"]    # "excel_data_abc123"
                
                # ✅ 2. Replace {{table}} placeholder with fully qualified name
                fully_qualified_table = f"{schema_name}.{table_name}"
                final_query = sql_query.replace("{{table}}", fully_qualified_table)
                
                logger.info(f"Executing query on: {fully_qualified_table}")
                logger.info(f"Final query: {final_query}")
                
                # ✅ 3. Execute query
                rows = await conn.fetch(final_query)
                
                if rows:
                    columns = list(rows[0].keys())
                    data = [dict(row) for row in rows]
                else:
                    columns = []
                    data = []
                
                execution_time = time.time() - start_time
                
                # ✅ 4. Generate chart configuration if requested
                chart_config = None
                if generate_chart and data:
                    try:
                        # Use the first 5 rows for chart generation (or all if less than 5)
                        sample_data = data[:5] if len(data) > 5 else data
                        
                        # Create default chart prompt if not provided
                        if not chart_prompt:
                            chart_prompt = f"Visualize the data with columns: {', '.join(columns)}"
                        
                        # Generate chart configuration using LLM
                        chart_config = await self.llm_service.generate_chart_config(
                            data=data,  # Pass full data for analysis
                            user_prompt=chart_prompt,
                            preferred_chart_type=chart_type,
                            color_scheme=color_scheme,
                            width=chart_width,
                            height=chart_height
                        )
                        
                        logger.info(f"Chart config generated: {chart_config.get('chart_type', 'unknown')} chart")
                        
                    except Exception as chart_error:
                        logger.error(f"Chart generation failed: {str(chart_error)}")
                        # Create fallback chart config
                        chart_config = self._create_fallback_config(
                            data=data,
                            user_prompt=chart_prompt or "Data visualization",
                            color_scheme=color_scheme,
                            width=chart_width,
                            height=chart_height
                        )
                
                return {
                    "success": True,
                    "data": data,
                    "columns": columns,
                    "row_count": len(data),
                    "schema_name": schema_name,
                    "table_name": table_name,
                    "execution_time_seconds": round(execution_time, 3),
                    "chart_config": chart_config  # ✅ Added chart configuration
                }
                
        except Exception as e:
            logger.error(f"Query execution error: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "data": [],
                "row_count": 0,
                "execution_time_seconds": time.time() - start_time,
                "columns": [],
                "chart_config": None
            }
    # ---------------------- Drop Dynamic Table ----------------------
    async def drop_dynamic_table(self, dataset_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SchemeExcel).where(SchemeExcel.dataset_id == dataset_id))
            record = result.scalar_one_or_none()
            if not record or not record.full_data.get("dynamic_table"):
                return False
            table_name = record.full_data["dynamic_table"]

            drop_sql = f'DROP TABLE IF EXISTS "{table_name}"'
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self.executor, self._execute_sync_ddl, drop_sql)

            record.full_data = {"dynamic_table": None, "created": False}
            record.is_active = False
            await session.commit()
            logger.info(f"Dropped dynamic table: {table_name}")
            return True

# ---------------------- FastAPI Router ----------------------
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query

router = APIRouter(prefix="/api/v1/dynamic", tags=["dynamic-excel"])

@router.post("/upload/excel")
async def upload_excel_dynamic(
    file: UploadFile = File(...),
    sheet_name: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    create_table: bool = Form(True),
    excel_service: DynamicExcelService = Depends(lambda: DynamicExcelService())
):
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls")):
        raise HTTPException(status_code=400, detail="File must be Excel (.xlsx/.xls)")
    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File size exceeds 50MB")
    return await excel_service.process_excel_dynamic_table(
        file_contents=contents,
        filename=file.filename,
        sheet_name=sheet_name,
        name=name,
        description=description,
        create_table=create_table
    )

@router.post("/query/{dataset_id}")
async def query_excel_data(
    dataset_id: str,
    query: str = Query(...),
    excel_service: DynamicExcelService = Depends(lambda: DynamicExcelService())
):
    result = await excel_service.query_dynamic_table(dataset_id, query)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.delete("/table/{dataset_id}")
async def drop_dynamic_table(
    dataset_id: str,
    excel_service: DynamicExcelService = Depends(lambda: DynamicExcelService())
):
    success = await excel_service.drop_dynamic_table(dataset_id)
    if not success:
        raise HTTPException(status_code=404, detail="Dataset not found or table already dropped")
    return {"message": "Dynamic table dropped successfully"}
