# back-end/app/services/import_services/csv_service.py
# services/dynamic_csv_service.py
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

# Import DynamicExcelService untuk diwariskan
from .excel_service import DynamicExcelService

logger = get_logger(__name__)

# Warisi DynamicCsvService dari DynamicExcelService
class DynamicCsvService(DynamicExcelService):
    """Service untuk menangani CSV dengan dynamic table creation, 
    menggunakan ulang logic umum dari DynamicExcelService"""

    SCHEMA_NAME = 'schema_csv'

    def __init__(self):
        super().__init__()
        self.schema_name = self.SCHEMA_NAME

    # ---------------------- CSV Parsing (Dipertahankan karena spesifik CSV) ----------------------
    def _parse_csv(self, file_contents: bytes, encoding: Optional[str] = None, delimiter: Optional[str] = None) -> Dict[str, Any]:
        """
        Parse CSV file. CSV tidak memiliki sheet seperti Excel.
        Mendeteksi encoding otomatis jika tidak diberikan.
        """
        try:
            # Try to detect encoding if not provided
            encodings_to_try = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252', 'utf-16']
            if encoding:
                encodings_to_try.insert(0, encoding)
            
            df = None
            detected_encoding = None
            error_message = None
            
            for enc in encodings_to_try:
                try:
                    # Try different delimiters if not specified
                    delimiters_to_try = [',', ';', '\t', '|'] if delimiter is None else [delimiter]
                    
                    for delim in delimiters_to_try:
                        try:
                            df = pd.read_csv(
                                io.BytesIO(file_contents),
                                encoding=enc,
                                delimiter=delim,
                                on_bad_lines='skip',  # Skip bad lines instead of erroring
                                engine='python'  # More flexible for malformed files
                            )
                            detected_encoding = enc
                            if delimiter is None and delim != ',':
                                logger.info(f"Detected delimiter: {delim}")
                            break
                        except Exception as e:
                            if df is None:
                                error_message = str(e)
                            continue
                    
                    if df is not None:
                        break
                        
                except Exception as e:
                    error_message = str(e)
                    continue
            
            if df is None or df.empty:
                raise InvalidFileFormatError(f"Could not parse CSV file: {error_message or 'Unknown error'}")
            
            # Clean DataFrame
            df.columns = [str(col).strip() for col in df.columns]
            
            # Remove completely empty rows
            df = df.dropna(how='all')
            
            if len(df) > self.max_rows:
                logger.warning(f"CSV has {len(df)} rows, truncating to {self.max_rows}")
                df = df.head(self.max_rows)
            
            sample_data = df.head(5).fillna("").to_dict(orient="records")
            
            return {
                "dataframe": df,
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": df.columns.tolist(),
                "column_types": df.dtypes.astype(str).to_dict(),
                "sample": sample_data,
                "encoding": detected_encoding or encoding or 'utf-8'
            }

        except InvalidFileFormatError:
            raise
        except Exception as e:
            raise InvalidFileFormatError(f"Invalid CSV file: {str(e)}")


    # ---------------------- Schema and Metadata Table Creation (Dipertahankan) ----------------------
    # Dipertahankan karena DynamicExcelService tidak memiliki implementasi eksplisitnya
    async def _ensure_schema_and_metadata_table(self):
        """Ensure schema_csv schema and datasets_metadata table exist"""
        schema_name = self.schema_name
        
        create_schema_sql = f'CREATE SCHEMA IF NOT EXISTS "{schema_name}";'
        
        create_metadata_table_sql = f"""
        CREATE TABLE IF NOT EXISTS "{schema_name}".datasets_metadata (
            dataset_id VARCHAR(255) PRIMARY KEY,
            schema_name VARCHAR(255) NOT NULL,
            table_name VARCHAR(255) NOT NULL,
            original_filename VARCHAR(500),
            created_by VARCHAR(255),
            row_count INTEGER NOT NULL,
            column_count INTEGER NOT NULL,
            column_names JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, self._execute_sync_ddl, create_schema_sql)
        await loop.run_in_executor(self.executor, self._execute_sync_ddl, create_metadata_table_sql)
        logger.info(f"Ensured schema {schema_name} and datasets_metadata table exist")

    # ---------------------- Dynamic Table Creation (Override untuk nama skema) ----------------------
    async def _create_dynamic_table(self, df: pd.DataFrame, table_name: str, dataset_id: str):
        schema_name = self.schema_name
        
        # Ensure schema and metadata table exist first (DIJAGA untuk Fungsionalitas)
        await self._ensure_schema_and_metadata_table()
        
        column_defs = [
            "id SERIAL PRIMARY KEY",
            f"dataset_id VARCHAR(50) DEFAULT '{dataset_id}'",
            "created_at TIMESTAMP DEFAULT NOW()"
        ]
        
        # 1. Generate definisi kolom dari DataFrame (diwarisi)
        for col in df.columns:
            col_name = self._sanitize_column_name(col)
            col_type = self._infer_sql_type(df[col].dtype, df[col].dropna())
            column_defs.append(f'"{col_name}" {col_type}')

        # 2. Query CREATE TABLE dinamis
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS "{schema_name}"."{table_name}" (
            {', '.join(column_defs)}
        )
        """

        # 3. Jalankan CREATE TABLE di thread pool (diwarisi)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, self._execute_sync_ddl, create_sql)

        # 4. Setelah tabel berhasil dibuat, daftarkan ke tabel metadata
        try:
            await self._register_dataset_metadata(
                dataset_id=dataset_id,
                table_name=table_name,
                df=df,
                original_filename="unknown.csv",
                created_by="system"
            )
            logger.info(f"Registered metadata for dataset {dataset_id}")
        except Exception as e:
            logger.error(f"Failed to register dataset metadata: {e}")

        # 5. Logging final
        logger.info(f"Created dynamic table: {table_name}")

    # ---------------------- Insert Batch Data (Override untuk nama skema) ----------------------
    # Override untuk menggunakan self.schema_name saat memanggil to_sql
    def _insert_batch_sync(self, batch_df: pd.DataFrame, table_name: str):
        from sqlalchemy import create_engine
        sync_url = self.settings.DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
        engine = create_engine(sync_url, echo=False)
        # Gunakan self.schema_name
        batch_df.to_sql(table_name, engine, schema=self.schema_name, if_exists="append", index=False, method="multi")
        engine.dispose()


    # ---------------------- Register Metadata (Override untuk nama skema) ----------------------
    # Hapus panggilan _ensure_schema_and_metadata_table agar sama dengan ExcelService
    async def _register_dataset_metadata(
        self,
        dataset_id: str,
        table_name: str,
        df: pd.DataFrame,
        original_filename: str,
        created_by: str = None
    ):
        """Register dataset info ke tabel metadata"""
        schema_name = self.schema_name
        
        # **Perubahan:** Panggilan ke await self._ensure_schema_and_metadata_table() telah dihapus 
        # untuk menghilangkan redundansi dan menyelaraskan dengan struktur DynamicExcelService.
        
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

    
    # ---------------------- Main CSV Processing (Dipertahankan) ----------------------
    async def process_csv_dynamic_table(
        self,
        file_contents: bytes,
        filename: str,
        encoding: Optional[str] = None,
        delimiter: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        create_table: bool = True
    ) -> Dict[str, Any]:

        csv_data = self._parse_csv(file_contents, encoding=encoding, delimiter=delimiter)
        df = csv_data["dataframe"]

        dataset_id = uuid.uuid4()
        dataset_name = name or f"csv_{str(dataset_id)[:8]}"
        table_name = self._sanitize_table_name(dataset_name)

        if create_table:
            await self._create_dynamic_table(df, table_name, dataset_id)
            await self._insert_data_to_dynamic_table(df, table_name)

        # Save metadata - reuse SchemeExcel but set sheet_name to "N/A" for CSV
        record = SchemeExcel(
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            filename=filename,
            sheet_name="N/A",  # CSV doesn't have sheets
            description=description,
            rows_count=csv_data["rows"],
            columns_count=csv_data["columns"],
            column_names=csv_data["column_names"],
            column_types=csv_data["column_types"],
            available_sheets=[],  # Empty list for CSV
            file_size_bytes=len(file_contents),
            sample_data=csv_data["sample"],
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
                "rows": csv_data["rows"],
                "columns": csv_data["columns"],
                "column_names": csv_data["column_names"],
                "encoding": csv_data.get("encoding", "utf-8")
            }
        }

    # ---------------------- Drop Dynamic Table (Override untuk nama skema) ----------------------
    # Override untuk menggunakan self.schema_name
    async def drop_dynamic_table(self, dataset_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SchemeExcel).where(SchemeExcel.dataset_id == dataset_id))
            record = result.scalar_one_or_none()
            if not record or not record.full_data.get("dynamic_table"):
                return False
            table_name = record.full_data["dynamic_table"]

            # Gunakan DROP TABLE yang memenuhi syarat skema
            drop_sql = f'DROP TABLE IF EXISTS "{self.schema_name}"."{table_name}";'
            
            # Gunakan _execute_sync_ddl yang diwarisi
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self.executor, self._execute_sync_ddl, drop_sql)

            record.full_data = {"dynamic_table": None, "created": False}
            record.is_active = False
            await session.commit()
            logger.info(f"Dropped dynamic table: {table_name}")
            return True