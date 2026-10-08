"""
@File: sql_logic_debugger.py
@Desc: 零行数据逻辑调试节点 - 注入降维提示引导LLM放宽查询条件
@Author: h
@Date: 2026-09-09
"""
import logging
from graph.state import Chat2DataState

logger = logging.getLogger(__name__)

# 逻辑降维提示词（三原则）
DEBUG_GUIDANCE_TEMPLATE = """
🔍 **SQL逻辑诊断指引**（当前查询返回0行，需要调整逻辑）

**核心三原则**：

1. **模糊匹配替代硬匹配**
   - ❌ 避免：`asset_type = '股票'` 或 `product_name = 'XX基金'`
   - ✅ 使用：`asset_type LIKE '%股票%'` 或 `product_name LIKE '%基金%'`
   - 原因：数据中可能存在前后缀、空格等差异

2. **绝对分母替代AVG()**
   - ❌ 避免：`AVG(daily_asset)` （可能因数据缺失导致结果不准确）
   - ✅ 使用：`SUM(asset) / <固定自然日天数>` 
   - 示例：计算月均资产 → `SUM(asset) / 30` 而非 `AVG(asset)`

3. **逐步放宽过滤条件**
   - 如果多表INNER JOIN无数据：
     * 改用 LEFT JOIN 检查是否某张表为空
     * 或先单表查询确认数据存在性
   - 如果有HAVING子句：
     * 暂时注释掉HAVING，先确保能出数
   - 检查日期范围：
     * 确认 `data_dt = 'YYYYMMDD'` 格式正确
     * 检查日期是否在合理范围内（如最近一年）

**常见问题排查**：
- **字段拼写**：金融数仓交易金额通常是 `buy_amt` / `sell_amt`（Amount），避免写成 `buy_mnt`
- **快照表绑定**：关联日终资产/持仓等每日快照表时，务必带上 `data_dt = 'YYYYMMDD'` 条件
- **JOIN条件**：确保关联键（如 `user_id`, `account_id`）在所有表中存在且格式一致

---
**请根据以上指引重新生成SQL，放宽查询条件以确保能获取到数据。**
"""


async def sql_logic_debugger(state: Chat2DataState) -> Chat2DataState:
    """
    零行数据逻辑调试节点
    
    功能：
    1. 检测到执行成功但返回0行数据
    2. 注入"逻辑降维"提示词到 State
    3. 递增 zero_rows_retry_count（独立于语法错误重试）
    4. 返回到 sql_generator 重新生成
    
    Args:
        state: Chat2DataState 状态字典
        
    Returns:
        Chat2DataState: 更新后的状态（注入debug_guidance）
    """
    logger.warning("⚠️  检测到零行数据，启动逻辑调试器")
    
    generated_sql = state.get("generated_sql", "")
    question = state.get("question", "")
    zero_rows_retry_count = state.get("zero_rows_retry_count", 0) + 1
    
    logger.info(f"零行重试次数: {zero_rows_retry_count}")
    logger.info(f"问题SQL:\n{generated_sql}")
    
    # 构建调试上下文
    debug_context = f"""
## 当前问题
{question}

## 已生成SQL（返回0行）
```sql
{generated_sql}
```

{DEBUG_GUIDANCE_TEMPLATE}
"""
    
    logger.debug(f"注入调试指引:\n{debug_context}")
    
    return {
        **state,
        "debug_guidance": debug_context,
        "zero_rows_retry_count": zero_rows_retry_count,
        # 不增加 retry_count（与语法错误区分）
        # 不修改 error_message（执行本身没有错误）
    }


__all__ = ["sql_logic_debugger"]
