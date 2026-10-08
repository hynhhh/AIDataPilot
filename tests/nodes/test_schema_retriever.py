"""Unit tests for schema and example retrieval helpers."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def retriever_module(module_loader):
    async def empty_database_schema(**kwargs):
        return {"success": True, "data": {"tables": []}}

    async def empty_execute_sql_query(query):
        return {"success": True, "data": []}

    return module_loader(
        "nodes.schema_retreiver",
        {
            "core.llm": {"get_model": lambda: None},
            "core.database": {
                "get_database_schema": empty_database_schema,
                "execute_sql_query": empty_execute_sql_query,
            },
        },
    )


def test_extract_columns_from_sqlite_schema(retriever_module):
    schema = {"columns": [{"name": "id"}, {"name": "active"}]}

    assert retriever_module.extract_columns_from_schema(schema) == ["id", "active"]


def test_extract_columns_from_postgres_schema(retriever_module):
    schema = {"columns": [{"column_name": "id"}, {"column_name": "created_at"}]}

    assert retriever_module.extract_columns_from_schema(schema) == ["id", "created_at"]


def test_extract_columns_from_mongo_schema(retriever_module):
    assert retriever_module.extract_columns_from_schema({"sample_fields": ["_id", "name"]}) == [
        "_id",
        "name",
    ]


def test_format_schema_info_supports_sqlite_and_postgres(retriever_module):
    formatted = retriever_module.format_schema_info(
        {
            "users": {"columns": [{"name": "id", "type": "INTEGER", "notnull": 1}]},
            "events": {
                "columns": [
                    {"column_name": "created_at", "data_type": "timestamp", "is_nullable": "NO"}
                ]
            },
        }
    )

    assert "CREATE TABLE users" in formatted
    assert "id INTEGER" in formatted
    assert "CREATE TABLE events" in formatted
    assert "created_at timestamp NOT NULL" in formatted


@pytest.mark.known_defect
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SQLite notnull metadata is currently rendered without NOT NULL",
)
def test_format_schema_info_preserves_sqlite_not_null(retriever_module):
    formatted = retriever_module.format_schema_info(
        {"users": {"columns": [{"name": "id", "type": "INTEGER", "notnull": 1}]}}
    )

    assert "id INTEGER NOT NULL" in formatted


@pytest.mark.asyncio
async def test_get_all_tables_and_table_schema(retriever_module, monkeypatch):
    async def fake_schema(**kwargs):
        if kwargs.get("table_name"):
            return {"success": True, "data": {"table": "users", "columns": []}}
        return {"success": True, "data": {"tables": ["users", "orders"]}}

    monkeypatch.setattr(retriever_module, "get_database_schema", fake_schema)

    assert await retriever_module.get_all_tables() == ["users", "orders"]
    assert await retriever_module.get_table_schema("users") == {
        "table": "users",
        "columns": [],
    }


@pytest.mark.asyncio
async def test_get_all_few_shot_examples_decodes_table_list(retriever_module, monkeypatch):
    async def fake_execute(query):
        return {
            "success": True,
            "data": [
                {"question": "Count users", "sql": "SELECT COUNT(*) FROM users", "tables": '["users"]'},
                {"question": "List orders", "sql": "SELECT * FROM orders", "tables": "orders"},
            ],
        }

    monkeypatch.setattr(retriever_module, "execute_sql_query", fake_execute)

    examples = await retriever_module.get_all_few_shot_examples()

    assert examples[0]["tables"] == ["users"]
    assert examples[1]["tables"] == ["orders"]


@pytest.mark.asyncio
async def test_retrieve_few_shot_examples_limits_to_ten(
    retriever_module, monkeypatch, fake_model_factory
):
    examples = [
        {"question": f"Question {i}", "sql": f"SELECT {i}", "tables": [], "similarity": 1.0}
        for i in range(12)
    ]
    fake_model = fake_model_factory([json.dumps({"few_shot_examples": examples})])
    monkeypatch.setattr(retriever_module, "get_all_few_shot_examples", lambda: _async_value(examples))
    monkeypatch.setattr(retriever_module, "get_model", lambda: fake_model)

    result = await retriever_module.retrieve_few_shot_examples("count users", "count")

    assert len(result) == 10


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_schema_retreiver_updates_state(retriever_module, state_factory, monkeypatch, fake_model_factory):
    fake_model = fake_model_factory(
        [
            '{"intent": "list users"}',
            '{"relevant_tables": [{"table_name": "users", "similarity": 1.0, "description": "customers"}]}',
            '{"relevant_columns": ["id"]}',
        ]
    )
    monkeypatch.setattr(retriever_module, "get_model", lambda: fake_model)
    monkeypatch.setattr(retriever_module, "get_all_tables", lambda: _async_value(["users"]))
    monkeypatch.setattr(
        retriever_module,
        "get_table_schema",
        lambda table_name: _async_value({"table": table_name, "columns": [{"name": "id"}]}),
    )
    monkeypatch.setattr(retriever_module, "retrieve_few_shot_examples", lambda *args: _async_value([]))

    result = await retriever_module.schema_retreiver(state_factory(question="List users"))

    assert result["intent"] == "list users"
    assert result["relevant_tables"][0]["table_name"] == "users"
    assert result["relevant_columns"] == {"users": ["id"]}
    assert "CREATE TABLE users" in result["schema_info"]["formatted_ddl"]


@pytest.mark.known_defect
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="table candidates are not interpolated into the table selection prompt",
)
@pytest.mark.asyncio
async def test_schema_retreiver_includes_table_candidates_in_prompt(
    retriever_module, state_factory, monkeypatch, fake_model_factory
):
    fake_model = fake_model_factory(
        [
            '{"intent": "list users"}',
            '{"relevant_tables": []}',
        ]
    )
    monkeypatch.setattr(retriever_module, "get_model", lambda: fake_model)
    monkeypatch.setattr(retriever_module, "get_all_tables", lambda: _async_value(["private_users"]))
    monkeypatch.setattr(retriever_module, "retrieve_few_shot_examples", lambda *args: _async_value([]))

    await retriever_module.schema_retreiver(state_factory(question="List private users"))

    table_prompt = "\n".join(str(message.content) for message in fake_model.calls[1])
    assert "private_users" in table_prompt


@pytest.mark.known_defect
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="few-shot candidates are not included in the selection prompt",
)
@pytest.mark.asyncio
async def test_retrieve_few_shot_examples_includes_candidates_in_prompt(
    retriever_module, monkeypatch, fake_model_factory
):
    examples = [{"question": "Count users", "sql": "SELECT COUNT(*) FROM users", "tables": []}]
    fake_model = fake_model_factory(['{"few_shot_examples": []}'])
    monkeypatch.setattr(retriever_module, "get_all_few_shot_examples", lambda: _async_value(examples))
    monkeypatch.setattr(retriever_module, "get_model", lambda: fake_model)

    await retriever_module.retrieve_few_shot_examples("count users", "count")

    prompt = "\n".join(str(message.content) for message in fake_model.calls[0])
    assert "SELECT COUNT(*) FROM users" in prompt
