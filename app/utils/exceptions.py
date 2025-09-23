class BaseError(Exception):
    """Base exception class"""
    pass

class SQLValidationError(BaseError):
    """SQL validation failed"""
    pass

class SQLExecutionError(BaseError):
    """SQL execution failed"""
    pass

class LLMError(BaseError):
    """LLM service error"""
    pass

class TokenLimitError(BaseError):
    """Token limit exceeded"""
    pass

# Tambahkan exceptions ini ke exceptions.py yang sudah ada

class BaseAPIException(Exception):
    """Base exception for API"""
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class InvalidFileFormatError(BaseAPIException):
    """Raised when uploaded file format is invalid"""
    def __init__(self, message: str = "Invalid file format"):
        super().__init__(message, status_code=400)

class FileSizeExceededError(BaseAPIException):
    """Raised when uploaded file size exceeds limit"""
    def __init__(self, message: str = "File size exceeds maximum allowed"):
        super().__init__(message, status_code=413)

class DatabaseConnectionError(BaseAPIException):
    """Raised when database connection fails"""
    def __init__(self, message: str = "Database connection failed"):
        super().__init__(message, status_code=500)

class DatasetNotFoundError(BaseAPIException):
    """Raised when dataset is not found"""
    def __init__(self, dataset_id: str):
        super().__init__(f"Dataset {dataset_id} not found", status_code=404)

class ConnectionNotFoundError(BaseAPIException):
    """Raised when database connection is not found"""
    def __init__(self, connection_id: str):
        super().__init__(f"Connection {connection_id} not found", status_code=404)

class QueryExecutionError(BaseAPIException):
    """Raised when query execution fails"""
    def __init__(self, message: str = "Query execution failed"):
        super().__init__(message, status_code=500)

class SchemaParsingError(BaseAPIException):
    """Raised when schema parsing fails"""
    def __init__(self, message: str = "Failed to parse schema"):
        super().__init__(message, status_code=500)

class UnsupportedDatabaseError(BaseAPIException):
    """Raised when database type is not supported"""
    def __init__(self, db_type: str):
        super().__init__(f"Database type '{db_type}' is not supported", status_code=400)