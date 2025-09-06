from typing import Dict, Any, Optional, List
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain.chat_models import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.schema import BaseMessage, HumanMessage, SystemMessage
import tiktoken
from ..core.config import get_settings
from ..models.schemas import TokenUsage
from ..models.enums import LLMProvider
from ..utils.logger import get_logger
import json
from datetime import datetime

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
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
            model="deepseek/deepseek-r1:free",
            temperature=0,
            max_tokens=settings.MAX_RESPONSE_TOKENS,
            default_headers={
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "AI Dashboard"
            }
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
    
    # async def generate_chart_config(
    #     self,
    #     data: List[Dict],
    #     user_prompt: str
    # ) -> Dict[str, Any]:
    #     """Generate chart configuration from data"""
        
    #     # Sample data for context (limit to reduce tokens)
    #     sample_data = data[:5] if len(data) > 5 else data
        
    #     prompt = f"""
    #     Given this data sample:
    #     {json.dumps(sample_data, indent=2)}
        
    #     User request: {user_prompt}
        
    #     Generate a chart configuration with:
    #     - chart_type: "line", "bar", "area", "pie", or "scatter"
    #     - x_axis: field name for x-axis
    #     - y_axis: field name for y-axis
    #     - title: descriptive title
        
    #     Return as JSON only.
    #     """
        
    #     messages = [HumanMessage(content=prompt)]
    #     response = await self.llm.ainvoke(messages)
        
    #     try:
    #         config = json.loads(response.content)
    #         return config
    #     except json.JSONDecodeError:
    #         # Fallback config
    #         return {
    #             "chart_type": "bar",
    #             "x_axis": list(data[0].keys())[0],
    #             "y_axis": list(data[0].keys())[1] if len(data[0].keys()) > 1 else list(data[0].keys())[0],
    #             "title": "Data Visualization"
    #         }
    async def generate_chart_config(
            self,
            data: List[Dict],
            user_prompt: str,
            preferred_chart_type: Optional[str] = None,
            color_scheme: Optional[str] = None,
            width: int = 800,
            height: int = 400,
        ) -> Dict[str, Any]:
            """Generate chart configuration from data with better logic"""
            
            if not data:
                raise ValueError("No data provided for chart generation")
            
            # Sample data for context (limit to reduce tokens)
            sample_data = data[:5] if len(data) > 5 else data
            
            # Analyze data structure
            data_analysis = self._analyze_data_for_chart(data)
            
            # Build preferred chart type hint
            chart_type_hint = f"Preferred chart type: {preferred_chart_type}" if preferred_chart_type else ""
            color_hint = f"Preferred color scheme: {color_scheme}" if color_scheme else ""
            
            prompt = f"""
            Given this data sample:
            {json.dumps(sample_data, indent=2)}
            
            Data analysis:
            - Total rows: {len(data)}
            - Columns: {list(data[0].keys()) if data else []}
            - Numeric columns: {data_analysis['numeric_columns']}
            - Categorical columns: {data_analysis['categorical_columns']}
            - Date columns: {data_analysis['date_columns']}
            
            User request: {user_prompt}
            {chart_type_hint}
            {color_hint}
            
            Based on the data structure and user request, generate the BEST chart configuration:
            
            Guidelines:
            - Bar charts: Good for categorical data comparison
            - Line charts: Good for time series or continuous data trends  
            - Pie charts: Good for parts of a whole (limit to <10 categories)
            - Area charts: Good for showing cumulative totals over time
            - Scatter plots: Good for showing correlation between two numeric variables
            - Histogram: Good for showing distribution of single numeric variable
            
            Generate a chart configuration with these EXACT fields:
            - chart_type: "line", "bar", "area", "pie", "scatter", or "histogram"
            - x_axis: field name for x-axis (must exist in data)
            - y_axis: field name for y-axis (must exist in data, should be numeric for most charts)
            - title: descriptive title based on the data and request
            - colors: array of hex color codes (e.g., ["#8884d8", "#82ca9d", "#ffc658"])
            - color_scheme: "blue", "green", "purple", "red", "orange", "teal", "pink"
            - width: {width}
            - height: {height}
            - show_legend: boolean
            - show_grid: boolean
            - show_tooltip: boolean
            - animate: boolean
            - aggregate_function: "sum", "avg", "count", "max", "min" (if needed for grouping, otherwise null)
            - group_by: column name to group by (if needed, otherwise null)
            - additional_config: object with chart-specific settings
            
            Return ONLY valid JSON, no additional text or markdown.
            """
            
            messages = [HumanMessage(content=prompt)]
            response = await self.llm.ainvoke(messages)
            
            try:
                # Clean response (remove any markdown formatting)
                clean_content = response.content.strip()
                if clean_content.startswith('```json'):
                    clean_content = clean_content[7:]
                if clean_content.startswith('```'):
                    clean_content = clean_content[3:]
                if clean_content.endswith('```'):
                    clean_content = clean_content[:-3]
                
                config = json.loads(clean_content.strip())
                
                # Validate and enhance config
                config = self._validate_and_enhance_chart_config(
                    config, data, color_scheme, width, height
                )
                
                logger.info(f"Generated chart config: {config['chart_type']} chart for {len(data)} rows")
                return config
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse chart config JSON: {e}")
                logger.error(f"Raw response: {response.content[:500]}...")
                # Enhanced fallback config
                return self._create_fallback_config(data, user_prompt, color_scheme, width, height)

    def _analyze_data_for_chart(self, data: List[Dict]) -> Dict:
        """Analyze data structure to help with chart type selection"""
        if not data:
            return {"numeric_columns": [], "categorical_columns": [], "date_columns": []}
        
        sample_row = data[0]
        numeric_columns = []
        categorical_columns = []
        date_columns = []
        
        for key, value in sample_row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric_columns.append(key)
            elif isinstance(value, str):
                # Try to detect if it's a date
                if self._is_date_string(value):
                    date_columns.append(key)
                else:
                    categorical_columns.append(key)
            else:
                categorical_columns.append(key)
        
        return {
            "numeric_columns": numeric_columns,
            "categorical_columns": categorical_columns,
            "date_columns": date_columns
        }
    
    def _is_date_string(self, value: str) -> bool:
        """Check if string looks like a date"""
        try:
            # Try ISO format first
            datetime.fromisoformat(value.replace('Z', '+00:00'))
            return True
        except:
            # Try other common date formats
            import re
            date_patterns = [
                r'\d{4}-\d{2}-\d{2}',      # YYYY-MM-DD
                r'\d{2}/\d{2}/\d{4}',      # MM/DD/YYYY
                r'\d{2}-\d{2}-\d{4}',      # MM-DD-YYYY
                r'\d{4}/\d{2}/\d{2}',      # YYYY/MM/DD
                r'\w+ \d{1,2}, \d{4}',     # Month DD, YYYY
            ]
            return any(re.match(pattern, value) for pattern in date_patterns)

    def _validate_and_enhance_chart_config(
        self, 
        config: Dict, 
        data: List[Dict], 
        color_scheme: Optional[str] = None,
        width: int = 800,
        height: int = 400
    ) -> Dict:
        """Validate and enhance chart configuration"""
        if not data:
            return config
        
        available_columns = list(data[0].keys())
        data_analysis = self._analyze_data_for_chart(data)
        
        # Validate x_axis exists
        if config.get('x_axis') not in available_columns:
            config['x_axis'] = available_columns[0]
        
        # Validate y_axis exists
        if config.get('y_axis') not in available_columns:
            # Find first numeric column or use second column
            numeric_cols = data_analysis['numeric_columns']
            if numeric_cols:
                config['y_axis'] = numeric_cols[0]
            elif len(available_columns) > 1:
                config['y_axis'] = available_columns[1]
            else:
                config['y_axis'] = available_columns[0]
        
        # Validate chart_type
        valid_types = ["line", "bar", "area", "pie", "scatter", "histogram", "heatmap"]
        if config.get('chart_type') not in valid_types:
            config['chart_type'] = "bar"  # default
        
        # Set default values for required fields
        config.setdefault('width', width)
        config.setdefault('height', height)
        config.setdefault('show_legend', True)
        config.setdefault('show_grid', True)
        config.setdefault('show_tooltip', True)
        config.setdefault('animate', True)
        
        # Set color scheme
        if color_scheme:
            config['color_scheme'] = color_scheme
        config.setdefault('color_scheme', 'blue')
        
        # Set default colors based on color scheme
        color_palettes = {
            'blue': ["#8884d8", "#82ca9d", "#ffc658", "#ff7300", "#00ff00"],
            'green': ["#00C49F", "#0088FE", "#FFBB28", "#FF8042", "#8884d8"],
            'purple': ["#8B5CF6", "#A78BFA", "#C4B5FD", "#DDD6FE", "#EDE9FE"],
            'red': ["#EF4444", "#F87171", "#FCA5A5", "#FECACA", "#FEE2E2"],
            'orange': ["#F97316", "#FB923C", "#FDBA74", "#FED7AA", "#FFEDD5"],
            'teal': ["#14B8A6", "#5EEAD4", "#99F6E4", "#CCFBF1", "#F0FDFA"],
            'pink': ["#EC4899", "#F472B6", "#F9A8D4", "#FBCFE8", "#FDF2F8"]
        }
        
        config['colors'] = color_palettes.get(config.get('color_scheme', 'blue'), color_palettes['blue'])
        
        # Set chart-specific additional_config
        chart_type = config.get('chart_type')
        additional_config = config.get('additional_config', {})
        
        if chart_type == 'pie':
            additional_config.setdefault('show_labels', True)
            additional_config.setdefault('label_threshold', 0.05)
        elif chart_type == 'line':
            additional_config.setdefault('smooth_curve', True)
            additional_config.setdefault('show_dots', True)
            additional_config.setdefault('line_width', 2)
        elif chart_type == 'bar':
            additional_config.setdefault('bar_width', 0.8)
            additional_config.setdefault('show_values', False)
        elif chart_type == 'scatter':
            additional_config.setdefault('dot_size', 6)
            additional_config.setdefault('show_regression_line', False)
        elif chart_type == 'area':
            additional_config.setdefault('fill_opacity', 0.6)
            additional_config.setdefault('stack_areas', False)
        elif chart_type == 'histogram':
            additional_config.setdefault('bin_count', 20)
            additional_config.setdefault('show_density', False)
        
        config['additional_config'] = additional_config
        
        return config

    def _create_fallback_config(
        self, 
        data: List[Dict], 
        user_prompt: str,
        color_scheme: Optional[str] = None,
        width: int = 800,
        height: int = 400
    ) -> Dict:
        """Create a smart fallback configuration when LLM fails"""
        if not data:
            return {
                "chart_type": "bar", 
                "x_axis": "", 
                "y_axis": "", 
                "title": "No Data Available",
                "width": width,
                "height": height,
                "colors": ["#8884d8"],
                "color_scheme": color_scheme or "blue",
                "show_legend": True,
                "show_grid": True,
                "show_tooltip": True,
                "animate": True,
                "additional_config": {}
            }
        
        columns = list(data[0].keys())
        data_analysis = self._analyze_data_for_chart(data)
        numeric_columns = data_analysis['numeric_columns']
        categorical_columns = data_analysis['categorical_columns']
        
        # Smart defaults based on data structure
        if len(numeric_columns) >= 2:
            chart_type = "scatter"
            y_axis = numeric_columns[0]
            x_axis = numeric_columns[1]
        elif len(numeric_columns) == 1 and categorical_columns:
            chart_type = "bar"
            y_axis = numeric_columns[0]
            x_axis = categorical_columns[0]
        elif len(numeric_columns) == 1:
            chart_type = "histogram" 
            x_axis = numeric_columns[0]
            y_axis = "frequency"
        else:
            chart_type = "bar"
            x_axis = columns[0]
            y_axis = columns[1] if len(columns) > 1 else columns[0]
        
        # Generate title
        title_base = user_prompt[:50] + "..." if len(user_prompt) > 50 else user_prompt
        title = f"Chart: {title_base}" if title_base else "Data Visualization"
        
        color_palettes = {
            'blue': ["#8884d8", "#82ca9d", "#ffc658"],
            'green': ["#00C49F", "#0088FE", "#FFBB28"],
            'purple': ["#8B5CF6", "#A78BFA", "#C4B5FD"],
            'red': ["#EF4444", "#F87171", "#FCA5A5"],
            'orange': ["#F97316", "#FB923C", "#FDBA74"],
        }
        
        selected_scheme = color_scheme or "blue"
        
        return {
            "chart_type": chart_type,
            "x_axis": x_axis,
            "y_axis": y_axis,
            "title": title,
            "colors": color_palettes.get(selected_scheme, color_palettes['blue']),
            "color_scheme": selected_scheme,
            "width": width,
            "height": height,
            "show_legend": True,
            "show_grid": True,
            "show_tooltip": True,
            "animate": True,
            "aggregate_function": None,
            "group_by": None,
            "additional_config": {}
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
        1. All table and column names must be lowercase.
        2. Do not replace spaces with underscores. If the name contains spaces, keep the space.
        3. If a table or column name contains spaces, wrap it in double quotes (" ").
        Example: SELECT * FROM "tabsales invoice item";
        4. Only SELECT queries are allowed (no DML/DDL).
        5. Always add LIMIT 100 at the end unless a LIMIT is already provided.
        6. Use explicit column names instead of SELECT *.
        7. Use proper JOIN conditions when multiple tables are queried.
        8. Add appropriate WHERE clauses for filtering.
        9. Use aggregation functions when needed.
        10. If referencing a column from a table, ensure that the table is included in the FROM clause or properly joined.
        11. Always define an explicit JOIN when selecting columns from multiple tables. Do not reference a table unless it has been included in FROM or JOIN.
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