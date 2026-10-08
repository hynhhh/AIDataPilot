"""
@File: distinct_values.py
@Desc: 离线抽取数据库中所有分类字段的唯一取值，构建 TF-IDF 向量索引（SQLite3 存储），
      用于在线实体纠错——将用户口语化表达映射到数据库真实取值。
@Author: h
@Date: 2024
"""
import json
import logging
import math
import sqlite3
import threading
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 所有分类取值向量的 SQLite 路径
VECTOR_DB_PATH = "D:/AIDataPilot/bank_vector_index.sqlite3"

# 字符级 bigram
_CHAR_NGRAM = 2
# 相似度阈值
DEFAULT_SIMILARITY_THRESHOLD = 0.15
# 最大基数量（超过此值的列视为数值/日期列）
MAX_CARDINALITY = 500
# 排除的列名
EXCLUDE_COLUMNS = {"id", "user_id", "order_id", "campaign_id", "stat_date",
                   "order_date", "created_at", "updated_at"}


def _char_ngrams(text: str, n: int = _CHAR_NGRAM) -> List[str]:
    """将字符串切分为字符级 n-gram（用于中文/英文统一向量化）"""
    text = str(text).strip().lower()
    return [text[i:i + n] for i in range(len(text) - n + 1)] if len(text) >= n else [text]


def _cosine_sim(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """余弦相似度（两向量均已单位归一化）"""
    common = set(vec_a) & set(vec_b)
    if not common:
        return 0.0
    dot = sum(vec_a[k] * vec_b[k] for k in common)
    return max(0.0, dot)


class ColumnValueIndex:
    """分类字段取值向量索引

    将数据库中所有低基数字段（如 vip_level、city、brand）的唯一取值及其 TF-IDF
    向量存储在 SQLite3 文件中，供在线模糊匹配使用。
    """

    def __init__(self, db_path: str = VECTOR_DB_PATH,
                 similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD):
        self.db_path = db_path
        self.threshold = similarity_threshold
        self._local_lock = threading.Lock()
        self._local_db: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._local_db is None:
            self._local_db = sqlite3.connect(self.db_path)
            self._local_db.row_factory = sqlite3.Row
        return self._local_db

    def close(self):
        if self._local_db:
            self._local_db.close()
            self._local_db = None

    def _ensure_tables(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS column_metadata (
                table_name     TEXT    NOT NULL,
                column_name    TEXT    NOT NULL,
                cardinality    INTEGER NOT NULL,
                example_value  TEXT,
                PRIMARY KEY (table_name, column_name)
            );
            CREATE TABLE IF NOT EXISTS value_vectors (
                table_name     TEXT    NOT NULL,
                column_name    TEXT    NOT NULL,
                value          TEXT    NOT NULL,
                feature_str    TEXT    NOT NULL,
                tfidf_vector   TEXT    NOT NULL,
                PRIMARY KEY (table_name, column_name, value)
            );
            CREATE TABLE IF NOT EXISTS table_descriptions (
                table_name     TEXT    PRIMARY KEY,
                description    TEXT,
                columns_json   TEXT,
                generated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()


    def extract_and_store(self, business_db_path: str = "C:\\Users\\yhuang\\AP\\tools\\build_vector_index.py") -> Dict[str, Any]:
        """扫描业务数据库，提取所有分类字段的唯一取值并写入向量索引。

        Args:
            business_db_path: 业务数据库文件路径（SQLite），用于扫描表和列。
                              默认使用当前项目中的电商示例数据库。
        """
        self._ensure_tables()
        # 索引文件的连接（用于写入 column_metadata 和 value_vectors）
        index_conn = self._get_conn()
        # 业务数据库的连接（用于读取表和列数据）
        business_conn = sqlite3.connect(business_db_path)
        business_conn.row_factory = sqlite3.Row

        try:
            table_rows = business_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            tables = [dict(r)["name"] for r in table_rows]
        except Exception as e:
            logger.error(f"获取业务数据库表列表失败: {e}")
            business_conn.close()
            return {"tables_scanned": 0, "categorical_columns": 0, "total_values": 0}

        total_values = 0
        categorical_columns = 0

        for table_name in tables:
            if table_name in {"sql_examples", "sql_case_library"}:
                continue

            try:
                col_info = business_conn.execute(
                    f"PRAGMA table_info('{table_name}')"
                ).fetchall()
                col_names = [dict(c)["name"] for c in col_info]

                for col_name in col_names:
                    if col_name.lower() in EXCLUDE_COLUMNS:
                        continue

                    try:
                        result = business_conn.execute(
                            f'SELECT COUNT(DISTINCT "{col_name}") AS cnt FROM "{table_name}" LIMIT 1'
                        ).fetchone()
                        if result is None:
                            continue
                        cnt = dict(result)["cnt"]
                        if cnt is None or cnt == 0 or cnt > MAX_CARDINALITY:
                            continue

                        rows = business_conn.execute(
                            f'SELECT DISTINCT "{col_name}" AS val FROM "{table_name}" '
                            f'WHERE "{col_name}" IS NOT NULL'
                        ).fetchall()
                        values = [dict(r)["val"] for r in rows]

                        example = values[0] if values else None
                        index_conn.execute(
                            "INSERT OR REPLACE INTO column_metadata "
                            "(table_name, column_name, cardinality, example_value) "
                            "VALUES (?, ?, ?, ?)",
                            (table_name, col_name, cnt, example)
                        )
                        self._write_value_vectors(index_conn, table_name, col_name, values)
                        total_values += len(values)
                        categorical_columns += 1
                    except Exception as e:
                        logger.warning(f"处理 {table_name}.{col_name} 失败: {e}")
                        continue
            except Exception as e:
                logger.warning(f"处理表 {table_name} 失败: {e}")
                continue

        index_conn.commit()
        business_conn.close()

        logger.info(
            f"[distinct_values] 抽取完成: 扫描 {len(tables)} 张表, "
            f"{categorical_columns} 个分类列, {total_values} 个唯一取值"
        )
        return {
            "tables_scanned": len(tables),
            "categorical_columns": categorical_columns,
            "total_values": total_values,
        }

    def _write_value_vectors(self, conn, table_name, col_name, values):
        """为一组值计算 TF-IDF 向量并批量写入。"""
        n_docs = len(values)
        if n_docs == 0:
            return

        doc_ngrams: List[List[str]] = []
        doc_freq: Counter = Counter()
        for v in values:
            ngrams = _char_ngrams(v)
            doc_ngrams.append(ngrams)
            unique_ngrams = set(ngrams)
            doc_freq.update(unique_ngrams)

        vocab = {term: idx for idx, term in enumerate(sorted(doc_freq))}
        idf = {}
        for term, freq in doc_freq.items():
            idf[term] = math.log(n_docs / freq) if freq > 0 else 0.0

        for v, ngrams in zip(values, doc_ngrams):
            tf_counter = Counter(ngrams)
            feature_dict: Dict[str, float] = {}
            for term, count in tf_counter.items():
                idx = vocab[term]
                weight = (count / len(ngrams)) * idf[term]
                if abs(weight) > 1e-9:
                    feature_dict[term] = round(weight, 6)

            norm = math.sqrt(sum(w * w for w in feature_dict.values())) if feature_dict else 1.0
            if norm > 0:
                feature_dict = {k: v / norm for k, v in feature_dict.items()}

            conn.execute(
                "INSERT OR REPLACE INTO value_vectors "
                "(table_name, column_name, value, feature_str, tfidf_vector) "
                "VALUES (?, ?, ?, ?, ?)",
                (table_name, col_name, v,
                 " ".join(f"{k}:{round(v, 6)}" for k, v in feature_dict.items()),
                 json.dumps(feature_dict))
            )

    def search_corrections(self, entity_words: List[str]) -> List[Dict[str, Any]]:
        """对每个实体词执行相似度搜索，返回修正映射。"""
        if not entity_words:
            return []

        self._ensure_tables()
        conn = self._get_conn()

        rows = conn.execute(
            "SELECT table_name, column_name, value, tfidf_vector "
            "FROM value_vectors"
        ).fetchall()

        # 构建列索引: (table, column) -> [(value, tfidf_dict), ...]
        col_index = defaultdict(list)
        for row in rows:
            key = (dict(row)["table_name"], dict(row)["column_name"])
            val = dict(row)["value"]
            vec = json.loads(dict(row)["tfidf_vector"])
            col_index[key].append((val, vec))

        # 为每个 entity 词搜索
        results = []
        for entity in entity_words:
            entity_lower = entity.strip().lower()

            # 过滤含数字的实体（数字应精确匹配，n-gram 相似度会误匹配日期/金额列）
            has_digit = any(c.isdigit() for c in entity)
            if has_digit:
                continue

            # 先检查 entity 本身是否已经是数据库中的真实取值
            is_exact_match = False
            for (tbl, col), candidates in col_index.items():
                for val, _ in candidates:
                    if str(val).strip().lower() == entity_lower:
                        is_exact_match = True
                        break
                if is_exact_match:
                    break

            if is_exact_match:
                continue  # 用户已使用正确取值，无需纠错

            # 构建 entity 的 TF-IDF 向量
            entity_ngrams = _char_ngrams(entity)
            tf_counter = Counter(entity_ngrams)
            total = len(entity_ngrams) if entity_ngrams else 1

            entity_vec = {}
            for term, count in tf_counter.items():
                tf_val = count / total
                # 查找该 n-gram 出现在哪些列中，累加 IDF 加权
                idf_sum = 0.0
                for (tbl, col), candidates in col_index.items():
                    for val, vec in candidates:
                        if term in vec:
                            idf_sum += vec[term]
                            break
                entity_vec[term] = tf_val * idf_sum if idf_sum > 0 else 0.0

            # 归一化 entity 向量
            norm = math.sqrt(sum(w * w for w in entity_vec.values()))
            if norm > 0:
                entity_vec = {k: v / norm for k, v in entity_vec.items()}
            if not entity_vec:
                continue

            # 与所有候选值做余弦相似度
            for (tbl, col), candidates in col_index.items():
                for val, candidate_vec in candidates:
                    sim = _cosine_sim(entity_vec, candidate_vec)
                    if sim >= self.threshold:
                        results.append({
                            "entity_word": entity,
                            "table_name": tbl,
                            "column_name": col,
                            "correct_value": val,
                            "score": round(sim, 4),
                        })

        # 去重：按 (entity_word, column_name) 保留最高分
        best = {}
        for r in results:
            key = (r["entity_word"], r["column_name"])
            if key not in best or r["score"] > best[key]["score"]:
                best[key] = r

        # 过滤掉 score 过低的匹配（防止无关实体词触发错误纠错）
        high_confidence = [r for r in best.values() if r["score"] >= 0.5]
        return high_confidence




def build_context_for_sql_generation(entity_corrections: List[Dict[str, Any]]) -> str:
    """将纠错结果格式化为 SQL 生成 prompt 中可阅读的文本块。

    Returns:
        类似:
        "## 数据库字段取值纠正（请务必使用纠正后的取值生成 SQL）\n\n"
        "- vip_level: 用户提到: [黄金] -> 数据库真实取值: 黄金会员\n"
    """
    if not entity_corrections:
        return ""

    lines = ["## 数据库字段取值纠正（请务必使用纠正后的取值生成 SQL）\n"]
    seen: set = set()
    for c in entity_corrections:
        col = c["column_name"]
        user_word = c["entity_word"]
        real_val = c["correct_value"]
        table = c["table_name"]
        key = (col, real_val)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {table}.{col}: 用户提到「{user_word}」 → 数据库真实取值: `{real_val}`")

    return "\n".join(lines)


# ==========================================
# 辅助函数
# ==========================================

def extract_columns_from_schema(schema: Dict[str, Any]) -> List[str]:
    """从表结构字典中提取列名列表

    Args:
        schema: 表结构字典，支持 SQLite/PostgreSQL 格式

    Returns:
        列名列表
    """
    columns = []

    # 处理 SQLite/PostgreSQL 的列信息
    if "columns" in schema:
        for col in schema["columns"]:
            if isinstance(col, dict):
                # SQLite: 'name' 字段，PostgreSQL: 'column_name' 字段
                col_name = col.get("name") or col.get("column_name")
                if col_name:
                    columns.append(col_name)

    # 处理 MongoDB 的字段示例
    if "sample_fields" in schema:
        columns.extend(schema["sample_fields"])

    return columns


# ==========================================
# 表描述生成与存储
# ==========================================

TABLE_DESCRIPTION_PROMPT = """你是一个电商数据仓库架构师。请根据以下表的列信息，
生成一段简洁的业务描述（50 字以内），说明该表的用途和典型查询场景。

表名：{table_name}
列信息：{columns}

返回严格的 JSON 格式：
{{
  "description": "表的业务描述"
}}

示例：
表名：dim_user
列信息：user_id, user_alias, gender, age, city, vip_level
描述：用户基础属性维度表，存储用户的性别、年龄、城市、注册时间、会员等级。适合按用户属性做分群统计和聚合分析。

表名：fact_order
列信息：order_id, user_id, amount, order_date, status
描述：订单事实表，存储每笔交易的订单金额、下单日期、活动关联和订单状态。适合计算 GMV、订单量等核心指标。
"""


class TableDescriptionGenerator:
    """表描述生成器

    使用 LLM 为数据库中的每个表生成业务描述，并存储到 SQLite 数据库中。
    描述可用于在线表检索时帮助 LLM 理解表的结构和业务背景。
    """

    def __init__(self, llm, db_path: str = VECTOR_DB_PATH):
        self.llm = llm
        self.db_path = db_path

    def generate_description(self, table_name: str, columns: List[str]) -> str:
        """生成单个表的业务描述

        Args:
            table_name: 表名
            columns: 列名列表

        Returns:
            表的业务描述字符串
        """
        columns_str = ", ".join(columns)
        prompt = TABLE_DESCRIPTION_PROMPT.format(
            table_name=table_name,
            columns=columns_str
        )

        try:
            from langchain_core.messages import HumanMessage
            response = self.llm.invoke([HumanMessage(content=prompt)])
            content = response.content.strip()

            # 尝试解析 JSON
            if content.startswith("{"):
                import json
                try:
                    data = json.loads(content)
                    return data.get("description", f"{table_name} 表")
                except json.JSONDecodeError:
                    pass

            # 如果 JSON 解析失败，尝试提取引号内的描述
            if "描述：" in content:
                desc = content.split("描述：")[-1].strip()
                # 清理可能的额外内容
                desc = desc.split("\\n")[0].strip()
                return desc

            return f"{table_name} 表"

        except Exception as e:
            logger.warning(f"生成表描述失败 ({table_name}): {e}")
            return f"{table_name} 表"

    def store_description(self, table_name: str, description: str, columns: List[str]):
        """存储表描述到数据库

        Args:
            table_name: 表名
            description: 表的业务描述
            columns: 列名列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        columns_json = json.dumps(columns, ensure_ascii=False)

        cursor.execute("""
            INSERT INTO table_descriptions (table_name, description, columns_json, generated_at, updated_at)
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(table_name) DO UPDATE SET
                description = excluded.description,
                columns_json = excluded.columns_json,
                updated_at = datetime('now')
        """, (table_name, description, columns_json))

        conn.commit()
        conn.close()

    def get_description(self, table_name: str) -> Optional[str]:
        """获取表的业务描述

        Args:
            table_name: 表名

        Returns:
            表的业务描述，如果不存在则返回 None
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT description FROM table_descriptions WHERE table_name = ?", (table_name,))
        row = cursor.fetchone()
        conn.close()

        return row[0] if row else None

    def generate_and_store_all(self, all_tables: List[str], schema_getter) -> Dict[str, str]:
        """为所有表生成描述并存储

        Args:
            all_tables: 表名列表
            schema_getter: 获取表结构的函数，返回 (columns_list)

        Returns:
            表名到描述的映射字典
        """
        results = {}

        for table in all_tables:
            try:
                schema = schema_getter(table)
                columns = extract_columns_from_schema(schema) if isinstance(schema, dict) else []

                description = self.generate_description(table, columns)
                self.store_description(table, description, columns)
                results[table] = description

                print(f"  ✅ {table}: {description[:30]}...")

            except Exception as e:
                logger.warning(f"生成表描述失败 ({table}): {e}")
                results[table] = f"{table} 表"

        return results

