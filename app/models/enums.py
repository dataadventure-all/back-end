from enum import Enum

class QueryMode(str, Enum):
    SIMPLE = "simple"       # Direct SQL execution
    ADVANCED = "advanced"   # With Graph/Vector
    AUTO = "auto"          # Auto-detect based on token count

class OutputFormat(str, Enum):
    TABLE = "table"
    CHART = "chart"
    JSON = "json"
    CSV = "csv"

class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    SCATTER = "scatter"
    HISTOGRAM = "histogram"
    HEATMAP = "heatmap"

class LLMProvider(str, Enum):
    GROQ = "groq"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    LOCAL = "local"
    DEEPSEEK = "deepseek"

class QueryStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"