from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from .enums import QueryMode, OutputFormat, QueryStatus

# Request Models
class QueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)
    output_format: OutputFormat = OutputFormat.CHART
    mode: QueryMode = QueryMode.AUTO
    context: Optional[Dict[str, Any]] = None
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
    chart_type: str  # line, bar, pie, scatter, area
    x_axis: str
    y_axis: str
    title: str
    colors: List[str] = ["#8884d8", "#82ca9d", "#ffc658"]
    additional_config: Optional[Dict[str, Any]] = None

class QueryResponse(BaseModel):
    success: bool
    query_id: str
    status: QueryStatus
    sql_query: Optional[SQLQuery] = None
    data: Optional[List[Dict[str, Any]]] = None
    chart_config: Optional[ChartConfig] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    execution_time: float
    token_usage: Optional[Dict[str, int]] = None

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