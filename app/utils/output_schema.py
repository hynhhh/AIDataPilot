from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from langchain_core.language_models import BaseChatModel
from typing import Type, TypeVar
T = TypeVar("T", bound=BaseModel)
def generate_structured_data(
    llm: BaseChatModel, 
    prompt: str, 
    response_schema: Type[T]  # 
) -> T:
    """
    通用结构化输出函数，根据传入的 response_schema 动态决定返回格式
    """
    # 动态绑定传入的 Schema
    structured_llm = llm.with_structured_output(response_schema, method="json_mode")
    
    # 运行并直接返回对应类型的实例
    return structured_llm.invoke(prompt)
# ==========================================
# 1. 意图分析 Schema (Intent)
# ==========================================
class IntentResponse(BaseModel):
    intent: Literal[
        "data_query", 
        "aggregation", 
        "user_behavior", 
        "schema_query", 
        "complex_analysis",
        "none_query",
    ] = Field(..., description="核心查询意图分类，none_query 表示非数据/非数据库问题")
    description: str = Field(..., description="对运营意图的简要分析说明")

# ==========================================
# 2. 表检索 Schema (Table Retriever)
# ==========================================
class TableScore(BaseModel):
    table_name: str = Field(..., description="选中的表名")
    similarity: float = Field(..., description="相关性打分 (0.0 到 1.0之间)")
    description: str = Field(..., description="选择该表的原因及包含的关键数据")
    relevant_columns: List[str] = Field(default_factory=list, description="该表中建议用于回答问题的相关列名（可空）")

class TableRetrieverResponse(BaseModel):
    # 注意：如果问的是元数据（如有哪些表），这里允许返回空列表
    relevant_tables: List[TableScore] = Field(default_factory=list, description="相关表列表")

# ==========================================
# 3. 列检索 Schema (Column Retriever)
# ==========================================
class ColumnRetrieverResponse(BaseModel):
    relevant_columns: List[str] = Field(default_factory=list, description="必须用到的列名列表，剔除冗余字段")

# ==========================================
# 4. 示例检索 Schema (Example Retriever)
# ==========================================
class ExampleScore(BaseModel):
    example_id: int = Field(..., description="示例 ID")
    question: str = Field(..., description="历史问题原文")
    sql: str = Field(..., description="对应 SQL 语句")
    tables: List[str] = Field(default_factory=list, description="涉及的表名列表")
    similarity: float = Field(..., description="与当前问题的相似度 (0.0 到 1.0之间)")
    reason: str = Field(..., description="选择该示例的业务参考价值说明")

class ExampleRetrieverResponse(BaseModel):
    relevant_examples: List[ExampleScore] = Field(default_factory=list, description="最相关的优质 SQL 示例")

# ==========================================
# 5. 查询构建/思考 Schema (CoT Planning)
# ==========================================
class QueryPlanResponse(BaseModel):
    thought_process: str = Field(..., description="详细的多步分析过程和 SQL 规划思考")
    primary_table: str = Field(..., description="查询所围绕的主表名称")
    requires_join: bool = Field(..., description="是否需要跨表 JOIN")

# ==========================================
# 6. SQL 生成 Schema (SQL Generator) - 最核心！
# ==========================================
class SQLGeneratorResponse(BaseModel):
    sql: str = Field(..., description="最终生成的纯 SQLite3 SQL 语句，绝对禁止 Markdown 包裹")

# ==========================================
# 7. 图表生成 Schema (Chart Generator)
# ==========================================
class ChartConfig(BaseModel):
    x_axis: Optional[str] = Field(None, description="用作 X 轴（分类/时间）的字段名，无则填 null")
    y_axis: Optional[str] = Field(None, description="用作 Y 轴（数值）的字段名，无则填 null")

class ChartGeneratorResponse(BaseModel):
    chart_type: Literal["table", "bar", "line", "pie", "metric"] = Field(
        ..., 
        description="选择的最优图表类型"
    )
    reason: str = Field(..., description="选择该图表类型的业务合理性解释")
    config: ChartConfig = Field(..., description="图表的 X/Y 轴字段配置")
