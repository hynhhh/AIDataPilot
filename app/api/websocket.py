"""
@File: websocket.py
@Desc: 给前端流式推送节点状态
@Author: h
@Date: 8.13
"""
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Any

from graph.workflow import agent
from graph.state import Chat2DataState

router = APIRouter()


class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
    
    async def send_message(self, client_id: str, message: Dict[str, Any]):
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            await websocket.send_json(message)


manager = ConnectionManager()


@router.websocket("/chat")
async def websocket_endpoint(websocket: WebSocket, client_id: str = "default"):
    """
    WebSocket 端点，用于流式推送节点执行状态
    
    Args:
        websocket: WebSocket 连接
        client_id: 客户端 ID
    """
    await manager.connect(websocket, client_id)
    
    try:
        while True:
            # 接收客户端消息
            data = await websocket.receive_json()
            question = data.get("question")
            thread_id = data.get("thread_id")
            
            if not question:
                await manager.send_message(client_id, {
                    "type": "error",
                    "message": "问题不能为空"
                })
                continue
            
            # 构建初始状态（使用 Chat2DataState 结构）
            initial_state: Chat2DataState = {
                "question": question,
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
                "chart_json": {}
            }
            
            # 配置
            config = {}
            if thread_id:
                config["configurable"] = {"thread_id": thread_id}
            
            # 发送开始消息
            await manager.send_message(client_id, {
                "type": "start",
                "message": "开始处理查询...",
                "question": question
            })
            
            # 流式执行工作流
            try:
                async for event in agent.astream(initial_state, config=config):
                    # 推送每个节点的执行状态
                    for node_name, node_state in event.items():
                        # 构建友好的消息
                        message = {
                            "type": "node_update",
                            "node": node_name,
                            "state": {}
                        }
                        
                        # 根据节点类型发送不同的信息
                        if node_name == "schema_retreiever":
                            message["message"] = "正在检索相关表和列..."
                            message["state"] = {
                                "tables": [t.get("table_name") for t in node_state.get("relevant_tables", [])]
                            }
                        elif node_name == "sql_generator":
                            message["message"] = "正在生成SQL查询..."
                            message["state"] = {
                                "sql": node_state.get("generated_sql")
                            }
                        elif node_name == "sql_executor":
                            message["message"] = "正在执行SQL查询..."
                            message["state"] = {
                                "has_result": node_state.get("execution_result") is not None
                            }
                        elif node_name == "sql_validator":
                            message["message"] = "正在验证结果..."
                            message["state"] = {
                                "error": node_state.get("error_message"),
                                "retry_count": node_state.get("retry_count", 0)
                            }
                        elif node_name == "recommendation_generator":
                            message["message"] = "正在生成推荐问题..."
                            message["state"] = {
                                "recommendations": node_state.get("recommendations", [])
                            }
                        elif node_name == "chart_generator":
                            message["message"] = "正在生成图表配置..."
                            message["state"] = {
                                "chart_json": node_state.get("chart_json")
                            }
                        
                        await manager.send_message(client_id, message)
                
                # 发送完成消息（包含最终结果）
                final_state = event  # 最后一个事件包含最终状态
                last_node_state = list(final_state.values())[0] if final_state else {}
                
                await manager.send_message(client_id, {
                    "type": "complete",
                    "message": "查询完成",
                    "result": {
                        "sql": last_node_state.get("generated_sql"),
                        "data": last_node_state.get("execution_result"),
                        "chart_json": last_node_state.get("chart_json"),
                        "error": last_node_state.get("error_message")
                    }
                })
                
            except Exception as e:
                await manager.send_message(client_id, {
                    "type": "error",
                    "message": str(e)
                })
    
    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        await manager.send_message(client_id, {
            "type": "error",
            "message": f"服务器错误: {str(e)}"
        })
        manager.disconnect(client_id)
