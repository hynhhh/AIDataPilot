#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
初始化元数据表并插入业务规则
用于解决计算总资产时遗漏外币购买资产的问题
"""

import sqlite3
import json

DB_PATH = r'C:\Users\yhuang\bank.db'



def init_metadata_tables(conn):
    """创建金融元数据表（已扩充金融特性）"""
    cursor = conn.cursor()
    
    # 1. 创建业务规则表
    # cursor.execute("""
    #     CREATE TABLE IF NOT EXISTS meta_business_rules (
    #         rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    #         rule_name TEXT NOT NULL,
    #         rule_type TEXT NOT NULL,             -- calculation, temporal, currency, filter_scope, ratio
    #         target_concept TEXT NOT NULL,         -- 目标概念/指标名称
    #         formula TEXT,                         -- SQL 公式或逻辑表达式
    #         related_columns TEXT,                 -- 关联的物理字段（JSON 数组）
    #         explanation TEXT,                     -- 业务口径详细解释
    #         examples TEXT,                        -- 推荐的 SQL 片段示例
    #         priority INTEGER DEFAULT 0,           -- 规则优先级，数值越大越先被匹配
    #         is_active BOOLEAN DEFAULT 1,
    #         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    #     )
    # """)
    
    # 2. 创建列语义表（补充了时点/时期属性、币种、安全脱敏等金融专属字段）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meta_column_semantics (
            column_id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            business_name TEXT,
            data_type TEXT,
            is_measure BOOLEAN DEFAULT 0,
            is_dimension BOOLEAN DEFAULT 0,
            calculation_type TEXT,                -- additive, non-additive等
            temporal_type TEXT DEFAULT 'flow',    -- snapshot (时点，如余额/资产) 或 flow (时期，如交易量/发生额)
            aggregation_behavior TEXT,            -- sum, avg, last_value (期末值), daily_avg (日均值)
            currency TEXT DEFAULT 'CNY',          -- CNY, USD, MULTI (多币种)
            is_sensitive BOOLEAN DEFAULT 0,       -- 是否是敏感数据（如手机号、身份证、姓名）
            related_concept TEXT,
            warning_message TEXT,
            usage_note TEXT,
            UNIQUE(table_name, column_name)
        )
    """)
    
    conn.commit()
    print("✅ 金融元数据表创建/升级成功")


def insert_business_rules(conn):
    """插入金融核心业务规则（包含多币种、时点指标防乱SUM、金融比率与过滤口径）"""
    cursor = conn.cursor()
    
    # 清空现有规则
    cursor.execute("DELETE FROM meta_business_rules")
    
    rules = [
        # --- 1. 资产与余额计算规则 ---
        {
            'rule_name': '客户总资产计算',
            'rule_type': 'calculation',
            'target_concept': '客户总资产',
            'formula': 'COALESCE(nm_tot_aset, 0) + COALESCE(fc_pur_aset, 0)',
            'related_columns': json.dumps(["nm_tot_aset", "fc_pur_aset"]),
            'explanation': '客户总资产 = 本币总资产 + 外币购买资产。注意：nm_bal和fc_bal是余额字段，不代表总资产',
            'examples': 'SUM(COALESCE(b.nm_tot_aset,0) + COALESCE(b.fc_pur_aset,0)) AS total_asset',
            'priority': 100
        },
        # --- 2. 时点指标聚合规则（解决乱SUM痛点） ---
        {
            'rule_name': '时点指标跨期聚合限制',
            'rule_type': 'temporal',
            'target_concept': '时点余额与资产',
            'formula': 'LIMIT: NO SUM OVER TIME',
            'related_columns': json.dumps(["nm_tot_aset", "fc_pur_aset", "nm_bal", "fc_bal"]),
            'explanation': '资产和余额为时点指标（snapshot），跨时间维度查询（如月、季、年）时绝对不能直接 SUM 累加！默认应取期末数（最后一天）或计算日均（AVG）。',
            'examples': '-- 查月度余额（取期末最后一天）:\nSELECT nm_bal FROM dws_cust_aset_d WHERE p_date = \'2026-08-31\'\n-- 查月日均余额:\nSELECT AVG(nm_bal) FROM dws_cust_aset_d WHERE p_date BETWEEN \'2026-08-01\' AND \'2026-08-31\'',
            'priority': 200
        },
        # --- 3. 汇率折算规则 ---
        {
            'rule_name': '外币折算本币规则',
            'rule_type': 'currency',
            'target_concept': '外币本币折算',
            'formula': 'fc_field * rate.exc_rate',
            'related_columns': json.dumps(["fc_pur_aset", "fc_bal"]),
            'explanation': '涉及外币字段参与总资产或总余额计算，且用户未指定单外币时，必须左关联汇率维表 dim_exchange_rate 并根据业务日期（p_date）的折算率（exc_rate）统一折算为人民币（CNY）。',
            'examples': 'SELECT SUM(a.nm_tot_aset + COALESCE(a.fc_pur_aset * r.exc_rate, 0)) FROM dws_cust_aset_d a LEFT JOIN dim_exchange_rate r ON a.p_date = r.p_date AND r.cur_code = \'USD\'',
            'priority': 150
        },
        # --- 4. 统计口径定义 ---
        {
            'rule_name': '活跃零售客户过滤口径',
            'rule_type': 'filter_scope',
            'target_concept': '活跃零售客户',
            'formula': 'cust_type_code = \'1\' AND acct_status = \'A\' AND last_active_days <= 30',
            'related_columns': json.dumps(["cust_type_code", "acct_status", "last_active_days"]),
            'explanation': '当用户问及“活跃零售客户”时，必须限定：1. 客户类型为个人零售（cust_type_code=\'1\'），2. 账户状态正常（acct_status=\'A\'），3. 30天内有活跃动账记录。',
            'examples': 'SELECT COUNT(DISTINCT cust_id) FROM dws_cust_info_d WHERE cust_type_code = \'1\' AND acct_status = \'A\' AND last_active_days <= 30',
            'priority': 90
        },
        # --- 5. 金融分析常用比率 ---
        {
            'rule_name': '不良贷款率计算',
            'rule_type': 'ratio',
            'target_concept': '不良贷款率',
            'formula': 'SUM(CASE WHEN loan_class IN (\'3\', \'4\', \'5\') THEN loan_bal ELSE 0 END) / SUM(loan_bal)',
            'related_columns': json.dumps(["loan_class", "loan_bal"]),
            'explanation': '不良贷款率 = (次级贷款余额 + 可疑贷款余额 + 损失贷款余额) / 全部贷款余额。五级分类代码：3-次级，4-可疑，5-损失。',
            'examples': 'SELECT SUM(CASE WHEN loan_class IN (\'3\',\'4\',\'5\') THEN loan_bal ELSE 0 END) * 1.0 / SUM(loan_bal) AS npl_ratio FROM dws_loan_info_d',
            'priority': 120
        }
    ]
    
    for rule in rules:
        cursor.execute("""
            INSERT INTO meta_business_rules (
                rule_name, rule_type, target_concept, formula,
                related_columns, explanation, examples, priority, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            rule['rule_name'],
            rule['rule_type'],
            rule['target_concept'],
            rule['formula'],
            rule['related_columns'],
            rule['explanation'],
            rule['examples'],
            rule['priority']
        ))
    
    conn.commit()
    print(f"✅ 成功导入了 {len(rules)} 条金融专属业务规则")


def ensure_meta_business_rules_table(conn):
    """若 meta_business_rules 表不存在则创建（幂等），供下面的非破坏性规则写入使用。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta_business_rules (
            rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_name TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            target_concept TEXT NOT NULL,
            formula TEXT,
            related_columns TEXT,
            explanation TEXT,
            examples TEXT,
            priority INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def insert_temporal_time_rules(conn):
    """非破坏性写入离线数仓相关规则（默认无时间过滤 / 分区键对齐 / 期间盈亏人群期末圈定）。

    按 rule_name 幂等去重：已存在则跳过，绝不删除或覆盖现有规则。
    """
    cursor = conn.cursor()

    new_rules = [
        # --- A. 离线数仓时间字段规范（默认无时间过滤，严禁硬编码当前日期） ---
        {
            'rule_name': '离线数仓时间字段规范',
            'rule_type': 'temporal',
            'target_concept': '时间字段与数据日期（默认无时间过滤）',
            'formula': "DEFAULT NO TIME FILTER；严禁硬编码当前日期（data_dt = 今天）",
            'related_columns': json.dumps(["data_dt"], ensure_ascii=False),
            'explanation': '当前数据库为非实时离线数仓。默认情况下不要对 data_dt 做任何时间过滤。除非用户明确指定了特定时间区间（如“2026 年 Q1”、“8 月份”），或 data_dt 是该查询必须关联的日快照分区键，否则严禁在 WHERE 中猜测或硬编码当前日期（如 a.data_dt=\'20260908\'）。data_dt 真实存储为 YYYYMMDD 字符串。',
            'examples': "-- 未指定时间区间：不要对 data_dt 加任何过滤\\nSELECT COUNT(*) FROM dws_cust_aset_d\\n-- 用户指定季度/月份时，才按该时段末尾取期末快照：Q1 → YYYY0331，8 月 → YYYY0831\\nSELECT * FROM dws_cust_aset_d WHERE data_dt = '20260331'",
            'priority': 210
        },
        # --- B. 日快照表分区键对齐（JOIN 防笛卡尔积膨胀） ---
        {
            'rule_name': '日快照表分区键对齐',
            'rule_type': 'temporal',
            'target_concept': '日快照表关联与分区键对齐',
            'formula': "JOIN 多个 _d 日快照表时分区键必须对齐：a.data_dt = b.data_dt",
            'related_columns': json.dumps(["data_dt"], ensure_ascii=False),
            'explanation': '当且仅当多个日快照表（通常以 _d 结尾、含 data_dt 分区键）进行 JOIN 时，必须保证它们的分区键对齐（如 a.data_dt = b.data_dt），严禁跨天/错位关联，否则会产生笛卡尔积导致数据膨胀、汇总翻倍。',
            'examples': "-- 正确：多张 _d 快照表按分区键对齐后再 JOIN\\nSELECT a.cust_id, SUM(a.nm_tot_aset)\\nFROM dws_cust_aset_d a\\nLEFT JOIN dwd_cust_hold_d b ON a.cust_id = b.cust_id AND a.data_dt = b.data_dt",
            'priority': 205
        },
        # --- C. 期间盈亏人群期末圈定（过滤回溯到期末） ---
        {
            'rule_name': '期间盈亏人群期末圈定',
            'rule_type': 'filter_scope',
            'target_concept': '期间盈亏与人物群圈定（回溯到期末）',
            'formula': "人群过滤（是否持有某产品 / 资产达标 / 客户等级）必须回溯到该时段末尾（期末）来圈定",
            'related_columns': json.dumps(["data_dt"], ensure_ascii=False),
            'explanation': '当查询“过去某特定时段（如 Q1）内”的资产变化、交易盈亏或投资表现，且包含持仓、资产规模、客户等级等限制条件时，所有人群特征过滤（是否持有某产品、资产是否达标、客户等级）必须回溯到“该特定时段末尾（期末）”来圈定，绝不能筛选“今天（最新）”满足条件的人再去查其历史资产。注意：具体 data_dt 取值见“离线数仓时间字段规范”。',
            'examples': "-- 计算 2026 年 Q1 盈亏并圈定“持有比亚迪”人群：持仓表 dwd_cust_hold_d 必须取 Q1 的最后一天（期末）\\n-- 而不是今天；若为某月，则取该月最后一天。\\nSELECT cust_id FROM dwd_cust_hold_d h WHERE h.data_dt = '20260331' AND h.prdcd = '比亚迪'",
            'priority': 190
        }
    ]

    for rule in new_rules:
        exists = cursor.execute(
            "SELECT 1 FROM meta_business_rules WHERE rule_name = ?", (rule['rule_name'],)
        ).fetchone()
        if exists:
            print(f"  ⏭️ 规则已存在，跳过: {rule['rule_name']}")
            continue
        cursor.execute("""
            INSERT INTO meta_business_rules (
                rule_name, rule_type, target_concept, formula,
                related_columns, explanation, examples, priority, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            rule['rule_name'],
            rule['rule_type'],
            rule['target_concept'],
            rule['formula'],
            rule['related_columns'],
            rule['explanation'],
            rule['examples'],
            rule['priority']
        ))
        print(f"  ✅ 新增规则: {rule['rule_name']} ({rule['rule_type']}, priority={rule['priority']})")

    conn.commit()
    print("✅ 离线数仓时间/分区相关规则写入完成（幂等）")


def insert_column_semantics(conn):
    """插入细化的列语义信息（包含时点标识、币种及安全脱敏属性）"""
    cursor = conn.cursor()
    
    # 清空现有语义
    cursor.execute("DELETE FROM meta_column_semantics")
    
    # 结构：(table_name, column_name, business_name, is_measure, temporal_type, aggregation_behavior, currency, is_sensitive, warning_message, usage_note)
    semantics = [
        # 1. 资产相关列（时点指标，期末值/日均值聚合，区分本外币）
        ('dws_cust_aset_d', 'nm_tot_aset', '本币总资产', 1, 'snapshot', 'last_value', 'CNY', 0, 
         None, '本币时点指标。计算客户总资产时，需与外币折算资产相加，跨期时切勿直接SUM'),
         
        ('dws_cust_aset_d', 'fc_pur_aset', '外币购买资产', 1, 'snapshot', 'last_value', 'MULTI', 0, 
         None, '外币时点指标。计算时需关联汇率表折算为CNY，跨期时切勿直接SUM'),
         
        # 2. 易混淆的余额列（带警告）
        ('dws_cust_aset_d', 'nm_bal', '本币余额', 1, 'snapshot', 'last_value', 'CNY', 0, 
         '这是余额时点字段，不是总资产！', '如需计算资产总额，请使用 nm_tot_aset'),
         
        ('dws_cust_aset_d', 'fc_bal', '外币余额', 1, 'snapshot', 'last_value', 'MULTI', 0, 
         '这是外币余额时点字段，不是总资产！', '如需计算资产总额，请使用 fc_pur_aset'),
         
        # 3. 客户敏感信息列（启用数据安全脱敏）
        ('dws_cust_info_d', 'cust_name', '客户姓名', 0, 'snapshot', None, None, 1, 
         '包含敏感客户隐私信息！', '生成的 SQL 或结果集输出时，必须进行掩码脱敏处理（例如：张*、*三）'),
         
        ('dws_cust_info_d', 'phone_no', '手机号', 0, 'snapshot', None, None, 1, 
         '高敏感个人数据！', '禁止明文直接输出。SQL生成必须配合掩码处理，例如：SUBSTR(phone_no, 1, 3) || \'****\' || SUBSTR(phone_no, 8)'),
         
        # 4. 贷款交易额列（典型的时期流向指标，支持常规SUM累加）
        ('dws_loan_info_d', 'loan_trd_amt', '贷款发放金额', 1, 'flow', 'sum', 'CNY', 0, 
         None, '时期流量指标。支持时间跨度上的直接 SUM 累加计算时期总发放额')
    ]
    
    for sem in semantics:
        cursor.execute("""
            INSERT INTO meta_column_semantics (
                table_name, column_name, business_name, is_measure,
                temporal_type, aggregation_behavior, currency, is_sensitive,
                warning_message, usage_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, sem)
    
    conn.commit()
    print(f"✅ 成功导入了 {len(semantics)} 条高精细度列语义信息")


def verify_metadata(conn):
    """验证金融元数据和防错标签是否正确插入"""
    cursor = conn.cursor()
    
    print("\n=== 🔍 验证金融业务规则 ===")
    cursor.execute("""
        SELECT rule_name, rule_type, target_concept, explanation 
        FROM meta_business_rules 
        WHERE is_active = 1
        ORDER BY priority DESC
    """)
    rules = cursor.fetchall()
    for rule in rules:
        print(f"[{rule[1].upper()}] 规则名: {rule[0]}")
        print(f"  -> 目标概念: {rule[2]}")
        print(f"  -> 口径解释: {rule[3]}\n")
        
    print("=== 🛡️ 验证敏感字段脱敏与时点防护拦截 ===")
    cursor.execute("""
        SELECT table_name, column_name, business_name, temporal_type, is_sensitive, warning_message
        FROM meta_column_semantics
    """)
    columns = cursor.fetchall()
    for col in columns:
        print(f"字段: {col[0]}.{col[1]} ({col[2]})")
        print(f"  -> 时点/时期: {col[3]} | 敏感脱敏: {'⚠️是' if col[4] else '否'}")
        if col[5]:
            print(f"  -> 警告提示: {col[5]}")
        print("-" * 40)


# --- 测试运行 ---




def main():
    """主函数"""
    print(f"🔧 初始化元数据表: {DB_PATH}\n")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        
        # 创建表
        init_metadata_tables(conn)
        
        # 插入业务规则
        #insert_business_rules(conn)

        # 确保 meta_business_rules 表存在（幂等）
        ensure_meta_business_rules_table(conn)

        # 非破坏性写入：离线数仓时间字段/分区对齐/期间盈亏人群圈定规则（幂等，按 rule_name 去重）
        insert_temporal_time_rules(conn)
        
        # 插入列语义
        insert_column_semantics(conn)
        
        # 验证
        verify_metadata(conn)
        
        conn.close()
        
        print("\n🎉 元数据初始化完成！")
        print("\n说明：现在当您查询总资产时，系统会自动检测并提醒需要同时使用 nm_tot_aset 和 fc_pur_aset")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        raise


if __name__ == '__main__':
    main()
