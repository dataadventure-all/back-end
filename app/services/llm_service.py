from typing import Dict, Any, Optional, List
from langchain_groq import ChatGroq
# from langchain_openai import ChatOpenAI
from langchain.chat_models import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.schema import BaseMessage, HumanMessage, SystemMessage
import tiktoken
from ..core.config import get_settings
from ..models.schemas import TokenUsage
from ..models.enums import LLMProvider
from ..utils.logger import get_logger
import json

logger = get_logger(__name__)
settings = get_settings()

class LLMService:
    """Unified LLM service for multiple providers"""
    
    def __init__(self, provider: Optional[LLMProvider] = None):
        self.provider = provider or LLMProvider(settings.LLM_PROVIDER)
        self.llm = self._initialize_llm()
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        
    def _initialize_llm(self):
        """Initialize LLM based on provider"""
        if self.provider == LLMProvider.GROQ:
            return ChatGroq(
                groq_api_key=settings.GROQ_API_KEY,
                model_name="mixtral-8x7b-32768",
                temperature=0,
                max_tokens=settings.MAX_RESPONSE_TOKENS
            )
        elif self.provider == LLMProvider.OPENAI:
            return ChatOpenAI(
                openai_api_key=settings.OPENAI_API_KEY,
                model="gpt-4-turbo-preview",
                temperature=0,
                max_tokens=settings.MAX_RESPONSE_TOKENS
            )
        elif self.provider == LLMProvider.DEEPSEEK:
            return ChatOpenAI(
                openai_api_key=settings.DEEPSEEK_API_KEY,
                model="deepseek/deepseek-r1-0528-qwen3-8b:free",
                temperature=0,
                max_tokens=settings.MAX_RESPONSE_TOKENS
            )
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text"""
        return len(self.tokenizer.encode(text))
    
    async def generate_sql_query(
        self, 
        prompt: str, 
        schema_context: Dict[str, Any],
        examples: Optional[List[Dict]] = None
    ) -> tuple[str, TokenUsage]:
        """Generate SQL query from natural language"""
        
        # Build context
        system_prompt = self._build_sql_system_prompt(schema_context, examples)
        
        # Count tokens
        prompt_tokens = self.count_tokens(system_prompt + prompt)
        
        # Check if we need advanced mode
        if prompt_tokens > settings.MAX_PROMPT_TOKENS:
            logger.warning(f"Prompt tokens ({prompt_tokens}) exceed limit")
            # In future, trigger graph/vector mode here
            
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt)
        ]
        
        try:
            response = await self.llm.ainvoke(messages)
            sql_query = self._extract_sql_from_response(response.content)
            
            completion_tokens = self.count_tokens(response.content)
            
            token_usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                estimated_cost=self._calculate_cost(prompt_tokens, completion_tokens)
            )
            
            return sql_query, token_usage
            
        except Exception as e:
            logger.error(f"LLM query generation failed: {str(e)}")
            raise
    
    async def generate_chart_config(
        self,
        data: List[Dict],
        user_prompt: str
    ) -> Dict[str, Any]:
        """Generate chart configuration from data"""
        
        # Sample data for context (limit to reduce tokens)
        sample_data = data[:5] if len(data) > 5 else data
        
        prompt = f"""
        Given this data sample:
        {json.dumps(sample_data, indent=2)}
        
        User request: {user_prompt}
        
        Generate a chart configuration with:
        - chart_type: "line", "bar", "area", "pie", or "scatter"
        - x_axis: field name for x-axis
        - y_axis: field name for y-axis
        - title: descriptive title
        
        Return as JSON only.
        """
        
        messages = [HumanMessage(content=prompt)]
        response = await self.llm.ainvoke(messages)
        
        try:
            config = json.loads(response.content)
            return config
        except json.JSONDecodeError:
            # Fallback config
            return {
                "chart_type": "bar",
                "x_axis": list(data[0].keys())[0],
                "y_axis": list(data[0].keys())[1] if len(data[0].keys()) > 1 else list(data[0].keys())[0],
                "title": "Data Visualization"
            }
    
    def _build_sql_system_prompt(
        self, 
        schema: Dict[str, Any],
        examples: Optional[List[Dict]] = None
    ) -> str:
        """Build system prompt for SQL generation"""
        
        prompt = f"""You are a PostgreSQL expert. Generate SQL queries based on natural language.
        
        Database Schema:
        {json.dumps(schema, indent=2)}
        
        Rules:
        1. Use only existing tables and columns
        2. Always add LIMIT 100 to prevent large results
        3. Use proper JOIN conditions
        4. Prefer explicit column names over SELECT *
        5. Add appropriate WHERE clauses for filtering
        6. Use aggregation functions when needed
        """
        
        if examples:
            prompt += "\n\nExamples:\n"
            for ex in examples:
                prompt += f"Q: {ex['question']}\nSQL: {ex['sql']}\n\n"
        
        prompt += "\nReturn ONLY the SQL query, no explanations."
        
        return prompt
    
    def _extract_sql_from_response(self, response: str) -> str:
        """Extract SQL query from LLM response"""
        # Remove markdown code blocks if present
        response = response.strip()
        if response.startswith("```sql"):
            response = response[6:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        
        return response.strip()
    
    def _calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate estimated cost based on provider"""
        # Groq is free, OpenAI has pricing
        if self.provider == LLMProvider.GROQ:
            return 0.0
        elif self.provider == LLMProvider.OPENAI:
            # GPT-4 Turbo pricing (example)
            prompt_cost = (prompt_tokens / 1000) * 0.01
            completion_cost = (completion_tokens / 1000) * 0.03
            return prompt_cost + completion_cost
        return 0.0