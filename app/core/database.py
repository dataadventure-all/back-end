import time
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from contextlib import asynccontextmanager
import asyncpg
from typing import AsyncGenerator, List
from .config import get_settings
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional
import asyncio  

settings = get_settings()

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
    echo=settings.DEBUG,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()

# Dependency for FastAPI
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# Direct connection for raw SQL
@asynccontextmanager
async def get_raw_connection():
    conn = await asyncpg.connect(settings.DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()

dynamic_connections: Dict[str, Dict[str, Any]] = {}

async def test_database_connection(connection_string: str) -> Dict[str, Any]:
    """
    Test database connection and retrieve basic schema information
    
    Args:
        connection_string: SQLAlchemy connection string
        
    Returns:
        Dictionary with connection test results
    """
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    
    def _test_connection():
        result = {
            "success": False,
            "error": None,
            "schema": {},
            "query_time": 0
        }
        
        try:
            # Create engine
            engine = create_engine(connection_string, pool_pre_ping=True)
            
            # Test connection with simple query
            start_time = time.time()
            with engine.connect() as conn:
                # Test query based on database type
                if "sqlite" in connection_string:
                    test_query = "SELECT 1"
                elif "postgresql" in connection_string:
                    test_query = "SELECT 1"
                elif "mysql" in connection_string:
                    test_query = "SELECT 1"
                elif "mssql" in connection_string:
                    test_query = "SELECT 1"
                elif "oracle" in connection_string:
                    test_query = "SELECT 1 FROM DUAL"
                else:
                    test_query = "SELECT 1"
                
                conn.execute(text(test_query))
                query_time = time.time() - start_time
                
                # Get schema information
                inspector = inspect(engine)
                tables = inspector.get_table_names()
                
                # Get basic schema info
                schema_info = {
                    "tables": tables,
                    "table_count": len(tables),
                    "table_details": {}
                }
                
                # Get column info for first 5 tables (to avoid timeout)
                for table in tables[:5]:
                    columns = inspector.get_columns(table)
                    schema_info["table_details"][table] = {
                        "columns": [col["name"] for col in columns],
                        "column_count": len(columns)
                    }
                
                result["success"] = True
                result["schema"] = schema_info
                result["query_time"] = query_time
                
            engine.dispose()
            
        except SQLAlchemyError as e:
            result["error"] = str(e)
        except Exception as e:
            result["error"] = f"Unexpected error: {str(e)}"
        
        return result
    
    # Run in thread pool to avoid blocking
    result = await loop.run_in_executor(executor, _test_connection)
    return result

async def add_dynamic_connection(
    connection_id: str,
    connection_name: str,
    connection_string: str,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Add a dynamic database connection to the connection pool
    
    Args:
        connection_id: Unique identifier for the connection
        connection_name: Friendly name for the connection
        connection_string: SQLAlchemy connection string
        metadata: Additional metadata about the connection
        
    Returns:
        True if connection added successfully
    """
    try:
        # Create engine for the connection
        engine = create_engine(
            connection_string,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600  # Recycle connections after 1 hour
        )
        
        # Store connection details
        dynamic_connections[connection_id] = {
            "id": connection_id,
            "name": connection_name,
            "engine": engine,
            "connection_string": connection_string,
            "metadata": metadata or {},
            "created_at": time.time()
        }
        
        return True
        
    except Exception as e:
        raise Exception(f"Failed to add dynamic connection: {str(e)}")

async def get_dynamic_connection(connection_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a dynamic database connection by ID
    
    Args:
        connection_id: Connection identifier
        
    Returns:
        Connection details or None if not found
    """
    return dynamic_connections.get(connection_id)

async def remove_dynamic_connection(connection_id: str) -> bool:
    """
    Remove a dynamic database connection
    
    Args:
        connection_id: Connection identifier
        
    Returns:
        True if removed successfully
    """
    if connection_id in dynamic_connections:
        try:
            # Dispose of the engine to close all connections
            engine = dynamic_connections[connection_id].get("engine")
            if engine:
                engine.dispose()
            
            del dynamic_connections[connection_id]
            return True
        except Exception:
            pass
    
    return False

async def list_dynamic_connections() -> List[Dict[str, Any]]:
    """
    List all dynamic database connections
    
    Returns:
        List of connection metadata (without engine objects)
    """
    connections = []
    for conn_id, conn_data in dynamic_connections.items():
        connections.append({
            "id": conn_data["id"],
            "name": conn_data["name"],
            "metadata": conn_data["metadata"],
            "created_at": conn_data["created_at"]
        })
    
    return connections

async def execute_query_on_connection(
    connection_id: str,
    query: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute a query on a specific dynamic connection
    
    Args:
        connection_id: Connection identifier
        query: SQL query to execute
        params: Query parameters
        
    Returns:
        Query results
    """
    connection = await get_dynamic_connection(connection_id)
    if not connection:
        raise ValueError(f"Connection {connection_id} not found")
    
    engine = connection["engine"]
    
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    
    def _execute_query():
        try:
            with engine.connect() as conn:
                result = conn.execute(text(query), params or {})
                
                # Handle different result types
                if result.returns_rows:
                    rows = result.fetchall()
                    columns = list(result.keys())
                    
                    # Convert to list of dicts
                    data = [dict(zip(columns, row)) for row in rows]
                    
                    return {
                        "success": True,
                        "data": data,
                        "columns": columns,
                        "row_count": len(data)
                    }
                else:
                    return {
                        "success": True,
                        "rows_affected": result.rowcount,
                        "message": "Query executed successfully"
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    result = await loop.run_in_executor(executor, _execute_query)
    return result