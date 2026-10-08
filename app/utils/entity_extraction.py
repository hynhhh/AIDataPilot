"""
@File: entity_extraction.py
@Desc: 在线实体抽取与纠错，将用户口语化表达映射到数据库真实取值。

流程:
  1. LLM 从用户问题中提取实体词列表
  2. 对每个实体词执行向量相似度搜索
  3. 返回修正映射供 SQL 生成使用
@Author: h
@Date: 2024
"""
import logging
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate

from utils.distinct_values import ColumnValueIndex, build_context_for_sql_generation

logger = logging.getLogger(__name__)

# 实体词抽取 LLM prompt
ENTITY_EXTRACTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是一个实体抽取助手。从用户的问题中提取出可能需要与数据库取值进行匹配的"实体词"。

规则：
- 只提取名词性实体词（如会员等级名称、城市名、品牌名等）
- 只提取可能与数据库分类字段取值对应的实体词
- 不要提取数字、日期、SQL 关键字、标点符号
- 不要提取已经明确匹配的值
- 输出格式为 JSON 数组，如 ["黄金", "北京"]
- 如果没有需要纠错的实体词，返回空数组 []"""),
    ("user", "{question}"),
])


class EntityCorrector:
    """在线实体抽取与纠错器

    通过 LLM 提取用户问题中的实体词，并使用 ColumnValueIndex 进行
    相似度搜索，将口语化表达映射到数据库真实取值。
    """

    def __init__(
        self,
        llm: Any,
        index: Optional[ColumnValueIndex] = None,
        threshold: float = 0.15,
        max_corrections: int = 10,
    ):
        self.llm = llm
        self.index = index or ColumnValueIndex(similarity_threshold=threshold)
        self.threshold = threshold
        self.max_corrections = max_corrections

    def extract_entities(self, question: str) -> List[str]:
        """使用 LLM 从问题中提取实体词列表。

        Args:
            question: 用户原始问题文本

        Returns:
            实体词列表，如 ["黄金", "北京", "华为"]
        """
        try:
            prompt = ENTITY_EXTRACTION_PROMPT.invoke({"question": question})
            response = self.llm.invoke(prompt)
            content = response.content.strip()
            if not content:
                return []

            # 尝试解析 JSON 数组
            if content.startswith("["):
                import json
                try:
                    entities = json.loads(content)
                    if isinstance(entities, list):
                        return entities
                except (json.JSONDecodeError, ValueError):
                    pass

            # 如果 JSON 解析失败，尝试逐行提取
            raw = content.replace("[", "").replace("]", "").replace('"', "").replace("'", "")
            entities = [e.strip() for e in raw.split(",") if e.strip()]
            return entities
        except Exception as e:
            logger.warning(f"实体抽取失败: {e}")
            return []

    def correct_entities(
        self,
        question: str,
        llm: Any,
    ) -> List[Dict[str, Any]]:
        """抽取实体并执行纠错映射，返回 (entity, table, column, correct_value) 列表。

        Args:
            question: 用户原始问题文本
            llm: 可选的 LangChain LLM 实例（当 LLM 需要从外部传入时使用）

        Returns:
            [
                {"entity_word": "黄金", "table_name": "dim_user",
                 "column_name": "vip_level", "correct_value": "黄金会员", "score": 0.85},
                ...
            ]
        """
        # Step 1: 抽取实体词
        entities = self.extract_entities(question)
        if not entities:
            return []

        # Step 2: 向量相似度搜索
        corrections = self.index.search_corrections(entities)

        # Step 3: 按分数排序并截取
        corrections.sort(key=lambda x: x["score"], reverse=True)
        return corrections[:self.max_corrections]

    def get_correction_context(self, question: str, llm: Any) -> str:
        """获取纠错上下文文本块，可直接注入到 SQL 生成 prompt 中。

        Args:
            question: 用户原始问题文本
            llm: LangChain LLM 实例

        Returns:
            格式化的 Markdown 文本块，如:
            "## 数据库字段取值纠正（请务必使用纠正后的取值生成 SQL）\n\n"
            "- dim_user.vip_level: 用户提到「黄金」 → 数据库真实取值: `黄金会员`\n"
        """
        corrections = self.correct_entities(question, llm)
        return build_context_for_sql_generation(corrections)

