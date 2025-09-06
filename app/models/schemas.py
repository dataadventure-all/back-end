from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from .enums import QueryMode, OutputFormat, QueryStatus

# Request Models
class QueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)
    output_format: OutputFormat = OutputFormat.TABLE
    mode: QueryMode = QueryMode.AUTO
    context: Optional[Dict[str, Any]] = None
    use_cache: bool = True
    
    # Chart-specific parameters (optional)
    preferred_chart_type: Optional[Literal["line", "bar", "area", "pie", "scatter", "histogram", "heatmap"]] = None
    chart_width: Optional[int] = Field(None, ge=200, le=2000)
    chart_height: Optional[int] = Field(None, ge=200, le=1500)
    color_scheme: Optional[Literal["blue", "green", "purple", "red", "orange", "teal", "pink"]] = None
    
    @validator('prompt')
    def validate_prompt(cls, v):
        if not v.strip():
            raise ValueError("Prompt cannot be empty")
        return v.strip()
    
    @validator('preferred_chart_type')
    def validate_chart_type_with_format(cls, v, values):
        """Only allow chart_type if output_format is chart"""
        if v and values.get('output_format') != OutputFormat.CHART:
            raise ValueError("preferred_chart_type can only be specified when output_format is 'chart'")
        return v

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

class QueryResponse(BaseModel):
    success: bool
    query_id: str
    status: QueryStatus
    sql_query: Optional[SQLQuery] = None
    data: Optional[List[Dict[str, Any]]] = None
    chart_config: Optional[ChartConfig] = None
    data_summary: Optional[DataSummary] = None  # New field
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    execution_time: float
    token_usage: Optional[Dict[str, int]] = None
    
    # Chart generation specific metadata
    chart_generation_time: Optional[float] = None
    chart_fallback_used: bool = False
    
    @validator('data_summary', always=True)
    def generate_data_summary(cls, v, values):
        """Auto-generate data summary if data is present"""
        data = values.get('data')
        if data and not v:
            return cls._create_data_summary(data)
        return v
    
    @classmethod
    def _create_data_summary(cls, data: List[Dict[str, Any]]) -> DataSummary:
        """Create data summary from the actual data"""
        if not data:
            return DataSummary(total_rows=0, total_columns=0)
        
        sample_row = data[0]
        columns = list(sample_row.keys())
        
        numeric_columns = []
        categorical_columns = []
        date_columns = []
        has_nulls = False
        
        for col in columns:
            # Check sample values to classify column types
            sample_values = [row.get(col) for row in data[:10] if row.get(col) is not None]
            
            if not sample_values:
                has_nulls = True
                continue
                
            # Check if numeric
            if all(isinstance(val, (int, float)) for val in sample_values):
                numeric_columns.append(col)
            # Check if date-like
            elif all(isinstance(val, str) and cls._is_date_string(val) for val in sample_values):
                date_columns.append(col)
            else:
                categorical_columns.append(col)
        
        # Check for nulls
        for row in data:
            if any(val is None for val in row.values()):
                has_nulls = True
                break
        
        return DataSummary(
            total_rows=len(data),
            total_columns=len(columns),
            numeric_columns=numeric_columns,
            categorical_columns=categorical_columns,
            date_columns=date_columns,
            has_nulls=has_nulls,
            sample_values={col: sample_row[col] for col in columns[:5]}  # First 5 columns
        )
    
    @staticmethod
    def _is_date_string(val: str) -> bool:
        """Check if string looks like a date"""
        try:
            from datetime import datetime
            datetime.fromisoformat(val.replace('Z', '+00:00'))
            return True
        except:
            # Try other common date formats
            import re
            date_patterns = [
                r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
                r'\d{2}/\d{2}/\d{4}',  # MM/DD/YYYY
                r'\d{2}-\d{2}-\d{4}',  # MM-DD-YYYY
            ]
            return any(re.match(pattern, val) for pattern in date_patterns)

class HealthResponse(BaseModel):
    status: str
    version: str
    database: bool
    llm: bool
    cache: bool
    timestamp: datetime

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