"""
@File: database.py
@Desc: 数据库连接和SQL执行工具，用于LangGraph Agent
@Author: h
@Date: 8.13
"""
import logging
from typing import Annotated, Any, Dict, List, Optional
from contextlib import asynccontextmanager
import sqlite3
import aiosqlite
from langchain_core.tools import tool

from core.config import settings, DatabaseType
import re
logger = logging.getLogger(__name__)


class DatabaseConnectionManager:
    """数据库连接管理器，支持 SQLite, PostgreSQL, MongoDB"""
    
    def __init__(self):
        self._connection = None
        self._connection_type = settings.DATABASE_TYPE
    
    @asynccontextmanager
    async def get_connection(self):
        """获取数据库连接的异步上下文管理器"""
        try:
            if self._connection_type == DatabaseType.SQLITE:
                async with aiosqlite.connect(settings.SQLITE_DB_PATH) as conn:
                    conn.row_factory = aiosqlite.Row
                    yield conn
                    
            elif self._connection_type == DatabaseType.POSTGRES:
                import asyncpg
                
                if not all([settings.POSTGRES_USER, settings.POSTGRES_PASSWORD, 
                           settings.POSTGRES_HOST, settings.POSTGRES_PORT, settings.POSTGRES_DB]):
                    raise ValueError("Missing PostgreSQL configuration")
                
                conn = await asyncpg.connect(
                    user=settings.POSTGRES_USER,
                    password=settings.POSTGRES_PASSWORD.get_secret_value() if settings.POSTGRES_PASSWORD else None,
                    host=settings.POSTGRES_HOST,
                    port=settings.POSTGRES_PORT,
                    database=settings.POSTGRES_DB
                )
                try:
                    yield conn
                finally:
                    await conn.close()
                    
            elif self._connection_type == DatabaseType.MONGO:
                from motor.motor_asyncio import AsyncIOMotorClient
                
                if not all([settings.MONGO_HOST, settings.MONGO_PORT, settings.MONGO_DB]):
                    raise ValueError("Missing MongoDB configuration")
                
                # 构建连接字符串
                if settings.MONGO_USER and settings.MONGO_PASSWORD:
                    mongo_uri = (
                        f"mongodb://{settings.MONGO_USER}:"
                        f"{settings.MONGO_PASSWORD.get_secret_value()}@"
                        f"{settings.MONGO_HOST}:{settings.MONGO_PORT}"
                    )
                else:
                    mongo_uri = f"mongodb://{settings.MONGO_HOST}:{settings.MONGO_PORT}"
                
                client = AsyncIOMotorClient(mongo_uri)
                try:
                    yield client[settings.MONGO_DB]
                finally:
                    client.close()
            else:
                raise ValueError(f"Unsupported database type: {self._connection_type}")
                
        except Exception as e:
            logger.error(f"Database connection error: {str(e)}")
            raise


# 全局连接管理器实例
db_manager = DatabaseConnectionManager()

_SELECT_LEAD_KEYWORDS = ("SELECT", "WITH")

def _query_is_select(sql: str) -> bool:
    """判断 SQL 是否为会返回数据的查询语句（SELECT / WITH...SELECT）。
    兼容被 startswith("SELECT") 误判为 False 的情况：
    - 前导注释/空白：/* c */ SELECT ...、-- c\nSELECT ...
    - CTE：WITH t AS (...) SELECT ...
    """
    if not sql:
        return False
    no_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)      # 去掉块注释
    no_line = re.sub(r"--[^\n]*", " ", no_block)               # 去掉行注释
    stripped = no_line.strip()
    if not stripped:
        return False
    first = stripped.split(None, 1)[0].upper()
    if first not in _SELECT_LEAD_KEYWORDS:
        return False
    if first == "WITH":
        return re.search(r"\bSELECT\b", stripped, flags=re.I) is not None
    return True

async def execute_sql_query(
    query: Annotated[str, "SQL查询语句，支持SELECT、INSERT、UPDATE、DELETE等"],
    params: Annotated[Optional[List[Any]], "查询参数，用于参数化查询以防止SQL注入"] = None
) -> Dict[str, Any]:
    """
    执行SQL查询并返回结果。
    
    支持的数据库类型：SQLite, PostgreSQL
    注意：此工具仅支持关系型数据库（SQLite和PostgreSQL），不支持MongoDB
    
    参数:
        query: SQL查询语句
        params: 可选的查询参数列表，用于参数化查询
    
    返回:
        包含查询结果的字典，格式为:
        {
            "success": bool,
            "data": List[Dict] (对于SELECT查询) 或 None,
            "rows_affected": int (对于INSERT/UPDATE/DELETE),
            "message": str
        }
    
    示例:
        # SELECT查询
        await execute_sql_query("SELECT * FROM users WHERE age > ?", [18])
        
        # INSERT查询
        await execute_sql_query("INSERT INTO users (name, age) VALUES (?, ?)", ["Alice", 25])
    """
    try:
        if settings.DATABASE_TYPE == DatabaseType.MONGO:
            return {
                "success": False,
                "data": None,
                "rows_affected": 0,
                "message": "SQL查询不支持MongoDB，请使用execute_mongo_query工具"
            }
        
        async with db_manager.get_connection() as conn:
            if settings.DATABASE_TYPE == DatabaseType.SQLITE:
                cursor = await conn.execute(query, params or [])
                
                # 检查是否是SELECT查询
                if _query_is_select(query):
                    rows = await cursor.fetchall()
                    data = [dict(row) for row in rows]
                    await conn.commit()
                    return {
                        "success": True,
                        "data": data,
                        "rows_affected": len(data),
                        "message": f"查询成功，返回 {len(data)} 条记录"
                    }
                else:
                    await conn.commit()
                    return {
                        "success": True,
                        "data": None,
                        "rows_affected": cursor.rowcount,
                        "message": f"执行成功，影响 {cursor.rowcount} 行"
                    }
                    
            elif settings.DATABASE_TYPE == DatabaseType.POSTGRES:
                if _query_is_select(query):
                    rows = await conn.fetch(query, *(params or []))
                    data = [dict(row) for row in rows]
                    return {
                        "success": True,
                        "data": data,
                        "rows_affected": len(data),
                        "message": f"查询成功，返回 {len(data)} 条记录"
                    }
                else:
                    result = await conn.execute(query, *(params or []))
                    # PostgreSQL的execute返回类似 "INSERT 0 1" 的字符串
                    rows_affected = int(result.split()[-1]) if result else 0
                    return {
                        "success": True,
                        "data": None,
                        "rows_affected": rows_affected,
                        "message": f"执行成功，影响 {rows_affected} 行"
                    }
                    
    except Exception as e:
        logger.error(f"SQL执行错误: {str(e)}")
        return {
            "success": False,
            "data": None,
            "rows_affected": 0,
            "message": f"执行失败: {str(e)}"
        }


@tool
async def execute_mongo_query(
    collection: Annotated[str, "MongoDB集合名称"],
    operation: Annotated[str, "操作类型: find, insert_one, insert_many, update_one, update_many, delete_one, delete_many"],
    query: Annotated[Optional[Dict], "查询条件（用于find/update/delete操作）"] = None,
    document: Annotated[Optional[Dict | List[Dict]], "要插入或更新的文档"] = None,
    update: Annotated[Optional[Dict], "更新操作（用于update操作）"] = None,
    limit: Annotated[Optional[int], "返回结果数量限制（用于find操作）"] = None
) -> Dict[str, Any]:
    """
    执行MongoDB查询操作。
    
    仅在DATABASE_TYPE=mongo时可用。
    
    参数:
        collection: 集合名称
        operation: 操作类型
        query: 查询条件
        document: 文档数据
        update: 更新操作
        limit: 结果限制
    
    返回:
        包含操作结果的字典
    
    示例:
        # 查询
        await execute_mongo_query("users", "find", {"age": {"$gt": 18}}, limit=10)
        
        # 插入
        await execute_mongo_query("users", "insert_one", document={"name": "Alice", "age": 25})
        
        # 更新
        await execute_mongo_query("users", "update_one", {"name": "Alice"}, update={"$set": {"age": 26}})
    """
    try:
        if settings.DATABASE_TYPE != DatabaseType.MONGO:
            return {
                "success": False,
                "data": None,
                "message": f"当前数据库类型为 {settings.DATABASE_TYPE}，请使用execute_sql_query工具"
            }
        
        async with db_manager.get_connection() as db:
            coll = db[collection]
            
            if operation == "find":
                cursor = coll.find(query or {})
                if limit:
                    cursor = cursor.limit(limit)
                results = await cursor.to_list(length=limit)
                # 转换ObjectId为字符串
                for doc in results:
                    if '_id' in doc:
                        doc['_id'] = str(doc['_id'])
                return {
                    "success": True,
                    "data": results,
                    "message": f"查询成功，返回 {len(results)} 条记录"
                }
                
            elif operation == "insert_one":
                result = await coll.insert_one(document)
                return {
                    "success": True,
                    "data": {"inserted_id": str(result.inserted_id)},
                    "message": "插入成功"
                }
                
            elif operation == "insert_many":
                result = await coll.insert_many(document)
                return {
                    "success": True,
                    "data": {"inserted_ids": [str(id) for id in result.inserted_ids]},
                    "message": f"插入成功，共 {len(result.inserted_ids)} 条"
                }
                
            elif operation == "update_one":
                result = await coll.update_one(query or {}, update or {})
                return {
                    "success": True,
                    "data": {"matched": result.matched_count, "modified": result.modified_count},
                    "message": f"更新成功，匹配 {result.matched_count} 条，修改 {result.modified_count} 条"
                }
                
            elif operation == "update_many":
                result = await coll.update_many(query or {}, update or {})
                return {
                    "success": True,
                    "data": {"matched": result.matched_count, "modified": result.modified_count},
                    "message": f"更新成功，匹配 {result.matched_count} 条，修改 {result.modified_count} 条"
                }
                
            elif operation == "delete_one":
                result = await coll.delete_one(query or {})
                return {
                    "success": True,
                    "data": {"deleted": result.deleted_count},
                    "message": f"删除成功，共 {result.deleted_count} 条"
                }
                
            elif operation == "delete_many":
                result = await coll.delete_many(query or {})
                return {
                    "success": True,
                    "data": {"deleted": result.deleted_count},
                    "message": f"删除成功，共 {result.deleted_count} 条"
                }
            else:
                return {
                    "success": False,
                    "data": None,
                    "message": f"不支持的操作: {operation}"
                }
                
    except Exception as e:
        logger.error(f"MongoDB操作错误: {str(e)}")
        return {
            "success": False,
            "data": None,
            "message": f"执行失败: {str(e)}"
        }



async def get_database_schema(
    table_name: Annotated[Optional[str], "可选的表名，如果提供则只返回该表的schema"] = None
) -> Dict[str, Any]:
    """
    获取数据库架构信息。
    """
    try:
        if settings.DATABASE_TYPE == DatabaseType.SQLITE:
            async with db_manager.get_connection() as conn:
                if table_name:
                    # PRAGMA 返回的列：(cid, name, type, notnull, dflt_value, pk)
                    cursor = await conn.execute(f"PRAGMA table_info({table_name})")
                    columns = await cursor.fetchall()
                    
              
                    parsed_columns = []
                    for col in columns:
                        parsed_columns.append({
                            "cid": col[0],
                            "name": col[1],
                            "type": col[2],
                            "notnull": col[3],
                            "dflt_value": col[4],
                            "pk": col[5]
                        })
                        
                    return {
                        "success": True,
                        "data": {
                            "table": table_name,
                            "columns": parsed_columns
                        },
                        "message": f"获取表 {table_name} 的schema成功"
                    }
                else:
                    cursor = await conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                    tables = await cursor.fetchall()
                    
                    # 🚀 使用 t[0] 直接提取表名，绕过 dict() 转换崩溃
                    table_list = [t[0] for t in tables]
                    
                    return {
                        "success": True,
                        "data": {"tables": table_list},
                        "message": f"获取所有表列表成功，共 {len(tables)} 个表"
                    }
                    
        elif settings.DATABASE_TYPE == DatabaseType.POSTGRES:
            async with db_manager.get_connection() as conn:
                if table_name:
                    rows = await conn.fetch("""
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_name = $1
                        ORDER BY ordinal_position
                    """, table_name)
                    return {
                        "success": True,
                        "data": {
                            "table": table_name,
                            "columns": [dict(row) for row in rows]
                        },
                        "message": f"获取表 {table_name} 的schema成功"
                    }
                else:
                    rows = await conn.fetch("""
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public'
                    """)
                    return {
                        "success": True,
                        "data": {"tables": [row['table_name'] for row in rows]},
                        "message": f"获取所有表列表成功，共 {len(rows)} 个表"
                    }
                    
        elif settings.DATABASE_TYPE == DatabaseType.MONGO:
            async with db_manager.get_connection() as db:
                collections = await db.list_collection_names()
                if table_name:
                    if table_name in collections:
                        sample = await db[table_name].find_one()
                        return {
                            "success": True,
                            "data": {
                                "collection": table_name,
                                "sample_fields": list(sample.keys()) if sample else []
                            },
                            "message": f"获取集合 {table_name} 的字段示例成功"
                        }
                    else:
                        return {
                            "success": False,
                            "data": None,
                            "message": f"集合 {table_name} 不存在"
                        }
                else:
                    return {
                        "success": True,
                        "data": {"collections": collections},
                        "message": f"获取所有集合列表成功，共 {len(collections)} 个集合"
                    }
                    
    except Exception as e:
        logger.error(f"获取schema错误: {str(e)}", exc_info=True)
        return {
            "success": False,
            "data": None,
            "message": f"获取失败: {str(e)}"
        }

async def init_sql_case_library():
    """
    从 .env 加载本地数据库路径并连接，返回数据库中的表数量
    """
    try:
        # 从 .env 加载数据库路径（通过 settings）
        db_path = settings.SQLITE_DB_PATH
        logger.info(f"📂 从 .env 加载的数据库路径: {db_path}")

        # 连接数据库并获取所有表
        async with db_manager.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = await cursor.fetchall()
            table_names = [dict(t)['name'] for t in tables]
            table_count = len(table_names)

            logger.info(f"✅ 成功连接数据库: {db_path}")
            logger.info(f"📊 数据库中共有 {table_count} 张表")
            logger.info(f"📋 表列表: {', '.join(table_names)}")

            return {
                "success": True,
                "database_path": db_path,
                "table_count": table_count,
                "tables": table_names
            }

    except Exception as e:
        logger.error(f"初始化数据库连接失败: {str(e)}")
        return {"success": False, "error": str(e)}



# 导出所有工具
database_tools = [
    execute_sql_query,
    execute_mongo_query,
    get_database_schema,
]

__all__ = [
    "DatabaseConnectionManager",
    "db_manager",
    "execute_sql_query",
    "execute_mongo_query",
    "get_database_schema",
    "init_sql_case_library",
    "database_tools",
]
#TODO：tools加一个标志位，除非是空表或者权限是admin，否则只执行select