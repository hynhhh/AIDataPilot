
# import_to_sqlite.py

import sqlite3
from pathlib import Path

import pandas as pd

DB_NAME = "C:\\Users\\yhuang\\bank.db"

CSV_FILES = [
    "C:\\Users\\yhuang\\Adata\\ads_cust_info_d.csv",
    "C:\\Users\\yhuang\\Adata\\dim_branch.csv",
    "C:\\Users\\yhuang\\Adata\\dim_product.csv",
    "C:\\Users\\yhuang\\Adata\\dim_public.csv",
    "C:\\Users\\yhuang\\Adata\\dwd_cust_hold_d.csv",
    "C:\\Users\\yhuang\\Adata\\dwd_cust_tran_d.csv",
    "C:\\Users\\yhuang\\Adata\\dws_cust_aset_d.csv",
    "C:\\Users\\yhuang\\Adata\\dws_cust_fin_d.csv",
]


def main():
    conn = sqlite3.connect(DB_NAME)

    try:
        for csv_file in CSV_FILES:
            csv_path = Path(csv_file)

            if not csv_path.exists():
                print(f"❌ 文件不存在: {csv_file}")
                continue

            table_name = csv_path.stem

            print(f"📥 导入 {csv_file} -> {table_name}")

            df = pd.read_csv(
                csv_path,
                dtype=str,  # 全部按字符串导入，避免丢失前导0
                low_memory=False,
            )

            df.to_sql(
                name=table_name,
                con=conn,
                if_exists="replace",
                index=False,
            )

            print(
                f"✅ {table_name} 导入成功 "
                f"({len(df):,} rows)"
            )

        tables = pd.read_sql_query(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            ORDER BY name
            """,
            conn,
        )

        print("\n=== 数据库中的表 ===")
        print(tables)

        print(f"\n🎉 SQLite数据库已生成: {DB_NAME}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()