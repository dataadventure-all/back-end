from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from .enums import QueryMode, OutputFormat, QueryStatus

# Request Models
class QueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)
    mode: QueryMode = QueryMode.AUTO
    use_cache: bool = True
    
    @validator('prompt')
    def validate_prompt(cls, v):
        if not v.strip():
            raise ValueError("Prompt cannot be empty")
        return v.strip()

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
    prompt: str
    mode: str
    query_id: str
    query: Optional[str] = None
    success: bool = False
    error: Optional[str] = None

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