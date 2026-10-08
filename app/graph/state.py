"""
@File: state.py
@Desc: 定义状态
@Author: h
@Date: 8.13
"""
from typing import TypedDict, List, Dict, Any


class Chat2DataState(TypedDict):
    question: str                        # 用户的原始自然语言问题
    intent: str                          # 问题的意图
    relevant_tables: List[Dict[str, Any]]  # 命中的表名集合 (第一层 RAG 结果, 使用 TableScore 结构)
    relevant_columns: Dict[str, List[str]]  # 命中的表中相关列名集合
    schema_info: Dict[str, Any]          # 拼接好的表结构DDL和字段注释 (第二层 RAG 结果)
    few_shot_examples: List[Dict[str, Any]]  # 检索到的历史优质 SQL 示例 (使用 ExampleScore 结构) 
    entity_corrections: List[Dict[str, Any]]  # 实体纠错映射: [{entity_word, table_name, column_name, correct_value, score}]
    recommendations: List[str]           # LLM 驱动的后续推荐问题（从 SQL 执行结果生成）
    generated_sql: str                   # 当前生成的 SQL 语句
    execution_result: Any                # SQL 跑出来的真实数据结果
    error_message: list[str]             # 如果 SQL 执行报错，存放报错信息
    retry_count: int                     # 重试次数控制
    sql_history: list[str]               #失败的sql
    chart_json: Dict                     # 最终要给前端渲染的图表配置 (Generative UI)
    validation_error_type: str           # 验证错误类型: "business_rule" | "cross_layer_join" | "unauthorized_table" | "syntax" | ""
    unauthorized_tables: List[str]       # 未授权的表名列表（需要尝试扩展）
    use_slim_context: bool               # 是否使用瘦身版上下文（业务规则错误时使用）
    debug_guidance: str                  # 逻辑降维调试指引（零行数据时注入）
    zero_rows_retry_count: int           # 零行数据逻辑重试计数（独立于语法错误重试）
