"""
@File: sql_syntax_patcher.py
@Desc: 专精修补跨层JOIN的时间对齐问题
@Author: h
@Date: 9.9.2026
"""
import logging
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage

from core.llm import get_model
from graph.state import Chat2DataState
from utils.output_schema import generate_structured_data, SQLGeneratorResponse

logger = logging.getLogger(__name__)


async def sql_syntax_patcher(state: Chat2DataState) -> Chat2DataState:
    """
    SQL 语法修补节点 - 专门处理跨层JOIN时间对齐问题
    
    职责：
    1. 接收带有跨层JOIN错误的SQL
    2. 只在ON条件中增加时间对齐（a.data_dt = b.data_dt）
    3. 不改动其他部分
    
    Args:
        state: Chat2DataState 状态字典
        
    Returns:
        Chat2DataState: 更新后的状态
    """
    generated_sql = state.get("generated_sql", "")
    error_messages = state.get("error_message", [])
    
    if not generated_sql:
        logger.error("sql_syntax_patcher: 没有SQL可修补")
        return {
            **state,
            "error_message": error_messages + ["修补失败：没有SQL"],
            "retry_count": state.get("retry_count", 0) + 1
        }
    
    # 提取跨层JOIN错误信息
    cross_layer_errors = [err for err in error_messages if "跨层 JOIN" in err]
    if not cross_layer_errors:
        logger.warning("sql_syntax_patcher: 没有找到跨层JOIN错误")
        return state
    
    # 构建修补提示
    patch_prompt = f"""你是一个SQL修补专家。当前SQL存在跨层JOIN时间对齐问题。

**你的唯一任务：在ON条件中增加时间字段对齐（a.data_dt = b.data_dt），不改动其他任何部分。**

## 当前SQL
```sql
{generated_sql}
```

## 错误信息
{chr(10).join(cross_layer_errors)}

## 修补规则
1. **只修改ON条件**：在现有ON条件基础上，用AND增加时间对齐
2. **时间字段名**：data_dt（如果表中没有data_dt，则不修补，保持原样）
3. **格式示例**：
   - 原来：`JOIN dws_table b ON a.id = b.id`
   - 修补后：`JOIN dws_table b ON a.id = b.id AND a.data_dt = b.data_dt`
4. **不改动其他部分**：SELECT子句、WHERE子句、GROUP BY等保持不变
5. **保持SQL格式**：不添加注释，不重新格式化

请直接返回修补后的完整SQL，不要添加任何解释。
"""
    
    try:
        model = get_model()
        
        messages = [
            SystemMessage(content="你是SQL修补专家，专注于修复跨层JOIN的时间对齐问题。"),
            HumanMessage(content=patch_prompt)
        ]
        
        # 使用结构化输出
        patched_sql_response = generate_structured_data(
            model,
            messages,
            SQLGeneratorResponse,
        )

        patched_sql = patched_sql_response.sql.strip()
        
        if not patched_sql:
            logger.error("sql_syntax_patcher: LLM返回空SQL")
            return {
                **state,
                "error_message": error_messages + ["修补失败：LLM返回空SQL"],
                "retry_count": state.get("retry_count", 0) + 1
            }
        
        logger.info(f"sql_syntax_patcher: 修补完成")
        logger.info(f"原始SQL: {generated_sql}")
        logger.info(f"修补后: {patched_sql}")
        
        # 返回修补后的SQL，清空错误类型（让validator重新验证）
        return {
            **state,
            "generated_sql": patched_sql,
            "validation_error_type": "",  # 清空，让validator重新分类
            "error_message": [],  # 清空错误，让validator重新验证
        }
        
    except Exception as e:
        logger.error(f"sql_syntax_patcher 失败: {str(e)}")
        return {
            **state,
            "error_message": error_messages + [f"修补失败: {str(e)}"],
            "retry_count": state.get("retry_count", 0) + 1
        }

