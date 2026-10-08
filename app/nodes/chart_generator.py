"""
@File: chart_generator.py
@Desc: node5,根据执行结果生成图表,json,返回前端调用
@Author: h
@Date: 8.13
"""
from langchain_core.messages import SystemMessage, HumanMessage
from core.llm import get_model
from utils.prompts import chart_generator_prompt
from utils.output_schema import ChartGeneratorResponse
from utils.output_schema import generate_structured_data
from typing import Dict, Any, List, Optional


def _build_echarts_config(
    chart_type: str,
    data: List[Dict[str, Any]],
    x_field: Optional[str],
    y_field: Optional[str],
    question: str
) -> Dict[str, Any]:
    """
    根据图表类型和数据构建 ECharts 配置
    
    Args:
        chart_type: 图表类型 (bar/line/pie/table/metric)
        data: 查询结果数据
        x_field: X 轴字段名
        y_field: Y 轴字段名
        question: 用户问题（用于生成标题）
    
    Returns:
        ECharts 配置对象
    """
    if not data:
        return None
    
    # 表格类型直接返回数据
    if chart_type == "table":
        return {
            "type": "table",
            "data": data
        }
    
    # 指标卡类型
    if chart_type == "metric":
        # 取第一行第一列数据作为指标
        first_row = data[0]
        metric_value = list(first_row.values())[0] if first_row else 0
        metric_label = list(first_row.keys())[0] if first_row else "结果"
        
        return {
            "type": "metric",
            "value": metric_value,
            "label": metric_label
        }
    
    # 提取 X 和 Y 轴数据
    x_data = [row.get(x_field) for row in data] if x_field else []
    y_data = [row.get(y_field) for row in data] if y_field else []
    
    # 饼图配置
    if chart_type == "pie":
        pie_data = [
            {"name": str(row.get(x_field, "")), "value": row.get(y_field, 0)}
            for row in data
        ]
        
        return {
            "type": "pie",
            "title": {"text": question, "left": "center"},
            "tooltip": {"trigger": "item"},
            "legend": {"orient": "vertical", "left": "left"},
            "series": [
                {
                    "name": y_field or "数值",
                    "type": "pie",
                    "radius": "50%",
                    "data": pie_data,
                    "emphasis": {
                        "itemStyle": {
                            "shadowBlur": 10,
                            "shadowOffsetX": 0,
                            "shadowColor": "rgba(0, 0, 0, 0.5)"
                        }
                    }
                }
            ]
        }
    
    # 柱状图/折线图配置
    base_config = {
        "type": chart_type,
        "title": {"text": question},
        "tooltip": {"trigger": "axis"},
        "xAxis": {
            "type": "category",
            "data": x_data,
            "axisLabel": {"rotate": 30}
        },
        "yAxis": {"type": "value"},
        "series": [
            {
                "name": y_field or "数值",
                "type": chart_type,
                "data": y_data,
                "smooth": True if chart_type == "line" else False
            }
        ]
    }
    
    return base_config


def _generate_suggestions(question: str, has_data: bool) -> List[str]:
    """
    生成推荐的后续问题
    
    Args:
        question: 当前问题
        has_data: 是否有数据返回
    
    Returns:
        推荐问题列表
    """
    if not has_data:
        return [
            "有哪些可用的数据表？",
            "能否换一个问题试试？"
        ]
    
    # 根据问题类型生成相关推荐
    suggestions = []
    
    if "销售" in question or "revenue" in question.lower():
        suggestions = [
            "显示最近一个月的销售趋势",
            "哪个地区的销售额最高？",
            "对比不同产品类别的销售情况"
        ]
    elif "用户" in question or "user" in question.lower():
        suggestions = [
            "用户增长趋势如何？",
            "活跃用户数量是多少？",
            "用户地区分布情况"
        ]
    else:
        suggestions = [
            "能否看看详细数据？",
            "换个时间范围试试",
            "对比一下不同维度"
        ]
    
    return suggestions[:3]  # 最多返回 3 个


def chart_generator(state):
    """
    图表生成节点：根据执行结果生成图表配置和完整的前端响应
    
    Args:
        state: 当前状态，包含问题、SQL、执行结果等
    
    Returns:
        更新后的状态，包含 chart_json（完整的 AgentResponse 格式）
    """
    question = state.get("question", "")
    execution_result = state.get("execution_result")
    generated_sql = state.get("generated_sql", "")
    error_message = state.get("error_message", [])
    retry_count = state.get("retry_count", 0)
    
    # 判断是否有有效数据
    has_data = execution_result and isinstance(execution_result, list) and len(execution_result) > 0
    has_error = bool(error_message)
    has_none_result = execution_result is None

    # none_query: 标记为不可回答
    is_unanswerable = has_none_result
    
    # 构建自然语言回答（初始默认值）
    answer = ""
    chart_config = None

    if has_error:
        answer = f"抱歉，查询过程中遇到了问题：{error_message[-1] if error_message else '未知错误'}。"
        if retry_count >= 3:
            answer += " 已达到最大重试次数，请尝试换一个问题。"
    elif has_none_result:
        # none_query 路径：非数据问题，跳过全部取数链路
        answer = "这是一个非数据问题，暂不支持回答。您可以尝试以下问题："
    elif not has_data:
        answer = "查询成功，当前没有返回数据。您可以尝试：\n- 换一个时间范围\n- 调整查询条件"
        # 空数据也展示指标卡，展示为 0
        chart_config = {
            "type": "metric",
            "value": 0,
            "label": question or "数据"
        }
    else:
        # 简单总结数据
        row_count = len(execution_result)
        answer = f"为您找到了 {row_count} 条数据。"
        # 有数据时才调用 LLM 生成图表
        messages = [
            SystemMessage(content=chart_generator_prompt),
            HumanMessage(content=f"问题：{question}\n\n数据示例：{execution_result[:3]}")
        ]
        
        llm = get_model()
        chart_response: ChartGeneratorResponse = generate_structured_data(
            llm, messages, ChartGeneratorResponse
        )
        
        chart_config = _build_echarts_config(
            chart_type=chart_response.chart_type,
            data=execution_result,
            x_field=chart_response.config.x_axis,
            y_field=chart_response.config.y_axis,
            question=question
        )
        
        # 优化回答，加入图表推荐理由
        if chart_config:
            answer = f"为您找到了 {row_count} 条数据。{chart_response.reason}"
        # 调用 LLM 决定图表类型
        messages = [
            SystemMessage(content=chart_generator_prompt),
            HumanMessage(content=f"问题：{question}\n\n数据示例：{execution_result[:3]}")
        ]
        
        llm = get_model()
        chart_response: ChartGeneratorResponse = generate_structured_data(
            llm, messages, ChartGeneratorResponse
        )
        
        # 构建 ECharts 配置
        chart_config = _build_echarts_config(
            chart_type=chart_response.chart_type,
            data=execution_result,
            x_field=chart_response.config.x_axis,
            y_field=chart_response.config.y_axis,
            question=question
        )
        
        # 优化回答，加入图表推荐理由
        if chart_config:
            answer = f"为您找到了 {row_count} 条数据。{chart_response.reason}"
    
    # 生成推荐问题
    suggestions = _generate_suggestions(question, has_data)
    
    # 构建完整的前端响应（AgentResponse 格式）
    agent_response = {
        "answer": answer,
        "sql": generated_sql if generated_sql else None,
        "table": execution_result if has_data else None,
        "chart": chart_config,
        "suggestions": suggestions,
        "recommendations": state.get("recommendations", []),
        "unanswerable": is_unanswerable,
        "metadata": {
            "retry_count": retry_count,
            "has_error": has_error,
            "error_details": error_message[-1] if error_message else None,
            "row_count": len(execution_result) if has_data else 0
        }
    }
    
    # 更新状态
    return {
        "chart_json": agent_response
    }