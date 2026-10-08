"""
@File: connect_web.py
@Desc: WebSocket 接口测试脚本（流式推送）
@Author: h
@Date: 8.19
"""
import asyncio
import websockets
import json
from datetime import datetime
from typing import Dict, Any


class WebSocketClient:
    """WebSocket 客户端，用于测试实时流式推送"""
    
    def __init__(self, url: str = "ws://localhost:8000/ws/chat", client_id: str = "test-client"):
        self.url = f"{url}?client_id={client_id}"
        self.client_id = client_id
    
    def format_timestamp(self) -> str:
        """获取格式化的时间戳"""
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    def print_message(self, msg_type: str, content: str, indent: int = 0):
        """格式化打印消息"""
        prefix = "  " * indent
        timestamp = self.format_timestamp()
        print(f"{prefix}[{timestamp}] {msg_type}: {content}")
    
    async def send_query(self, question: str, thread_id: str = None):
        """发送查询并接收流式响应"""
        try:
            print("=" * 70)
            print(f"🔌 连接到 WebSocket: {self.url}")
            print("=" * 70)
            
            async with websockets.connect(self.url) as websocket:
                print(f"✅ 连接成功 (客户端ID: {self.client_id})")
                
                # 构建消息
                message = {"question": question}
                if thread_id:
                    message["thread_id"] = thread_id
                
                # 发送查询
                print(f"\n📤 发送问题: {question}")
                if thread_id:
                    print(f"   会话ID: {thread_id}")
                await websocket.send(json.dumps(message))
                print("⏳ 等待响应...\n")
                
                # 接收流式响应
                message_count = 0
                async for response in websocket:
                    message_count += 1
                    data = json.loads(response)
                    msg_type = data.get("type", "unknown")
                    
                    # 根据消息类型显示不同的内容
                    if msg_type == "start":
                        self.print_message("🚀 开始", data.get("message", ""))
                        print(f"   问题: {data.get('question', '')}\n")
                    
                    elif msg_type == "node_update":
                        node = data.get("node", "unknown")
                        message = data.get("message", "")
                        state = data.get("state", {})
                        
                        self.print_message(f"⚙️  节点 [{node}]", message, indent=1)
                        
                        # 显示节点状态详情
                        if "tables" in state:
                            print(f"      相关表: {', '.join(state['tables'])}")
                        if "sql" in state and state["sql"]:
                            print(f"      SQL: {state['sql'][:100]}...")
                        if "error" in state and state["error"]:
                            print(f"      错误: {state['error']}")
                        if "retry_count" in state:
                            print(f"      重试次数: {state['retry_count']}")
                        print()
                    
                    elif msg_type == "complete":
                        print("=" * 70)
                        self.print_message("✅ 完成", data.get("message", ""))
                        result = data.get("result", {})
                        
                        print("\n📊 最终结果:")
                        print("-" * 70)
                        
                        # SQL
                        if result.get("sql"):
                            print(f"🔍 生成的 SQL:")
                            print(f"   {result['sql']}\n")
                        
                        # 数据
                        if result.get("data"):
                            data_items = result["data"]
                            print(f"📦 返回数据: {len(data_items)} 行")
                            if data_items:
                                print(f"   示例（前3行）:")
                                for i, item in enumerate(data_items[:3], 1):
                                    print(f"   {i}. {json.dumps(item, ensure_ascii=False)}")
                            print()
                        
                        # 图表配置
                        if result.get("chart_json"):
                            chart = result["chart_json"]
                            print(f"📈 图表配置:")
                            print(f"   类型: {chart.get('type', 'N/A')}")
                            print(f"   标题: {chart.get('title', 'N/A')}")
                            print()
                        
                        # 错误
                        if result.get("error"):
                            print(f"❌ sql错误: {result['error']}\n")
                        
                        print("=" * 70)
                        print(f"📨 收到消息总数: {message_count}")
                        print("=" * 70)
                        break
                    
                    elif msg_type == "error":
                        self.print_message("❌msg 错误", data.get("message", ""))
                        break
                    
                    else:
                        self.print_message("ℹ️  其他", f"未知消息类型: {msg_type}")
        
        except websockets.exceptions.WebSocketException as e:
            print(f"\n❌ WebSocket 错误: {str(e)}")
        except ConnectionRefusedError:
            print(f"\n❌ 连接被拒绝：无法连接到 {self.url}")
            print("   请确认服务是否在运行")
        except Exception as e:
            print(f"\n❌ 发生错误: {str(e)}")
    
    async def interactive_mode(self):
        """交互模式：持续发送问题"""
        print("=" * 70)
        print("🎮 WebSocket 交互模式")
        print("=" * 70)
        print("输入问题后按回车发送，输入 'quit' 或 'exit' 退出\n")
        
        while True:
            try:
                question = input("💬 请输入问题: ").strip()
                
                if question.lower() in ['quit', 'exit', 'q']:
                    print("👋 再见！")
                    break
                
                if not question:
                    print("⚠️  问题不能为空\n")
                    continue
                
                print()  # 空行分隔
                await self.send_query(question)
                print("\n")  # 空行分隔
                
            except KeyboardInterrupt:
                print("\n\n👋 收到中断信号，退出")
                break
            except Exception as e:
                print(f"❌ 错误: {str(e)}\n")


async def main():
    """主函数"""
    # 创建 WebSocket 客户端
    client = WebSocketClient(
        url="ws://localhost:8000/ws/chat",
        client_id="python-test-client"
    )
    
    # 示例1：单次查询测试
    print("\n【示例1】单次查询测试\n")
    await client.send_query("找出所有VIP等级为‘黄金’的客户名单")
    
    print("\n\n")
    
    # 示例2：带会话ID的查询
    print("\n【示例2】带会话ID的查询\n")
    await client.send_query("找出所有VIP等级为‘黄金’的客户名单", thread_id="session-demo-001")
    
    print("\n\n")
    
    # 示例3：进入交互模式（取消注释以启用）
    # print("\n【示例3】交互模式\n")
    # await client.interactive_mode()


if __name__ == "__main__":
    # 运行异步主函数
    asyncio.run(main())
