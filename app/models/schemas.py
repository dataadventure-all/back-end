from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from .enums import QueryMode, OutputFormat, QueryStatus, Tools
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean
from sqlalchemy.sql import func
from ..core.database import Base
from sqlalchemy.dialects.postgresql import UUID
import uuid

# Request Models
from pydantic import BaseModel, Field, field_validator

class QueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)
    mode: QueryMode = QueryMode.AUTO
    use_cache: bool = True
    querytype: str = Field(default="excel")

    @field_validator('prompt')
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Prompt cannot be empty")
        return v.strip()

class ExcelQueryRequest(QueryRequest):
    dataset_id: str

class AdvancedQueryRequest(QueryRequest):
    """For future graph/vector implementation"""
    use_vector_search: bool = False
    use_graph_analysis: bool = False
    similarity_threshold: float = 0.7
    max_graph_depth: int = 3

# Response Models
class SQLQuery(BaseModel):
    query: str
    is_safe: bool
    estimated_rows: Optional[int]
    execution_time_ms: Optional[float]

class ChartConfig(BaseModel):
    chart_type: Literal["line", "bar", "area", "pie", "scatter", "histogram", "heatmap"]
    x_axis: str = Field(..., description="Column name for x-axis")
    y_axis: str = Field(..., description="Column name for y-axis")
    title: str
    
    # Styling options
    colors: List[str] = ["#8884d8", "#82ca9d", "#ffc658", "#ff7300", "#00ff00", "#ff00ff", "#00ffff"]
    color_scheme: Optional[str] = "blue"
    width: int = Field(default=800, ge=200, le=2000)
    height: int = Field(default=400, ge=200, le=1500)
    
    # Chart-specific configurations
    show_legend: bool = True
    show_grid: bool = True
    show_tooltip: bool = True
    animate: bool = True
    
    # Data processing options
    aggregate_function: Optional[Literal["sum", "avg", "count", "max", "min"]] = None
    group_by: Optional[str] = None  # Column to group by
    sort_by: Optional[str] = None   # Column to sort by
    sort_order: Optional[Literal["asc", "desc"]] = "asc"
    
    # Chart type specific options
    additional_config: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    @validator('colors')
    def validate_colors(cls, v):
        """Ensure at least one color is provided"""
        if not v:
            return ["#8884d8", "#82ca9d", "#ffc658"]
        return v
    
    @validator('additional_config')
    def set_chart_specific_defaults(cls, v, values):
        """Set defaults based on chart type"""
        chart_type = values.get('chart_type')
        if not v:
            v = {}
            
        if chart_type == 'pie':
            v.setdefault('show_labels', True)
            v.setdefault('label_threshold', 0.05)  # Hide labels < 5%
        elif chart_type == 'line':
            v.setdefault('smooth_curve', True)
            v.setdefault('show_dots', True)
            v.setdefault('line_width', 2)
        elif chart_type == 'bar':
            v.setdefault('bar_width', 0.8)
            v.setdefault('show_values', False)
        elif chart_type == 'scatter':
            v.setdefault('dot_size', 6)
            v.setdefault('show_regression_line', False)
        elif chart_type == 'area':
            v.setdefault('fill_opacity', 0.6)
            v.setdefault('stack_areas', False)
        elif chart_type == 'histogram':
            v.setdefault('bin_count', 20)
            v.setdefault('show_density', False)
        elif chart_type == 'heatmap':
            v.setdefault('color_scale', 'viridis')
            v.setdefault('show_values', True)
            
        return v

class DataSummary(BaseModel):
    """Summary statistics for the returned data"""
    total_rows: int
    total_columns: int
    numeric_columns: List[str] = Field(default_factory=list)
    categorical_columns: List[str] = Field(default_factory=list)
    date_columns: List[str] = Field(default_factory=list)
    has_nulls: bool = False
    sample_values: Optional[Dict[str, Any]] = None

# Token tracking
class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    
    @property
    def requires_advanced_mode(self) -> bool:
        from ..core.config import get_settings
        settings = get_settings()
        return self.total_tokens > settings.USE_ADVANCED_MODE_THRESHOLD

class QueryResponse(BaseModel):
    prompt: str
    mode: str
    query_id: str
    query: Optional[str] = None
    success: bool = False
    error: Optional[str] = None
    token_usage: Optional[TokenUsage] = None

class HealthResponse(BaseModel):
    status: str
    version: str
    database: bool
    llm: bool
    cache: bool
    timestamp: datetime

class ToolsResponse(BaseModel):
    status: str
    error: str  
    tools: str
    success: bool = False

class ChartGenerationRequest(BaseModel):
    """Direct chart generation without SQL query"""
    data: List[Dict[str, Any]]
    user_prompt: str
    preferred_chart_type: Optional[Literal["line", "bar", "area", "pie", "scatter", "histogram", "heatmap"]] = None
    title: Optional[str] = None
    color_scheme: Optional[str] = "blue"
    width: int = Field(default=800, ge=200, le=2000)
    height: int = Field(default=400, ge=200, le=1500)

class ChartGenerationResponse(BaseModel):
    """Response for direct chart generation"""
    success: bool
    chart_config: Optional[ChartConfig] = None
    data_summary: DataSummary
    error: Optional[str] = None
    generation_time: float
    fallback_used: bool = False


class FileUploadResponse(BaseModel):
    """Response for file upload operations"""
    success: bool
    dataset_id: str
    dataset_name: str
    message: str
    file_info: Dict[str, Any]
    
    class Config:
        orm_mode = True
        json_schema_extra = {
            "example": {
                "success": True,
                "dataset_id": "123e4567-e89b-12d3-a456-426614174000",
                "dataset_name": "sales_data_2024",
                "message": "CSV file uploaded successfully",
                "file_info": {
                    "filename": "sales.csv",
                    "rows": 1000,
                    "columns": 10,
                    "column_names": ["date", "product", "quantity", "price"],
                    "size_bytes": 102400
                }
            }
        }

# Database Connection Models
class DatabaseCredentials(BaseModel):
    """Database connection credentials"""
    db_type: Literal["postgresql", "mysql", "sqlite", "sqlserver", "oracle"] = Field(
        ..., 
        description="Type of database"
    )
    host: Optional[str] = Field(None, description="Database host (not needed for SQLite)")
    port: Optional[int] = Field(None, description="Database port")
    username: Optional[str] = Field(None, description="Database username")
    password: Optional[str] = Field(None, description="Database password")
    database: str = Field(..., description="Database name or path (for SQLite)")
    name: Optional[str] = Field(None, description="Friendly name for this connection")
    description: Optional[str] = Field(None, description="Description of the database")
    
    @validator('port')
    def set_default_port(cls, v, values):
        """Set default port based on database type if not provided"""
        if v is None and 'db_type' in values:
            default_ports = {
                'postgresql': 5432,
                'mysql': 3306,
                'sqlserver': 1433,
                'oracle': 1521
            }
            return default_ports.get(values['db_type'].lower())
        return v
    
    @validator('host')
    def validate_host(cls, v, values):
        """Validate host is provided for non-SQLite databases"""
        if 'db_type' in values and values['db_type'].lower() != 'sqlite':
            if not v:
                raise ValueError(f"Host is required for {values['db_type']} database")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "db_type": "postgresql",
                "host": "localhost",
                "port": 5432,
                "username": "user",
                "password": "password",
                "database": "mydb",
                "name": "Production DB",
                "description": "Main production database"
            }
        }

class DatabaseTestResponse(BaseModel):
    """Response for database connection test"""
    success: bool
    connection_id: str
    connection_name: str
    message: str
    connection_info: Dict[str, Any]
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "connection_id": "123e4567-e89b-12d3-a456-426614174000",
                "connection_name": "production_db",
                "message": "Database connection successful",
                "connection_info": {
                    "db_type": "postgresql",
                    "host": "localhost",
                    "port": 5432,
                    "database": "mydb",
                    "tables_count": 25,
                    "tables": ["users", "orders", "products"],
                    "test_query_time": 0.025
                }
            }
        }

# Dataset Models for managing uploaded files
class DatasetInfo(BaseModel):
    """Information about an uploaded dataset"""
    id: str
    name: str
    type: Literal["csv", "excel", "database"]
    filename: Optional[str]
    rows: int
    columns: int
    column_names: List[str]
    upload_time: datetime
    description: Optional[str]
    
class DatasetListResponse(BaseModel):
    """Response for listing datasets"""
    success: bool
    count: int
    datasets: List[DatasetInfo]

# Query Models with Dataset Support
class QueryRequestWithDataset(QueryRequest):
    """Query request that can reference uploaded datasets"""
    dataset_id: Optional[str] = Field(None, description="ID of uploaded dataset to query")
    connection_id: Optional[str] = Field(None, description="ID of database connection to use")
    
    @validator('dataset_id')
    def validate_dataset_or_connection(cls, v, values):
        """Ensure either dataset_id or connection_id is provided, not both"""
        if v and values.get('connection_id'):
            raise ValueError("Cannot specify both dataset_id and connection_id")
        return v
    

class SchemeExcel(Base):
    __tablename__ = "schema_excel"
    __table_args__ = {"schema": "public"}
    
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    dataset_name = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    sheet_name = Column(String, nullable=False)
    description = Column(Text)
    
    # Metadata
    rows_count = Column(Integer, nullable=False)
    columns_count = Column(Integer, nullable=False)
    column_names = Column(JSON, nullable=False)  # List of column names
    column_types = Column(JSON, nullable=False)  # Dict of column types
    available_sheets = Column(JSON, nullable=False)  # List of available sheets
    
    # File info
    file_size_bytes = Column(Integer, nullable=False)
    
    # Data storage - in production, consider storing in separate table or file storage
    sample_data = Column(JSON)  # First 5 rows for preview
    full_data = Column(JSON)    # All data - consider using JSONB in PostgreSQL
    
    # Status
    is_active = Column(Boolean, default=True)
    processed = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())