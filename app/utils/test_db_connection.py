"""
测试数据库连接并查看表结构
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
# app/utils/test_db_connection.py -> 向上两级到达项目根目录
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.core.database import execute_sql_query


async def test_connection():
    """测试数据库连接"""
    print("=" * 80)
    print("测试数据库连接")
    print("=" * 80)
    
    # 1. 列出所有表
    print("\n📋 查询所有表...")
    result = await execute_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    
    if result.get("success"):
        tables = result.get("data", [])
        print(f"\n✅ 找到 {len(tables)} 个表：")
        for i, table in enumerate(tables, 1):
            table_name = table.get("name") if isinstance(table, dict) else table[0]
            print(f"  {i}. {table_name}")
        
        # 2. 查看每个表的结构和数据量
        print("\n" + "=" * 80)
        print("📊 表详情")
        print("=" * 80)
        
        for table in tables:
            table_name = table.get("name") if isinstance(table, dict) else table[0]
            
            # 跳过系统表
            if table_name.startswith("sqlite_"):
                continue
            
            print(f"\n【{table_name}】")
            
            # 查看表结构
            schema_result = await execute_sql_query(f"PRAGMA table_info({table_name})")
            if schema_result.get("success"):
                columns = schema_result.get("data", [])
                print(f"  列数: {len(columns)}")
                print("  结构:")
                for col in columns[:5]:  # 只显示前5列
                    col_name = col.get("name") if isinstance(col, dict) else col[1]
                    col_type = col.get("type") if isinstance(col, dict) else col[2]
                    print(f"    - {col_name} ({col_type})")
                if len(columns) > 5:
                    print(f"    ... 还有 {len(columns) - 5} 列")
            
            # 查看数据量
            count_result = await execute_sql_query(f"SELECT COUNT(*) as count FROM {table_name}")
            if count_result.get("success"):
                count = count_result.get("data", [{}])[0].get("count", 0)
                print(f"  数据量: {count:,} 行")
            
            # 显示示例数据
            sample_result = await execute_sql_query(f"SELECT * FROM {table_name} LIMIT 3")
            if sample_result.get("success") and sample_result.get("data"):
                print("  示例数据（前3行）:")
                for i, row in enumerate(sample_result.get("data", []), 1):
                    print(f"    第{i}行: {dict(list(row.items())[:3])}..." if isinstance(row, dict) else f"    第{i}行: {row[:3]}...")
    else:
        print(f"❌ 查询失败: {result.get('message')}")
    
    print("\n" + "=" * 80)
    print("测试完成！")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_connection())