"""Shared pytest fixtures and deliberately small test doubles."""

from __future__ import annotations

import importlib
import sys
from copy import deepcopy
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import pytest


@dataclass(frozen=True)
class FakeResponse:
    """Minimal response object matching the ``content`` contract used by nodes."""

    content: str


class FakeModel:
    """Deterministic synchronous model that records every invocation."""

    def __init__(self, responses: list[str]):
        self._responses = iter(responses)
        self.calls: list[list[Any]] = []

    def invoke(self, messages: list[Any]) -> FakeResponse:
        self.calls.append(messages)
        try:
            content = next(self._responses)
        except StopIteration as exc:
            raise AssertionError("FakeModel received more calls than configured") from exc
        return FakeResponse(content=content)


@pytest.fixture
def fake_model_factory():
    """Create independent fake models without sharing response state."""

    return FakeModel


@pytest.fixture
def state_factory():
    """Create a complete, fresh Chat2DataState-shaped dictionary."""

    base_state = {
        "question": "How many customers are active?",
        "intent": "count active customers",
        "relevant_tables": [],
        "relevant_columns": {},
        "schema_info": {"tables": {}, "formatted_ddl": ""},
        "few_shot_examples": [],
        "generated_sql": "",
        "execution_result": None,
        "error_message": [],
        "retry_count": 0,
        "sql_history": [],
        "chart_json": {},
    }

    def build(**overrides: Any) -> dict[str, Any]:
        state = deepcopy(base_state)
        state.update(overrides)
        return state

    return build


@pytest.fixture
def module_loader(monkeypatch):
    """Import one app module with explicit, test-local direct dependencies.

    Several prototype modules currently depend on missing application modules.
    Unit tests inject only the direct collaborators of the module under test;
    this fixture intentionally does not make the full application importable.
    """

    imported_modules: set[str] = set()

    def load(module_name: str, stubs: dict[str, dict[str, Any]]) -> ModuleType:
        for stub_name, attributes in stubs.items():
            stub = ModuleType(stub_name)
            for name, value in attributes.items():
                setattr(stub, name, value)
            monkeypatch.setitem(sys.modules, stub_name, stub)

        monkeypatch.delitem(sys.modules, module_name, raising=False)
        module = importlib.import_module(module_name)
        imported_modules.add(module_name)
        return module

    yield load

    for module_name in imported_modules:
        sys.modules.pop(module_name, None)
