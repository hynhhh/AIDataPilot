"""
@File: main.py
@Desc: fastapi服务入口
@Author: h
@Date: 8.13
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from api.websocket import router as ws_router
from api.chat_routes import router as chat_router
from core.database import init_sql_case_library


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    print("启动 Chat2Data API...")
    
    # 初始化 SQL 案例库表
    print("初始化 SQL 案例库...")
    res = await  init_sql_case_library()
    print(res)
    yield
    
    # 关闭时执行
    print("关闭 Chat2Data API...")


# 创建 FastAPI 应用
app = FastAPI(
    title="Chat2Data API",
    description="自然语言转数据查询与可视化",
    version="1.0.0",
    lifespan=lifespan
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该指定具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由（chat_router 已在自身定义了 /api/chat 前缀，无需再加）
app.include_router(chat_router, tags=["chat"])
app.include_router(router, prefix="/api", tags=["chat2data"])
app.include_router(ws_router, prefix="/ws", tags=["websocket"])

@app.get("/")
async def root():
    return {"message": "Chat2Data API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)