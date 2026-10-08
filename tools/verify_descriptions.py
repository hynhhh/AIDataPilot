"""验证表描述数据库"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.utils.distinct_values import TableDescriptionGenerator, VECTOR_DB_PATH
import sqlite3


def main():
    print("=" * 60)
    print("📋 验证表描述数据库")
    print("=" * 60)
    
    # 检查数据库文件是否存在
    if not os.path.exists(VECTOR_DB_PATH):
        print(f"❌ 数据库不存在：{VECTOR_DB_PATH}")
        return
    
    print(f"数据库路径：{VECTOR_DB_PATH}")
    print()
    
    # 直接查询数据库
    conn = sqlite3.connect(VECTOR_DB_PATH)
    cursor = conn.cursor()
    
    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='table_descriptions'")
    table_exists = cursor.fetchone()
    
    if not table_exists:
        print("❌ table_descriptions 表不存在")
        conn.close()
        return
    
    print("✅ table_descriptions 表存在")
    print()
    
    # 查询所有记录
    cursor.execute("SELECT * FROM table_descriptions")
    rows = cursor.fetchall()
    
    print(f"共有 {len(rows)} 条表描述记录:")
    print()
    
    for row in rows:
        print(f"  表名：{row[0]}")
        print(f"  描述：{row[1] or '无'}")
        print(f"  列数：{len(row[2]) if row[2] else 0}")
        print()
    
    conn.close()
    print("✅ 验证完成!")


if __name__ == "__main__":
    main()