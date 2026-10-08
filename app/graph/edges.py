"""
@File: edges.py
@Desc: 路由逻辑,additional edge,通常是失败重试
@Author: h
@Date: 8.13
"""
import logging
logger = logging.getLogger(__name__)
MAX_SQL_RETRIES = 6
MAX_ZERO_ROWS_RETRIES = 3  # 零行数据逻辑重试上限


def _route_sql_result(state):
    """Route one SQL step without mutating the shared graph state."""
    error_message = state.get("error_message", [])
    has_error = bool(error_message)

    if not has_error:
        return "success"
    if state.get("retry_count", 0) < MAX_SQL_RETRIES:
        return "retry"
    return "failed"


def route_sql_val_result_refined(state):
    """
    精细化路由 SQL 验证结果
    
    根据错误类型路由到不同节点:
    - cross_layer_join: 路由到 sql_syntax_patcher（专精修补ON条件）
    - unauthorized_table: 路由到 sql_generator（已扩展表，重新生成）
    - business_rule: 路由到 sql_generator（使用瘦身上下文）
    - syntax: 路由到 sql_generator（完整重写）
    - success: 路由到 sql_executor
    - failed: 超过重试次数，路由到 chart_generator
    """
    error_message = state.get("error_message", [])
    has_error = bool(error_message)
    
    # 没有错误，验证成功
    if not has_error:
        return "success"
    
    # 超过重试次数
    if state.get("retry_count", 0) >= MAX_SQL_RETRIES:
        return "failed"
    
    # 根据错误类型路由
    validation_error_type = state.get("validation_error_type", "")
    
    if validation_error_type == "cross_layer_join":
        return "patch_syntax"
    elif validation_error_type == "unauthorized_table":
        return "retry"  # 已在validator中扩展表，直接重试生成
    elif validation_error_type == "business_rule":
        return "retry"  # 使用瘦身上下文重试（state中已设置use_slim_context=True）
    else:
        return "retry"  # 其他错误，完整重写


def route_sql_val_result(state):
    """Route SQL validation results (legacy, use route_sql_val_result_refined)."""
    return _route_sql_result(state)


def route_sql_exec_result(state):
    """
    Route SQL execution results with zero-rows detection.
    
    Routes:
    - zero_rows: 执行成功但返回0行 → sql_logic_debugger
    - success: 执行成功且有数据 → recommendation_generator
    - retry: 执行错误且未超重试次数 → sql_generator
    - failed: 超过重试次数 → chart_generator
    """
    error_message = state.get("error_message", [])
    has_error = bool(error_message)
    execution_result = state.get("execution_result")
    
    # 执行成功但无数据（兼容 None 和 []）
    is_empty = (
        (isinstance(execution_result, list) and len(execution_result) == 0) or
        execution_result is None
    )
    
    if not has_error and is_empty:
        zero_rows_retry_count = state.get("zero_rows_retry_count", 0)
        logger.warning(f"⚠️  检测到零行数据！zero_rows_retry_count={zero_rows_retry_count}")
        
        if zero_rows_retry_count < MAX_ZERO_ROWS_RETRIES:
            return "zero_rows"
        else:
            logger.warning(f"→ 超过零行重试上限，路由到 'success'")
            return "success"
    
    # 常规路由逻辑
    return _route_sql_result(state)

