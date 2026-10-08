"""
@File: chat_routes.py
@Desc: 前端对话相关接口 - 支持流式、历史、反馈
@Author: h&m
@Date: 8.20
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import json
import asyncio
from datetime import datetime
import os

from graph.workflow import agent
from graph.state import Chat2DataState
from schema.response_models import (
    AgentResponse,
    StreamEvent,
    ConversationHistory,
    ConversationMessage,
    FeedbackRequest,
    FeedbackResponse
)
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat")


# ==========================================
# 配置模型
# ==========================================
class CompatibleSettings(BaseModel):
    """OpenAI 兼容模型配置"""
    compatible_model: Optional[str] = Field(None, description="模型名称")
    compatible_api_key: Optional[str] = Field(None, description="API Key")
    compatible_base_url: Optional[str] = Field(None, description="Base URL")


class SettingsResponse(BaseModel):
    """配置响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="响应消息")


# ==========================================
# 请求模型
# ==========================================
class ChatRequest(BaseModel):
    """聊天请求"""
    question: str
    thread_id: Optional[str] = None


# ==========================================
# 内存存储（生产环境应使用 Redis/数据库）
# ==========================================
_conversation_store: Dict[str, ConversationHistory] = {}
_feedback_store: List[Dict[str, Any]] = []


# ==========================================
# GET /settings - 获取配置
# ==========================================
@router.get("/settings")
async def get_settings():
    """
    获取当前配置
    """
    try:
        from core.config import settings
        return {
            "success": True,
            "data": {
                "compatible_model": settings.COMPATIBLE_MODEL,
                "compatible_api_key": settings.COMPATIBLE_API_KEY.get_secret_value() if settings.COMPATIBLE_API_KEY else "",
                "compatible_base_url": settings.COMPATIBLE_BASE_URL,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# POST /settings - 更新配置
# ==========================================
@router.post("/settings")
async def update_settings(request: CompatibleSettings):
    """
    更新 OpenAI 兼容模型配置（写入 .env 文件）
    
    Args:
        request: 配置数据
        
    Returns:
        配置结果
    """
    try:
        from pathlib import Path
        from dotenv import set_key, load_dotenv
        
        env_path = Path(__file__).parent.parent.parent / ".env"
        if not env_path.exists():
            raise HTTPException(status_code=404, detail=".env 文件不存在")
        
        # 加载现有环境变量
        load_dotenv(env_path)
        
        # 写入配置
        if request.compatible_model is not None:
            set_key(str(env_path), "COMPATIBLE_MODEL", request.compatible_model)
        if request.compatible_api_key is not None:
            set_key(str(env_path), "COMPATIBLE_API_KEY", request.compatible_api_key)
        if request.compatible_base_url is not None:
            set_key(str(env_path), "COMPATIBLE_BASE_URL", request.compatible_base_url)
        
        # 重新加载配置
        os.environ["COMPATIBLE_MODEL"] = request.compatible_model or ""
        os.environ["COMPATIBLE_API_KEY"] = request.compatible_api_key or ""
        os.environ["COMPATIBLE_BASE_URL"] = request.compatible_base_url or ""
        
        return SettingsResponse(
            success=True,
            message="配置已更新到 .env 文件，请重启后端服务以生效"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# POST /stream - 流式对话接口
# ==========================================
@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """
    流式对话接口 - 支持 Server-Sent Events (SSE)
    
    前端使用示例：
    ```javascript
    const eventSource = new EventSource('/api/chat/stream');
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log(data);
    };
    ```
    """
    
    async def event_generator():
        try:
            # 发送开始事件
            yield _sse_message(StreamEvent(
                event="start",
                step="开始处理您的问题...",
                data={"question": request.question}
            ))
            
            # 构建初始状态
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
            
            # 配置
            config = {}
            if request.thread_id:
                config["configurable"] = {"thread_id": request.thread_id}
            
            # 流式执行 workflow - 监听每个节点的输出
            async for event in agent.astream(initial_state, config=config):
                # event 是一个字典，key 是节点名，value 是节点输出
                for node_name, node_output in event.items():
                    
                    # Schema 检索完成
                    if node_name == "schema_retreiever":
                        yield _sse_message(StreamEvent(
                            event="schema_retrieved",
                            step="已检索相关数据表",
                            data={
                                "tables": node_output.get("relevant_tables", [])
                            }
                        ))
                    
                    # SQL 生成完成
                    elif node_name == "sql_generator":
                        yield _sse_message(StreamEvent(
                            event="sql_generated",
                            step="SQL 语句已生成",
                            data={
                                "sql": node_output.get("generated_sql", "")
                            }
                        ))
                    
                    # SQL 验证通过
                    elif node_name == "sql_validator":
                        if not node_output.get("error_message"):
                            yield _sse_message(StreamEvent(
                                event="sql_validated",
                                step="SQL 验证通过",
                                data={}
                            ))
                    
                    # SQL 执行完成
                    elif node_name == "sql_executor":
                        if node_output.get("execution_result") is not None:
                            yield _sse_message(StreamEvent(
                                event="sql_executed",
                                step="数据查询完成",
                                data={
                                    "row_count": len(node_output.get("execution_result", []))
                                }
                            ))
                    
                    # 推荐问题已生成
                    elif node_name == "recommendation_generator":
                        recommendations = node_output.get("recommendations", [])
                        print(f"[SSE] recommendation: {len(recommendations)} 个推荐问题")
                        if recommendations:
                            print("[SSE] 推送推荐问题到前端")
                            yield _sse_message(
                                StreamEvent(
                                    event="recommendation_generated",
                                    step="已生成推荐问题",
                                    data={
                                        "recommendations": recommendations,
                                    }
                                )
                            )
                        else:
                            print("[SSE] 无推荐问题，跳过推送")
                    # 图表生成完成（最终结果）
                    elif node_name == "chart_generator":
                        chart_json = node_output.get("chart_json", {})
                        
                        yield _sse_message(StreamEvent(
                            event="chart_generated",
                            step="图表配置已生成",
                            data={"chart_json": chart_json}
                        ))
                        
                        # 发送完成事件
                        yield _sse_message(StreamEvent(
                            event="complete",
                            step="处理完成",
                            data={"chart_json": chart_json}
                        ))
                        
                        # 保存到历史记录
                        if request.thread_id:
                            _save_to_history(
                                thread_id=request.thread_id,
                                question=request.question,
                                agent_response=chart_json
                            )
            
        except Exception as e:
            logger.exception("SSE 事件流处理异常: %s", e)
            yield _sse_message(StreamEvent(
                event="error",
                step="处理失败",
                data={"error": str(e)}
            ))
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 Nginx 缓冲
        }
    )


def _sse_message(event: StreamEvent) -> str:
    """格式化 SSE 消息"""
    return f"data: {event.model_dump_json()}\n\n"


# ==========================================
# GET /history - 获取对话历史
# ==========================================
@router.get("/history", response_model=List[ConversationHistory])
async def get_history(thread_id: Optional[str] = None):
    """
    获取对话历史
    
    Args:
        thread_id: 可选，指定会话 ID。不传则返回所有会话列表
    
    Returns:
        会话历史列表或单个会话的详细历史
    """
    if thread_id:
        # 返回特定会话的历史
        if thread_id not in _conversation_store:
            raise HTTPException(status_code=404, detail=f"会话 {thread_id} 不存在")
        
        return [_conversation_store[thread_id]]
    
    else:
        # 返回所有会话的概览
        return list(_conversation_store.values())


# ==========================================
# POST /feedback - 提交反馈
# ==========================================
@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(feedback: FeedbackRequest):
    """
    提交用户反馈
    
    Args:
        feedback: 反馈内容，包含会话 ID、消息索引、反馈类型等
    
    Returns:
        反馈结果
    """
    try:
        # 验证会话是否存在
        if feedback.thread_id not in _conversation_store:
            raise HTTPException(
                status_code=404,
                detail=f"会话 {feedback.thread_id} 不存在"
            )
        
        conversation = _conversation_store[feedback.thread_id]
        
        # 验证消息索引
        if feedback.message_index >= len(conversation.messages):
            raise HTTPException(
                status_code=400,
                detail=f"消息索引 {feedback.message_index} 超出范围"
            )
        
        # 保存反馈
        feedback_record = {
            "feedback": feedback.model_dump(),
            "saved_at": datetime.now().isoformat()
        }
        _feedback_store.append(feedback_record)
        
        # 集成到 sql_saver：更新案例库评分
        message = conversation.messages[feedback.message_index]
        if message.role == "assistant" and message.agent_response:
            from nodes.sql_saver import provide_user_feedback
            
            sql = message.agent_response.sql
            # 获取对应的用户问题（前一条消息）
            question = ""
            if feedback.message_index > 0:
                prev_msg = conversation.messages[feedback.message_index - 1]
                if prev_msg.role == "user":
                    question = prev_msg.content
            
            if sql and question:
                # 映射反馈类型到 positive 字段
                positive = feedback.feedback_type == "thumbs_up"
                
                # 调用 sql_saver 更新案例库
                await provide_user_feedback(
                    question=question,
                    sql=sql,
                    followed_up=False,  # 可以后续通过追问逻辑判断
                    positive=positive,
                    rating=5 if positive else 1
                )
                
                logger.info(f"✅ 已更新案例库评分：positive={positive}, sql_len={len(sql)}")
        
        # TODO: 生产环境应该：
        # 1. 保存到数据库
        # 2. 如果是 thumbs_down，可以触发人工审核
        # 3. 如果是 flag，立即通知管理员
        # 4. 用于 RLHF 训练数据收集
        
        return FeedbackResponse(
            success=True,
            message="感谢您的反馈！这将帮助我们改进服务。"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 辅助函数
# ==========================================
def _save_to_history(
    thread_id: str,
    question: str,
    agent_response: Dict[str, Any]
):
    """保存对话到历史记录"""
    
    # 获取或创建会话
    if thread_id not in _conversation_store:
        _conversation_store[thread_id] = ConversationHistory(
            thread_id=thread_id,
            messages=[]
        )
    
    conversation = _conversation_store[thread_id]
    
    # 添加用户消息
    conversation.messages.append(ConversationMessage(
        role="user",
        content=question
    ))
    
    # 添加助手消息
    conversation.messages.append(ConversationMessage(
        role="assistant",
        content=agent_response.get("answer", ""),
        agent_response=AgentResponse(**agent_response)
    ))
    
    # 更新时间
    conversation.updated_at = datetime.now()


# ==========================================
# 额外工具接口
# ==========================================
@router.delete("/history/{thread_id}")
async def delete_history(thread_id: str):
    """删除指定会话历史"""
    if thread_id not in _conversation_store:
        raise HTTPException(status_code=404, detail=f"会话 {thread_id} 不存在")
    
    del _conversation_store[thread_id]
    
    return {"success": True, "message": f"会话 {thread_id} 已删除"}


@router.get("/feedback/stats")
async def get_feedback_stats():
    """获取反馈统计（用于管理后台）"""
    
    if not _feedback_store:
        return {
            "total": 0,
            "thumbs_up": 0,
            "thumbs_down": 0,
            "flags": 0
        }
    
    stats = {
        "total": len(_feedback_store),
        "thumbs_up": sum(1 for f in _feedback_store if f["feedback"]["feedback_type"] == "thumbs_up"),
        "thumbs_down": sum(1 for f in _feedback_store if f["feedback"]["feedback_type"] == "thumbs_down"),
        "flags": sum(1 for f in _feedback_store if f["feedback"]["feedback_type"] == "flag"),
    }
    
    return stats
