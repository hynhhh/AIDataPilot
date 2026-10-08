"""Unit tests for SQL validation orchestration."""

from __future__ import annotations

from enum import StrEnum
from types import SimpleNamespace

import pytest


class StubDatabaseType(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    MONGO = "mongo"


@pytest.fixture
def validator_setup(module_loader):
    calls = []

    def fake_ast_parser(**kwargs):
        calls.append(kwargs)
        return {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "tables": ["users"],
            "columns": ["id"],
            "formatted_sql": "SELECT id FROM users",
        }

    settings = SimpleNamespace(DATABASE_TYPE=StubDatabaseType.SQLITE)
    module = module_loader(
        "nodes.sql_validator",
        {
            "utils.ast_parser": {
                "ast_parser": fake_ast_parser,
                "validate_select_only": lambda *args, **kwargs: (True, ""),
                "validate_tables_exist": lambda *args, **kwargs: (True, ""),
            },
            "core.config": {"settings": settings, "DatabaseType": StubDatabaseType},
        },
    )
    return module, calls, settings


def test_get_allowed_tables_combines_and_deduplicates_sources(validator_setup, state_factory):
    module, _, _ = validator_setup
    state = state_factory(
        relevant_tables=[
            {"table_name": "users", "similarity": 0.9, "description": "customers"},
            {"table_name": "orders", "similarity": 0.8, "description": "orders"},
        ],
        schema_info={"tables": {"users": {}, "events": {}}, "formatted_ddl": ""},
    )

    assert set(module.get_allowed_tables_from_state(state)) == {"users", "orders", "events"}


def test_get_sql_dialect_maps_database_types(validator_setup):
    module, _, settings = validator_setup

    assert module.get_sql_dialect() == "sqlite"
    settings.DATABASE_TYPE = StubDatabaseType.POSTGRES
    assert module.get_sql_dialect() == "postgres"
    settings.DATABASE_TYPE = StubDatabaseType.MONGO
    assert module.get_sql_dialect() == "sqlite"


def test_validate_sql_security_passes_policy_context_to_ast_parser(
    validator_setup, state_factory
):
    module, calls, _ = validator_setup
    state = state_factory(
        relevant_tables=[
            {"table_name": "users", "similarity": 1.0, "description": "customers"}
        ]
    )

    result = module.validate_sql_security("SELECT id FROM users", state)

    assert result["is_valid"] is True
    assert calls == [
        {
            "sql": "SELECT id FROM users",
            "allowed_tables": ["users"],
            "dialect": "sqlite",
        }
    ]


@pytest.mark.parametrize(
    ("valid", "retry_count", "expected"),
    [(False, 0, True), (False, 3, False), (True, 0, False)],
)
def test_should_retry_generation(validator_setup, state_factory, valid, retry_count, expected):
    module, _, _ = validator_setup

    assert (
        module.should_retry_generation(
            {"is_valid": valid}, state_factory(retry_count=retry_count)
        )
        is expected
    )


@pytest.mark.asyncio
async def test_sql_validator_rejects_missing_sql(validator_setup, state_factory):
    module, _, _ = validator_setup
    state = state_factory(generated_sql="")

    result = await module.sql_validator(state)

    assert result["error_message"] == "没有生成 SQL 语句"
    assert result["retry_count"] == 1


@pytest.mark.asyncio
async def test_sql_validator_updates_sql_on_success(validator_setup, state_factory):
    module, _, _ = validator_setup
    state = state_factory(generated_sql="SELECT id FROM users")

    result = await module.sql_validator(state)

    assert result["generated_sql"] == "SELECT id FROM users"
    assert result["error_message"] == []
    assert result["retry_count"] == 0


@pytest.mark.asyncio
async def test_sql_validator_increments_retry_on_failure(validator_setup, state_factory, monkeypatch):
    module, _, _ = validator_setup
    monkeypatch.setattr(
        module,
        "validate_sql_security",
        lambda sql, state: {"is_valid": False, "errors": ["只允许 SELECT"]},
    )
    state = state_factory(generated_sql="UPDATE users SET active = 0")

    result = await module.sql_validator(state)

    assert result["error_message"] == ["验证错误: 只允许 SELECT"]
    assert result["retry_count"] == 1


@pytest.mark.known_defect
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="an empty retrieved allowlist currently disables table authorization",
)
def test_validate_sql_security_fails_closed_without_allowed_tables(
    validator_setup, state_factory
):
    module, _, _ = validator_setup

    result = module.validate_sql_security("SELECT id FROM secrets", state_factory())

    assert result["is_valid"] is False


@pytest.mark.known_defect
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="column authorization is not yet passed from Validator to AST policy",
)
def test_validate_sql_security_passes_allowed_columns(validator_setup, state_factory):
    module, calls, _ = validator_setup
    state = state_factory(
        relevant_tables=[
            {"table_name": "users", "similarity": 1.0, "description": "customers"}
        ],
        relevant_columns={"users": ["id"]},
    )

    module.validate_sql_security("SELECT id FROM users", state)

    assert calls[0].get("allowed_columns") == {"users": ["id"]}
