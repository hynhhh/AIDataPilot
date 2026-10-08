"""Tests for finite SQL validation and execution routing."""

import pytest

from graph.edges import route_sql_exec_result, route_sql_val_result


@pytest.mark.parametrize("route", [route_sql_val_result, route_sql_exec_result])
def test_sql_routes_return_success_without_error(route, state_factory):
    assert route(state_factory()) == "success"


@pytest.mark.parametrize("route", [route_sql_val_result, route_sql_exec_result])
def test_sql_routes_retry_before_limit_without_mutating_state(route, state_factory):
    state = state_factory(error_message=["syntax error"], retry_count=2)

    assert route(state) == "retry"
    assert state["retry_count"] == 2


@pytest.mark.parametrize("route", [route_sql_val_result, route_sql_exec_result])
def test_sql_routes_fail_at_retry_limit(route, state_factory):
    state = state_factory(error_message=["syntax error"], retry_count=3)

    assert route(state) == "failed"
    assert state["retry_count"] == 3
