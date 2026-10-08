"""Unit tests for SQL generation context and response handling."""

from __future__ import annotations

import pytest


@pytest.fixture
def generator_module(module_loader):
    return module_loader(
        "nodes.sql_generator",
        {"core.llm": {"get_model": lambda: None}},
    )


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"sql": "SELECT id FROM users"}', "SELECT id FROM users"),
        ("```sql\nSELECT id FROM users\n```", "SELECT id FROM users"),
        ("```\nSELECT id FROM users\n```", "SELECT id FROM users"),
        ("SELECT id FROM users", "SELECT id FROM users"),
    ],
)
def test_extract_sql_from_response(generator_module, content, expected):
    assert generator_module.extract_sql_from_response(content) == expected


def test_build_sql_generation_context_contains_state_sections(generator_module, state_factory):
    state = state_factory(
        question="Show active users",
        intent="filter active users",
        relevant_tables=[
            {"table_name": "users", "similarity": 0.9, "description": "customer table"}
        ],
        relevant_columns={"users": ["id", "active"]},
        schema_info={"tables": {}, "formatted_ddl": "CREATE TABLE users (id INT)"},
        few_shot_examples=[
            {
                "question": "Count users",
                "sql": "SELECT COUNT(*) FROM users",
                "tables": ["users"],
                "similarity": 0.8,
            }
        ],
    )

    context = generator_module.build_sql_generation_context(state)

    assert "Show active users" in context
    assert "filter active users" in context
    assert "users" in context
    assert "active" in context
    assert "CREATE TABLE users" in context
    assert "SELECT COUNT(*) FROM users" in context


@pytest.mark.asyncio
async def test_sql_generator_writes_generated_sql(generator_module, state_factory, fake_model_factory, monkeypatch):
    fake_model = fake_model_factory(['{"sql": "SELECT id FROM users"}'])
    monkeypatch.setattr(generator_module, "get_model", lambda: fake_model)

    result = await generator_module.sql_generator(state_factory(question="List users"))

    assert result["generated_sql"] == "SELECT id FROM users"
    assert len(fake_model.calls) == 1
