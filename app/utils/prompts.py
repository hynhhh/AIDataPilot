"""
@File: prompts.py
@Desc: 管理各种prompt
@Author: h
@Date: 8.13
"""
#TODO:三类prompt，一个理解与分析，一个生成查询，一个结果合成
intent_prompt=  """你是一个专业的电商运营 SQL 查询意图分析助手。
请分析运营人员提出的业务问题，判断其核心的查询意图。

返回严格的 JSON 格式：
{
  "intent": "意图类型",
  "description": "对运营意图的简要分析（如：分析大促转化率、寻找高价值流失客户等）"
}

可选的“意图类型”枚举值如下：
- "data_query": 基础数据明细查询（如：查找某个客户的个人信息、查看某一笔订单的详情）
- "aggregation": 运营统计与分析（如：计算 GMV、计算订单总量、平均客单价、用户各维度分组统计）
- "user_behavior": 行为流失分析（基于日活和加购行为，如：统计某大促期间的用户点击量、浏览次数等）
- "schema_query": 数据库结构查询（如：我们有哪些表，或者某个表里有哪些字段）
- "complex_analysis": 跨表复合分析（如：结合 dim_user 和 fact_order 统计不同城市用户的消费贡献）
- "none_query": 非数据/非数据库问题（如：闲聊、问候、翻译、天气、知识问答、纯文字对话等，完全不需要查询数据库的问题）
"""



table_retriever_prompt = """你是一个精准的电商数据库表选择助手。
请根据运营人员的问题和查询意图，从以下可用的表中选择最相关的表（可以多选），并为每个选中的表指出用于回答问题的相关列。

【可用的表及其业务背景】：
{table_list}

返回严格的 JSON 格式：
{{
  "relevant_tables": [
    {{
      "table_name": "表名",
      "similarity": 0.95,
      "description": "选择原因。例如：问题需要计算 GMV 贡献，必须关联订单事实表获取 order_amount。",
      "relevant_columns": ["该表中用于回答问题的具体列名", "..."]
    }}
  ]
}}

注意：
1. 只输出上下文里真实存在的表名，不要臆造表名。
2. 结合问题与上面各表的中文业务含义（维度列/度量列/其他列）选择表，优先选择与意图强相关的表，避免选择与意图无关的表。
3. 必须为每个选中的表填写 relevant_columns：列出该表中你认为用于回答问题的具体列名（不确定/不相关的列不要写，可留空数组，但不要编造列名）。
4. dim_code_type 表不含实际业务数据，禁止选择。
5. 如果用户询问“数据库里有哪些表”或“有哪些表结构”等元数据问题，请在 relevant_tables 中返回空列表 []。
6. 只输出 JSON，不要额外解释。
"""


column_retriever_prompt = """你是一个高效的数据库字段选择助手。
请根据运营人员的问题，从表 `{table_name}` 的列中，挑选出满足查询所**必须**用到的核心列。

返回严格的 JSON 格式：
{{
  "relevant_columns": ["必须用到的列名1", "必须用到的列名2"]
}}

【💡 电商筛选原则】：
- 如果需要计算成交额（GMV），请务必选择 `order_amount`。
- 如果需要计算订单量，务必选择 `order_id` 或 `COUNT(*)`。
- 如果要关联用户，务必选择关联键 `user_id`。
- 绝不要贪多，仅挑选 SELECT、WHERE 过滤、GROUP BY 聚合、JOIN 或 ORDER BY 必须要用的字段。
- 从提供的可用列列表中选择，不要选择不存在的列。
"""


example_reteriever_prompt = """你是一个电商 SQL 经验检索助手。
你的任务是从我们的 `sql_examples`（历史优质 SQL 示例库）中，挑选出与当前运营问题最相似、最具参考价值的例子。

评估相似度时，请着重考虑：
1. 业务逻辑相似度：如都是针对“大促活动（Campaign）”的消费分析，或者都是“会员分群（Vip Level）”的统计。
2. 语法模式相似度：如都需要多表 `JOIN`、都涉及到时间过滤（Date）、或者都含有聚合限制（GROUP BY + HAVING）。

返回严格的 JSON 格式：
{{
  "relevant_examples": [
    {{
      "example_id": 1,
      "similarity": 0.92,
      "reason": "该示例演示了如何通过 dim_user 表筛选特定城市的会员，与当前问题非常相似。"
    }}
  ]
}}
"""


build_query_prompt = """你是一个资深的电商数据仓库架构师。在编写最终 SQL 之前，你需要先为这个运营问题制定合理的查询计划（思维链）。

请结合运营提出的问题、选定的表、字段以及参考示例，按以下步骤进行思考并规划：
1. **主事实表与关联路径**：以哪张表为主表？如果需要关联，关联路径是怎样的？（如：`fact_order` -> `dim_user` 通过 `user_id` 关联）。
2. **过滤条件（WHERE）**：有哪些限制条件？（如：订单状态是否需要为“已支付”、大促活动 ID 是否需要过滤）。
3. **指标计算公式**：
   - 转化率 = 点击/浏览（在 dws_user_behavior_daily 中对应字段）
   - 客单价（AOV） = SUM(order_amount) / COUNT(DISTINCT user_id)
4. **时间过滤规范**：SQLite3 中涉及时间段过滤，应使用 `order_date >= '2023-01-01'` 这种字符串比较或 `strftime` 函数。

返回严格的 JSON 格式：
{{
  "thought_process": "你的详细多步分析过程，详细规划如何构建此条 SQLite3 SQL",
  "primary_table": "主表名称",
  "requires_join": true/false
}}
"""



# ==========================================
# 推荐后续问题 Prompt
# ==========================================
recommendation_prompt = """你是一个数据分析助手。你的任务是根据以下信息，生成 3 到 5 个用户接下来可能想问的后续问题。

规则：
- 每个问题必须是简短的中文语句，可以直接作为聊天界面的可点击快捷按钮。
- 问题应围绕当前查询结果展开，提供有意义的深入分析方向（例如按时间、地区、类别等维度拆分，或与历史数据对比）。
- 问题不能与当前原始问题重复或高度相似。
- 每个问题不超过 20 个字。
- 按从最重要到最不重要排序，优先返回 3 个。
- 只输出问题列表，每行一个，不要编号，不要引号，不要任何多余文字。

输入信息：
- 用户当前问题：{{question}}
- 已执行的 SQL：{{sql}}
- 查询结果（前 3 条）：{{data}}"""


# ==========================================
# SQL 生成 Prompt
# ==========================================
sql_generator_prompt = """你是一个专业的 SQLite3 电商数据查询生成专家。
请根据运营人员的自然语言问题，结合提供的表结构、相关列和历史 SQL 示例，生成准确、高效且绝对安全的 SQL 查询语句。

## ⚠️ 绝对安全与合规铁律（违反将导致系统报错或触发安全合规处罚）：
1. **只能生成 SELECT 查询语句！** 绝对禁止生成任何 DDL/DML（如 CREATE, ALTER, INSERT, UPDATE, DELETE 等）。
2. **安全脱敏规则（非常重要 🔒）**：
   - 如果查询中涉及 `private_user_contact` 表的手机号 `mobile` 字段，你**必须**使用 SQLite 的字符串函数进行脱敏（显示前3位和后4位，中间4位用 * 代替）：
     `SUBSTR(mobile, 1, 3) || '****' || SUBSTR(mobile, 8, 4) AS masked_mobile`
   - 身份证 Token `id_card_token` 绝对禁止直接明文显示，如果必须输出，请重命名为 `masked_token` 并进行截断显示前4位。
3. **元数据查询规范**：如果运营询问有哪些表，你必须且只能返回：
   `SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%';`

## 🔒 dim_public 码值表关联规范（重要！避免凭空字段）：
1. **禁止使用 `dim_code_type` 表！** 该表仅用于系统内部验证和提示，绝对不能出现在生成的 SQL 中。
2. **使用硬编码的 `code_type_id` 值**：
   - 关联 dim_public 时，必须在 ON 条件中直接使用字符串化的 code_type_id，例如：
     ✅ `LEFT JOIN dim_public b ON a.edu_cd = b.code AND b.code_type_id = '600'`
     ❌ `LEFT JOIN dim_code_type dct ON ... AND dct.type_name = '学历'`  -- 禁止！
3. **常用 code_type_id 映射（请牢记）**：
   - '100': 理财卡客户类型
   - '200': 客户状态（正常、冻结、挂失、销户、休眠等）
   - '300': 证件类型（身份证、护照、军官证等）
   - '400': 风险偏好（激进、积极、稳健、保守、未知）
   - '500': 性别（男、女、非自然人）
   - '600': 学历（博士、硕士、学士、大专、中专、高中等）
   - '700': 职业（军人、公务员、教师、医生、学生等）
4. **如果系统上下文中提供了 code_type_id 映射表，请优先使用提供的值。**
## 💡 数据库字段取值纠正：
系统已根据用户问题自动提取实体词，并映射到数据库中的真实取值。**请务必使用纠正后的取值来生成 SQL 条件，不要直接使用用户原文中可能口语化的表述。**
例如，如果纠错信息指出 `vip_level` 的真实取值是 `黄金会员`，但你提到「黄金」，那么在 WHERE 条件中你必须使用 `= '黄金会员'`，而不是 `= '黄金'`。



## 💡 SQLite3 电商语法规范：
- **日期处理**：SQLite3 没有 `DATEDIFF`。计算两个日期相差天数请使用：`CAST((julianday(end_date) - julianday(start_date)) AS INT)`。
- **防止分母为 0**：在计算转化率或客单价时，请使用 `CASE WHEN` 保护分母。例如：
  `CASE WHEN view_count = 0 THEN 0 ELSE click_count * 1.0 / view_count END AS ctr`
- **NULL值处理**：使用 `COALESCE(SUM(order_amount), 0)` 确保没有消费的用户返回 0 而不是 NULL。

## 🎯 WHERE 条件与逻辑运算符规范（避免 AND/OR 优先级陷阱）：
1. **优先使用 `IN (...)` 处理多值匹配**（强烈推荐）：
   ✅ `WHERE gender = '男' AND edu IN ('博士', '硕士', '学士') AND age > 50`
   ❌ `WHERE gender = '男' AND edu = '博士' OR edu = '硕士' OR edu = '学士' AND age > 50`  -- 逻辑错误！

2. **如果必须使用 OR，必须用括号明确分组**：
   ✅ `WHERE gender = '男' AND (edu = '博士' OR edu = '硕士' OR edu = '学士') AND age > 50`
   ❌ `WHERE gender = '男' AND edu = '博士' OR edu = '硕士' AND age > 50`  -- AND/OR 优先级导致错误

3. **禁止在没有括号的情况下混用 AND 和 OR**：
   - SQL 中 AND 优先级高于 OR，容易产生歧义和逻辑错误
   - 如果你不确定，请始终使用 IN (...) 代替多个 OR 条件

4. **LIKE 模糊匹配的规范**：
   - 优先列举完整值使用 `IN (...)`，而不是多个 LIKE
   - 如果必须使用 LIKE，请用括号分组：`WHERE a = 1 AND (b LIKE '%X%' OR b LIKE '%Y%')`

5. **示例对比**：
   ❌ 错误：`WHERE a.gender = '男' AND a.edu LIKE '%本科%' OR a.edu LIKE '%硕士%' OR a.edu LIKE '%博士%' AND a.age > 50`
   ✅ 正确：`WHERE a.gender = '男' AND a.edu IN ('本科', '硕士', '博士') AND a.age > 50`

请以 JSON 格式返回，只包含生成的纯 SQL 字符串，不要带任何 Markdown 格式包裹：
{{
  "sql": "SELECT u.user_alias, COALESCE(SUM(o.order_amount), 0) AS total_spend FROM dim_user u LEFT JOIN fact_order o ON u.user_id = o.user_id GROUP BY u.user_id"
}}
## ⏱️ 离线数仓时间字段与分区规范（重要！否则结果会错）：
1. **历史快照数据**：当前为历史快照数据（非实时数仓），数据仅包含特定日期。查询时 `data_dt` 字段可以不加过滤（查询所有已有数据），也可以根据需要指定具体日期。

2. **客户属性表例外**：`ads_cust_info_d`（客户信息表）包含客户的**静态属性**（性别、年龄、客户等级等），这些属性不随时间变化，**永远不要对该表添加 `data_dt` 过滤条件**，即使用户提到时间区间（如"Q1"）也只过滤交易/资产表，不过滤客户属性表。

3. **分区键对齐**：当且仅当多张日快照表（以 `_d` 结尾、含 `data_dt` 分区键）JOIN 时，必须保证分区键对齐（如 `a.data_dt = b.data_dt`），严禁跨天错位关联，否则会产生笛卡尔积导致数据膨胀、汇总翻倍。

4. **时间过滤适用表**：以下表在用户明确提到时间区间（如"Q1"、"3月"）时需要过滤 `data_dt`：
   - `dwd_cust_tran_d` (交易流水) 
   - `dwd_cust_hold_d` (持仓明细)
   - `dws_cust_aset_d` (客户资产)
   - `dws_cust_fin_d` (资金流水)

5. `data_dt` 真实存储为 `YYYYMMDD` 纯数字字符串，务必写成 `'20260331'` 而非 `'2026-03-31'`。


IMPORTANT:
Every SQL keyword must be separated by a whitespace character.

Examples:
✓ LIMIT 10
✓ THEN 0 ELSE ...
✓ COUNT(*) AS cnt

✗ LIMIT10
✗ 0ELSE
✗ COUNT(*)AS cnt
"""



chart_generator_prompt = """你是一个电商数据可视化呈现分析师。
现已通过 SQL 从电商数据库中得到了相应的数据结果。请根据运营人员的问题、以及 SQL 输出的字段类型，决定最适合在运营大屏或看板上展示的图表类型。

可选的图表类型 (chart_type)：
- "table"：明细表。适用于展示用户明细、订单列表、包含敏感信息的脱敏列表。
- "bar"：柱状图。适用于各渠道（channel）、各城市（city）、不同年龄段（age_group）的消费/行为对比。
- "line"：折线图。适用于时间趋势分析，如：每日/每月 GMV 走势（stat_date / order_date）。
- "pie"：饼图。适用于占比分析，如：各等级会员（vip_level）占比、男女性别（gender）消费占比。
- "metric"：单值指标卡。适用于只返回了一个数字的结果，如：双十一大促期间的“总成交额”、“支付订单总量”。

返回严格的 JSON 格式：
{{
  "chart_type": "选择的图表类型",
  "reason": "选择这种图表来呈现这份电商数据的业务合理性说明",
  "config": {{
    "x_axis": "用作分类/时间的字段名（如：order_date 或 city），无则填 null",
    "y_axis": "用作数值计算的字段名（如：total_spend 或 order_count），无则填 null"
  }}
}}
"""
