"""离线扫描业务数据库，提取所有分类字段的唯一取值，构建 TF-IDF 向量索引。

用法:
    python tools/build_vector_index.py [--generate-descriptions]

依赖:
    - SQLite3 业务数据库：C:/Users/yhuang/bank.db
    - 输出到：C:/Users/yhuang/bank_vector_index.sqlite3
    - 纯 Python stdlib，无需额外依赖

参数:
    --generate-descriptions: 同时为所有表生成业务描述并存储
"""
import sys
import os
import sqlite3
import argparse

# 将 app/ 加入 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.utils.distinct_values import ColumnValueIndex, TableDescriptionGenerator

try:
    from app.core.llm import get_model
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    print("[WARNING] 无法导入 LLM 模块，表描述将使用默认值")


def _get_table_schema(business_db: str, table_name: str) -> dict:
    """获取表结构的同步函数"""
    conn = sqlite3.connect(business_db)
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns_info = cursor.fetchall()
    conn.close()
    
    columns = []
    for col in columns_info:
        columns.append({"name": col[1]})
    
    return {"columns": columns}


def main():
    # 设置 UTF-8 输出
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    
    parser = argparse.ArgumentParser(description="离线向量索引构建工具")
    parser.add_argument("--generate-descriptions", action="store_true", 
                       help="同时为所有表生成业务描述并存储")
    args = parser.parse_args()
    
    # 业务数据库路径（硬编码）
    business_db = r"C:\\Users\\yhuang\\bank.db"
    print("=" * 60)
    print("[INFO] 离线向量索引构建工具")
    print("=" * 60)
    print(f"  业务数据库：{business_db}")
    print(f"  输出索引：   C:\\Users\\yhuang\\bank_vector_index.sqlite3")
    print("=" * 60)

    # 检查业务数据库是否存在
    if not os.path.exists(business_db):
        print(f"[ERROR] 业务数据库不存在：{business_db}")
        sys.exit(1)

    # 构建索引
    index = ColumnValueIndex()
    result = index.extract_and_store(business_db_path=business_db)

    print()
    print("[OK] 抽取完成!")
    print(f"  扫描表数：{result['tables_scanned']}")
    print(f"  分类列数：{result['categorical_columns']}")
    print(f"  唯一取值：{result['total_values']}")
    
    # 可选：生成表描述
    if args.generate_descriptions:
        print()
        print("=" * 60)
        print("[INFO] 生成表描述...")
        print("=" * 60)
        
        # 获取所有表
        conn = sqlite3.connect(business_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = [t[0] for t in cursor.fetchall()]
        conn.close()
        
        # 准备 LLM
        llm = None
        if LLM_AVAILABLE:
            try:
                llm = get_model()
                print("[INFO] LLM 已准备就绪")
            except Exception as e:
                print(f"[WARNING] LLM 初始化失败：{e}")
                print("[INFO] 将使用默认描述")
        
        # 生成描述
        generator = TableDescriptionGenerator(llm=llm, db_path=index.db_path)
        results = generator.generate_and_store_all(all_tables, lambda t: _get_table_schema(business_db, t))
        
        print()
        print(f"[OK] 表描述生成完成！共 {len(results)} 个表")

    print()
    print(f"[INFO] 索引文件：C:\\Users\\yhuang\\bank_vector_index.sqlite3")


if __name__ == "__main__":
    main()