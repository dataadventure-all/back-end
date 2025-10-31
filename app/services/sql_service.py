import asyncpg
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
import re
from ..core.database import get_raw_connection
from ..core.config import get_settings
from ..models.schemas import SQLQuery
from ..utils.logger import get_logger
from ..utils.exceptions import SQLExecutionError, SQLValidationError

logger = get_logger(__name__)
settings = get_settings()

class SQLService:
    """Service for SQL query validation and execution"""
    
    # Dangerous SQL patterns
    DANGEROUS_PATTERNS = [
        r'\b(DROP|DELETE|TRUNCATE|UPDATE|INSERT|ALTER|CREATE|REPLACE)\b',
        r'\b(EXEC|EXECUTE|CALL)\b',
        r'(;|\-\-|\/\*|\*\/)',  # Multiple statements, comments
    ]
    
    def __init__(self):
        self.max_execution_time = 30  # seconds
        
    # ----------------------------------------
# Main dispatcher
# ----------------------------------------
    async def get_schema_info(self, querytype: str, dataset_id: str) -> Dict[str, Any]:
        """Route ke fungsi sesuai querytype"""
        if querytype == "excel":
            return await self._get_excel_schema(dataset_id)
        elif querytype == "csv":
            return await self._get_csv_schema(dataset_id)
        else:
            return await self._get_public_schema()


    # ----------------------------------------
    # Handler khusus Excel
    # ----------------------------------------
    async def _get_excel_schema(self, dataset_id: str) -> Dict[str, Any]:
        """Ambil schema info untuk dataset Excel"""
        async with get_raw_connection() as conn:
            # 🔹 1. Ambil metadata dari tabel datasets_metadata
            meta_sql = """
                SELECT schema_name, table_name
                FROM schema_excel.datasets_metadata
                WHERE dataset_id = 5f0c22cc-bf8b-4ff0-b5b8-693d9668fbb6
                LIMIT 1
            """
            meta_row = await conn.fetchrow(meta_sql, dataset_id)
            if not meta_row:
                raise ValueError(f"Dataset ID {dataset_id} not found in metadata")

            schema_name = meta_row["schema_name"]
            table_name = meta_row["table_name"]

            # 🔹 2. Ambil kolom dari information_schema
            columns_sql = """
                SELECT 
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.character_maximum_length
                FROM information_schema.columns c
                WHERE c.table_schema = $1
                AND c.table_name = $2
                ORDER BY c.ordinal_position
            """
            rows = await conn.fetch(columns_sql, schema_name, table_name)

            # 🔹 3. Format hasil
            return {
                table_name: [
                    {
                        "column": r["column_name"],
                        "type": r["data_type"],
                        "nullable": r["is_nullable"],
                        "max_length": r["character_maximum_length"],
                    }
                    for r in rows
                ]
            }


    # ----------------------------------------
    # Handler khusus CSV (nanti bisa isi)
    # ----------------------------------------
    async def _get_csv_schema(self, dataset_id: str) -> Dict[str, Any]:
        """Ambil schema untuk CSV (belum diimplementasi)"""
        logger.warning("CSV schema fetch not implemented yet")
        return {}


    # ----------------------------------------
    # Handler default untuk schema public
    # ----------------------------------------
    async def _get_public_schema(self) -> Dict[str, Any]:
        """Ambil schema default dari public"""
        async with get_raw_connection() as conn:
            query = """
            SELECT 
                t.table_name,
                array_agg(
                    json_build_object('column', c.column_name)
                    ORDER BY c.ordinal_position
                ) AS columns
            FROM information_schema.tables t
            JOIN information_schema.columns c
            ON t.table_name = c.table_name
            AND t.table_schema = c.table_schema
            WHERE t.table_schema = 'public'
            AND t.table_type = 'BASE TABLE'
            GROUP BY t.table_name
            ORDER BY t.table_name
            """
            rows = await conn.fetch(query)

            schema = {}
            for row in rows:
                schema[row["table_name"]] = row["columns"]
            return schema

    

    def validate_query(self, sql: str) -> tuple[bool, Optional[str]]:
        """Validate SQL query for safety"""
        sql = sql.strip()
        if sql.endswith(";"):
            sql = sql[:-1]

        sql_upper = sql.upper()
        
        # Check for dangerous patterns
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, sql_upper):
                return False, f"Query contains forbidden pattern: {pattern}"
        
        # Must be SELECT query
        if not sql_upper.strip().startswith('SELECT'):
            return False, "Only SELECT queries are allowed"
        
        # Check for LIMIT
        if 'LIMIT' not in sql_upper:
            sql += ' LIMIT 100'
            
        return True, sql

    
    async def execute_query(
        self, 
        sql: str,
        timeout: Optional[float] = None
    ) -> tuple[List[Dict[str, Any]], SQLQuery]:
        """Execute SQL query with safety checks"""
        
        # Validate query
        is_valid, validated_sql = self.validate_query(sql)
        if not is_valid:
            raise SQLValidationError(validated_sql)
        
        timeout = timeout or self.max_execution_time
        start_time = datetime.now()
        
        try:
            async with get_raw_connection() as conn:
                # Set statement timeout
                await conn.execute(f"SET statement_timeout = {int(timeout * 1000)}")
                
                # Execute query
                rows = await asyncio.wait_for(
                    conn.fetch(validated_sql),
                    timeout=timeout
                )
                
                # Convert to list of dicts
                results = [dict(row) for row in rows]
                
                execution_time = (datetime.now() - start_time).total_seconds() * 1000
                
                sql_info = SQLQuery(
                    query=validated_sql,
                    is_safe=True,
                    estimated_rows=len(results),
                    execution_time_ms=execution_time
                )
                
                return results, sql_info
                
        except asyncio.TimeoutError:
            raise SQLExecutionError(f"Query exceeded timeout of {timeout} seconds")
        except asyncpg.PostgresError as e:
            logger.error(f"PostgreSQL error: {str(e)}")
            raise SQLExecutionError(f"Database error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise SQLExecutionError(f"Query execution failed: {str(e)}")
    
    async def explain_query(self, sql: str) -> Dict[str, Any]:
        """Get query execution plan"""
        is_valid, validated_sql = self.validate_query(sql)
        if not is_valid:
            raise SQLValidationError(validated_sql)
        
        explain_sql = f"EXPLAIN (FORMAT JSON, ANALYZE FALSE) {validated_sql}"
        
        async with get_raw_connection() as conn:
            result = await conn.fetchrow(explain_sql)
            
        return result[0] if result else {}