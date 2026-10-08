"""
@File: workflow.py
@Desc: 组装图,add_node,add_edge
@Author: h
@Date: 8.13
"""
from langgraph.graph import END, START, StateGraph

from graph.edges import route_sql_exec_result, route_sql_val_result_refined
from graph.state import Chat2DataState
from nodes.chart_generator import chart_generator
from nodes.recommendation_generator import recommendation_generator
from nodes.schema_retreiver import schema_retreiver
from nodes.sql_executor import sql_executor
from nodes.sql_generator import sql_generator
from nodes.sql_validator import sql_validator
from nodes.sql_saver import sql_saver
from nodes.sql_syntax_patcher import sql_syntax_patcher
from nodes.sql_logic_debugger import sql_logic_debugger

agent = StateGraph(Chat2DataState)

# Add nodes
agent.add_node("schema_retreiever", schema_retreiver)
agent.add_node("sql_generator", sql_generator)
agent.add_node("sql_validator", sql_validator)
agent.add_node("sql_syntax_patcher", sql_syntax_patcher)  # 新增：跨层JOIN专精修补节点
agent.add_node("sql_logic_debugger", sql_logic_debugger)  # 新增：零行数据逻辑调试节点
agent.add_node("sql_executor", sql_executor)
agent.add_node("chart_generator", chart_generator)
agent.add_node("recommendation_generator", recommendation_generator)
agent.add_node("sql_saver", sql_saver)

agent.add_edge(START, "schema_retreiever")
agent.add_conditional_edges(
    "schema_retreiever",
    lambda state: "none_query" if state.get("intent") == "none_query" else "continue",
    {
        "none_query": "recommendation_generator",
        "continue": "sql_generator",
    }
)
agent.add_edge("sql_generator", "sql_validator")

# 使用精细化路由：根据错误类型分流
agent.add_conditional_edges(
    "sql_validator",
    route_sql_val_result_refined,
    {
        "retry": "sql_generator",              # 一般错误/业务规则错误/未授权表（已扩展）
        "patch_syntax": "sql_syntax_patcher",  # 跨层JOIN错误 -> 专精修补
        "failed": "chart_generator",           # 超过重试次数
        "success": "sql_executor",             # 验证通过
    }
)

# sql_syntax_patcher 修补后返回 sql_validator 重新验证
agent.add_edge("sql_syntax_patcher", "sql_validator")

# sql_executor 的精细化路由（支持零行数据检测）
agent.add_conditional_edges(
    "sql_executor",
    route_sql_exec_result,
    {
        "retry": "sql_generator",              # 执行错误，常规重试
        "zero_rows": "sql_logic_debugger",     # 执行成功但0行，逻辑调试
        "failed": "chart_generator",           # 超过重试次数
        "success": "recommendation_generator", # 执行成功且有数据
    }
)

# sql_logic_debugger 调试后返回 sql_generator 重新生成
agent.add_edge("sql_logic_debugger", "sql_generator")
agent.add_edge("recommendation_generator", "chart_generator")
agent.add_edge("chart_generator", "sql_saver")
agent.add_edge("sql_saver", END)
# Compile the agent
agent = agent.compile()
