"""
@File: sql_executor.py
@Desc: node4,执行sql获取数据
@Author: h
@Date: 8.13
"""
import logging
from typing import Dict, Any, List

from core.database import execute_sql_query, execute_mongo_query
from core.config import settings, DatabaseType
from graph.state import Chat2DataState

logger = logging.getLogger(__name__)


def format_execution_result(result: Dict[str, Any]) -> str:
    """
    格式化执行结果为可读文本
    
    Args:
        result: 执行结果字典
        
    Returns:
        str: 格式化的结果文本
    """
    if not result.get("success"):
        return f"执行失败: {result.get('message', '未知错误')}"
    
    data = result.get("data")
    if data is None:
        return "查询成功，但没有返回数据"
    
    if isinstance(data, list):
        count = len(data)
        if count == 0:
            return "查询成功，返回 0 条记录"
        
        # 格式化前几条数据作为预览
        preview_count = min(5, count)
        preview_text = f"查询成功，共返回 {count} 条记录。\n\n前 {preview_count} 条数据预览：\n"
        
        for i, row in enumerate(data[:preview_count], 1):
            preview_text += f"\n记录 {i}:\n"
            if isinstance(row, dict):
                for key, value in row.items():
                    preview_text += f"  {key}: {value}\n"
            else:
                preview_text += f"  {row}\n"
        
        return preview_text
    
    return f"查询成功: {result.get('message', '')}"


def analyze_execution_error(error_message: str, sql: str) -> str:
    """
    分析执行错误并提供修复建议
    
    Args:
        error_message: 错误消息
        sql: 执行的 SQL 语句
        
    Returns:
        str: 带有修复建议的错误消息
    """
    suggestions = []
    
    error_lower = error_message.lower()
    
    # 常见错误类型和建议
    if "no such table" in error_lower or "table" in error_lower and "not" in error_lower:
        suggestions.append("表名可能不存在或拼写错误，请检查表名是否正确")
    
    if "no such column" in error_lower or "column" in error_lower and "not" in error_lower:
        suggestions.append("列名可能不存在或拼写错误，请检查列名是否正确")
    
    if "syntax error" in error_lower:
        suggestions.append("SQL 语法错误，请检查 SQL 语句格式")
    
    if "ambiguous" in error_lower:
        suggestions.append("列名存在歧义，可能需要指定表名前缀（如 table.column）")
    
    if "group by" in error_lower or "aggregate" in error_lower:
        suggestions.append("聚合查询错误，请检查 GROUP BY 子句和聚合函数使用")
    
    if "join" in error_lower:
        suggestions.append("JOIN 操作错误，请检查关联条件和表名")
    
    # 构建完整的错误消息
    error_with_suggestions = f"执行错误: {error_message}\n\nSQL: {sql}"
    
    if suggestions:
        error_with_suggestions += "\n\n💡 修复建议:\n" + "\n".join(f"  • {s}" for s in suggestions)
    
    return error_with_suggestions


async def execute_sql_safely(sql: str, state: Chat2DataState) -> Dict[str, Any]:
    """
    安全执行 SQL 查询
    
    Args:
        sql: SQL 语句
        state: Chat2DataState 状态字典
        
    Returns:
        Dict: 执行结果
    """
    try:
        # 根据数据库类型选择执行方法
        if settings.DATABASE_TYPE == DatabaseType.MONGO:
            # MongoDB 不支持 SQL，应该使用 execute_mongo_query
            logger.warning("MongoDB 不支持 SQL 查询，请使用 MongoDB 查询语法")
            return {
                "success": False,
                "data": None,
                "message": "当前数据库为 MongoDB，不支持 SQL 查询"
            }
        else:
            # SQLite/PostgreSQL 执行 SQL
            result = await execute_sql_query(sql)
            return result
            
    except Exception as e:
        logger.error(f"SQL 执行异常: {str(e)}")
        return {
            "success": False,
            "data": None,
            "message": f"执行异常: {str(e)}"
        }


def should_retry_execution(state: Chat2DataState) -> bool:
    """
    判断是否应该重试 SQL 生成和执行
    
    Args:
        state: Chat2DataState 状态字典
        
    Returns:
        bool: 是否需要重试
    """
    retry_count = state.get("retry_count", 0)
    max_retries = 3
    error_message = state.get("error_message", "")
    
    # 如果有错误且未超过最大重试次数
    if error_message and retry_count < max_retries:
        return True
    
    return False


def calculate_result_statistics(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    计算查询结果的统计信息
    
    Args:
        data: 查询结果数据
        
    Returns:
        Dict: 统计信息
    """
    if data is None:
        return {"total_rows": 0, "columns": [], "has_data": False, "column_count": 0}
    if not isinstance(data, list):
        return {"total_rows": 0, "columns": [], "has_data": False, "column_count": 0}
    
    total_rows = len(data)
    
    # 提取列名
    columns = []
    if total_rows > 0 and isinstance(data[0], dict):
        columns = list(data[0].keys())
    
    return {
        "total_rows": total_rows,
        "columns": columns,
        "has_data": total_rows > 0,
        "column_count": len(columns)
    }


async def sql_executor(state: Chat2DataState) -> Chat2DataState:
    """
    SQL 执行节点函数
    
    执行经过验证的 SQL 语句并处理结果：
    1. 从 state 获取 generated_sql
    2. 执行 SQL 查询
    3. 处理执行结果或错误
    4. 更新 state（execution_result, error_message, retry_count）
    
    Args:
        state: Chat2DataState 状态字典
        
    Returns:
        Chat2DataState: 更新后的状态
    """
    generated_sql = state.get("generated_sql", "")
    
    # 检查是否有 SQL 可执行
    if not generated_sql:
        logger.error("没有 SQL 语句可执行")
        return {
            **state,
            "execution_result": None,
            "error_message": "没有生成 SQL 语句",
            "retry_count": state.get("retry_count", 0) + 1
        }
    
    logger.info(f"开始执行 SQL: {generated_sql}")
    
    # 执行 SQL
    result = await execute_sql_safely(generated_sql, state)
    
    # 处理执行结果
    if result.get("success"):
        # 执行成功
        data = result.get("data")
        message = result.get("message", "")
        
        logger.info(f"SQL 执行成功: {message}")
        
        # 计算统计信息
        stats = calculate_result_statistics(data)
        logger.info(f"查询结果: {stats['total_rows']} 行, {stats['column_count']} 列")
        
        # 格式化结果预览
        result_preview = format_execution_result(result)
        logger.debug(f"结果预览:\n{result_preview}")
        print(result_preview)
        return {
            **state,
            "execution_result": data,
            "error_message": [],  # 清空错误消息列表
            "retry_count": 0,  # 重置重试计数
            "sql_history": []  # 清空失败历史
        }
    else:
        # 执行失败
        error_message = result.get("message", "未知执行错误")
        
        logger.warning(f"SQL 执行失败: {error_message}")
        
        # 分析错误并提供建议
        detailed_error = analyze_execution_error(error_message, generated_sql)
        logger.warning(detailed_error)
        
        retry_count = state.get("retry_count", 0) + 1
        
        # 更新错误历史和失败的 SQL 历史
        error_history = state.get("error_message", [])
        if isinstance(error_history, str):
            error_history = [error_history] if error_history else []
        error_history.append(detailed_error)
        
        sql_history = state.get("sql_history", [])
        if isinstance(sql_history, str):
            sql_history = [sql_history] if sql_history else []
        sql_history.append(generated_sql)
        
        return {
            **state,
            "execution_result": None,
            "error_message": error_history,
            "sql_history": sql_history,
            "retry_count": retry_count
        }


def get_execution_summary(state: Chat2DataState) -> str:
    """
    获取执行摘要信息（用于日志或返回给用户）
    
    Args:
        state: Chat2DataState 状态字典
        
    Returns:
        str: 执行摘要
    """
    sql = state.get("generated_sql", "")
    error_message = state.get("error_message", "")
    execution_result = state.get("execution_result")
    
    if error_message:
        return f"执行失败:\n{error_message}"
    
    if execution_result is not None:
        stats = calculate_result_statistics(execution_result)
        return (
            f"执行成功:\n"
            f"SQL: {sql}\n"
            f"返回: {stats['total_rows']} 行, {stats['column_count']} 列\n"
            f"列名: {', '.join(stats['columns'])}"
        )
    
    return "未执行"


__all__ = [
    "sql_executor",
    "execute_sql_safely",
    "get_execution_summary",
    "should_retry_execution",
]