"""
@File: sql_validator.py
@Desc: node3,利用AST先校验
@Author: h
@Date: 8.13
"""
import logging
import re
import sqlite3
from datetime import datetime
from typing import Dict, Any, List
from utils.ast_parser import ast_parser, validate_select_only, validate_tables_exist
from graph.state import Chat2DataState
from core.config import settings

logger = logging.getLogger(__name__)


def extract_unauthorized_tables_from_errors(errors: List[str]) -> List[str]:
    """
    从错误信息中提取未授权的表名
    
    Args:
        errors: 错误信息列表
        
    Returns:
        List[str]: 未授权的表名列表
    """
    unauthorized_tables = []
    for error in errors:
        if "未授权的表" in error:
            # 提取表名，格式："使用了未授权的表: table1, table2"
            match = re.search(r"未授权的表:\s*(.+)", error)
            if match:
                tables_str = match.group(1).strip()
                # 分割多个表名
                tables = [t.strip() for t in tables_str.split(",")]
                unauthorized_tables.extend(tables)
    return list(set(unauthorized_tables))


async def try_expand_relevant_tables(state: Chat2DataState, unauthorized_tables: List[str]) -> Chat2DataState:
    """
    尝试扩展 relevant_tables 和 relevant_columns，将未授权表添加进去

    如果未授权表存在于数据库元数据中，将其添加到上下文中，并重新获取schema信息

    Args:
        state: 当前状态
        unauthorized_tables: 未授权的表名列表

    Returns:
        更新后的状态
    """
    if not unauthorized_tables:
        return state

    from core.database import get_database_schema, execute_sql_query

    logger.info(f"尝试将未授权表添加到相关表: {unauthorized_tables}")

    try:
        placeholders = ",".join(["?" for _ in unauthorized_tables])
        # meta_column_semantics 为列级语义表（每列一行）：table_comment / table_category
        # 并非该表字段，改用已确认的真实列组装上下文。
        #  - column_name：用于填充 relevant_columns（供生成 SQL 使用）
        #  - related_concept：列关联的业务概念，去重后作为表的描述
        result = await execute_sql_query(
            f"""
            SELECT table_name, column_name, related_concept
            FROM meta_column_semantics
            WHERE table_name IN ({placeholders})
            """,
            unauthorized_tables,
        )
        rows = result.get("data") or []

        if not rows:
            logger.warning(f"未授权表不存在于元数据中: {unauthorized_tables}")
            return state

        # 按表名聚合：收集列名与业务概念（related_concept）
        tables_by_name: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            table_name = row.get("table_name")
            if not table_name:
                continue
            bucket = tables_by_name.setdefault(table_name, {"columns": [], "concepts": set()})
            column_name = row.get("column_name")
            if column_name and column_name not in bucket["columns"]:
                bucket["columns"].append(column_name)
            concept = row.get("related_concept")
            if concept:
                bucket["concepts"].add(concept)

        # 扩展 relevant_tables（description 取该表各列业务概念去重拼接；category 无合适表级字段留空）
        relevant_tables = state.get("relevant_tables", []).copy()
        for table_name, info in tables_by_name.items():
            # 检查是否已存在
            if not any(t.get("table_name") == table_name for t in relevant_tables):
                description = "，".join(sorted(info["concepts"]))
                relevant_tables.append({
                    "table_name": table_name,
                    "description": description,
                    "similarity": 0.5,  # 扩展的表给较低相似度
                    "category": ""
                })
                logger.info(f"已扩展表: {table_name}")

        # 扩展 relevant_columns（已在上方聚合得到各列表名）
        relevant_columns = state.get("relevant_columns", {}).copy()
        for table_name, info in tables_by_name.items():
            if table_name not in relevant_columns and info["columns"]:
                relevant_columns[table_name] = info["columns"]
                logger.info(f"已扩展表 {table_name} 的列: {len(info['columns'])} 个")

        # 更新 schema_info（需要重新获取DDL）
        # 这里简化处理，只更新 relevant_tables 和 relevant_columns
        # schema_info 会在重新生成时由 schema_retriever 更新

        return {
            **state,
            "relevant_tables": relevant_tables,
            "relevant_columns": relevant_columns,
            "unauthorized_tables": [],  # 清空，已处理
        }

    except Exception as e:
        logger.error(f"扩展未授权表失败: {str(e)}")
        return state


def get_allowed_tables_from_state(state: Chat2DataState) -> List[str]:
    """
    从 state 中提取允许的表名列表
    
    Args:
        state: Chat2DataState 状态字典
        
    Returns:
        List[str]: 允许的表名列表
    """
    allowed_tables = []
    
    # 从 relevant_tables 中提取
    relevant_tables = state.get("relevant_tables", [])
    for table_info in relevant_tables:
        table_name = table_info.get("table_name")
        if table_name:
            allowed_tables.append(table_name)
    
    # 从 schema_info 中提取
    schema_info = state.get("schema_info", {})
    if schema_info and "tables" in schema_info:
        allowed_tables.extend(schema_info["tables"].keys())
    
    # 去重
    return list(set(allowed_tables))


def validate_sql_security(sql: str, state: Chat2DataState) -> Dict[str, Any]:
    """
    对 SQL 进行安全性验证
    
    验证项：
    1. 只允许 SELECT 查询
    2. 不允许危险操作（INSERT, UPDATE, DELETE, DROP 等）
    3. 只允许访问检索到的相关表
    4. SQL 语法正确性
    
    Args:
        sql: 生成的 SQL 语句
        state: Chat2DataState 状态字典
        
    Returns:
        Dict: 验证结果
    """
    # 获取允许的表列表
    allowed_tables = get_allowed_tables_from_state(state)
    
    # 使用 ast_parser 进行完整验证
    validation_result = ast_parser(
        sql=sql,
        allowed_tables=allowed_tables if allowed_tables else None,
        dialect=get_sql_dialect()
    )
    
    return validation_result


def get_sql_dialect() -> str:
    """
    根据配置获取 SQL 方言
    
    Returns:
        str: SQL 方言 (sqlite, postgres, mysql 等)
    """
    from core.config import DatabaseType
    
    dialect_map = {
        DatabaseType.SQLITE: "sqlite",
        DatabaseType.POSTGRES: "postgres",
        DatabaseType.MONGO: "sqlite",  # MongoDB 不适用，默认 sqlite
    }
    
    return dialect_map.get(settings.DATABASE_TYPE, "sqlite")


def should_retry_generation(validation_result: Dict[str, Any], state: Chat2DataState) -> bool:
    """
    判断是否应该重新生成 SQL
    
    Args:
        validation_result: 验证结果
        state: Chat2DataState 状态字典
        
    Returns:
        bool: 是否需要重新生成
    """
    # 如果验证失败且重试次数未超限
    retry_count = state.get("retry_count", 0)
    max_retries = 3
    
    if not validation_result["is_valid"] and retry_count < max_retries:
        return True
    
    return False


def _check_forbidden_tables(sql: str) -> List[str]:
    """检查 SQL 中是否使用了禁止的元数据表
    
    Args:
        sql: 生成的 SQL 语句
        
    Returns:
        List[str]: 错误信息列表
    """
    forbidden_tables = ['dim_code_type']
    errors = []
    
    sql_upper = sql.upper()
    for table in forbidden_tables:
        # 检查 FROM 或 JOIN 中是否出现了禁止的表
        # 使用单词边界来避免误匹配（如 dim_code_type_backup）
        pattern = r'\b' + table.upper() + r'\b'
        if re.search(pattern, sql_upper):
            errors.append(
                f"SQL 中不允许使用系统元数据表 '{table}'。"
                f"该表仅用于内部验证，请使用硬编码的 code_type_id 值（如 '500'、'600'）代替。"
            )
    
    return errors


def _check_hardcoded_current_date(sql: str) -> List[str]:
    """离线数仓：检查是否在 WHERE 中硬编码了"当前日期"用于 data_dt 过滤。

    规则：历史快照数据场景下，允许使用固定日期进行过滤。
    此检查已禁用，因为数据为历史某一天的快照，非实时更新数据。
    """
    # 历史快照数据场景：允许使用任何日期过滤，不做限制
    return []




def _check_snapshot_partition_alignment(sql: str) -> List[str]:
    """多张日快照表（_d 结尾）JOIN 时，检查分区键是否对齐。

    规则：当且仅当多个日快照表 JOIN 时，必须保证分区键对齐（如 a.data_dt = b.data_dt），
    否则跨天错位关联会产生笛卡尔积，导致数据膨胀、汇总翻倍。
    """
    if not sql:
        return []

    # 找出所有 _d 结尾的业务表（排除系统元数据表 dim_code_type）
    table_pattern = re.compile(r"\\b([A-Za-z_]\\w*)_d\\b", re.IGNORECASE)
    tables = {m.group(0).lower() for m in table_pattern.finditer(sql)}
    tables.discard("dim_code_type")
    if len(tables) < 2:
        return []

    # 检测是否存在分区键（*_dt）的等值 JOIN（如 a.data_dt = b.data_dt）
    align_pattern = re.compile(
        r"(?:[A-Za-z_]\\w+\\.)?(\\w+_dt)\\s*=\\s*(?:[A-Za-z_]\\w+\\.)?\\1\\b",
        re.IGNORECASE,
    )
    if align_pattern.search(sql):
        return []

    return [
        f"❌ 多张日快照表（{', '.join(sorted(tables))}）JOIN 时分区键未对齐："
        f"必须保证 a.data_dt = b.data_dt，否则跨天关联会产生笛卡尔积导致数据膨胀、汇总翻倍。"
    ]


def validate_business_rules(sql: str, business_rules: List[Dict[str, Any]]) -> List[str]:
    """
    验证 SQL 是否符合业务规则
    
    Args:
        sql: 生成的 SQL 语句
        business_rules: 业务规则列表
        
    Returns:
        List[str]: 违反的规则说明（空列表表示通过）
    """
    violations = []
    
    if not business_rules:
        return violations
    
    sql_lower = sql.lower()
    
    for rule in business_rules:
        rule_type = rule.get("rule_type")
        target_concept = rule.get("target_concept", "")
        related_columns = rule.get("related_columns", [])
        formula = rule.get("formula", "")
        
        if rule_type == "calculation" and related_columns:
            # 检查计算类规则
            
            # 1. 检查SQL中是否使用了相关列
            columns_in_sql = [col for col in related_columns if col.lower() in sql_lower]
            
            if columns_in_sql and len(columns_in_sql) < len(related_columns):
                # 部分使用但不完整
                missing = set(related_columns) - set(columns_in_sql)
                violations.append(
                    f"❌ 计算 '{target_concept}' 时不完整："
                    f"使用了 {columns_in_sql} 但缺少 {list(missing)}。"
                    f"正确公式: {formula}"
                )
            
            # 2. 特殊检查：如果目标概念是"资产"相关，检查是否误用了余额字段
            if "资产" in target_concept or "asset" in target_concept.lower():
                # 检查是否使用了 nm_bal 或 fc_bal（余额字段）
                if "nm_bal" in sql_lower or "fc_bal" in sql_lower:
                    # 但不在 related_columns 中（说明这是错误使用）
                    if "nm_bal" not in related_columns and "fc_bal" not in related_columns:
                        violations.append(
                            f"❌ 计算 '{target_concept}' 时使用了错误的字段："
                            f"nm_bal/fc_bal 是余额字段，不是总资产。"
                            f"应使用: {formula}"
                        )
        elif rule_type in ("temporal", "filter_scope"):
            name = rule.get("rule_name", "")
            if "时间字段" in name or "无时间" in name or "当前日期" in name:
                violations.extend(_check_hardcoded_current_date(sql))
            elif "分区键" in name or "日快照" in name:
                violations.extend(_check_snapshot_partition_alignment(sql))
            # filter_scope 口径类规则（如“期间盈亏人群期末圈定”）以 Prompt 引导为主，
    
    return violations




def _check_and_or_priority(sql: str) -> List[str]:
    """检查 WHERE 子句中是否存在 AND/OR 优先级陷阱
    
    Args:
        sql: 生成的 SQL 语句
        
    Returns:
        List[str]: 警告信息列表
    """
    warnings = []
    
    # 提取 WHERE 子句
    where_match = re.search(
        r'\bWHERE\b(.*?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|$)', 
        sql, 
        re.IGNORECASE | re.DOTALL
    )
    
    if not where_match:
        return warnings
    
    where_clause = where_match.group(1)
    
    # 检查是否同时包含 AND 和 OR
    has_and = re.search(r'\bAND\b', where_clause, re.IGNORECASE)
    has_or = re.search(r'\bOR\b', where_clause, re.IGNORECASE)
    
    if has_and and has_or:
        # 检查是否有括号包裹（简单检查）
        has_parens = '(' in where_clause and ')' in where_clause
        
        # 即使有括号，也检查是否正确使用（这是一个启发式检查）
        # 如果 AND 和 OR 混用但括号很少，可能有问题
        paren_count = where_clause.count('(')
        and_count = len(re.findall(r'\bAND\b', where_clause, re.IGNORECASE))
        or_count = len(re.findall(r'\bOR\b', where_clause, re.IGNORECASE))
        
        if not has_parens:
            warnings.append(
                "WHERE 子句中同时使用了 AND 和 OR，但没有使用括号明确优先级。"
                "这可能导致逻辑错误。建议：(1) 使用 IN (...) 代替多个 OR，"
                "或 (2) 使用括号明确分组，例如 WHERE a=1 AND (b=2 OR b=3)"
            )
        elif or_count > 1 and paren_count < or_count:
            # 如果有多个 OR 但括号数少于 OR 数，可能括号不够
            warnings.append(
                "WHERE 子句中有多个 OR 条件，建议检查是否正确使用了括号分组，"
                "或考虑使用 IN (...) 来简化逻辑。"
            )
    
    return warnings


async def sql_validator(state: Chat2DataState) -> Chat2DataState:
    """
    SQL 验证节点函数
    
    使用 AST 解析器验证生成的 SQL：
    1. 验证只包含 SELECT 查询（拦截危险操作）
    2. 验证语法正确性
    3. 验证表和列的合法性
    4. 如果验证失败，设置错误信息并可能触发重试
    
    Args:
        state: Chat2DataState 状态字典
        
    Returns:
        Chat2DataState: 更新后的状态
    """
    generated_sql = state.get("generated_sql", "")
    
    # 如果没有生成的 SQL，直接返回错误
    if not generated_sql:
        logger.error("没有生成的 SQL 可供验证")
        return {
            **state,
            "error_message": "没有生成 SQL 语句",
            "retry_count": state.get("retry_count", 0) + 1
        }
    
    # 1) AST 安全验证：只允许 SELECT，校验表/列合法性
    validation_result = validate_sql_security(generated_sql, state)

    # 1.5) 冲突 JOIN 警告（来自 ast_parser 确定性校验，仅记录日志，不强制阻断）
    for warning in validation_result.get("warnings", []):
        logger.warning(f"[冲突JOIN] {warning}")

    ast_valid = validation_result.get("is_valid", False)
    
    # 2) 取值域码值校验（独立必经：无论 AST 是否通过都执行，
    #    识别引用 dim_public 时凭空捏造 code/code_type_id/describe 的情况）
    value_reasons = _validate_code_values(generated_sql, state)
    
    # 2.5) 检查是否使用了禁止的元数据表（如 dim_code_type）
    forbidden_table_errors = _check_forbidden_tables(generated_sql)
    
    # 2.6) 业务规则验证
    business_rules = state.get("schema_info", {}).get("business_rules", [])
    business_rule_violations = validate_business_rules(generated_sql, business_rules)
    if business_rule_violations:
        logger.warning(f"[业务规则验证] 发现 {len(business_rule_violations)} 个违规")
        for violation in business_rule_violations:
            logger.warning(f"  {violation}")
    
    # 2.7) 检查 AND/OR 优先级问题（警告级别，记录日志但不强制重试）
    and_or_warnings = _check_and_or_priority(generated_sql)
    for warning in and_or_warnings:
        logger.warning(f"[SQL 优先级警告] {warning}")
    
    # 3) 累积错误信息
    error_history = state.get("error_message", [])
    if isinstance(error_history, str):
        error_history = [error_history] if error_history else []
    
    if not ast_valid:
        errors = validation_result.get("errors", [])
        error_message = "; ".join(errors)
        if error_message:
            logger.warning(f"SQL 验证失败: {error_message}")
            logger.warning(f"问题 SQL: {generated_sql}")
            error_history.append(f"验证错误: {error_message}")
    
    for reason in value_reasons:
        error_history.append(f"[码值校验] {reason}")
    
    # 添加禁止表检查的错误
    for error in forbidden_table_errors:
        error_history.append(f"[禁止表检查] {error}")
        logger.error(f"[禁止表检查] {error}")
    
    # 业务规则违规仅记录告警，不作为重试/阻断依据（降级处理）
    
    # AND/OR 警告也加入错误历史（触发重试）
    for warning in and_or_warnings:
        error_history.append(f"[逻辑优先级] {warning}")

    # Lever 4：确定性行膨胀检测（多行明细表未预聚合）
    row_expansion_reasons = _check_row_multiplication(generated_sql, state)
    if row_expansion_reasons:
        for r in row_expansion_reasons:
            logger.warning(f"[行膨胀检测] {r}")
        error_history.append("[行膨胀检测] " + "；".join(row_expansion_reasons))

    sql_history = state.get("sql_history", [])
    if isinstance(sql_history, str):
        sql_history = [sql_history] if sql_history else []
    sql_history.append(generated_sql)

    # 4) 统一决策：AST 通过 且 码值无 error 且 无禁止表 且 无严重优先级问题 且 无行膨胀风险 → 正常返回；否则重试
    # 注：业务规则违规已降级为仅告警，不作为通过/阻断依据
    if ast_valid and not value_reasons and not forbidden_table_errors and not and_or_warnings and not row_expansion_reasons:
        logger.info(f"SQL 验证通过: {generated_sql}")
        logger.info(f"使用的表: {validation_result['tables']}")
        logger.info(f"使用的列: {validation_result['columns']}")
        
        # 使用格式化后的 SQL
        formatted_sql = validation_result.get("formatted_sql", generated_sql)
        
        return {
            **state,
            "generated_sql": formatted_sql,
            "error_message": [],  # 清空错误消息
            "validation_error_type": "",  # 清空错误类型
            "unauthorized_tables": [],  # 清空未授权表
            "use_slim_context": False,  # 清空瘦身标记
        }
    
    # 5) 错误分类：根据错误类型设置不同的路由标记
    validation_error_type = ""
    unauthorized_tables = []
    use_slim_context = False
    
    ast_errors = validation_result.get("errors", [])
    
    # 5.1) 检查是否是跨层JOIN错误（优先级最高，专精修补）
    if any("跨层 JOIN" in err for err in ast_errors):
        validation_error_type = "cross_layer_join"
        logger.info("错误分类: 跨层JOIN错误 -> 路由到 sql_syntax_patcher")
    
    # 5.2) 检查是否是未授权表错误（次高优先级，尝试扩展）
    elif any("未授权的表" in err for err in ast_errors):
        validation_error_type = "unauthorized_table"
        unauthorized_tables = extract_unauthorized_tables_from_errors(ast_errors)
        logger.info(f"错误分类: 未授权表错误 -> 尝试扩展: {unauthorized_tables}")
        
        # 立即尝试扩展表
        state_with_expanded_tables = await try_expand_relevant_tables(state, unauthorized_tables)
        if state_with_expanded_tables.get("unauthorized_tables", unauthorized_tables) == []:
            # 扩展成功，更新state
            logger.info("未授权表已成功扩展，将重新生成SQL")
            state = state_with_expanded_tables
        else:
            logger.warning("未授权表扩展失败，将以错误状态重试")
    
    # 5.3) 检查是否是码值/行膨胀错误（使用瘦身上下文重写）
    # 注：业务规则违规已降级为仅告警，不再触发 business_rule 路由
    elif value_reasons or row_expansion_reasons:
        validation_error_type = "business_rule"
        use_slim_context = True
        logger.info("错误分类: 码值/行膨胀错误 -> 使用瘦身上下文重写")
    
    # 5.4) 其他语法错误（完整重写）
    else:
        validation_error_type = "syntax"
        logger.info("错误分类: 语法错误 -> 完整重写")
    
    retry_count = state.get("retry_count", 0) + 1
    return {
        **state,
        "error_message": error_history,
        "sql_history": sql_history,
        "retry_count": retry_count,
        "validation_error_type": validation_error_type,
        "unauthorized_tables": unauthorized_tables,
        "use_slim_context": use_slim_context,
    }


# ── 取值域码值校验（复用自 validate_code_values.py） ──────────────────
FIELD_TO_CODE_TYPE: Dict[str, str] = {
    "gender_cd": "500",  # 性别
    "edu_cd": "600",     # 学历
}


def _literal(g2, g3):
    """统一返回正则匹配到的字符串字面量（忽略引号类型）。"""
    return g2 if g2 is not None else g3


def parse_alias(sql):
    """返回 SQL 中 dim_public 的别名列表。"""
    return re.findall(r"\b(?:JOIN|FROM)\s+dim_public\s+(\w+)", sql, re.IGNORECASE)


def extract_code_type_id(sql, aliases):
    """返回 {alias: set(code_type_id str)}。"""
    pat = re.compile(r"(\w+)\.code_type_id\s*=\s*(?:'([^']*)'|\"([^\"]*)\")", re.IGNORECASE)
    out = {}
    for m in pat.finditer(sql):
        if m.group(1) in aliases:
            out.setdefault(m.group(1), set()).add(_literal(m.group(2), m.group(3)))
    return out


def extract_describe(sql, aliases):
    """返回 {alias: [describe, ...]}。"""
    eq = re.compile(r"(\w+)\.describe\s*=\s*(?:'([^']*)'|\"([^\"]*)\")", re.IGNORECASE)
    in_ = re.compile(r"(\w+)\.describe\s+IN\s*\(([^)]*)\)", re.IGNORECASE)
    lit = re.compile(r"(?:'([^']*)'|\"([^\"]*)\")")
    out = {}
    for m in eq.finditer(sql):
        if m.group(1) in aliases:
            out.setdefault(m.group(1), []).append(_literal(m.group(2), m.group(3)))
    for m in in_.finditer(sql):
        if m.group(1) in aliases:
            for lm in lit.finditer(m.group(2)):
                out.setdefault(m.group(1), []).append(_literal(lm.group(1), lm.group(2)))
    return out


def validate(sql, lookup, code_type_names):
    """对一条 SQL 做码值校验，返回报告条目列表（error / warn / info / ok）。"""
    report = []
    aliases = parse_alias(sql)
    if not aliases:
        return [{"level": "info", "message": "SQL 未引用 dim_public，无需码值校验。"}]
    alias_set = set(aliases)
    alias_ct = extract_code_type_id(sql, alias_set)
    alias_desc = extract_describe(sql, alias_set)
    for alias, descs in alias_desc.items():
        ct_set = alias_ct.get(alias, set())
        descs_unique = list(dict.fromkeys(descs))
        if not ct_set:
            report.append({"level": "warn", "alias": alias, "describe": None, "code_types": None,
                "message": f"别名 '{alias}' 未限定 code_type_id，describe 字面量无法定位所属类别。"})
            for d in descs_unique:
                found = any(d in b["describes"] for b in lookup.values())
                report.append({"level": "info" if found else "error", "alias": alias, "describe": d,
                    "code_types": None,
                    "message": (f"  describe='{d}' 存在于 dim_public 任意类别（类别不明）"
                        if found else f"  describe='{d}' 未在 dim_public 任何类别下出现（凭空生成）")})
            continue
        for d in descs_unique:
            found_in_ct = any(d in lookup[ct]["describes"] for ct in ct_set if ct in lookup)
            found_anywhere = any(d in b["describes"] for b in lookup.values())
            if not found_anywhere:
                report.append({"level": "error", "alias": alias, "describe": d, "code_types": sorted(ct_set),
                    "message": f"describe='{d}' 未在 dim_public 任何类别下出现（凭空生成），关联 code_type_id={sorted(ct_set)}"})
            elif not found_in_ct:
                report.append({"level": "warn", "alias": alias, "describe": d, "code_types": sorted(ct_set),
                    "message": f"describe='{d}' 存在于 dim_public，但不属于 code_type_id={sorted(ct_set)} 下任何类别，来源不明"})
            else:
                report.append({"level": "ok", "alias": alias, "describe": d, "code_types": sorted(ct_set),
                    "message": f"describe='{d}' 属于 code_type_id={sorted(ct_set)} 的合法取值"})
    field_re = re.compile(r"\b(" + "|".join(FIELD_TO_CODE_TYPE.keys()) + r")\s*=\s*(?:'([^']*)'|\"([^\"]*)\")", re.IGNORECASE)
    for m in field_re.finditer(sql):
        field = m.group(1)
        if field not in FIELD_TO_CODE_TYPE:
            continue
        value = _literal(m.group(2), m.group(3))
        ct = FIELD_TO_CODE_TYPE[field]
        name = code_type_names.get(ct, ct)
        expected = lookup.get(ct, {}).get("codes", set())
        if value not in expected:
            report.append({"level": "error", "field": field, "value": value, "code_type": ct, "type_name": name,
                "message": f"字段 {field} 码值 '{value}' 不在 code_type_id='{ct}'({name}) 合法 code 集合（凭空生成），示例: {sorted(expected)[:5]}"})
        else:
            report.append({"level": "ok", "field": field, "value": value, "code_type": ct,
                "message": f"字段 {field} = '{value}' 是 code_type_id='{ct}' 下的合法 code"})

    # 3) 校验 code_type_id 字面量合法性（如 SQL 误写 'gender'/'education' 而非 '500'/'600'）
    real_cts = set(lookup.keys())
    for alias, ct_set in alias_ct.items():
        for ct in sorted(ct_set):
            if ct not in real_cts:
                report.append({"level": "error", "alias": alias, "code_type_id": ct,
                    "message": f"alias '{alias}' 的 code_type_id='{ct}' 不是 dim_public 中的合法类别（应为 {sorted(real_cts)}）"})
            else:
                report.append({"level": "ok", "alias": alias, "code_type_id": ct,
                    "message": f"alias '{alias}' 的 code_type_id='{ct}' 是 dim_public 中的合法类别"})
    return report


def _build_public_lookup(conn):
    """从 dim_public 建取值表：{code_type_id(str): {'describes': set, 'codes': set}}。"""
    result = {}
    try:
        for cid, code, desc in conn.execute(
            "SELECT code_type_id, code, describe FROM dim_public"
        ):
            key = str(cid)
            b = result.setdefault(key, {"describes": set(), "codes": set()})
            b["describes"].add(desc)
            b["codes"].add(code)
    except sqlite3.OperationalError as exc:
        logger.warning(f"读取 dim_public 失败（可能表不存在）: {exc}")
    return result


def _build_code_type_names(conn):
    """从 dim_code_type 建映射：{code_type_id(str): type_name}；表缺失返回空 dict。"""
    try:
        has = conn.execute("SELECT 1 FROM dim_code_type LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return {}
    if not has:
        return {}
    return {str(ct): name for ct, name in conn.execute("SELECT code_type_id, type_name FROM dim_code_type")}


def _load_value_domain_resources(db_path):
    """连接 DB，返回 (public_lookup, code_type_names)。"""
    conn = sqlite3.connect(str(db_path))
    try:
        return _build_public_lookup(conn), _build_code_type_names(conn)
    finally:
        conn.close()


def _validate_code_values(sql, state):
    """取值域码值校验：仅对引用 dim_public 的 SQL 校验。

    返回 error 级别原因列表（触发重试）；warn 级别只记录日志，不记入错误。
    dim_public 缺失或库不可读时记 WARN 并返回 []，不阻断流程。
    """
    db_path = settings.SQLITE_DB_PATH
    if not db_path:
        logger.warning("取值域校验：SQLITE_DB_PATH 为空，跳过码值校验")
        return []
    try:
        lookup, code_type_names = _load_value_domain_resources(db_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"取值域校验：打开数据库失败，跳过校验: {exc}")
        return []
    if not lookup:
        logger.warning("取值域校验：dim_public 为空（可能表不存在），跳过校验")
        return []
    report = validate(sql, lookup, code_type_names)
    reasons = []
    for entry in report:
        if entry["level"] == "error":
            reasons.append(entry["message"])
        elif entry["level"] == "warn":
            logger.warning(f"[值域校验] {entry['message']}")
        else:
            logger.info(f"[值域校验] {entry['message']}")
    return reasons


# ──────────────────────────────────────────────
# Lever 4 确定性行膨胀检测：多行明细表 JOIN 未预聚合
# ──────────────────────────────────────────────
_MULTI_ROW_DETAIL_TABLES = (
    # "一人多行" 明细表（资金流水、持仓、交易流水）。
    # 与主表 pty_id JOIN 时不先 GROUP BY pty_id 塌缩，会直接导致 SUM 翻倍。
    "dws_cust_fin_d",
    "dwd_cust_hold_d",
    "dwd_cust_tran_d",
)


def _extract_main_query_body(sql: str) -> str:
    """
    从 SQL 中提取主查询体（排除 CTE 部分）
    
    Args:
        sql: 完整 SQL 语句
        
    Returns:
        str: 主查询体
    """
    # 检查是否有 WITH 子句
    with_pattern = r"^\s*WITH\s+"
    if not re.search(with_pattern, sql, re.IGNORECASE):
        return sql
    
    # 找到 WITH 子句结束的位置（最后一个 CTE 的右括号后）
    # 简化实现：找到第一个 SELECT（不在括号中）
    paren_depth = 0
    in_string = False
    string_char = None
    
    for i, ch in enumerate(sql):
        # 处理字符串
        if ch in ("'", '"'):
            if not in_string:
                in_string = True
                string_char = ch
            elif ch == string_char:
                in_string = False
                string_char = None
        
        if in_string:
            continue
        
        # 处理括号
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
        
        # 找到不在括号中的 SELECT
        if paren_depth == 0:
            # 检查是否是 SELECT 关键字的开始
            remaining = sql[i:i+6].upper()
            if remaining.startswith("SELECT"):
                # 确认这是主查询的 SELECT
                # 向前看是否有 WITH 或 CTE 别名
                prev_context = sql[max(0, i-50):i].upper()
                if "AS" not in prev_context or ")" in prev_context:
                    return sql[i:]
    
    # 如果没找到，返回原 SQL
    return sql


def _is_in_aggregated_subquery(context: str, table_name: str) -> bool:
    """
    检测表是否在包含 GROUP BY pty_id 的子查询中
    
    Args:
        context: 包含该表的上下文 SQL 片段
        table_name: 表名
        
    Returns:
        bool: 是否在预聚合子查询中
    """
    # 查找表名的位置
    table_pattern = r"\b" + re.escape(table_name) + r"\b"
    table_match = re.search(table_pattern, context, re.IGNORECASE)
    if not table_match:
        return False
    
    table_pos = table_match.start()
    
    # 向前找最近的 SELECT 关键字
    # 检查该 SELECT 是否在括号内（即是子查询而非主查询）
    select_pos = -1
    temp_pos = table_pos
    while temp_pos >= 0:
        check_fragment = context[max(0, temp_pos-10):temp_pos+7]
        if re.search(r"\bSELECT\b", check_fragment, re.IGNORECASE):
            select_pos = temp_pos
            break
        temp_pos -= 1
    
    if select_pos == -1:
        return False
    
    # 检查 SELECT 前是否有未闭合的左括号（说明是子查询）
    before_select = context[:select_pos]
    left_paren_count = before_select.count("(")
    right_paren_count = before_select.count(")")
    
    # 如果左括号数量 <= 右括号数量，说明这个 SELECT 不在子查询中
    if left_paren_count <= right_paren_count:
        return False
    
    # 找到这个子查询的结束位置（对应的右括号）
    paren_depth = left_paren_count - right_paren_count
    right_paren_pos = -1
    for i in range(table_pos, len(context)):
        if context[i] == "(":
            paren_depth += 1
        elif context[i] == ")":
            paren_depth -= 1
            if paren_depth == 0:
                right_paren_pos = i
                break
    
    if right_paren_pos == -1:
        # 没有找到对应的右括号，不是有效的子查询
        return False
    
    # 提取子查询内容（从最后一个未匹配的左括号到右括号）
    # 向前找最后一个未匹配的左括号
    last_left_paren = -1
    depth = 0
    for i in range(select_pos - 1, -1, -1):
        if context[i] == ")":
            depth += 1
        elif context[i] == "(":
            if depth == 0:
                last_left_paren = i
                break
            depth -= 1
    
    if last_left_paren == -1:
        return False
    
    # 提取子查询内容
    subquery = context[last_left_paren:right_paren_pos + 1]
    
    # 检查子查询中是否包含 GROUP BY pty_id
    # 支持多种格式：GROUP BY pty_id, GROUP BY a.pty_id, GROUP BY pty_id, other_col
    group_by_pattern = r"\bGROUP\s+BY\s+.*?\bpty_id\b"
    has_group_by_pty_id = re.search(group_by_pattern, subquery, re.IGNORECASE) is not None
    
    return has_group_by_pty_id


def _detect_row_multiplication(sql: str) -> List[str]:
    """检测 SQL 是否对多行明细表做了直接 JOIN 而未预聚合。

    判断规则（纯正则，不依赖完整解析器，避免额外引入 ANTLR 等重量依赖）：
      1. SQL 中出现了 _MULTI_ROW_DETAIL_TABLES 里的表。
      2. 该表在 JOIN 中不是 ``LEFT JOIN (SELECT ... FROM tbl WHERE ... GROUP BY pty_id) alias``
         这种"先按 pty_id 塌缩"的子查询形式（子查询体与 GROUP BY 同层出现即可）。
      3. 同时主查询体中存在 ``SUM(...)`` 或 ``GROUP BY`` 聚合（说明模型确实做了数值汇总，
         而非纯取维度的扫描查询，此时行膨胀必定污染汇总结果）。

    返回：原因列表（空列表 = 未检测到风险）。
    """
    if not sql:
        return []

    sql_normalized = sql.replace("\r", " ")
    
    # 移除 CTE 部分，只检查主查询体
    main_body = _extract_main_query_body(sql_normalized)
    
    reasons = []
    for tbl in _MULTI_ROW_DETAIL_TABLES:
        pattern = re.compile(
            r"\b" + re.escape(tbl) + r"\b",
            re.IGNORECASE,
        )
        matches = list(pattern.finditer(main_body))
        if not matches:
            continue

        # 检测该表是否在预聚合子查询中
        is_pre_aggregated = False
        for m in matches:
            # 向前回溯检查是否在子查询中
            ctx_start = max(0, m.start() - 500)
            ctx_end = min(len(main_body), m.end() + 500)
            context = main_body[ctx_start:ctx_end]
            
            # 检查是否在子查询中，且该子查询包含 GROUP BY pty_id
            if _is_in_aggregated_subquery(context, tbl):
                is_pre_aggregated = True
                break

        if not is_pre_aggregated:
            # 未在预聚合子查询中
            if re.search(r"\bGROUP\s+BY\b", main_body, re.IGNORECASE):
                reasons.append(
                    f"明细表 '{tbl}' 在主查询体中直接 JOIN 了该多行明细表（未先按 pty_id 塌缩）。"
                    f"参考范式：先在子查询里按 pty_id GROUP BY 预聚合，再 LEFT JOIN 到主表。"
                )
            else:
                reasons.append(
                    f"明细表 '{tbl}' 在主查询体中未被预聚合（无 GROUP BY），"
                    f"直接 JOIN 会导致 pty_id 一对多膨胀，若主查询有 SUM 汇总会导致结果翻倍。"
                )

    return reasons


def _check_row_multiplication(sql: str, state: Chat2DataState) -> List[str]:
    """封装：从 state 里取生成的 SQL 并运行行膨胀检测。"""
    generated_sql = state.get("generated_sql", "") or sql
    if not generated_sql:
        return []
    return _detect_row_multiplication(generated_sql)


def get_validation_summary(state: Chat2DataState) -> str:
    """
    获取验证摘要信息（用于日志或返回给用户）
    
    Args:
        state: Chat2DataState 状态字典
        
    Returns:
        str: 验证摘要
    """
    sql = state.get("generated_sql", "")
    error_message = state.get("error_message", "")
    retry_count = state.get("retry_count", 0)
    
    if error_message:
        return f"SQL 验证失败 (重试次数: {retry_count}): {error_message}\nSQL: {sql}"
    else:
        return f"SQL 验证通过: {sql}"


__all__ = [
    "sql_validator",
    "validate_sql_security",
    "get_validation_summary",
]
