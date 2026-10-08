"""Unit tests for SQL execution result handling."""

from __future__ import annotations

from enum import StrEnum
from types import SimpleNamespace

import pytest


class StubDatabaseType(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    MONGO = "mongo"


@pytest.fixture
def executor_module(module_loader):
    async def empty_sql_query(query):
        return {"success": True, "data": [], "message": "ok"}

    async def empty_mongo_query(*args, **kwargs):
        return {"success": False, "data": None, "message": "not configured"}

    return module_loader(
        "nodes.sql_executor",
        {
            "core.database": {
                "execute_sql_query": empty_sql_query,
                "execute_mongo_query": empty_mongo_query,
            },
            "core.config": {
                "settings": SimpleNamespace(DATABASE_TYPE=StubDatabaseType.SQLITE),
                "DatabaseType": StubDatabaseType,
            },
        },
    )


def test_format_execution_result_preview(executor_module):
    result = executor_module.format_execution_result(
        {"success": True, "data": [{"id": 1}, {"id": 2}], "message": "ok"}
    )

    assert "共返回 2 条记录" in result
    assert "id: 1" in result


def test_format_execution_result_handles_empty_result(executor_module):
    result = executor_module.format_execution_result(
        {"success": True, "data": [], "message": "ok"}
    )

    assert result == "查询成功，但没有返回数据"


def test_calculate_result_statistics(executor_module):
    stats = executor_module.calculate_result_statistics([{"id": 1, "name": "A"}])

    assert stats == {
        "total_rows": 1,
        "columns": ["id", "name"],
        "has_data": True,
        "column_count": 2,
    }


def test_calculate_result_statistics_handles_empty_data(executor_module):
    stats = executor_module.calculate_result_statistics([])

    assert stats["total_rows"] == 0
    assert stats["has_data"] is False


def test_analyze_execution_error_adds_specific_suggestion(executor_module):
    message = executor_module.analyze_execution_error(
        "no such column: users.email", "SELECT email FROM users"
    )

    assert "列名可能不存在" in message
    assert "SELECT email FROM users" in message


def test_should_retry_execution_respects_limit(executor_module, state_factory):
    assert executor_module.should_retry_execution(
        state_factory(error_message="syntax", retry_count=2)
    ) is True
    assert executor_module.should_retry_execution(
        state_factory(error_message="syntax", retry_count=3)
    ) is False


@pytest.mark.asyncio
async def test_execute_sql_safely_delegates_sql(executor_module, monkeypatch, state_factory):
    seen = []

    async def fake_execute(query):
        seen.append(query)
        return {"success": True, "data": [{"id": 1}], "message": "ok"}

    monkeypatch.setattr(executor_module, "execute_sql_query", fake_execute)

    result = await executor_module.execute_sql_safely("SELECT id FROM users", state_factory())

    assert seen == ["SELECT id FROM users"]
    assert result["success"] is True


@pytest.mark.asyncio
async def test_sql_executor_handles_success(executor_module, state_factory, monkeypatch):
    async def fake_execute(sql, state):
        return {"success": True, "data": [{"id": 1}], "message": "ok"}

    monkeypatch.setattr(executor_module, "execute_sql_safely", fake_execute)
    state = state_factory(generated_sql="SELECT id FROM users")

    result = await executor_module.sql_executor(state)

    assert result["execution_result"] == [{"id": 1}]
    assert result["error_message"] == []
    assert result["retry_count"] == 0


@pytest.mark.asyncio
async def test_sql_executor_handles_failure(executor_module, state_factory, monkeypatch):
    async def fake_execute(sql, state):
        return {"success": False, "data": None, "message": "syntax error"}

    monkeypatch.setattr(executor_module, "execute_sql_safely", fake_execute)
    state = state_factory(generated_sql="SELECT (")

    result = await executor_module.sql_executor(state)

    assert result["execution_result"] is None
    assert "执行错误" in result["error_message"][0]
    assert result["retry_count"] == 1


@pytest.mark.asyncio
async def test_sql_executor_retries_missing_sql(executor_module, state_factory):
    result = await executor_module.sql_executor(state_factory(generated_sql=""))

    assert result["execution_result"] is None
    assert result["error_message"] == "没有生成 SQL 语句"
    assert result["retry_count"] == 1
