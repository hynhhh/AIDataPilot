"""Graph topology tests using test-local node doubles."""

import pytest


@pytest.fixture
def workflow_module(module_loader):
    async def passthrough(state):
        return state

    return module_loader(
        "graph.workflow",
        {
            "nodes.schema_retreiver": {"schema_retreiver": passthrough},
            "nodes.sql_generator": {"sql_generator": passthrough},
            "nodes.sql_validator": {"sql_validator": passthrough},
            "nodes.sql_executor": {"sql_executor": passthrough},
            "nodes.chart_generator": {"chart_generator": passthrough},
        },
    )


def test_workflow_validates_before_execution(workflow_module):
    graph = workflow_module.agent.get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    assert ("sql_generator", "sql_validator") in edges
    assert ("sql_validator", "sql_executor") in edges
    assert ("sql_generator", "sql_executor") not in edges
    assert ("sql_executor", "sql_validator") not in edges
