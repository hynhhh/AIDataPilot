"""
@File: routes.py
@Desc: 定义接口
@Author: h
@Date: 8.13
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from graph.workflow import agent
from graph.state import Chat2DataState
from core.database import get_database_schema, execute_sql_query
from core.config import settings

router = APIRouter()


class QueryRequest(BaseModel):
    """查询请求模型"""
    question: str
    thread_id: Optional[str] = None


class QueryResponse(BaseModel):
    """查询响应模型"""
    success: bool
    sql: Optional[str] = None
    data: Optional[Any] = None
    error: Optional[str] = None
    chart_json: Optional[Dict[str, Any]] = None
    retry_count: Optional[int] = 0


@router.post("/query", response_model=QueryResponse)
async def execute_query(request: QueryRequest):
    """
    执行自然语言查询
    
    Args:
        request: 包含用户问题和配置的请求体
    
    Returns:
        查询结果，包括数据和图表配置
    """
    try:
        # 构建初始状态（使用 Chat2DataState 结构）
        initial_state: Chat2DataState = {
            "question": request.question,
            "intent": "",
            "relevant_tables": [],
            "relevant_columns": {},
            "schema_info": {},
            "few_shot_examples": [],
            "generated_sql": "",
            "execution_result": None,
            "error_message": [],
            "retry_count": 0,
            "sql_history": [],
            "chart_json": {},
            "validation_error_type":"",        
            "unauthorized_tables": [] ,   
            "use_slim_context": False  ,        
            "debug_guidance": "",
            "zero_rows_retry_count": 0,

        }
        
        # 配置（如果有 thread_id 则支持会话）
        config = {}
        if request.thread_id:
            config["configurable"] = {"thread_id": request.thread_id}
        
        # 执行工作流
        result = await agent.ainvoke(initial_state, config=config)
        
        # 检查是否有错误
        if result.get("error_message"):
            return QueryResponse(
                success=False,
                error=result["error_message"],
                retry_count=result.get("retry_count", 0)
            )
        
        # 返回成功结果
        return QueryResponse(
            success=True,
            sql=result.get("generated_sql"),
            data=result.get("execution_result"),
            chart_json=result.get("chart_json"),
            retry_count=result.get("retry_count", 0)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def stream_query(request: QueryRequest):
    """
    流式执行查询（用于 WebSocket 或 SSE）
    """
    # TODO: 实现流式响应
    pass


@router.get("/database/info")
async def get_database_info():
    """
    获取数据库基本信息（不需要 LLM API key）
    
    返回:
        数据库类型、路径、表列表等信息
    """
    try:
        # 获取数据库配置
        db_info = {
            "database_type": settings.DATABASE_TYPE,
            "database_path": settings.SQLITE_DB_PATH if settings.DATABASE_TYPE == "sqlite" else None,
        }
        
        # 获取表结构
        schema_result = await get_database_schema()
        
        if schema_result.get("success"):
            db_info["tables"] = schema_result.get("data", {}).get("tables", [])
            db_info["table_count"] = len(db_info["tables"])
            db_info["status"] = "connected"
        else:
            db_info["status"] = "error"
            db_info["error"] = schema_result.get("message")
        
        return db_info
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/database/tables")
async def list_tables():
    """
    列出所有表（不需要 LLM API key）
    
    返回:
        所有表的列表及详细信息
    """
    try:
        schema_result = await get_database_schema()
        
        if not schema_result.get("success"):
            raise HTTPException(
                status_code=500, 
                detail=schema_result.get("message", "获取表列表失败")
            )
        
        return {
            "success": True,
            "tables": schema_result.get("data", {}).get("tables", []),
            "count": len(schema_result.get("data", {}).get("tables", []))
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/database/tables/{table_name}")
async def get_table_schema(table_name: str):
    """
    获取指定表的结构（不需要 LLM API key）
    
    Args:
        table_name: 表名
        
    返回:
        表的详细结构信息
    """
    try:
        schema_result = await get_database_schema(table_name=table_name)
        
        if not schema_result.get("success"):
            raise HTTPException(
                status_code=404, 
                detail=f"表 '{table_name}' 不存在或获取失败"
            )
        
        return schema_result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class DirectSQLRequest(BaseModel):
    """直接执行 SQL 请求模型"""
    sql: str
    params: Optional[List[Any]] = None


@router.post("/database/execute")
async def execute_direct_sql(request: DirectSQLRequest):
    """
    直接执行 SQL 查询（不需要 LLM API key）
    
    警告：仅用于测试，生产环境应限制权限
    
    Args:
        request: SQL 语句和参数
        
    返回:
        查询结果
    """
    try:
        # 安全检查：只允许 SELECT 语句
        sql_upper = request.sql.strip().upper()
        if not sql_upper.startswith("SELECT"):
            raise HTTPException(
                status_code=403,
                detail="仅允许 SELECT 查询。如需修改数据，请使用完整的 AI 工作流。"
            )
        
        result = await execute_sql_query(request.sql, request.params)
        
        if not result.get("success"):
            raise HTTPException(
                status_code=400,
                detail=result.get("message", "SQL 执行失败")
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))