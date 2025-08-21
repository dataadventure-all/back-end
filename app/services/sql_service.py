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
        
    async def get_schema_info(self) -> Dict[str, Any]:
        """Get database schema information"""
        query = """
        SELECT 
            t.table_name,
            array_agg(
                json_build_object(
                    'column', c.column_name,
                    'type', c.data_type,
                    'nullable', c.is_nullable::boolean
                ) ORDER BY c.ordinal_position
            ) as columns
        FROM information_schema.tables t
        JOIN information_schema.columns c 
            ON t.table_name = c.table_name 
            AND t.table_schema = c.table_schema
        WHERE t.table_schema = 'public' 
            AND t.table_type = 'BASE TABLE'
        GROUP BY t.table_name
        ORDER BY t.table_name;
        """
        
        async with get_raw_connection() as conn:
            rows = await conn.fetch(query)
            
        schema = {}
        for row in rows:
            schema[row['table_name']] = row['columns']
            
        return schema
    
    def validate_query(self, sql: str) -> tuple[bool, Optional[str]]:
        """Validate SQL query for safety"""
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