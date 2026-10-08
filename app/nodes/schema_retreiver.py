"""
@File: schema_retreiever.py
@Desc: node1,检索表结构,专有名词
@Author: h&m
@Date: 8.13
"""
import json
import logging
import sqlite3
from typing import List, Dict, Any, Tuple
from langchain_core.messages import SystemMessage, HumanMessage

from core.llm import get_model
from core.database import get_database_schema, execute_sql_query
from graph.state import Chat2DataState
from utils.prompts import intent_prompt, table_retriever_prompt, example_reteriever_prompt, column_retriever_prompt
from utils.output_schema import IntentResponse,TableRetrieverResponse,ColumnRetrieverResponse,ExampleRetrieverResponse,QueryPlanResponse,SQLGeneratorResponse,ChartGeneratorResponse
from utils.output_schema import generate_structured_data
from utils.distinct_values import ColumnValueIndex, TableDescriptionGenerator, VECTOR_DB_PATH
from utils.entity_extraction import EntityCorrector

import json
import logging
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

#TODO:这个应该移到database里面
async def get_all_tables() -> List[str]:
    """
    获取数据库中所有表名

    Returns:
        List[str]: 表名列表
    """
    result = await get_database_schema()
    if result.get("success"):
        data = result.get("data", {})
        # 支持 SQLite/PostgreSQL 的 tables 和 MongoDB 的 collections
        return data.get("tables", data.get("collections", []))
    return []


async def get_table_schema(table_name: str) -> Dict[str, Any]:
    """
    获取指定表的结构信息

    Args:
        table_name: 表名

    Returns:
        Dict: 表结构信息字典
    """
    result = await get_database_schema(table_name=table_name)
    if result.get("success"):
        return result.get("data", {})
    return {}


def extract_columns_from_schema(schema: Dict[str, Any]) -> List[str]:
    """
    从表结构中提取列名

    Args:
        schema: 表结构字典

    Returns:
        List[str]: 列名列表
    """
    columns = []

    # 处理 SQLite/PostgreSQL 的列信息
    if "columns" in schema:
        for col in schema["columns"]:
            if isinstance(col, dict):
                # SQLite: 'name' 字段, PostgreSQL: 'column_name' 字段
                col_name = col.get("name") or col.get("column_name")
                if col_name:
                    columns.append(col_name)

    # 处理 MongoDB 的字段示例
    if "sample_fields" in schema:
        columns.extend(schema["sample_fields"])

    return columns



async def get_all_few_shot_examples() -> List[Dict[str, Any]]:
    """
    从 few-shot 数据库中获取所有历史 SQL 示例

    Returns:
        List[Dict]: 所有 few-shot 示例列表
    """
    # TODO: 根据实际的 few-shot 数据库表结构调整查询语句
    # 假设 few-shot 数据存储在名为 'sql_examples' 的表中
    # 包含字段：question, sql, tables (JSON 或逗号分隔的字符串)

    try:
        result = await execute_sql_query(
            "SELECT question, sql, tables FROM sql_examples LIMIT 100"
        )

        if result.get("success"):
            examples = result.get("data", [])
            # 处理 tables 字段（可能是 JSON 字符串或逗号分隔）
            for ex in examples:
                if isinstance(ex.get("tables"), str):
                    try:
                        ex["tables"] = json.loads(ex["tables"])
                    except:
                        ex["tables"] = [t.strip() for t in ex["tables"].split(",")]
            return examples
    except:
        pass

    return []


async def retrieve_few_shot_examples(question: str, intent: str) -> List[Dict[str, Any]]:
    """
    从 few-shot 数据库中检索相似的历史 SQL 示例（最多10个）

    Args:
        question: 用户问题
        intent: 问题意图


    Returns:
        List[SQLExample]: few-shot 示例列表
        List[SQLExample]: 最多10个 few-shot 示例，按相似度排序
    """

    llm = get_model()
    print(type(llm))

    # 获取所有 few-shot 示例
    all_examples = await get_all_few_shot_examples()


    if not all_examples:
        return []

    # 使用 LLM 从所有示例中选择最相似的最多10个
    example_selection_prompt = SystemMessage(content=example_reteriever_prompt )

    example_messages = [
        example_selection_prompt,
        HumanMessage(content=f"问题：{question}\n意图：{intent}")
    ]

    try:
        example_response = generate_structured_data(llm, example_messages, ExampleRetrieverResponse)
        example_data = example_response.relevant_examples[:10]
        
        # 将 Pydantic 模型转换为字典列表
        few_shot_examples = [example.model_dump() for example in example_data]
        
        return few_shot_examples
    except:
        return []


def _append_sample_values(schema_text: List[str], table_name: str, schema: Dict[str, Any]) -> None:
    """为当前表的 DDL 追加采样值，帮助模型对齐真实取值格式。

    - 日期列（含 _dt / data_dt / date）：显式标注真实存储格式 'YYYYMMDD'。
    - 类别列：从业务库直取前 N 个 distinct 真实取值。

    只读、容错：任何数据库失败都不影响 schema 输出。
    """
    if not schema:
        return

    # 列名 -> 类型（兼容 SQLite 与 PostgreSQL 两种 schema 格式）
    col_types: Dict[str, str] = {}
    columns = schema.get("columns", schema.get("fields", []))
    for col in columns:
        if isinstance(col, dict):
            if "name" in col:
                col_types[col.get("name", "")] = (col.get("type", "") or "").lower()
            elif "column_name" in col:
                col_types[col.get("column_name", "")] = (col.get("data_type", "") or "").lower()

    # 日期列默认格式：YYYYMMDD（与现有参考 SQL 一致，如 data_dt BETWEEN '20260101' AND '20260331'）
    date_cols = [name for name, t in col_types.items() if "_dt" in name or name in ("data_dt",) or "date" in name]

    sample_lines: List[str] = []

    # 日期列示例（不依赖查库，直接给出格式，最稳）
    if date_cols:
        date_example = " ".join(f"{d} = '20260101'" for d in date_cols)
        sample_lines.append(
            f"-- 日期取值格式（真实存储为纯数字 YYYYMMDD 字符串）：{date_example}"
        )

    # 类别列采样值（最多每个表查 3 个类别列，每列取 5 个值）
    sample_cols: List[Tuple[str, str]] = []  # (table, column)
    for name, t in col_types.items():
        if name in date_cols:
            continue
        if "int" in t or "float" in t or "dec" in t or "num" in t or t in ("",):
            continue
        # 只对有代表性的类别列采样（如 cust_lvl_cd、gender_cd、code_type_id 等），避免列太多噪声
        if name in ("cust_lvl_cd", "gender_cd", "code_type_id", "prdcd", "prdt_id"):
            sample_cols.append((table_name, name))

    try:
        from core.config import settings
        conn = sqlite3.connect(str(settings.SQLITE_DB_PATH))
        conn.row_factory = sqlite3.Row
        for _t, col in sample_cols:
            try:
                rows = conn.execute(
                    f'SELECT DISTINCT "{col}" AS v FROM "{_t}" WHERE "{col}" IS NOT NULL ORDER BY v LIMIT 5'
                ).fetchall()
                vals = [str(r["v"]) for r in rows]
                if vals:
                    sample_lines.append(f"-- {col} 示例取值: {', '.join(vals)}")
            except Exception:
                continue
        conn.close()
    except Exception:
        pass

    if sample_lines:
        schema_text.append("-- 采样值示例：")
        schema_text.append("\n".join(f"    {ln}" for ln in sample_lines))


def format_schema_info(schemas: Dict[str, Any]) -> str:
    """
    格式化表结构信息为 DDL 格式

    Args:
        schemas: 表名到表结构的映射

    Returns:
        str: 格式化的 schema 信息
    """
    schema_text = []

    for table_name, schema in schemas.items():
        schema_text.append(f"\n-- 表: {table_name}")

        if "columns" in schema:
            columns_info = []
            for col in schema["columns"]:
                if isinstance(col, dict):
                    # SQLite 格式
                    if "name" in col:
                        col_name = col.get("name", "")
                        col_type = col.get("type", "")
                        nullable = "" if col.get("notnull") else "NULL"
                        columns_info.append(f"  {col_name} {col_type} {nullable}".strip())
                    # PostgreSQL 格式
                    elif "column_name" in col:
                        col_name = col.get("column_name", "")
                        data_type = col.get("data_type", "")
                        nullable = col.get("is_nullable", "YES")
                        null_str = "NULL" if nullable == "YES" else "NOT NULL"
                        columns_info.append(f"  {col_name} {data_type} {null_str}")

            if columns_info:
                schema_text.append("CREATE TABLE " + table_name + " (")
                schema_text.append(",\n".join(columns_info))
                schema_text.append(");")
                # 采样值追加：对日期列写明真实格式（YYYYMMDD 字符串），对类别列列出
                # 实际存值，避免模型写成 '2026-03-31' 或自创取值导致过滤命中 0 行。
                _append_sample_values(schema_text, table_name, schemas[table_name])

        elif "sample_fields" in schema:
            # MongoDB 集合字段
            fields = schema.get("sample_fields", [])
            schema_text.append(f"Collection fields: {', '.join(fields)}")

    return "\n".join(schema_text)




# 只有问题明确出现这些语义时，才允许激活相应计算规则
CONCEPT_TRIGGER_GROUPS: Dict[str, List[str]] = {
    "日均资产": [
        "日均资产",
        "平均每日资产",
        "每日平均资产",
        "期间平均资产",
        "日均总资产",
        "日均金融资产",
    ],
    "持仓市值": [
        "持仓市值",
        "持有市值",
        "产品市值",
        "持仓金额",
        "持有金额",
        "市值超过",
        "市值大于",
        "市值不少于",
        "市值排名",
        "市值合计",
        "总市值",
    ],
    "总资产": [
        "总资产",
        "资产总额",
        "资产规模",
        "资产超过",
        "资产大于",
        "资产不少于",
    ],
    "盈亏": [
        "盈亏",
        "盈利",
        "亏损",
        "浮动盈亏",
        "累计盈亏",
    ],
    "收益": [
        "收益",
        "收益率",
        "回报率",
        "投资回报",
    ],
    "余额": [
        "余额",
        "账户余额",
        "资金余额",
    ],
}


# 这些词表示“是否存在/是否发生”，不是数值计算
EXISTENCE_KEYWORDS: Set[str] = {
    "交易过",
    "买过",
    "卖过",
    "购买过",
    "申购过",
    "赎回过",
    "持有",
    "持仓",
    "拥有",
    "有过",
    "是否持有",
    "曾经交易",
}


# 出现这些词时，才更可能需要 SUM、AVG、COUNT 或 HAVING 等计算规则
CALCULATION_KEYWORDS: Set[str] = {
    "计算",
    "多少",
    "金额",
    "市值",
    "资产",
    "余额",
    "收益",
    "盈亏",
    "平均",
    "日均",
    "合计",
    "总额",
    "超过",
    "大于",
    "小于",
    "不少于",
    "排名",
    "最高",
    "最低",
    "前十",
    "top",
}


# 这些列过于通用，不能单独证明某个计算规则适用
GENERIC_COLUMNS: Set[str] = {
    "pty_id",
    "prdt_id",
    "data_dt",
    "acct_id",
    "cust_id",
    "org_id",
}


# 表级触发只适合这些规则类型。
# calculation / metric 不应仅因为用了某张表就自动加载。
TABLE_TRIGGER_ALLOWED_TYPES: Set[str] = {
    "temporal",
    "filter",
    "filter_scope",
    "scope",
    "join",
    "mapping",
    "classification",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_related_columns(value: Any) -> List[str]:
    if not value:
        return []

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [
                str(item).strip()
                for item in parsed
                if str(item).strip()
            ]
    except (json.JSONDecodeError, TypeError):
        pass

    return []


def _question_has_any(question: str, keywords: List[str] | Set[str]) -> bool:
    question_lower = _normalize_text(question)
    return any(
        _normalize_text(keyword) in question_lower
        for keyword in keywords
        if keyword
    )


def _get_triggered_concepts(question: str) -> Set:
    """
    根据用户原始问题识别真正被触发的计算概念。
    不从已选列反向推导计算意图。
    """
    triggered = set()

    for concept, keywords in CONCEPT_TRIGGER_GROUPS.items():
        if _question_has_any(question, keywords):
            triggered.add(concept)

    return triggered


def _match_concept_group(target_concept: str) -> str | None:
    """
    判断规则的 target_concept 属于哪个受控概念组。
    """
    target_lower = _normalize_text(target_concept)

    for concept, keywords in CONCEPT_TRIGGER_GROUPS.items():
        concept_terms = [concept, *keywords]
        if any(
            _normalize_text(term) in target_lower
            or target_lower in _normalize_text(term)
            for term in concept_terms
            if term
        ):
            return concept

    return None


def _is_calculation_rule(rule: Dict[str, Any]) -> bool:
    rule_type = _normalize_text(rule.get("rule_type"))
    formula = _normalize_text(rule.get("formula"))

    calculation_types = {
        "calculation",
        "aggregation",
        "metric",
        "formula",
        "统计",
        "计算",
        "聚合",
        "指标",
    }

    formula_signals = (
        "sum(",
        "avg(",
        "count(",
        "having ",
        "calendar_day_count",
    )

    return (
        rule_type in calculation_types
        or any(signal in formula for signal in formula_signals)
    )


def _evaluate_rule_applicability(
    rule: Dict[str, Any],
    question: str,
    intent: str,
    selected_columns: Set[str],
    selected_tables: Set[str],
    triggered_concepts: Set[str],
) -> Tuple[bool, float, List[str]]:
    """
    判断候选规则是否真正适用于当前问题。

    返回:
        applicable: 是否保留
        score: 相关性分数
        reasons: 命中原因
    """
    score = 0.0
    reasons: List[str] = []

    question_lower = _normalize_text(question)
    intent_lower = _normalize_text(intent)

    rule_name = _normalize_text(rule.get("rule_name"))
    rule_type = _normalize_text(rule.get("rule_type"))
    target_concept = _normalize_text(rule.get("target_concept"))
    explanation = _normalize_text(rule.get("explanation"))
    examples = _normalize_text(rule.get("examples"))

    rule_columns = {
        _normalize_text(column)
        for column in _parse_related_columns(rule.get("related_columns"))
    }

    matched_columns = selected_columns & rule_columns
    specific_matched_columns = matched_columns - GENERIC_COLUMNS

    concept_group = _match_concept_group(target_concept)
    is_calculation_rule = _is_calculation_rule(rule)

    # 1. 问题明确命中 target_concept，属于最强信号
    if target_concept and target_concept in question_lower:
        score += 5.0
        reasons.append("问题直接命中 target_concept")

    # 2. 受控业务概念命中
    if concept_group and concept_group in triggered_concepts:
        score += 5.0
        reasons.append(f"问题触发业务概念: {concept_group}")

    # 3. 规则名称中的具体语义命中
    if rule_name and len(rule_name) >= 3 and rule_name in question_lower:
        score += 4.0
        reasons.append("问题直接命中规则名称")

    # 4. 具体业务列命中
    if specific_matched_columns:
        score += min(3.0, float(len(specific_matched_columns)))
        reasons.append(
            "命中具体业务列: "
            + ", ".join(sorted(specific_matched_columns))
        )

    # 5. 通用列只能提供很弱的相关性，不能激活计算规则
    generic_matched_columns = matched_columns & GENERIC_COLUMNS
    if generic_matched_columns:
        score += 0.2
        reasons.append(
            "仅命中通用列: "
            + ", ".join(sorted(generic_matched_columns))
        )

    # 6. intent 作为弱辅助信号
    if intent_lower:
        if intent_lower in target_concept or intent_lower in explanation:
            score += 1.0
            reasons.append("查询意图与规则语义匹配")

    # 7. 表级规则只允许 temporal/filter/scope/join 等类型
    table_trigger_allowed = rule_type in TABLE_TRIGGER_ALLOWED_TYPES

    if table_trigger_allowed and selected_tables:
        score += 1.0
        reasons.append("属于允许表级触发的规则类型")

    # 8. 关键防误报逻辑:
    # 如果是受控计算概念，但问题没有明确触发，则直接排除。
    if is_calculation_rule and concept_group:
        if concept_group not in triggered_concepts:
            return (
                False,
                score,
                reasons + [
                    f"排除: 问题未要求计算“{concept_group}”"
                ],
            )

    # 9. 计算规则不能仅依靠通用 ID、产品列或日期列激活
    if is_calculation_rule:
        has_explicit_calculation_intent = _question_has_any(
            question,
            CALCULATION_KEYWORDS,
        )

        has_specific_column_match = bool(specific_matched_columns)

        if (
            not has_explicit_calculation_intent
            and not has_specific_column_match
            and not (
                concept_group
                and concept_group in triggered_concepts
            )
        ):
            return (
                False,
                score,
                reasons + [
                    "排除: 计算规则仅命中通用列或表，问题无计算意图"
                ],
            )

    # 10. “持有某产品”与“计算持仓市值”要严格区分
    has_existence_intent = _question_has_any(
        question,
        EXISTENCE_KEYWORDS,
    )

    has_value_intent = _question_has_any(
        question,
        {
            "市值",
            "金额",
            "多少",
            "超过",
            "大于",
            "不少于",
            "合计",
            "总额",
            "排名",
        },
    )

    if (
        has_existence_intent
        and not has_value_intent
        and concept_group == "持仓市值"
    ):
        return (
            False,
            score,
            reasons + [
                "排除: 当前问题只判断是否持有，不计算持仓市值"
            ],
        )

    # 非计算规则门槛稍低，计算规则门槛更高
    minimum_score = 3.0 if is_calculation_rule else 1.0

    applicable = score >= minimum_score

    if not applicable:
        reasons.append(
            f"排除: 相关性分数 {score:.1f} 低于门槛 {minimum_score:.1f}"
        )

    return applicable, score, reasons


async def get_relevant_business_rules(
    question: str,
    intent: str,
    relevant_columns: Dict[str, List[str]],
    candidate_limit: int = 30,
    final_limit: int = 8,
) -> List[Dict[str, Any]]:
    """
    根据问题和已选列检索相关业务规则。

    流程:
    1. 数据库宽召回候选规则
    2. Python 判断规则是否适用
    3. 排除仅由通用列或表触发的计算规则
    4. 按适用分数和优先级排序
    5. 返回少量高质量规则

    Args:
        question: 用户问题
        intent: 查询意图
        relevant_columns: 已选择的表和列
        candidate_limit: 第一阶段候选召回数量
        final_limit: 最终返回给 SQL Generator 的规则数量
    """
    try:
        question = question or ""
        intent = intent or ""
        relevant_columns = relevant_columns or {}

        all_tables = {
            _normalize_text(table)
            for table in relevant_columns.keys()
            if table
        }

        all_columns = {
            _normalize_text(column)
            for columns in relevant_columns.values()
            for column in (columns or [])
            if column
        }

        if not question.strip() and not all_columns and not all_tables:
            return []

        triggered_concepts = _get_triggered_concepts(question)

        conditions = []
        params: List[Any] = []

        # 1. 问题明确包含 target_concept
        conditions.append(
            """
            instr(
                lower(?),
                lower(target_concept)
            ) > 0
            """
        )
        params.append(question)

        # 2. target_concept 包含问题触发的受控业务概念
        for concept in triggered_concepts:
            conditions.append(
                "instr(lower(target_concept), lower(?)) > 0"
            )
            params.append(concept)

        # 3. 召回列相关规则
        # 此处允许召回，但后续 Python 会阻止通用列激活计算规则
        for column in sorted(all_columns):
            conditions.append(
                "instr(lower(related_columns), lower(?)) > 0"
            )
            params.append(f'"{column}"')

        # 4. 表级召回只召回允许表级触发的规则类型
        # 注意这里没有依赖 meta_column_semantics 的具体表结构，
        # 如果你的表结构支持，可以继续追加表级候选。
        if all_tables:
            table_placeholders = ", ".join(
                ["?"] * len(all_tables)
            )

            allowed_type_placeholders = ", ".join(
                ["?"] * len(TABLE_TRIGGER_ALLOWED_TYPES)
            )

            conditions.append(
                f"""
                (
                    lower(rule_type) IN ({allowed_type_placeholders})
                    AND rule_id IN (
                        SELECT DISTINCT mbr.rule_id
                        FROM meta_business_rules mbr
                        JOIN meta_column_semantics mcs
                        ON mcs.related_concept = mbr.target_concept
                        WHERE lower(mcs.table_name)
                            IN ({table_placeholders})
                    )
                )
                """
            )

            params.extend(sorted(TABLE_TRIGGER_ALLOWED_TYPES))
            params.extend(sorted(all_tables))

        if not conditions:
            return []

        where_clause = " OR ".join(
            f"({condition})"
            for condition in conditions
        )

        query = f"""
        SELECT
            rule_id,
            rule_name,
            rule_type,
            target_concept,
            formula,
            related_columns,
            explanation,
            examples,
            priority
        FROM meta_business_rules
        WHERE is_active = 1
        AND (
            {where_clause}
        )
        ORDER BY priority DESC, rule_id
        LIMIT ?
        """

        params.append(candidate_limit)

        result = await execute_sql_query(
            query,
            params=params,
        )



        if not result.get("success"):
            logger.warning(
                "[schema_retriever] 业务规则候选召回失败"
            )
            return []

        candidates = result.get("data", [])
        print(candidates)

        selected_rules: List[Dict[str, Any]] = []

        for rule in candidates:
            rule["related_columns"] = _parse_related_columns(
                rule.get("related_columns")
            )

            applicable, score, reasons = _evaluate_rule_applicability(
                rule=rule,
                question=question,
                intent=intent,
                selected_columns=all_columns,
                selected_tables=all_tables,
                triggered_concepts=triggered_concepts,
            )

            logger.debug(
                "[schema_retriever] rule=%s, applicable=%s, "
                "score=%.1f, reasons=%s",
                rule.get("rule_name"),
                applicable,
                score,
                reasons,
            )

            if not applicable:
                continue

            rule["relevance_score"] = score
            rule["match_reasons"] = reasons
            selected_rules.append(rule)

        selected_rules.sort(
            key=lambda rule: (
                rule.get("relevance_score", 0),
                rule.get("priority", 0),
            ),
            reverse=True,
        )

        final_rules = selected_rules[:final_limit]

        logger.info(
            "[schema_retriever] 候选规则=%d, 适用规则=%d, "
            "最终规则=%d, tables=%s, columns=%s, "
            "triggered_concepts=%s",
            len(candidates),
            len(selected_rules),
            len(final_rules),
            sorted(all_tables),
            sorted(all_columns),
            sorted(triggered_concepts),
        )

        logger.warning(
            "[schema_retriever] 最终业务规则: %s",
            [
                {
                    "rule_id": rule.get("rule_id"),
                    "rule_name": rule.get("rule_name"),
                    "score": rule.get("relevance_score"),
                    "reasons": rule.get("match_reasons"),
                }
                for rule in final_rules
            ],
        )

        return final_rules

    except Exception as exc:
        logger.exception(
            "[schema_retriever] 获取业务规则失败: %s",
            exc,
        )
        return []


async def get_column_semantics(
    table_name: str, 
    columns: List[str]
) -> Dict[str, Dict[str, Any]]:
    """获取列的业务语义信息"""
    try:
        if not columns:
            return {}
            
        columns_placeholder = ", ".join([f"'{col}'" for col in columns])
        
        query = f"""
        SELECT column_name, business_name, is_measure, is_dimension,
               calculation_type, related_concept, warning_message, usage_note
        FROM meta_column_semantics
        WHERE table_name = ? AND column_name IN ({columns_placeholder})
        """
        
        result = await execute_sql_query(query, params=[table_name])
        
        if result.get("success"):
            semantics = {}
            for row in result.get("data", []):
                col_name = row["column_name"]
                semantics[col_name] = row
            return semantics
        else:
            return {}
            
    except Exception as e:
        logger.warning(f"[schema_retreiver] 获取列语义失败: {e}")
        return {}


def format_business_rules_for_prompt(rules: List[Dict[str, Any]]) -> str:
    """格式化业务规则为Prompt可用文本"""
    if not rules:
        return ""
    
    formatted = ["## 📌 相关业务规则（必须遵守）\n"]
    
    for rule in rules:
        formatted.append(f"### {rule['rule_name']}")
        formatted.append(f"- **业务概念**: {rule['target_concept']}")
        formatted.append(f"- **说明**: {rule['explanation']}")
        if rule.get('formula'):
            formatted.append(f"- **计算公式**: `{rule['formula']}`")
        if rule.get('examples'):
            formatted.append(f"- **示例**:\n```sql\n{rule['examples']}\n```")
        formatted.append("")
    
    return "\n".join(formatted)


def format_column_semantics_for_prompt(
    table_name: str, 
    semantics: Dict[str, Dict[str, Any]]
) -> str:
    """格式化列语义信息为Prompt可用文本"""
    if not semantics:
        return ""
    
    formatted = [f"## 📊 表 `{table_name}` 的列业务说明\n"]
    
    for col_name, info in semantics.items():
        business_name = info.get('business_name', col_name)
        formatted.append(f"### `{col_name}` - {business_name}")
        
        if info.get('usage_note'):
            formatted.append(f"  ℹ️ {info['usage_note']}")
        
        if info.get('warning_message'):
            formatted.append(f"  ⚠️ **警告**: {info['warning_message']}")
        
        if info.get('related_concept'):
            formatted.append(f"  🔗 关联概念: {info['related_concept']}")
            
        formatted.append("")
    
    return "\n".join(formatted)


def _is_clean_text(value: Any) -> bool:
    """只有纯 '?'/空白时才视为无效（metadata 历史导入编码损坏会让中文变成 ?）。"""
    if not value:
        return False
    return any(ch not in "? \t\n\r" for ch in str(value))


async def get_column_metadata_map() -> Dict[str, Dict[str, Any]]:
    """从 meta_column_semantics 按表聚合列信息（维度/度量/其他列）及可选业务说明。

    返回 {table_name: {"columns", "dimensions", "measures", "other", "description"}}。
    全量业务表（dim_*/fact_*/ads_* 等）均已被该元数据表覆盖。
    """
    meta: Dict[str, Dict[str, Any]] = {}
    try:
        query = (
            "SELECT table_name, column_name, business_name, is_dimension, "
            "is_measure, calculation_type, aggregation_behavior, temporal_type "
            "FROM meta_column_semantics"
        )
        result = await execute_sql_query(query)
        if not result or not result.get("success"):
            return meta
        for row in result.get("data", []):
            table_name = row.get("table_name")
            if not table_name:
                continue
            entry = meta.setdefault(
                table_name,
                {"columns": [], "dimensions": [], "measures": [], "other": [], "description": None},
            )
            column_name = row.get("column_name")
            if column_name:
                entry["columns"].append(column_name)
                is_dim = row.get("is_dimension")
                is_meas = row.get("is_measure")
                if is_dim:
                    entry["dimensions"].append(column_name)
                elif is_meas:
                    entry["measures"].append(column_name)
                else:
                    entry["other"].append(column_name)
            if entry["description"] is None and _is_clean_text(row.get("business_name")):
                entry["description"] = row.get("business_name")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("读取 meta_column_semantics 失败: %s", exc)
    return meta


def _build_table_candidate(table: str, meta_row: Dict[str, Any]) -> str:
    """为单张表生成供 LLM 选择的候选描述（维度列/度量列/其他列 + 可选业务说明）。"""
    parts = [f"- `{table}`"]
    description = meta_row.get("description")
    if description:
        parts.append(f"  业务说明: {description}")
    dims = meta_row.get("dimensions", [])
    measures = meta_row.get("measures", [])
    other = meta_row.get("other", [])
    if dims:
        parts.append(f"  维度列: [{', '.join(dims)}]")
    if measures:
        parts.append(f"  度量列: [{', '.join(measures)}]")
    if other:
        parts.append(f"  其他列: [{', '.join(other)}]")
    return "\n".join(parts)


async def retrieve_tables_only(question: str, intent: str, llm) -> List[Dict[str, Any]]:
    """回退路径：仅让 LLM 从全部表中选择相关表（合并检索返回为空时使用）。"""
    try:
        all_tables = await get_all_tables()
        table_list_text = "\n".join(f"- `{t}`" for t in all_tables) if all_tables else "(无可用表)"
        formatted_prompt = table_retriever_prompt.format(table_list=table_list_text)
        messages = [
            SystemMessage(content=formatted_prompt),
            HumanMessage(content=f"问题：{question}\n意图：{intent}\n可用表：{all_tables}")
        ]
        response = generate_structured_data(llm, messages, TableRetrieverResponse)
        return [table.model_dump() for table in response.relevant_tables]
    except Exception as exc:
        logger.warning("仅表检索失败: %s", exc)
        return []


async def retrieve_tables_and_columns(
    question: str,
    intent: str,
    llm,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    """合并检索：一次 LLM 调用同时选出「相关表 + 相关列」（方法3：由 LLM 完成语义匹配）。

    候选依据为 meta_column_semantics 的列清单与维度/度量标记，而非「仅前 5 列」的薄信号，
    从而降低漏选必要表的可能。未在该元数据表覆盖的表会回退到真实 schema 列，保证表可达。
    """
    try:
        all_tables = await get_all_tables()
        meta = await get_column_metadata_map()
        candidate_rows: List[Tuple[str, Dict[str, Any]]] = []
        for table in all_tables:
            meta_row = meta.get(table)
            if meta_row is None:
                schema = await get_table_schema(table)
                columns = extract_columns_from_schema(schema)
                candidate_rows.append((
                    table,
                    {"columns": columns, "other": columns, "dimensions": [], "measures": [], "description": None},
                ))
            else:
                candidate_rows.append((table, meta_row))

        table_list_text = "\n".join(_build_table_candidate(t, m) for t, m in candidate_rows)
        formatted_prompt = table_retriever_prompt.format(table_list=table_list_text)
        messages = [
            SystemMessage(content=formatted_prompt),
            HumanMessage(content=f"问题：{question}\n意图：{intent}\n可用表：{all_tables}")
        ]
        response = generate_structured_data(llm, messages, TableRetrieverResponse)

        relevant_tables = []
        relevant_columns = {}
        for table in response.relevant_tables:
            data = table.model_dump()
            columns = data.pop("relevant_columns", []) or []
            relevant_tables.append(data)
            if columns:
                relevant_columns[data["table_name"]] = columns
        return relevant_tables, relevant_columns
    except Exception as exc:
        logger.warning("合并检索失败: %s", exc)
        return [], {}


async def schema_retreiver(state: Chat2DataState) -> Chat2DataState:
    """
    检索表结构和专有名词的节点函数

    流程：
    1. LLM 分析 question 得到 intent
    2. 一次 LLM 调用同时选出「相关表 + 相关列」。
    # 依据 meta_column_semantics 的列清单与维度/度量标记，由 LLM 直接完成语义匹配（方法3）
    4. 拼接 schema_info
    5. 使用 question 和 intent 检索 few_shot_examples（最多10个）

    Args:
        state: Chat2DataState 状态字典

    Returns:
        Chat2DataState: 更新后的状态
    """
    question = state.get("question", "")
    llm = get_model()

    # Step 1: 分析意图
    try:
        intent_messages = [
            SystemMessage(content=intent_prompt),
            HumanMessage(content=question)
        ]
        intent_response = generate_structured_data(llm, intent_messages, IntentResponse)
        intent = intent_response.intent
        print("intent:{}".format(intent))
    except:
        intent = "data_query"
        print("Default intent")

    # none_query: 非数据问题，跳过全部 RAG 检索，直接返回基础状态
    if intent == "none_query":
        print("[schema_retriever] none_query 跳过 RAG，直接返回")
        return {
            "intent": intent,
            "relevant_tables": [],
            "relevant_columns": {},
            "schema_info": {},
            "few_shot_examples": [],
            "entity_corrections": [],
        }

    # Step 2（合并）：一次 LLM 调用同时选出「相关表 + 相关列」。
    # 依据 meta_column_semantics 的列清单与维度/度量标记，由 LLM 直接完成语义匹配（方法3），
    # 避免「仅前 5 列」薄信号导致漏选必要表。
    relevant_tables, relevant_columns = await retrieve_tables_and_columns(question, intent, llm)

    # 回退：合并检索返回为空时，先只选表，再取该表全部列，避免整表丢失。
    if not relevant_tables:
        logger.info("合并检索返回为空，回退到仅选表 + 全部列")
        relevant_tables = await retrieve_tables_only(question, intent, llm)
        for table_info in relevant_tables:
            schema = await get_table_schema(table_info["table_name"])
            relevant_columns[table_info["table_name"]] = extract_columns_from_schema(schema)

    # 为选中的表取真实 schema，用于拼 DDL。
    schemas = {}
    for table_info in relevant_tables:
        schemas[table_info["table_name"]] = await get_table_schema(table_info["table_name"])
    # Step 4: 检索业务规则和列语义信息
    business_rules = []
    all_column_semantics = {}
    try:
        business_rules = await get_relevant_business_rules(
            question=question,
            intent=intent,
            relevant_columns=relevant_columns
        )
        print(f"[schema_retreiver] 检索到 {len(business_rules)} 条业务规则")
        print(business_rules)
    except Exception as e:
        logger.warning(f"[schema_retreiver] 业务规则检索失败: {e}")
        business_rules = []
    
    try:
        for table_name, columns in relevant_columns.items():
            semantics = await get_column_semantics(table_name, columns)
            if semantics:
                all_column_semantics[table_name] = semantics
                logger.info(f"[schema_retreiver] 表 {table_name} 命中 {len(semantics)} 条列语义")
            else:
                logger.warning(f"[schema_retreiver] 表 {table_name} 未命中列语义 (可选列: {columns})")
        print(f"[schema_retreiver] 获取 {len(all_column_semantics)} 个表的列语义")
    except Exception as e:
        logger.warning(f"[schema_retreiver] 列语义检索失败: {e}")
        all_column_semantics = {}
    
    # Step 5: 拼接 schema_info（增强版）
    formatted_ddl = format_schema_info(schemas)
    
    # 添加业务规则说明
    if business_rules:
        formatted_ddl += "\n\n" + format_business_rules_for_prompt(business_rules)
    
    # 添加列语义说明
    for table_name, semantics in all_column_semantics.items():
        if semantics:
            formatted_ddl += "\n\n" + format_column_semantics_for_prompt(table_name, semantics)
    
    schema_info = {
        "tables": schemas,
        "formatted_ddl": formatted_ddl,
        "business_rules": business_rules,          # 结构化的规则（供后续验证使用）
        "column_semantics": all_column_semantics   # 结构化的列语义（供后续验证使用）
    }
    
    try:
        # Step 6: 使用 question 和 intent 检索 few-shot examples（最多10个）
        few_shot_examples = await retrieve_few_shot_examples(question, intent)

        if few_shot_examples:
            examples_text = "\n".join([
                f"问题: {ex['question']}\nSQL: {ex['sql']}"
                for ex in few_shot_examples
            ])
        print("examples sql success")
    except Exception as e:
        print(e)
        few_shot_examples = []

    # Step 7: 实体纠错——抽取用户问题中的实体词并映射到数据库真实取值
    entity_corrections = []
    try:
        llm = get_model()
        corrector = EntityCorrector(llm=llm)
        entity_corrections = corrector.correct_entities(question, llm=llm)
        if entity_corrections:
            logger.info(
                f"[schema_retreiver] 实体纠错完成: "
                f"{len(entity_corrections)} 个修正映射"
            )
    except Exception as e:
        logger.warning(f"[schema_retreiver] 实体纠错跳过: {e}")
        entity_corrections = []

    # 返回更新后的状态
    return {
        **state,
        "intent": intent,
        "relevant_tables": relevant_tables,
        "relevant_columns": relevant_columns,
        "schema_info": schema_info,
        "few_shot_examples": few_shot_examples,
        "entity_corrections": entity_corrections,
    }
