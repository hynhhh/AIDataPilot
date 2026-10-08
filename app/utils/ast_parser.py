"""
@File: ast_parser.py
@Desc: 校验sql,拦截除了select之外的
@Author: h&m
@Date: 8.13
"""
from typing import Dict, List, Any, Tuple, Optional
import sqlglot
import sqlparse


class SQLValidationError(Exception):
    """SQL 验证错误异常"""
    pass


def parse_sql_ast(sql: str, dialect: str = "sqlite"):
    """
    解析 SQL 为 AST 抽象语法树
    
    Args:
        sql: SQL 语句
        dialect: SQL 方言 (sqlite, postgres, mysql 等)
        
    Returns:
        sqlglot.Expression: AST 对象
        
    Raises:
        SQLValidationError: SQL 解析失败
    """
    try:
        # 使用 sqlglot 解析 SQL
        ast = sqlglot.parse_one(sql, dialect=dialect)
        return ast
    except Exception as e:
        raise SQLValidationError(f"SQL 解析失败: {str(e)}")


def validate_select_only(sql: str, dialect: str = "sqlite") -> Tuple[bool, str]:
    """
    验证 SQL 是否只包含 SELECT 查询，拦截 INSERT, UPDATE, DELETE, DROP 等危险操作
    """
    try:
        ast = parse_sql_ast(sql, dialect)
        
        # 1. 获取顶层语句类名
        statement_type = type(ast).__name__
        
        # 2. 定义危险 AST 节点的类名（包含 DDL 和 DML 修改操作）
        dangerous_node_types = {
            "Insert", "Update", "Delete", "Drop", "Truncate", "Create", "Alter",
            "Grant", "Revoke", "Command", "CommandStatement"
        }
        
        # 3. 拦截：如果最外层直接就是危险类型
        if statement_type in dangerous_node_types:
            return False, f"{statement_type.upper()} 操作被禁止"
            
        # 4. 深度扫描：遍历整棵 AST 语法树，确保子节点中没有任何修改或危险节点
        # 比如：防止有人在 SELECT 子查询里嵌套危险操作，或者通过 UNION 结合恶意命令
        for node_type in dangerous_node_types:
            # 根据 sqlglot 的命名约定寻找对应的表达式类型
            exp_class = getattr(sqlglot.exp, node_type, None)
            if exp_class and list(ast.find_all(exp_class)):
                return False, f"检测到未授权的 {node_type.upper()} 行为"
                
        # 5. 【双重物理防线】：最前端字符必须是只读查询关键字
        # 防止 sqlglot 无法解析某些恶意拼装的 SQL 导致漏网
        clean_sql = sql.strip().upper()
        if not (clean_sql.startswith("SELECT") or clean_sql.startswith("WITH") or clean_sql.startswith("(")):
            return False, f"非法查询起始，当前语句类型: {statement_type}"

        # 验证通过，确认为安全查询
        return True, ""
        
    except SQLValidationError as e:
        return False, str(e)
    except Exception as e:
        return False, f"SQL 验证失败: {str(e)}"



def extract_tables_from_sql(sql: str, dialect: str = "sqlite") -> List[str]:
    """
    从 SQL 中提取所有涉及的表名（排除 CTE 别名）
    
    Args:
        sql: SQL 语句
        dialect: SQL 方言
        
    Returns:
        List[str]: 表名列表（不包含 CTE 别名）
    """
    try:
        ast = parse_sql_ast(sql, dialect)
        
        # 1. 提取所有 CTE 别名
        cte_aliases = set()
        for cte in ast.find_all(sqlglot.exp.CTE):
            alias = cte.alias
            if alias:
                cte_aliases.add(alias)
        
        # 2. 遍历 AST 查找所有表引用
        tables = []
        for table in ast.find_all(sqlglot.exp.Table):
            table_name = table.name
            # 排除 CTE 别名
            if table_name and table_name not in cte_aliases:
                tables.append(table_name)
        
        return list(set(tables))  # 去重
    except:
        return []


def _column_inside_cte(column) -> bool:
    """判断某列引用是否位于某个 CTE 定义体内部（向上遍历 .parent 链检测 CTE 祖先）。"""
    n = column.parent
    while n is not None:
        if isinstance(n, sqlglot.exp.CTE):
            return True
        n = n.parent
    return False


def extract_columns_from_sql(sql: str, dialect: str = "sqlite", exclude_cte_body: bool = False) -> List[str]:
    """
    从 SQL 中提取所有涉及的列名
    
    Args:
        sql: SQL 语句
        dialect: SQL 方言
        
    Returns:
        List[str]: 列名列表
    """
    try:
        ast = parse_sql_ast(sql, dialect)
        columns = []
        
        # 遍历 AST 查找所有列引用（可按需跳过 CTE 定义体内部的列）
        for column in ast.find_all(sqlglot.exp.Column):
            if exclude_cte_body and _column_inside_cte(column):
                continue
            column_name = column.name
            if column_name and column_name != "*":
                columns.append(column_name)

        return list(set(columns))  # 去重
    except:
        return []


def extract_output_columns(sql: str, dialect: str = "sqlite") -> List[str]:
    """
    从 SQL 中提取最外层 SELECT 的输出列（结果列名 / 别名）。

    仅返回最外层查询的投影列（带别名取别名，无别名取列名），忽略 CTE 与子查询
    的中间列，因此可用于「指标命中」（对比参考 / 生成结果集的最后输出列名）。

    Args:
        sql: SQL 语句
        dialect: SQL 方言 (sqlite, postgres, mysql 等)

    Returns:
        List[str]: 输出列名列表（小写，去重）
    """
    try:
        ast = parse_sql_ast(sql, dialect)
    except Exception:
        return []

    # 定位最外层 Select（parent_select 为 None 的查询，避免把子查询/CTE 中间列当输出列）
    select = None
    for s in ast.find_all(sqlglot.exp.Select):
        if getattr(s, "parent_select", None) is None:
            select = s
            break
    if select is None:
        return []

    cols = []
    seen = set()
    for expr in select.expressions:
        name = getattr(expr, "output_name", "") or ""
        if not name:
            name = getattr(expr, "alias_or_name", "") or ""
        name = name.strip()
        if name and name != "*" and name.lower() not in seen:
            seen.add(name.lower())
            cols.append(name.lower())
    return cols


def validate_sql_syntax(sql: str, dialect: str = "sqlite") -> Tuple[bool, str]:
    """
    验证 SQL 语法是否正确
    
    Args:
        sql: SQL 语句
        dialect: SQL 方言
        
    Returns:
        Tuple[bool, str]: (是否有效, 错误消息)
    """
    try:
        # 使用 sqlparse 格式化验证
        parsed = sqlparse.parse(sql)
        if not parsed:
            return False, "SQL 语句为空或无法解析"
        
        # 使用 sqlglot 解析验证
        parse_sql_ast(sql, dialect)
        
        return True, ""
    except SQLValidationError as e:
        return False, str(e)
    except Exception as e:
        return False, f"SQL 语法错误: {str(e)}"


def validate_tables_exist(sql: str, allowed_tables: List[str], dialect: str = "sqlite") -> Tuple[bool, str]:
    """
    验证 SQL 中使用的表是否都在允许列表中
    
    Args:
        sql: SQL 语句
        allowed_tables: 允许的表名列表
        dialect: SQL 方言
        
    Returns:
        Tuple[bool, str]: (是否有效, 错误消息)
    """
    try:
        used_tables = extract_tables_from_sql(sql, dialect)
        
        # 检查是否有未授权的表
        unauthorized_tables = [t for t in used_tables if t not in allowed_tables]
        
        if unauthorized_tables:
            return False, f"使用了未授权的表: {', '.join(unauthorized_tables)}"
        
        return True, ""
    except Exception as e:
        return False, f"表验证失败: {str(e)}"


def format_sql(sql: str) -> str:
    """
    格式化 SQL 语句
    
    Args:
        sql: SQL 语句
        
    Returns:
        str: 格式化后的 SQL
    """
    try:
        return sqlparse.format(
            sql,
            reindent=True,
            keyword_case='upper',
            strip_comments=True
        )
    except:
        return sql


def _classify_layer(table_name: str, layer_prefixes: Dict[str, str]) -> Optional[str]:
    """按前缀识别物理表所属数仓层；无匹配返回 None。"""
    if not table_name:
        return None
    lower = table_name.lower()
    for prefix, layer in layer_prefixes.items():
        if lower.startswith(prefix):
            return layer
    return None


def _layer_of_operand(operand: Any, layer_prefixes: Dict[str, str]) -> Optional[str]:
    """判断 FROM / JOIN 操作数（物理表或派生子查询）所在数仓层。

    - 物理表：直接按表名前缀识别
    - 派生子查询 / 括号表达式：取内部第一个可识别的数仓表（启发式，单源子查询场景足够）
    """
    if operand is None:
        return None
    if isinstance(operand, sqlglot.exp.Table):
        return _classify_layer(operand.name, layer_prefixes)
    for table in operand.find_all(sqlglot.exp.Table):
        layer = _classify_layer(table.name, layer_prefixes)
        if layer is not None:
            return layer
    return None


def _get_sql_validation_config() -> Dict[str, Any]:
    """读取数仓分层校验配置（来自 core.config.settings），失败时回落到内置默认值。

    默认：dwd_/dws_/ads_/dim_/meta_/sql_ 前缀识别分层；跨层校验排除 meta_/sql_ 开头表；
    主时间字段 data_dt。DATALAKE_LAYERS 等字段支持用环境变量在外部覆盖，实现全局可配置。
    """
    config: Dict[str, Any] = {
        "layer_prefixes": {
            "dwd_": "dwd",
            "dws_": "dws",
            "ads_": "ads",
            "dim_": "dim",
            "meta_": "meta",
            "sql_": "sql",
        },
        "cross_layer_exclude_layers": {"meta", "sql"},
        "cross_layer_time_field": "data_dt",
    }
    try:
        from core.config import settings

        dl = getattr(settings, "DATALAKE_LAYERS", None)
        if isinstance(dl, dict) and dl:
            config["layer_prefixes"] = {str(k).lower(): str(v) for k, v in dl.items()}
        ex = getattr(settings, "CROSS_LAYER_EXCLUDE_LAYERS", None)
        if ex:
            config["cross_layer_exclude_layers"] = {str(x).lower() for x in ex}
        tf = getattr(settings, "CROSS_LAYER_TIME_FIELD", None)
        if tf:
            config["cross_layer_time_field"] = str(tf)
    except Exception:
        # settings 不可用（如测试隔离环境）时保持默认值
        pass
    return config


def check_unused_cte(sql: str, dialect: str = "sqlite") -> List[str]:
    """拦截"未使用的 CTE"：WITH 中定义却未被任何 FROM/JOIN（含子查询）引用的别名。

    命中则返回 error 文案，串入 ast_parser 聚合的 errors，经 sql_validator 打回大模型重写。
    """
    try:
        ast = parse_sql_ast(sql, dialect)
    except SQLValidationError:
        return []

    defined = {cte.alias for cte in ast.find_all(sqlglot.exp.CTE) if cte.alias}
    referenced = {t.name for t in ast.find_all(sqlglot.exp.Table) if t.name}

    unused = sorted(defined - referenced)
    return [
        f"未使用 CTE：'{name}' 已定义但未被任何 FROM/JOIN 引用，属于无用 CTE，请删除或确保被引用。"
        for name in unused
    ]


def _has_time_alignment(on_expr: Any, time_field: str) -> bool:
    """判断 ON 条件中是否出现时间字段的双边等值对齐（如 a.data_dt = b.data_dt）。"""
    if on_expr is None:
        return False
    tf = time_field.lower()
    for eq in on_expr.find_all(sqlglot.exp.EQ):
        left, right = eq.left, eq.right
        if (
            isinstance(left, sqlglot.exp.Column)
            and isinstance(right, sqlglot.exp.Column)
            and left.name.lower() == tf
            and right.name.lower() == tf
            and left.table.lower() != right.table.lower()
        ):
            return True
    return False


def check_cross_layer_join(
    sql: str, dialect: str = "sqlite", config: Optional[Dict[str, Any]] = None
) -> List[str]:
    """阻断跨层笛卡尔积风险：dwd_/dws_/ads_/dim_ 之间跨层 JOIN 时，ON 必须包含时间字段对齐。

    排除条件（任一命中即跳过该校验）：
    - 任一操作数所属层为未识别层
    - 任一操作数所属层为排除层（meta_ / sql_ 开头表）
    - 两端同层

    命中则返回 error 文案，串入 ast_parser 聚合的 errors，经 sql_validator 打回大模型重写。
    """
    if config is None:
        config = _get_sql_validation_config()
    layer_prefixes = config["layer_prefixes"]
    exclude_layers = config["cross_layer_exclude_layers"]
    time_field = config["cross_layer_time_field"]

    try:
        ast = parse_sql_ast(sql, dialect)
    except SQLValidationError:
        return []

    errors: List[str] = []
    for select in ast.find_all(sqlglot.exp.Select):
        from_operand = select.args.get("from_")
        left_layer = _layer_of_operand(
            from_operand.this if from_operand else None, layer_prefixes
        )
        for join in select.args.get("joins") or []:
            right_layer = _layer_of_operand(join.args.get("this"), layer_prefixes)
            on_expr = join.args.get("on")

            if (
                left_layer
                and right_layer
                and left_layer not in exclude_layers
                and right_layer not in exclude_layers
                and left_layer != right_layer
                and not _has_time_alignment(on_expr, time_field)
            ):
                errors.append(
                    f"跨层 JOIN 阻断：{left_layer} 层 与 {right_layer} 层 表关联时，"
                    f"ON 条件缺少时间字段 '{time_field}' 对齐，存在数据爆炸（笛卡尔积）风险。"
                    f"请用两张表的时间分区字段（如 a.{time_field} = b.{time_field}）关联后再 JOIN。"
                )

            # 推进 LEFT 侧到本次 JOIN 的右侧，供同一次查询的后续 JOIN 逐个校验
            left_layer = right_layer

    return errors


def check_conflicting_joins(sql: str, dialect: str = "sqlite") -> List[str]:
    """识别冲突的 JOIN 类型：对 LEFT JOIN 引入的表（允许匹配为空）后续施加非空限制。

    LEFT JOIN 的表本应允许为空，若后续 WHERE / INNER JOIN 的 ON 条件又对其字段施加
    IS NOT NULL，语义上等价于退化为 INNER JOIN，属潜在误用。命中返回 warning 文案，
    串入 ast_parser 聚合的 warnings（仅记录，不强制阻断）。
    """
    try:
        ast = parse_sql_ast(sql, dialect)
    except SQLValidationError:
        return []

    left_join_aliases = set()
    for select in ast.find_all(sqlglot.exp.Select):
        for join in select.args.get("joins") or []:
            side = str(join.args.get("side") or "").upper()
            right = join.args.get("this")
            if right is None:
                continue
            alias = getattr(right, "alias", None)
            if side == "LEFT" and alias:
                left_join_aliases.add(alias.lower())

    warnings: List[str] = []
    for is_node in ast.find_all(sqlglot.exp.Is):
        if isinstance(is_node.args.get("expression"), sqlglot.exp.Null):
            col = is_node.args.get("this")
            if (
                isinstance(col, sqlglot.exp.Column)
                and col.table
                and col.table.lower() in left_join_aliases
            ):
                warnings.append(
                    f"冲突 JOIN 警告：表 '{col.table}' 经 LEFT JOIN 关联（允许匹配为空），"
                    f"却在后续 WHERE/JOIN 中对 '{col.table}.{col.name}' 施加 IS NOT NULL 非空限制，"
                    f"语义冲突（等价于 INNER JOIN）。请确认是否误用。"
                )

    return warnings


def ast_parser(sql: str, allowed_tables: List[str] = None, dialect: str = "sqlite") -> Dict[str, Any]:
    """
    完整的 SQL AST 解析和验证
    
    Args:
        sql: SQL 语句
        allowed_tables: 允许的表名列表（可选）
        dialect: SQL 方言
        
    Returns:
        Dict: 验证结果，包含:
            - is_valid: bool - 是否通过验证
            - errors: List[str] - 错误列表
            - warnings: List[str] - 警告列表
            - tables: List[str] - 使用的表
            - columns: List[str] - 使用的列
            - formatted_sql: str - 格式化后的 SQL
    """
    errors = []
    warnings = []
    tables = []
    columns = []
    
    # 1. 语法验证
    is_valid, error_msg = validate_sql_syntax(sql, dialect)
    if not is_valid:
        errors.append(error_msg)
        return {
            "is_valid": False,
            "errors": errors,
            "warnings": warnings,
            "tables": [],
            "columns": [],
            "formatted_sql": sql
        }
    
    # 2. SELECT 验证（拦截危险操作）
    is_select, error_msg = validate_select_only(sql, dialect)
    if not is_select:
        errors.append(error_msg)
        return {
            "is_valid": False,
            "errors": errors,
            "warnings": warnings,
            "tables": [],
            "columns": [],
            "formatted_sql": sql
        }
    
    # 3. 提取表和列
    tables = extract_tables_from_sql(sql, dialect)
    columns = extract_columns_from_sql(sql, dialect)
    
    # 4. 表权限验证（如果提供了允许列表）
    if allowed_tables is not None:
        is_authorized, error_msg = validate_tables_exist(sql, allowed_tables, dialect)
        if not is_authorized:
            errors.append(error_msg)
    
    # 5. 数仓质量校验：未使用 CTE（error）、跨层笛卡尔积（error）、冲突 JOIN（warning）
    for cte_error in check_unused_cte(sql, dialect):
        errors.append(cte_error)
    errors.extend(check_cross_layer_join(sql, dialect, _get_sql_validation_config()))
    warnings.extend(check_conflicting_joins(sql, dialect))

    # 6. 格式化 SQL
    formatted_sql = format_sql(sql)

    # 返回验证结果
    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "tables": tables,
        "columns": columns,
        "formatted_sql": formatted_sql
    }