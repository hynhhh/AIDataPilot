"""
@File: recommendation_generator.py
@Desc: 从 SQL 执行结果生成 LLM 驱动的后续推荐问题
@Author: h&m
@Date:8.26
"""
import logging
from typing import Dict, Any, List, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from utils.prompts import recommendation_prompt
from graph.state import Chat2DataState
from core.llm import get_model

logger = logging.getLogger(__name__)

# 内置默认推荐问题（当无 SQL 执行结果时返回）
DEFAULT_RECOMMENDATIONS = [
    "过去一个月的总销售额是多少？",
    "列出单笔订单实付金额超过5000元的所有订单记录。",
    "帮我筛选出年龄在25岁到35岁之间的女性用户数量。",
]


def _parse_recommendations(raw_content: str, max_count: int = 5) -> List[str]:
    """将 LLM 输出的文本解析为推荐问题列表。"""
    if not raw_content:
        return []
    lines = raw_content.strip().splitlines()
    cleaned: List[str] = []
    for line in lines:
        line = line.strip()
        # 跳过空行、标题、编号行
        if not line or line.startswith("#") or line.startswith("##"):
            continue
        line = line.lstrip("0123456789.、•-*· ")
        line = line.strip()
        # 去引号
        if (line.startswith('"') and line.endswith('"')) or \
           (line.startswith("'") and line.endswith("'")) or \
           (line.startswith("《") and line.endswith("》")):
            line = line[1:-1].strip()
        if len(line) < 2 or len(line) > 200:
            continue
        cleaned.append(line)
    return cleaned[:max_count]


def recommendation_generator(state: Chat2DataState) -> Dict[str, Any]:
    """
    从 SQL 执行结果生成后续推荐问题。

    当 SQL 成功执行且有数据返回时，调用 LLM 生成 3-5 个用户可能感兴趣的
    后续问题。如果无数据，返回空列表。

    Args:
        state: 当前状态，包含 question、generated_sql、execution_result 等。

    Returns:
        更新后的状态，包含 recommendations 字段。
    """
    question = state.get("question", "")
    execution_result = state.get("execution_result")
    generated_sql = state.get("generated_sql", "")

    logger.info(
        f"[recommendation] 开始: question={question[:60]}..., "
        f"execution_result type={type(execution_result).__name__}, "
        f"generated_sql_len={len(generated_sql) if generated_sql else 0}"
    )

    has_data = (
        execution_result
        and isinstance(execution_result, list)
        and len(execution_result) > 0
    )

    if not has_data:
        logger.info(
            f"[recommendation] 无执行结果，返回内置默认推荐问题"
        )
        return {"recommendations": list(DEFAULT_RECOMMENDATIONS)}

    # 调用 LLM 生成后续问题
    llm = get_model()
    messages = [
        SystemMessage(content=recommendation_prompt),
        HumanMessage(content=(
            f"当前用户问题：{question}\n"
            f"已执行的 SQL：\n{generated_sql}\n"
            f"查询结果（前 3 条）：\n{execution_result[:3]}"
        )),
    ]

    try:
        logger.info(
            f"[recommendation] 调用 LLM, prompt 长度={len(messages[1].content)}"
        )
        response = llm.invoke(messages)
        raw = getattr(response, "content", "") or ""
        logger.debug(
            f"[recommendation] LLM 原始输出(前200字): {raw[:200]}"
        )
    except Exception as e:
        logger.warning(
            f"[recommendation] LLM 调用异常: {type(e).__name__}: {e}"
        )
        return {"recommendations": []}

    recommendations = _parse_recommendations(raw, max_count=5)
    logger.info(f"[recommendation] 解析完成: {len(recommendations)} 个推荐问题")
    if recommendations:
        for i, r in enumerate(recommendations, 1):
            logger.debug(f"  [{i}] {r}")

    return {"recommendations": recommendations}
