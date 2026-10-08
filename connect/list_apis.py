"""
@File: list_apis.py
@Desc: 列出所有可用的 API 端点
@Author: h
@Date: 2024
"""
import requests


def list_all_apis(base_url="http://localhost:8000"):
    """列出所有可用的 API 端点"""
    print("=" * 70)
    print("📋 Chat2Data API 端点列表")
    print("=" * 70)
    
    try:
        # 访问 OpenAPI docs
        response = requests.get(f"{base_url}/openapi.json")
        if response.status_code == 200:
            openapi_spec = response.json()
            paths = openapi_spec.get("paths", {})
            
            print(f"\n✅ 服务运行正常 ({base_url})")
            print(f"\n共找到 {len(paths)} 个端点:\n")
            
            for path, methods in paths.items():
                for method, details in methods.items():
                    summary = details.get("summary", "无描述")
                    tags = ", ".join(details.get("tags", []))
                    print(f"  {method.upper():6} {path}")
                    print(f"         📝 {summary}")
                    if tags:
                        print(f"         🏷️  标签: {tags}")
                    print()
        else:
            print(f"❌ 无法获取 API 文档 (HTTP {response.status_code})")
            print("\n手动列出已知端点:")
            print_manual_list(base_url)
            
    except requests.exceptions.ConnectionError:
        print(f"❌ 无法连接到 {base_url}")
        print("   请确保服务正在运行")
        print("\n已知端点列表:")
        print_manual_list(base_url)
    except Exception as e:
        print(f"❌ 错误: {str(e)}")
        print("\n已知端点列表:")
        print_manual_list(base_url)


def print_manual_list(base_url):
    """手动打印端点列表"""
    endpoints = [
        {
            "method": "GET",
            "path": "/",
            "desc": "根路径 - 服务状态",
            "example": f'curl {base_url}/',
            "needs_api_key": False
        },
        {
            "method": "GET",
            "path": "/health",
            "desc": "健康检查",
            "example": f'curl {base_url}/health',
            "needs_api_key": False
        },
        {
            "method": "GET",
            "path": "/api/database/info",
            "desc": "获取数据库信息（表数量、列表等）",
            "example": f'curl {base_url}/api/database/info',
            "needs_api_key": False
        },
        {
            "method": "GET",
            "path": "/api/database/tables",
            "desc": "列出所有表",
            "example": f'curl {base_url}/api/database/tables',
            "needs_api_key": False
        },
        {
            "method": "GET",
            "path": "/api/database/tables/{{table_name}}",
            "desc": "获取指定表的结构",
            "example": f'curl {base_url}/api/database/tables/users',
            "needs_api_key": False
        },
        {
            "method": "POST",
            "path": "/api/database/execute",
            "desc": "直接执行 SQL（仅限 SELECT）",
            "example": f'''curl -X POST {base_url}/api/database/execute \\
  -H "Content-Type: application/json" \\
  -d '{{"sql": "SELECT * FROM users LIMIT 5"}}\'''',
            "needs_api_key": False
        },
        {
            "method": "POST",
            "path": "/api/query",
            "desc": "AI 自然语言查询（需要 LLM）",
            "example": f'''curl -X POST {base_url}/api/query \\
  -H "Content-Type: application/json" \\
  -d '{{"question": "查询所有用户"}}\'''',
            "needs_api_key": True
        },
        {
            "method": "POST",
            "path": "/api/stream",
            "desc": "流式查询（TODO: 未实现）",
            "example": "暂未实现",
            "needs_api_key": True
        },
        {
            "method": "WS",
            "path": "/ws/chat?client_id=xxx",
            "desc": "WebSocket 实时推送（需要 LLM）",
            "example": f'wscat -c "{base_url.replace("http", "ws")}/ws/chat?client_id=test"',
            "needs_api_key": True
        }
    ]
    
    print()
    print("\n🟢 无需 API Key 的端点:")
    print("-" * 60)
    for ep in endpoints:
        if not ep.get('needs_api_key', False):
            print(f"  {ep['method']:6} {ep['path']}")
            print(f"         📝 {ep['desc']}")
            print(f"         💡 示例: {ep['example']}")
            print()
    
    print("\n🔑 需要 LLM API Key 的端点:")
    print("-" * 60)
    for ep in endpoints:
        if ep.get('needs_api_key', False):
            print(f"  {ep['method']:6} {ep['path']}")
            print(f"         📝 {ep['desc']}")
            print(f"         💡 示例: {ep['example']}")
            print()
    
    print("\n" + "=" * 70)
    print("📖 在线文档")
    print("=" * 70)
    print(f"  Swagger UI:  {base_url}/docs")
    print(f"  ReDoc:       {base_url}/redoc")
    print(f"  OpenAPI:     {base_url}/openapi.json")
    print("=" * 70)


if __name__ == "__main__":
    import sys
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    list_all_apis(base_url)
