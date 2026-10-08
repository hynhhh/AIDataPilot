"""Unit tests for the deterministic SQL AST utility."""

from __future__ import annotations

import pytest
import sqlglot
from utils.ast_parser import (
    SQLValidationError,
    ast_parser,
    extract_columns_from_sql,
    extract_tables_from_sql,
    format_sql,
    parse_sql_ast,
    validate_select_only,
    validate_sql_syntax,
    validate_tables_exist,
)


def test_parse_sql_ast_returns_select_expression():
    expression = parse_sql_ast("SELECT id FROM users")

    assert isinstance(expression, sqlglot.exp.Select)


def test_parse_sql_ast_wraps_parse_errors():
    with pytest.raises(SQLValidationError, match="SQL 解析失败"):
        parse_sql_ast("SELECT (")


@pytest.mark.parametrize("sql", ["SELECT 1", "SELECT id FROM users WHERE active = 1"])
def test_validate_select_only_accepts_select(sql):
    valid, error = validate_select_only(sql)

    assert valid is True
    assert error == ""


@pytest.mark.parametrize(
    ("sql", "operation"),
    [
        ("INSERT INTO users (id) VALUES (1)", "INSERT"),
        ("UPDATE users SET active = 0", "UPDATE"),
        ("DELETE FROM users", "DELETE"),
        ("DROP TABLE users", "DROP"),
    ],
)
def test_validate_select_only_rejects_mutations(sql, operation):
    valid, error = validate_select_only(sql)

    assert valid is False
    assert operation in error


def test_extract_tables_from_join_query():
    tables = extract_tables_from_sql(
        "SELECT u.id, o.total FROM users AS u JOIN orders AS o ON u.id = o.user_id"
    )

    assert set(tables) == {"users", "orders"}


def test_extract_columns_from_query():
    columns = extract_columns_from_sql(
        "SELECT u.id, o.total FROM users AS u JOIN orders AS o ON u.id = o.user_id"
    )

    assert set(columns) == {"id", "total", "user_id"}


def test_validate_sql_syntax_rejects_empty_input():
    valid, error = validate_sql_syntax("")

    assert valid is False
    assert "为空" in error


def test_validate_tables_exist_accepts_allowed_tables():
    valid, error = validate_tables_exist(
        "SELECT users.id FROM users JOIN orders ON users.id = orders.user_id",
        ["users", "orders"],
    )

    assert valid is True
    assert error == ""


def test_validate_tables_exist_rejects_unknown_table():
    valid, error = validate_tables_exist("SELECT * FROM secrets", ["users"])

    assert valid is False
    assert "secrets" in error


def test_format_sql_uppercases_keywords_and_removes_comments():
    formatted = format_sql("select id -- internal comment\nfrom users")

    assert "SELECT" in formatted
    assert "FROM" in formatted
    assert "internal comment" not in formatted


def test_ast_parser_returns_serializable_analysis():
    result = ast_parser("SELECT id FROM users", allowed_tables=["users"])

    assert result == {
        "is_valid": True,
        "errors": [],
        "warnings": [],
        "tables": ["users"],
        "columns": ["id"],
        "formatted_sql": "SELECT id\nFROM users",
    }


def test_ast_parser_rejects_multiple_statements():
    result = ast_parser("SELECT 1; DROP TABLE users")

    assert result["is_valid"] is False


@pytest.mark.known_defect
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SELECT INTO is currently accepted because only the root node is checked",
)
def test_ast_parser_rejects_select_into():
    result = ast_parser("SELECT id INTO users_backup FROM users", dialect="postgres")

    assert result["is_valid"] is False


@pytest.mark.known_defect
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="read-only set operations are not accepted by the root Select check",
)
def test_ast_parser_accepts_union_query():
    result = ast_parser("SELECT id FROM users UNION SELECT user_id FROM orders")

    assert result["is_valid"] is True


@pytest.mark.known_defect
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="CTE aliases are currently returned as physical tables",
)
def test_extract_tables_excludes_cte_aliases():
    tables = extract_tables_from_sql(
        "WITH recent AS (SELECT id FROM orders) SELECT id FROM recent"
    )

    assert set(tables) == {"orders"}


@pytest.mark.known_defect
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="table validation currently discards schema qualification",
)
def test_table_allowlist_checks_schema_qualification():
    valid, _ = validate_tables_exist("SELECT id FROM private.users", ["users"])

    assert valid is False


@pytest.mark.known_defect
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="dangerous functions are not inspected in the current AST walk",
)
def test_ast_parser_rejects_dangerous_functions():
    result = ast_parser("SELECT pg_sleep(10)", dialect="postgres")

    assert result["is_valid"] is False
