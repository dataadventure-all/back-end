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