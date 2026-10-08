"""
@File: sql_saver.py
@Desc: node6,存优质sql，实现个性化学习，历史经验沉淀，持续提升准确率
@Author: h&m
@Date: 8.17
"""
import json
import logging
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List

from core.database import execute_sql_query
from graph.state import Chat2DataState

logger = logging.getLogger(__name__)


class FeedbackScoreCalculator:
    """反馈评分计算器"""
    
    # 评分标准
    SCORE_WEIGHTS = {
        "execution_success": 40,      # 执行成功
        "has_result": 20,              # 结果非空
        "no_retry": 20,                # 未重试
        "no_follow_up": 10,            # 用户未追问（需要前端提供）
        "user_positive": 10,           # 用户正向反馈（需要前端提供）
    }
    
    # 分数等级阈值
    SCORE_THRESHOLDS = {
        "excellent": 80,    # 优秀（一定保存）
        "good": 60,         # 良好（建议保存）
        "medium": 40,       # 中等（选择性保存）
        "poor": 0,          # 较差（不保存）
    }
    
    @classmethod
    def calculate_score(
        cls,
        state: Chat2DataState,
        user_feedback: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        计算反馈评分
        
        Args:
            state: Chat2DataState 状态字典
            user_feedback: 用户反馈信息（可选），包含：
                - followed_up: bool, 是否追问
                - positive: bool, 是否正向反馈
                - rating: int, 用户评分 (1-5)
        
        Returns:
            int: 0-100 的评分
        """
        score = 0
        
        # 1. 执行成功（40分）
        execution_result = state.get("execution_result")
        error_message = state.get("error_message", [])
        has_error = len(error_message) > 0 if isinstance(error_message, list) else bool(error_message)
        
        if execution_result is not None and not has_error:
            score += cls.SCORE_WEIGHTS["execution_success"]
            logger.debug("✓ 执行成功: +40分")
        else:
            logger.debug("✗ 执行失败: +0分")
        
        # 2. 结果非空（20分）
        if execution_result:
            if isinstance(execution_result, list) and len(execution_result) > 0:
                score += cls.SCORE_WEIGHTS["has_result"]
                logger.debug("✓ 结果非空: +20分")
            elif execution_result:  # 非列表但有值
                score += cls.SCORE_WEIGHTS["has_result"]
                logger.debug("✓ 结果非空: +20分")
        else:
            logger.debug("✗ 结果为空: +0分")
        
        # 3. 未重试（20分）
        retry_count = state.get("retry_count", 0)
        if retry_count == 0:
            score += cls.SCORE_WEIGHTS["no_retry"]
            logger.debug("✓ 未重试: +20分")
        else:
            # 重试次数越多，扣分越多
            penalty = min(retry_count * 5, cls.SCORE_WEIGHTS["no_retry"])
            score += cls.SCORE_WEIGHTS["no_retry"] - penalty
            logger.debug(f"△ 重试{retry_count}次: +{cls.SCORE_WEIGHTS['no_retry'] - penalty}分")
        
        # 4. 用户未追问（10分）- 来自前端反馈
        if user_feedback:
            if not user_feedback.get("followed_up", True):  # 默认假设追问了
                score += cls.SCORE_WEIGHTS["no_follow_up"]
                logger.debug("✓ 用户未追问: +10分")
            else:
                logger.debug("✗ 用户追问: +0分")
            
            # 5. 用户正向反馈（10分）
            if user_feedback.get("positive", False):
                score += cls.SCORE_WEIGHTS["user_positive"]
                logger.debug("✓ 用户正向反馈: +10分")
            
            # 可选：用户评分加成
            rating = user_feedback.get("rating", 0)
            if rating >= 4:
                bonus = 5
                score += bonus
                logger.debug(f"✓ 用户评分{rating}星: +{bonus}分")
        
        logger.info(f"总分: {score}/100")
        return min(score, 100)  # 最高100分
    
    @classmethod
    def get_score_level(cls, score: int) -> str:
        """获取分数等级"""
        if score >= cls.SCORE_THRESHOLDS["excellent"]:
            return "excellent"
        elif score >= cls.SCORE_THRESHOLDS["good"]:
            return "good"
        elif score >= cls.SCORE_THRESHOLDS["medium"]:
            return "medium"
        else:
            return "poor"
    
    @classmethod
    def should_save(cls, score: int, min_score: int = 60) -> bool:
        """判断是否应该保存（默认良好以上）"""
        return score >= min_score


async def generate_case_id(question: str, sql: str) -> int:
    """
    生成唯一的 case_id
    
    使用问题和SQL的哈希值生成唯一ID
    
    Args:
        question: 用户问题
        sql: SQL语句
        
    Returns:
        int: case_id
    """
    # 使用 MD5 哈希生成唯一标识
    content = f"{question}||{sql}"
    hash_object = hashlib.md5(content.encode())
    # 取前16位作为 BIGINT
    return int(hash_object.hexdigest()[:16], 16)


async def save_sql_case(
    state: Chat2DataState,
    feedback_score: int,
    user_feedback: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    保存 SQL 案例到案例库
    
    Args:
        state: Chat2DataState 状态字典
        feedback_score: 反馈评分
        user_feedback: 用户反馈（可选）
    
    Returns:
        Dict: 保存结果
    """
    try:
        question = state.get("question", "")
        sql_text = state.get("generated_sql", "")
        relevant_tables = state.get("relevant_tables", [])
        
        # 提取使用的表名
        tables_used = [t.get("table_name") for t in relevant_tables if t.get("table_name")]
        tables_used_str = json.dumps(tables_used)
        
        logger.info(f"[sql_saver] 开始保存案例: question={question[:50]}..., sql_len={len(sql_text)}")
        
        # 基于 SQL 文本检查是否已存在
        check_query = "SELECT feedback_score, success_count FROM sql_case_library WHERE sql_text = ?"
        logger.debug(f"[sql_saver] 检查是否已存在: sql_text={sql_text[:80]}...")
        existing = await execute_sql_query(check_query, [sql_text])
        
        if existing.get("success") and existing.get("data"):
            # 已存在，更新记录
            old_record = existing["data"][0]
            old_score = old_record.get("feedback_score", 0)
            success_count = old_record.get("success_count", 0)
            
            # 更新评分（取最大值）
            new_score = max(old_score, feedback_score)
            
            update_query = """
                UPDATE sql_case_library 
                SET feedback_score = ?,
                    success_count = ?,
                    tables_used = ?,
                    updated_at = ?,
                    last_used_at = ?
                WHERE sql_text = ?
            """
            
            now = datetime.now().isoformat()
            result = await execute_sql_query(
                update_query,
                [new_score, success_count + 1, tables_used_str, now, now, sql_text]
            )
            
            if result.get("success"):
                logger.info(
                    f"✅ 更新案例: 评分 {old_score} → {new_score}, "
                    f"成功次数 {success_count} → {success_count + 1}"
                )
                return {
                    "success": True,
                    "action": "updated",
                    "old_score": old_score,
                    "new_score": new_score
                }
        else:
            # 不存在，插入新记录
            insert_query = """
                INSERT INTO sql_case_library 
                (question, sql_text, tables_used, feedback_score, success_count, fail_count, created_at, updated_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            now = datetime.now().isoformat()
            result = await execute_sql_query(
                insert_query,
                [
                    question,
                    sql_text,
                    tables_used_str,
                    feedback_score,
                    1,  # success_count
                    0,  # fail_count
                    now,  # created_at
                    now,  # updated_at
                    now   # last_used_at
                ]
            )
            
            if result.get("success"):
                logger.info(f"✅ 新增案例: 评分 {feedback_score}")
                return {
                    "success": True,
                    "action": "inserted",
                    "score": feedback_score
                }
        
        logger.warning(f"❌ 保存失败: {result.get('message', '未知错误')}")
        return {
            "success": False,
            "error": result.get("message", "未知错误")
        }
        
    except Exception as e:
        logger.error(f"保存 SQL 案例失败: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


async def update_failure_case(state: Chat2DataState) -> Dict[str, Any]:
    """
    更新失败案例的统计
    
    Args:
        state: Chat2DataState 状态字典
        
    Returns:
        Dict: 更新结果
    """
    try:
        question = state.get("question", "")
        sql_text = state.get("generated_sql", "")
        
        if not sql_text:
            logger.warning("[sql_saver] SQL 文本为空，跳过更新失败统计")
            return {"success": False, "error": "SQL 文本为空"}
        
        logger.info(f"[sql_saver] 更新失败统计：question={question[:50]}..., sql_len={len(sql_text)}")
        
        # 基于 SQL 文本检查是否存在
        check_query = "SELECT fail_count FROM sql_case_library WHERE sql_text = ?"
        existing = await execute_sql_query(check_query, [sql_text])
        
        if existing.get("success") and existing.get("data"):
            # 存在，更新失败次数
            fail_count = existing["data"][0].get("fail_count", 0)
            
            update_query = """
                UPDATE sql_case_library 
                SET fail_count = ?,
                    updated_at = ?
                WHERE sql_text = ?
            """
            now = datetime.now().isoformat()
            await execute_sql_query(update_query, [fail_count + 1, now, sql_text])
            
            logger.info(f"✅ 更新失败案例：失败次数 {fail_count} → {fail_count + 1}")
        
        return {"success": True}
        
    except Exception as e:
        logger.error(f"更新失败案例统计失败: {str(e)}")
        return {"success": False, "error": str(e)}


async def sql_saver(
    state: Chat2DataState,
    user_feedback: Optional[Dict[str, Any]] = None,
    min_save_score: int = 60
) -> Chat2DataState:
    """
    SQL 保存节点函数
    
    根据执行结果和用户反馈，评估并保存优质 SQL 到案例库
    
    评分规则：
    - 执行成功: 40分
    - 结果非空: 20分
    - 未重试: 20分
    - 用户未追问: 10分
    - 用户正向反馈: 10分
    
    默认保存 60分以上（良好及以上）的 SQL
    
    Args:
        state: Chat2DataState 状态字典
        user_feedback: 用户反馈信息（可选）
            - followed_up: 是否追问
            - positive: 是否正向反馈
            - rating: 用户评分 (1-5)
        min_save_score: 最低保存分数（默认60）
        
    Returns:
        Chat2DataState: 更新后的状态
    """
    logger.info("=" * 60)
    logger.info("开始评估 SQL 质量...")
    
    # 1. 计算反馈评分
    feedback_score = FeedbackScoreCalculator.calculate_score(state, user_feedback)
    score_level = FeedbackScoreCalculator.get_score_level(feedback_score)
    
    logger.info(f"评分: {feedback_score}/100 (等级: {score_level})")
    
    # 2. 判断是否保存
    should_save = FeedbackScoreCalculator.should_save(feedback_score, min_save_score)
    
    save_result = None
    if should_save:
        logger.info(f"✅ 评分达到保存标准 (>= {min_save_score})，保存到案例库...")
        save_result = await save_sql_case(state, feedback_score, user_feedback)
    else:
        logger.info(f"⏭️ 评分未达到保存标准 (< {min_save_score})，跳过保存")
        
        # 如果失败，更新失败统计
        error_message = state.get("error_message", [])
        has_error = len(error_message) > 0 if isinstance(error_message, list) else bool(error_message)
        if has_error:
            await update_failure_case(state)
    
    logger.info("=" * 60)
    
    # 3. 返回更新后的状态（添加保存元数据）
    return {
        **state,
        "sql_saved": should_save,
        "feedback_score": feedback_score,
        "score_level": score_level,
        "save_result": save_result
    }


async def provide_user_feedback(
    question: str,
    sql: str,
    followed_up: bool = False,
    positive: bool = True,
    rating: int = 5
) -> Dict[str, Any]:
    """
    由前端调用，提供用户反馈并更新案例库
    
    Args:
        question: 用户问题
        sql: 执行的 SQL
        followed_up: 用户是否追问
        positive: 是否正向反馈
        rating: 用户评分 (1-5)
        
    Returns:
        Dict: 更新结果
    """
    try:
        if not sql:
            logger.warning("[sql_saver] SQL 文本为空，跳过用户反馈")
            return {"success": False, "error": "SQL 文本为空"}
        
        logger.info(f"[sql_saver] 处理用户反馈：question={question[:50]}..., sql_len={len(sql)}")
        
        # 根据反馈调整评分
        user_feedback = {
            "followed_up": followed_up,
            "positive": positive,
            "rating": rating
        }
        
        # 计算额外分数
        bonus = 0
        if not followed_up:
            bonus += 10
        if positive:
            bonus += 10
        if rating >= 4:
            bonus += 5
        
        # 更新评分和用户反馈统计
        update_query = """
            UPDATE sql_case_library 
            SET feedback_score = feedback_score + ?,
                user_feedback_positive = user_feedback_positive + ?,
                user_feedback_negative = user_feedback_negative + ?,
                updated_at = ?
            WHERE sql_text = ?
        """
        
        now = datetime.now().isoformat()
        positive_increment = 1 if positive else 0
        negative_increment = 0 if positive else 1
        
        result = await execute_sql_query(
            update_query, 
            [bonus, positive_increment, negative_increment, now, sql]
        )
        
        logger.info(f"✅ 更新反馈：bonus={bonus}, rows={result.get('rows_affected', 0)}")
        
        return {
            "success": result.get("success", False),
            "bonus_score": bonus,
            "feedback": user_feedback
        }
        
    except Exception as e:
        logger.error(f"提供用户反馈失败: {str(e)}")
        return {"success": False, "error": str(e)}


__all__ = [
    "sql_saver",
    "FeedbackScoreCalculator",
    "save_sql_case",
    "provide_user_feedback",
]
