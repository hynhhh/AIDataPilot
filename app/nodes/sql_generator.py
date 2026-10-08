"""
@File: sql_generator.py
@Desc: node2,组装prompt,调用llm生成sql
@Author: h
@Date: 8.13
"""
import json
import logging
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage

from core.llm import get_model
from graph.state import Chat2DataState
from utils.prompts import sql_generator_prompt
from utils.output_schema import generate_structured_data
from utils.output_schema import SQLGeneratorResponse
from utils.distinct_values import build_context_for_sql_generation
from datetime import datetime

logger = logging.getLogger(__name__)
current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def build_sql_generation_context(state: Chat2DataState, slim_mode: bool = False) -> str:
    """
    构建 SQL 生成的上下文信息
    
    Args:
        state: Chat2DataState 状态字典
        slim_mode: 是否使用瘦身模式（业务规则错误时使用）
        
    Returns:
        str: 格式化的上下文信息
    """
    context_parts = []
    context_parts.append(f"## 当前日期\n{current_time_str}")
    # 1. 用户问题和意图
    context_parts.append(f"## 用户问题\n{state.get('question', '')}")
    context_parts.append(f"\n## 问题意图\n{state.get('intent', '')}")
    
    # 瘦身模式：跳过重内容，只保留核心信息
    if not slim_mode:
        # 2. 相关表信息
        relevant_tables = state.get('relevant_tables', [])
        if relevant_tables:
            tables_info = []
            for table in relevant_tables:
                table_name = table.get('table_name', '')
                description = table.get('description', '')
                tables_info.append(f"- {table_name}: {description}")
            context_parts.append(f"\n## 相关表\n" + "\n".join(tables_info))
        
        # 3. 表结构（DDL）
        schema_info = state.get('schema_info', {})
        if schema_info and schema_info.get('formatted_ddl'):
            context_parts.append(f"\n## 数据库表结构\n{schema_info['formatted_ddl']}")
        
        # 4. 相关列信息
        relevant_columns = state.get('relevant_columns', {})
        if relevant_columns:
            columns_info = []
            for table_name, columns in relevant_columns.items():
                columns_info.append(f"- {table_name}: {', '.join(columns)}")
            context_parts.append(f"\n## 相关列\n" + "\n".join(columns_info))
        
        # 5. Few-shot 示例
        few_shot_examples = state.get('few_shot_examples', [])
        if few_shot_examples:
            examples_info = []
            for i, example in enumerate(few_shot_examples, 1):
                question = example.get('question', '')
                sql = example.get('sql', '')
                tables = example.get('tables', [])
                similarity = example.get('similarity', 0)
                
                # 格式化相似度为百分比
                similarity_pct = f"{similarity:.2%}" if isinstance(similarity, (int, float)) else str(similarity)
                
                # 格式化涉及表信息
                tables_str = ', '.join(tables) if isinstance(tables, list) else str(tables)
                
                examples_info.append(
                    f"### 示例 {i} (相似度: {similarity_pct})\n"
                    f"问题: {question}\n"
                    f"涉及表: {tables_str}\n"
                    f"SQL:\n```sql\n{sql}\n```"
                )
            context_parts.append(f"\n## 参考示例（历史优质SQL）\n" + "\n\n".join(examples_info))
    else:
        # 瘦身模式：只添加业务规则（从 schema_info 提取）
        schema_info = state.get('schema_info', {})
        business_rules = schema_info.get('business_rules', [])
        if business_rules:
            rules_info = []
            for rule in business_rules:
                rule_name = rule.get('rule_name', '')
                rule_description = rule.get('rule_description', '')
                rules_info.append(f"- {rule_name}: {rule_description}")
            context_parts.append(f"\n## 业务规则（务必遵守）\n" + "\n".join(rules_info))
    
    # 6. 实体纠错信息（从 schema_retreiver 注入）
    entity_corrections = state.get("entity_corrections", [])
    if entity_corrections:
        correction_block = build_context_for_sql_generation(entity_corrections)
        if correction_block:
            context_parts.append(f"\n{correction_block}")
    
    # 7. 失败重试历史（从 sql_executor 注入）
    error_history = state.get("error_message", [])
    if isinstance(error_history, str):
        error_history = [error_history] if error_history else []
    sql_history = state.get("sql_history", [])
    if isinstance(sql_history, str):
        sql_history = [sql_history] if sql_history else []
    if error_history or sql_history:
        retry_note = f"## 失败重试记录（共 {len(error_history)} 次失败）\n\n"
        for i, (err, failed_sql) in enumerate(
            zip(error_history, sql_history), 1
        ):
            retry_note += (
                f"### 失败 {i}\n"
                f"失败的 SQL:\n```sql\n{failed_sql}\n```\n\n"
                f"错误信息:\n{err}\n\n"
            )
        retry_note += "请根据以上失败记录，避免重复同样的错误，重新生成正确的 SQL。"
        context_parts.append(f"\n{retry_note}")
    
    # 7.5. 客户总资产计算的固定强提示（硬性约束：本币 + 外币购买资产）
    # 说明：业务规则检索可能在问题措辞不匹配时漏判，这里用固定知识兜底，
    #      确保任何生成时刻模型都知晓“总资产必须同时加上外币购买资产”。
    total_asset_rule = """
## 💰 总资产计算的硬性规则（务必遵守）

当 SQL 中需要统计/汇总“客户总资产”（如 total_asset、总资产、资产合计等）时：

- **客户总资产 = 本币总资产 + 外币购买资产**
- 必须同时使用两个字段：`dws_cust_aset_d.nm_tot_aset`（本币总资产）和
  `dws_cust_aset_d.fc_pur_aset`（外币购买资产），**二者相加**，不能只用其中任意一个。
- 正确写法：
  ```sql
  SUM(COALESCE(b.nm_tot_aset, 0) + COALESCE(b.fc_pur_aset, 0)) AS total_asset
  ```
- 错误写法：`SUM(COALESCE(b.nm_tot_aset, 0))`（会遗漏外币购买资产）
- 注意：`nm_bal` / `fc_bal` 是余额字段，不代表总资产，计算总资产时不要使用。
"""
    context_parts.append(f"\n{total_asset_rule}")

    # 7.6. 查询结构与范式固定强提示（硬性约束：先聚合再 JOIN、CTE 递减收窄、HAVING、贴合源表格式）
    # 说明：现有提示词只教了"条件怎么写"，没教"查询怎么组装"。模型拿到一堆条件后最自然的做法是
    #      扁平 JOIN + 条件全塞 WHERE，会在"一人多行"明细表上产生行膨胀，导致 SUM 翻倍。
    #      用固定知识兜底，确保任何检索结果下模型都遵循与参考 SQL 一致的结构范式。
    structure_rule = """
## 📐 查询结构与范式铁律（务必遵守，否则结果会翻倍错误）

1. **先聚合、再 JOIN**（防止行膨胀）：
   当需要关联"一人多行"的明细表（如资金流水 dws_cust_fin_d、持仓 dwd_cust_hold_d 等），
   且这些表的行数可能使最终结果翻倍时，**禁止直接把该明细表 INNER JOIN 进主查询再 GROUP BY**。
   必须先在子查询/CTE 中按主键聚合到"每人一行"，再 LEFT JOIN 该聚合结果：
   ```sql
   -- ✅ 正确：先在子查询里按 pty_id 塌缩到每人一行，再 LEFT JOIN
   LEFT JOIN (
       SELECT pty_id,
              SUM(cash_in) + SUM(tran_in) + SUM(assign_in) AS aset_in,
              SUM(cash_out) + SUM(tran_out) + SUM(assign_out) AS aset_out
       FROM dws_cust_fin_d
       WHERE data_dt BETWEEN '20260101' AND '20260331'
       GROUP BY pty_id
   ) d ON a.pty_id = d.pty_id
   ```

2. **先圈定人群、再逐级收窄（用 CTE + EXISTS）**：
   - 先用一个 CTE 只 SELECT 满足基础筛选条件的 pty_id（如客户类型、性别、年龄）；
   - 后续表通过 `EXISTS(SELECT 1 FROM 人群CTE z WHERE a.pty_id = z.pty_id)` 判断归属，
     不要直接把筛选表 JOIN 进主查询，避免把维度表/筛选表 JOIN 进来导致行膨胀。

3. **"合计超过阈值"用 GROUP BY + HAVING**：
   对于"某人 X 合计 > 阈值"（如持仓市值合计 > 1000），必须 GROUP BY pty_id 后再
   `HAVING SUM(mkt_val) > 1000`，而不是 WHERE 里过滤单行 `mkt_val > 1000`（那是"单只超过"，语义不同）。

4. **日期/取值必须贴合源表真实格式**：
   - 严格使用 schema 中 `data_dt` 等字段的真实取值格式（如源表存的是 `YYYYMMDD` 字符串，就写 `'20260331'`，
     不要写成 `'2026-03-31'`；可直接参考上面样例里 `data_dt BETWEEN '20260101' AND '20260331'`）。
   - 筛选维码值时，使用实体纠错后的真实取值，用 `=` 或 `IN(...)` 精确匹配，不要自创 `LIKE '%x%'`。
"""
    context_parts.append(f"\n{structure_rule}")
    
    # 7.7. 【新增】字段防错与快照绑定提示（建议三：Generator优化）
    field_safety_rule = """
## 🛡️ 字段与快照表的防错规则（必须遵守）

**1. 字段拼写防错**：
- 金融数仓交易金额字段通常为 `buy_amt` / `sell_amt` / `trade_amt`（Amount）
- ❌ 避免拼写成 `buy_mnt` / `sell_mnt` 等不存在的字段
- ❌ 避免将 `asset`（资产）误写为 `aset`（除非表结构明确使用此缩写）

**2. 快照表日期绑定**（避免笛卡尔积/内存溢出）：
- 关联日终资产、持仓等每日快照表时，**当多张 `_d` 快照表 JOIN 时，务必在 JOIN ON 条件中对齐 `data_dt`**
- 正确写法：
  ```sql
  FROM dws_cust_aset_d AS a
  LEFT JOIN dwd_cust_hold_d AS b 
    ON a.cust_no = b.cust_no 
    AND a.data_dt = b.data_dt  -- 分区键对齐
  ```
- 错误写法（会导致笛卡尔积）：
  ```sql
  FROM dws_cust_aset_d AS a
  LEFT JOIN dwd_cust_hold_d AS b 
    ON a.cust_no = b.cust_no  -- 缺少 data_dt 对齐条件
  ```

**3. 日期格式验证**：
- 确保 `data_dt` 使用正确的格式（如 `'YYYYMMDD'` 或数据库实际格式）
- 检查日期范围是否在合理区间（如最近一年）
"""
    context_parts.append(f"\n{field_safety_rule}")


    # 8. dim_public code_type_id 映射表（固定知识，确保模型使用正确的值）
    code_type_mapping = """
## dim_public 码值类别映射（关联 dim_public 时必须参考）

在使用 dim_public 表时，必须在 JOIN 条件中指定 code_type_id 来区分不同类别的码值：

| code_type_id | 类别名称       | 典型取值示例                                      |
|--------------|----------------|---------------------------------------------------|
| '100'        | 理财卡客户类型 | 紫金理财等                                        |
| '200'        | 客户状态       | 正常、冻结、挂失、销户、休眠、首次接触、紧密、回访 |
| '300'        | 证件类型       | 身份证、护照、军官证、驾驶证、学生证、统一社会信用代码等 |
| '400'        | 风险偏好       | 激进、积极、稳健、保守、未知                      |
| '500'        | 性别           | 男、女、非自然人                                  |
| '600'        | 学历           | 未知学历、博士、硕士、学士、大专、中专、高中、初中及其以下、其他 |
| '700'        | 职业           | 军人、公务员、教师、医生、金融、证券、学生、无业、自由职业等 |

**关联示例（请严格遵循此模式）**：
```sql
-- ✅ 正确：查询男性客户
LEFT JOIN dim_public dp_gender 
  ON a.gender_cd = dp_gender.code 
  AND dp_gender.code_type_id = '500'
WHERE dp_gender.describe = '男'

-- ✅ 正确：查询本科及以上学历（使用 IN）
LEFT JOIN dim_public dp_edu 
  ON a.edu_cd = dp_edu.code 
  AND dp_edu.code_type_id = '600'
WHERE dp_edu.describe IN ('博士', '硕士', '学士')

-- ✅ 正确：更简洁的别名写法
LEFT JOIN dim_public b ON a.edu_cd = b.code AND b.code_type_id = '600'
LEFT JOIN dim_public c ON a.gender_cd = c.code AND c.code_type_id = '500'
WHERE b.describe IN ('博士', '硕士', '学士') AND c.describe = '男'

-- ❌ 错误：不要关联 dim_code_type 表！
LEFT JOIN dim_code_type dct ON ...  -- 禁止！该表仅用于系统内部验证
```

**重要提醒**：
- dim_code_type 表仅用于系统验证，不是业务表，绝对不能出现在 SQL 中
- 必须使用硬编码的 code_type_id 字符串值（如 '500'、'600'）
- 多个取值优先使用 IN (...) 而不是多个 OR
"""
    context_parts.append(code_type_mapping)
    
    return "\n".join(context_parts)


# def extract_sql_from_response(response_content: str) -> str:
#     """
#     从 LLM 响应中提取 SQL 语句
    
#     Args:
#         response_content: LLM 的响应内容
        
#     Returns:
#         str: 提取的 SQL 语句
#     """
#     # 尝试从 JSON 格式中提取
#     try:
#         data = json.loads(response_content)
#         if isinstance(data, dict) and 'sql' in data:
#             return data['sql']
#     except:
#         pass
    
#     # 尝试从 markdown 代码块中提取
#     if '```sql' in response_content:
#         start = response_content.find('```sql') + 6
#         end = response_content.find('```', start)
#         if end != -1:
#             return response_content[start:end].strip()
    
#     if '```' in response_content:
#         start = response_content.find('```') + 3
#         end = response_content.find('```', start)
#         if end != -1:
#             return response_content[start:end].strip()
    
#     # 如果都不是，返回整个响应（去除空白）
#     return response_content.strip()


# async def sql_generator(state: Chat2DataState) -> Chat2DataState:
#     """
#     SQL 生成节点函数
    
#     根据 state 中检索到的信息（intent, relevant_tables, relevant_columns, 
#     schema_info, few_shot_examples）生成 SQL 查询语句
    
#     Args:
#         state: Chat2DataState 状态字典
        
#     Returns:
#         Chat2DataState: 更新后的状态，包含 generated_sql
#     """
#     # 构建上下文信息
#     context = build_sql_generation_context(state)
    
#     # 构建完整的 prompt
#     full_prompt = f"""{sql_generator_prompt}


# {context}


# """
# #TODO:添加用户角色部分只允许select
#     # 构建消息
#     messages = [
#         SystemMessage(content=full_prompt),
#         HumanMessage(content=f"请为以下问题生成SQL查询：\n{state.get('question', '')}")
#     ]
    
#     # 调用 LLM
#     llm = get_model()
#     response = generate_structured_data(llm, messages, SQLGeneratorResponse)
    
#     # 提取 SQL#TODO:改成格式化输出
#     generated_sql = response.sql
    
#     # 返回更新后的状态
#     return {
#         **state,
#         "generated_sql": generated_sql
#     }


# # TODO: 可以添加 SQL 验证、优化等功能
async def sql_generator(state: Chat2DataState) -> Chat2DataState:
    try:
        # 检查是否使用瘦身模式
        use_slim_context = state.get("use_slim_context", False)
        
        # 构建上下文（根据模式选择）
        context = build_sql_generation_context(state, slim_mode=use_slim_context)
        
        if use_slim_context:
            logger.info("使用瘦身模式生成SQL（仅包含业务规则和错误历史）")
        
        # 【新增】检查是否有零行数据调试指引
        debug_guidance = state.get("debug_guidance", "")
        if debug_guidance:
            logger.warning("🔍 检测到零行调试模式，注入逻辑降维提示")
            context = f"{context}\n\n{debug_guidance}"
        
        full_prompt = f"{sql_generator_prompt}\n\n{context}\n\n"
        
        messages = [
            SystemMessage(content=full_prompt),
            HumanMessage(content=f"请为以下问题生成SQL查询：\n{state.get('question', '')}")
        ]
        
        # 调用 LLM
        llm = get_model()
        response = generate_structured_data(llm, messages, SQLGeneratorResponse)
        
        # 🚀 【调试打印】：看看 response 到底长成什么样
        print("📸 Response 类型:", type(response))
        print("📸 Response 内容:", response)
        
        # 提取并强转为字符串
        generated_sql = str(response.sql)
        
        return {
            **state,
            "generated_sql": generated_sql
        }
        
    except Exception as e:
        # 🚀 在这里把具体是在哪一行崩溃的 Traceback 详细捕获并打在控制台上！
        import traceback
        print("🚨 崩溃位置 Traceback:")
        traceback.print_exc()
        raise e
