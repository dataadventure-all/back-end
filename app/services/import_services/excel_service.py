# services/dynamic_excel_service.py
import pandas as pd
import io
import uuid
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.sql import func

from ...core.database import AsyncSessionLocal, engine, Base
from ...core.config import get_settings
from ...models.schemas import SchemeExcel
from ...utils.logger import get_logger
from ...utils.exceptions import InvalidFileFormatError

logger = get_logger(__name__)

class DynamicExcelService:
    """Service untuk menangani Excel dengan dynamic table creation"""

    def __init__(self):
        self.max_file_size = 50 * 1024 * 1024  # 50MB
        self.max_rows = 100_000
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.settings = get_settings()

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
        column_defs = [
            "id SERIAL PRIMARY KEY",
            f"dataset_id VARCHAR(50) DEFAULT '{dataset_id}'",
            "created_at TIMESTAMP DEFAULT NOW()"
        ]
        for col in df.columns:
            col_name = self._sanitize_column_name(col)
            col_type = self._infer_sql_type(df[col].dtype, df[col].dropna())
            column_defs.append(f'"{col_name}" {col_type}')

        create_sql = f"""
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            {', '.join(column_defs)}
        )
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, self._execute_sync_ddl, create_sql)
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
        batch_df.to_sql(table_name, engine, schema=None, if_exists="append", index=False, method="multi")
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
        dataset_name = name or f"excel_{dataset_id[:8]}"
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

    # ---------------------- Query Dynamic Table ----------------------
    async def query_dynamic_table(self, dataset_id: str, query: str) -> Dict[str, Any]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SchemeExcel).where(SchemeExcel.dataset_id == dataset_id))
            record = result.scalar_one_or_none()
            if not record or not record.full_data.get("dynamic_table"):
                return {"success": False, "error": "Dataset not found or no dynamic table created"}
            table_name = record.full_data["dynamic_table"]

            result = await session.execute(text(query))
            rows = result.fetchall()
            columns = list(result.keys())
            data = [dict(zip(columns, row)) for row in rows]

            return {"success": True, "data": data, "columns": columns, "row_count": len(data), "table_name": table_name}

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
