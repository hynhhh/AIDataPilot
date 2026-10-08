"""
@File: check_health.py
@Desc: 健康检查和基本 API 测试脚本
@Author: h
@Date: 8.19
"""
import requests
import json
from typing import Dict, Any


class HealthChecker:
    """API 健康检查和测试工具"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
    
    def check_health(self) -> Dict[str, Any]:
        """检查服务健康状态"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            response.raise_for_status()
            result = response.json()
            print("✅ 健康检查通过")
            print(f"   状态: {result.get('status')}")
            return {"success": True, "data": result}
        except requests.exceptions.ConnectionError:
            print("❌ 连接失败：无法连接到服务器")
            print(f"   请确认服务是否在 {self.base_url} 运行")
            return {"success": False, "error": "连接失败"}
        except requests.exceptions.Timeout:
            print("❌ 请求超时")
            return {"success": False, "error": "超时"}
        except Exception as e:
            print(f"❌ 健康检查失败: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def check_root(self) -> Dict[str, Any]:
        """检查根路径"""
        try:
            response = requests.get(self.base_url, timeout=5)
            response.raise_for_status()
            result = response.json()
            print("✅ 根路径访问成功")
            print(f"   消息: {result.get('message')}")
            return {"success": True, "data": result}
        except Exception as e:
            print(f"❌ 根路径访问失败: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def test_query(self, question: str, thread_id: str = None) -> Dict[str, Any]:
        """测试查询接口"""
        try:
            payload = {"question": question}
            if thread_id:
                payload["thread_id"] = thread_id
            
            print(f"\n📤 发送查询: {question}")
            response = requests.post(
                f"{self.api_url}/query",
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get("success"):
                print("✅ 查询成功")
                print(f"   SQL: {result.get('sql')}")
                print(f"   数据行数: {len(result.get('data', []))}")
                print(f"   重试次数: {result.get('retry_count', 0)}")
                if result.get('chart_json'):
                    print(f"   图表配置: {list(result.get('chart_json', {}).keys())}")
            else:
                print("❌ 查询失败")
                print(f"   错误: {result.get('error')}")
            
            return {"success": True, "data": result}
            
        except requests.exceptions.Timeout:
            print("❌ 查询超时（可能是复杂查询）")
            return {"success": False, "error": "超时"}
        except Exception as e:
            print(f"❌ 查询失败: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def test_database_connection(self) -> Dict[str, Any]:
        """测试数据库连接（不需要 LLM API key）"""
        try:
            print(f"\n📊 测试数据库连接...")
            response = requests.get(f"{self.api_url}/database/info", timeout=10)
            response.raise_for_status()
            result = response.json()
            
            print("✅ 数据库连接成功")
            print(f"   类型: {result.get('database_type')}")
            print(f"   路径: {result.get('database_path')}")
            print(f"   状态: {result.get('status')}")
            print(f"   表数量: {result.get('table_count', 0)}")
            if result.get('tables'):
                print(f"   表列表: {', '.join(result['tables'][:5])}")
                if len(result['tables']) > 5:
                    print(f"            ... 等共 {len(result['tables'])} 张表")
            
            return {"success": True, "data": result}
            
        except Exception as e:
            print(f"❌ 数据库连接失败: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def test_direct_sql(self, sql: str = "SELECT 1 as test") -> Dict[str, Any]:
        """测试直接执行 SQL（不需要 LLM API key）"""
        try:
            print(f"\n🔍 测试直接 SQL: {sql}")
            response = requests.post(
                f"{self.api_url}/database/execute",
                json={"sql": sql},
                timeout=10
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get("success"):
                print("✅ SQL 执行成功")
                print(f"   返回行数: {result.get('rows_affected', 0)}")
                if result.get('data'):
                    print(f"   示例数据: {result['data'][:3]}")
            else:
                print(f"❌ SQL 执行失败: {result.get('message')}")
            
            return {"success": True, "data": result}
            
        except Exception as e:
            print(f"❌ SQL 执行失败: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def run_full_check(self):
        """运行完整的健康检查和测试"""
        print("=" * 60)
        print("🔍 Chat2Data API 健康检查")
        print("=" * 60)
        
        # 1. 检查根路径
        print("\n[1/4] 检查根路径...")
        self.check_root()
        
        # 2. 检查健康接口
        print("\n[2/4] 检查健康接口...")
        health_result = self.check_health()
        
        # 3. 测试数据库连接（不需要 API key）
        if health_result.get("success"):
            print("\n[3/4] 测试数据库连接（无需 API key）...")
            db_result = self.test_database_connection()
            
            # 4. 测试直接 SQL
            if db_result.get("success"):
                print("\n[4/4] 测试直接 SQL 执行（无需 API key）...")
                self.test_direct_sql("SELECT name FROM sqlite_master WHERE type='table' LIMIT 3")
            else:
                print("\n[4/4] ⏭️  跳过 SQL 测试（数据库不可用）")
        else:
            print("\n[3/4] ⏭️  跳过数据库测试（服务不可用）")
            print("[4/4] ⏭️  跳过 SQL 测试（服务不可用）")
        
        print("\n" + "=" * 60)
        print("检查完成")
        print("=" * 60)


def main():
    """主函数"""
    # 创建检查器实例
    checker = HealthChecker()
    
    # 运行完整检查
    checker.run_full_check()
    
    # 额外的测试示例
    print("\n\n" + "=" * 60)
    print("📝 可用的测试方法")
    print("=" * 60)
    print("\n1️⃣  测试数据库（无需 API key）:")
    print("   checker.test_database_connection()")
    print("   checker.test_direct_sql('SELECT * FROM your_table LIMIT 5')")
    print("\n2️⃣  测试 AI 查询（需要配置 LLM API key）:")
    print("   checker.test_query('查询所有用户')")
    print("   checker.test_query('统计订单数量', thread_id='session-001')")
    print("=" * 60)


if __name__ == "__main__":
    main()
