"""
最简单的数据库测试脚本
直接运行: python quick_test.py
"""
import sqlite3
import os

# 从环境变量或默认路径读取数据库
db_path = r"C:\Users\yhuang\Downloads\ecommerce_demo.sqlite3"

print("=" * 80)
print("🔍 数据库快速测试")
print("=" * 80)
print(f"\n📁 数据库路径: {db_path}")

# 检查文件是否存在
if not os.path.exists(db_path):
    print(f"❌ 错误: 数据库文件不存在！")
    print(f"   请确认路径: {db_path}")
    exit(1)

print(f"✅ 数据库文件存在 ({os.path.getsize(db_path):,} 字节)")

try:
    # 连接数据库
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("\n✅ 数据库连接成功！")
    
    # 列出所有表
    print("\n" + "=" * 80)
    print("📋 数据库表列表")
    print("=" * 80)
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cursor.fetchall()
    
    print(f"\n找到 {len(tables)} 个表：\n")
    
    for i, row in enumerate(tables, 1):
        table_name = row['name']
        
        # 跳过系统表
        if table_name.startswith('sqlite_'):
            continue
        
        print(f"{i}. {table_name}")
        
        # 获取表结构
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        print(f"   列数: {len(columns)}")
        print(f"   字段: ", end="")
        col_names = [col['name'] for col in columns[:5]]
        print(", ".join(col_names), end="")
        if len(columns) > 5:
            print(f" ... (共{len(columns)}个)")
        else:
            print()
        
        # 获取行数
        cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
        count = cursor.fetchone()['count']
        print(f"   数据量: {count:,} 行")
        
        # 示例数据
        if count > 0:
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 2")
            samples = cursor.fetchall()
            print(f"   示例:")
            for j, sample in enumerate(samples, 1):
                # 显示前3个字段
                sample_dict = dict(sample)
                first_three = dict(list(sample_dict.items())[:3])
                print(f"      {j}. {first_three}")
        
        print()
    
    conn.close()
    
    print("=" * 80)
    print("✅ 测试完成！数据库可以正常访问")
    print("=" * 80)
    print("\n💡 提示: 现在可以运行 'python app\\main.py' 启动服务")
    
except Exception as e:
    print(f"\n❌ 错误: {e}")
    import traceback
    traceback.print_exc()
