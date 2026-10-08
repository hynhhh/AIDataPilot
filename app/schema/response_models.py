"""
@File: response_models.py
@Desc: 前端响应模型定义 - assistantui + echarts
@Author: h
@Date: 8.26
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime


# ==========================================
# 前端展示核心协议
# ==========================================
class AgentResponse(BaseModel):
    """Agent 返回给前端的统一响应格式"""
    
    # 基础回答
    answer: str = Field(..., description="自然语言回答，直接展示给用户")
    
    # SQL 相关
    sql: Optional[str] = Field(None, description="生成的 SQL 语句（可选）")
    
    # 数据表格
    table: Optional[List[Dict[str, Any]]] = Field(None, description="查询结果数据，JSON 数组格式")
    
    # 图表配置（ECharts 格式）
    chart: Optional[Dict[str, Any]] = Field(None, description="ECharts 图表配置对象")
    
    # 相关推荐问题
    suggestions: Optional[List[str]] = Field(None, description="推荐的后续问题列表")
    
    # 元数据
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, 
        description="额外的元数据，如执行时间、重试次数等"
    )


# ==========================================
# 流式响应模型
# ==========================================
class StreamEvent(BaseModel):
    """流式传输的事件格式"""
    
    event: Literal[
        "start",           # 开始处理
        "thinking",        # 思考中（展示当前步骤）
        "schema_retrieved", # 表结构检索完成
        "sql_generated",   # SQL 生成完成
        "sql_validated",   # SQL 验证通过
        "sql_executed",    # SQL 执行完成
        "recommendation_generated", # 推荐问题已生成
        "chart_generated", # 图表生成完成
        "complete",        # 完成
        "error"            # 错误
    ] = Field(..., description="事件类型")
    
    step: Optional[str] = Field(None, description="当前步骤描述")
    data: Optional[Dict[str, Any]] = Field(None, description="步骤相关数据")
    timestamp: datetime = Field(default_factory=datetime.now, description="事件时间戳")


# ==========================================
# 历史记录模型
# ==========================================
class ConversationMessage(BaseModel):
    """单条对话消息"""
    
    role: Literal["user", "assistant"] = Field(..., description="角色：用户或助手")
    content: str = Field(..., description="消息内容")
    timestamp: datetime = Field(default_factory=datetime.now, description="消息时间")
    
    # 如果是 assistant 消息，可以包含完整的 AgentResponse
    agent_response: Optional[AgentResponse] = Field(None, description="完整的 Agent 响应数据")


class ConversationHistory(BaseModel):
    """会话历史"""
    
    thread_id: str = Field(..., description="会话 ID")
    messages: List[ConversationMessage] = Field(default_factory=list, description="消息列表")
    created_at: datetime = Field(default_factory=datetime.now, description="会话创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="最后更新时间")


# ==========================================
# 反馈模型
# ==========================================
class FeedbackRequest(BaseModel):
    """用户反馈请求"""
    
    thread_id: str = Field(..., description="会话 ID")
    message_index: int = Field(..., description="反馈的消息索引（从 0 开始）")
    
    feedback_type: Literal["thumbs_up", "thumbs_down", "flag"] = Field(
        ..., 
        description="反馈类型：赞/踩/举报"
    )
    
    comment: Optional[str] = Field(None, description="用户评论（可选）")
    
    # 具体问题分类
    issue_tags: Optional[List[Literal[
        "incorrect_sql",
        "wrong_data",
        "chart_mismatch",
        "incomplete_answer",
        "other"
    ]]] = Field(None, description="问题标签（踩时使用）")
    
    timestamp: datetime = Field(default_factory=datetime.now, description="反馈时间")


class FeedbackResponse(BaseModel):
    """反馈响应"""
    
    success: bool = Field(..., description="是否成功保存反馈")
    message: str = Field(..., description="响应消息")
