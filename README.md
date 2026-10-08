# Agentic AI Data Query Platform

面向客户营销场景的自然语言取数原型。项目探索如何将业务问题转换为结构化查询，并通过语义元数据、SQL 校验和数据访问控制降低模型幻觉与越权风险，最终以表格、文字说明或图表返回结果。

## 查询流程

```text
自然语言问题
  → Schema、业务术语与示例检索
  → 查询意图和条件解析
  → SQL 生成与校验
  → 只读执行
  → 生成推荐问题
  → 结果解释与图表配置
```
以下可用mermaid查看
flowchart TD

    START --> schema_retreiever

    schema_retreiever -->|none_query| recommendation_generator
    schema_retreiever -->|continue| sql_generator

    sql_generator --> sql_validator

    sql_validator -->|retry| sql_generator
    sql_validator -->|success| sql_executor
    sql_validator -->|failed| chart_generator

    sql_executor -->|retry| sql_generator
    sql_executor -->|success| recommendation_generator
    sql_executor -->|failed| chart_generator

    recommendation_generator --> chart_generator

    chart_generator --> sql_saver

    sql_saver --> END
核心流程由 LangGraph 编排，各节点分别负责 Schema 检索、SQL 生成、校验、执行和结果展示。设计上，模型负责生成候选内容，权限、SQL 安全和执行限制由程序控制。

## 项目结构

```text
app/
├── api/       API 与 WebSocket 接口
├── core/      配置、模型和数据库适配
├── graph/     状态、路由与工作流编排
├── memory/    SQLite、PostgreSQL、MongoDB 状态存储
├── nodes/     查询流程节点
├── utils/     Prompt 与 SQL 辅助工具
├── connect/   测试流程连通性
└── main.py    服务入口
frontend/      前端
```
基础端点在main.py中定义，查询端点在api/中定义
routes.py最简测试系统功能
websocket.py模拟给前端推送节点
chat_routes.py前端对话相关接口
可用connect中的list_api.py查询可用端点
可在http://localhost:8000/docs测试端点（确保已运行main.py），这很好用，有具体报错信息

.env配置参考.env.local
如果模型是中转站或者网站被block了记得配base_url
类似
COMPATIBLE_MODEL=
COMPATIBLE_API_KEY=
COMPATIBLE_BASE_URL=
各模块的职责和数据流见 [架构说明](docs/architecture.md)。

## 技术栈

- Python 3.11
- FastAPI、Uvicorn
- LangGraph、LangChain
- OpenAI、Anthropic、Google、Groq、AWS Bedrock、Ollama 等模型服务
- Pydantic Settings、SQLGlot、SQLParse
- SQLite、PostgreSQL、MongoDB
- Ruff、pytest、pre-commit、GitHub Actions

## 开发环境

推荐使用 [uv](https://docs.astral.sh/uv/)：

```bash
make setup
source .venv/bin/activate
make pre-commit-install
```

Fish 用户使用对应的激活脚本：

```fish
source .venv/bin/activate.fish
```

也可以使用 Conda：

```bash
conda create --name agentic-data-query python=3.11 pip
conda activate agentic-data-query
make setup-conda
make pre-commit-install
```

运行代码检查和测试：

```bash
make check
pre-commit run --all-files
```

## 单元测试

单元测试使用 pytest，放在根目录 `tests/`，覆盖 SQL AST、查询节点和 Graph 路由等基础组件。测试默认使用 Fake Model 和 Fake Database，不访问真实模型、外网或生产数据库。

在项目虚拟环境中运行全部或定向测试：

```bash
source .venv/bin/activate
python -m pytest
python -m pytest tests/utils/test_ast_parser.py
```

Fish 用户先执行 `source .venv/bin/activate.fish`，或在任意 Shell 中直接使用：

```bash
.venv/bin/python -m pytest
.venv/bin/python -m pytest tests/utils/test_ast_parser.py
```

也可以不激活环境，直接执行 `.venv/bin/python -m pytest`。标记为严格 `xfail` 的用例记录当前原型中的已知缺陷；缺陷修复后产生 XPASS 并要求同步更新测试。GitHub Actions 会在独立的 `unit-tests` job 中自动运行完整单元测试。

环境配置和常用命令见 [开发指南](docs/development.md)。扩展查询流程前请阅读 [问数 Agent 开发指南](docs/agent-development.md)。

## 参与贡献

提交改动前，请阅读 [贡献指南](CONTRIBUTING.md)、[行为准则](CODE_OF_CONDUCT.md) 和 [安全策略](SECURITY.md)。

## License

本项目基于 [Apache License 2.0](LICENSE) 开源。
