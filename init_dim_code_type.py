#!/usr/bin/env python3
"""幂等初始化 dim_code_type 码值映射表（dim_public 的 code_type_id -> 类别名 的官方对照）。

- 表不存在则 CREATE，已存在则不动（幂等，可安全重放）。
- 类别映射用 INSERT OR REPLACE 覆盖写入，后续若需增减类别，改 CODE_TYPE_MAP 后重跑即可。
- 映射来源：直接统计 dim_public.code_type_id 下出现的所有 describe 归纳。
"""
import sqlite3

DB_PATH = r"C:\Users\yhuang\bank.db"

# code_type_id -> (type_name, type_desc)
CODE_TYPE_MAP = {
    "100": ("理财卡客户类型", "紫金理财等理财卡客户等级"),
    "200": ("客户状态", "客户/账户状态：正常、冻结、挂失、销户、休眠、首次接触、紧密、回访等"),
    "300": ("证件类型", "身份证件及营业执照等：身份证、护照、军官证、驾驶证、学生证、统一社会信用代码等"),
    "400": ("风险偏好", "投资风险承受能力等级：激进、积极、稳健、保守、未知"),
    "500": ("性别", "性别：男、女、非自然人"),
    "600": ("学历", "最高学历：未知学历、博士、硕士、学士、大专、中专、高中、初中及其以下、其他"),
    "700": ("职业", "从事职业类别：军人、公务员、教师、医生、金融、证券、学生、无业、自由职业等"),
}


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 检查 dim_public 里实际的 code_type_id 集合，确保映射完整
    real_cids = set(
        row[0] for row in cur.execute("SELECT DISTINCT code_type_id FROM dim_public")
    )
    planned_cids = set(CODE_TYPE_MAP.keys())
    missing_in_planned = real_cids - planned_cids
    extra_in_planned = planned_cids - real_cids
    if missing_in_planned:
        print(
            f"警告: dim_public 中存在未规划的 code_type_id: {sorted(missing_in_planned)}，"
            f"请在 CODE_TYPE_MAP 中补全后再跑本脚本。"
        )
    if extra_in_planned:
        print(
            f"警告: CODE_TYPE_MAP 中有不在 dim_public 的 code_type_id: {sorted(extra_in_planned)}，"
            f"已忽略写入。"
        )

    # 建表（幂等）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS dim_code_type (
            code_type_id TEXT PRIMARY KEY,
            type_name    TEXT    NOT NULL,
            type_desc    TEXT
        )
        """
    )

    # 写入
    written = 0
    for cid, (name, desc) in CODE_TYPE_MAP.items():
        if cid not in real_cids:
            continue
        cur.execute(
            "INSERT OR REPLACE INTO dim_code_type (code_type_id, type_name, type_desc) VALUES (?, ?, ?)",
            (cid, name, desc),
        )
        written += 1

    conn.commit()

    # 打印结果
    rows = cur.execute(
        "SELECT code_type_id, type_name, type_desc FROM dim_code_type ORDER BY code_type_id"
    ).fetchall()
    print(f"\ndim_code_type 已固化 {written} 条映射：")
    for r in rows:
        print(f"  {r[0]:>3}  {r[1]:<10}  {r[2]}")

    conn.close()


if __name__ == "__main__":
    main()
