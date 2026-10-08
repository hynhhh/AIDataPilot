1.对于数据表中字段具体取值不清楚，比如客户等级黄金和黄金等级客户的sql，vip等级一列
离线取值+在线向量检索
已解决，好像没有完美解决。比如双十一大促

2.怎么加猜你想问，比如上面的客户等级result只会返回客户id和等级，那我会不会想知道城市分布什么的，这对于问数是需要的吗？
半解决，加了一个node，确实生成了后续问题但是前端推送失败了
已解决
3.流式输出有一些中间过程输出重复
已解决
4.需不需要加一个获取当前时间的tool，比如问过去一个月的总销售额是多少
from datetime import datetime

current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
直接拼接到prompt中

已解决

5.sql exec失败重试的机制好像失败了
已解决
6.添加前端写api_key的接口
已解决，考虑增加监听，目前需要手动重启。
7.有很多图表类型，什么时候返回其他类型
目前似乎只会返回table，metric，柱状图
8.关于异常输入信息的处理，比如输入你好
已解决
9.sql_case_librarySQL执行错误: Python int too large to convert to SQLite INTEGER
已解决
10.已生成推荐问题没有在前端显示
已解决
11.加一个登录页面和用户role
这个必要吗？
12.时间问题。Schema_retreiever耗时长，sql_text添加索引,example_sql查询时间长
#TODO
13.一些问题会解析失败，不应该重新生成，还是模型根本没接收错误数据？
看不懂，好像重复解决了
14.metric表显示问题
已解决
15.考虑是复用sql generator node还是用一个新的repair node，另外现在的sql generator node没有带错误信息
已暂时解决，目前还是generator node，并更新了一下prompt
16.处理失败的都缺少兜底信息，为什么sql_executor查询为空会直接处理失败
效果
已解决
17.增加一个当前执行的sql语句看板，可折叠
已解决
18.data table的刷新问题
已解决
19.根据正式数据库情况测试连接情况，实现在前端settings界面更改并能传到.env参数中，改成确认立刻生效
20.评测流程，等正式数据ing
21./history页面404
22.agentresponse的字段使用情况
{
    "answer":           ✅ ← mapToCanvasState 用了
    "sql":             ❌ ← 没用
    "table":           ✅ ← 用了
    "chart":           ✅ ← 用了
    "suggestions":     ✅ ← 用了
    "recommendations": ✅ ← 刚才才加的
    "metadata":        ❌ ← 没用（retry_count, has_error, error_details, row_count）
}
已增加sql展示和recommend
23.增加历史对话管理
已解决
24.增加暗色主题
已解决
25.目前的分析比较简单，考虑增加insight，去看看其他产品怎么做的
#TODO
26.修改布局和标题和slogan
已完成
27.完善feedback节点和sql——saver node
#TODO
28.增加一个analysis node
29.未来方向
1.权限管理
2.问数运营就是用户个性化
3.看板功能
4.企业知识库
5.编辑图表，下钻字段
6.收藏问题
7.显示问答解析过程
8.导出下载


30针对具体场景的改进
30.1增加了一个元数据表
结构升级（meta_column_semantics）：

增加了 temporal_type（时点 snapshot / 时期 flow），配合规则彻底解决大模型乱写 SUM(余额) 的低级错误。

增加了 currency（币种）和 aggregation_behavior（默认聚合行为：last_value / sum / avg），指导系统智能生成时间轴上的取值逻辑。

增加了 is_sensitive（敏感字段标识），用于前置或后置的数据安全脱敏。

规则扩充（meta_business_rules）：

增加了时点指标日均/期末取值规则、汇率折算规则、**金融比率（不良贷款率）以及客户口径（活跃客户、正常零售客户）**的标准定义。
30.2
时点拦截器 (Temporal Interceptor)：在 LLM 生成 SQL 阶段，如果生成的 SQL 里包含了 temporal_type = 'snapshot' 的列（如余额），且外层使用了 SUM(...) 并且没有按日期 p_date 过滤成单日，系统应当触发安全拦截或自动重写提示，要求大模型改用 AVG() 或自动定位到该时间区间的最后一天。

脱敏机制 (Masking Engine)：在返回数据或生成 SQL 时，读取 is_sensitive = 1 的标记，若成立，SQL 自动嵌套脱敏函数（如 REPLACE ），防止明文泄露。

关于检索相关表和列
## 三、能否把「表检索 + 列检索」合并（你的思路）——可以，且很契合

__能。__ `meta_column_semantics` 的行本身就是 `(table_name, column_name) → (business_name, related_concept, usage_note)`。所以可&#x4EE5;__&#x6309;业务概念一次性把「该用哪些表 + 哪些列」都检索出来__，表与列同时得到，省掉 Step2→Step3 两次 LLM 调用。

__新 Step2' 设计（问题 → 概念命中 → 表+列）：__

```javascript
问题  -->  在 meta_column_semantics 的
          related_concept / business_name / usage_note
          上做关键词/概念匹配(可加权重排序)
        -->  命中 Top-K 行 (table_name, column_name, concept, ...)
        -->  表去重 = relevant_tables
               (table, columns) 分组 = relevant_columns
```

- 匹配方式三选一（与你现有代码一致度排序）：

  1. __纯 SQL 关键词匹配__（`instr` + 权重，最便宜，和 `get_relevant_business_rules` 同风格）——推荐起步。
  2. __向量/余弦相似度__（`distinct_values.py` 已有 char-ngram + `_cosine_sim`，可复用思路）。
  3. __先让 LLM 抽业务概念词，再做查找__（保留一点 LLM 泛化）。

- Step4 的「业务规则 + 列语义」&#x53EF;__&#x539F;样保留__（本就查这张表）。

- 优点：一次命中表+列、信号来自业务语义、从根本上减少「漏必要表」；__合并后整个 schema_retreiver 能少一次 LLM 调用、少一本 prompt__。

__⚠️ 关键风险与对策：`meta_column_semantics` 的覆盖完整性__

- 合并后，__没注册进 `meta_column_semantics` 的表/列会彻底捞不到__（而现在 Step2 能选中任意 DB 表）。这是合并的最大隐患。

- 对策（推荐组合）：

  - __兜底并集__：`relevant_tables/columns = 概念命中结果 UNION 保留原有 LLM 表检索（作为 fallback）`——概念命中为主，LLM 检索兜底，覆盖不全时不丢表。
  - 或在上线&#x524D;__&#x8865;齐元数据__：确保所有业务表（`dim_*`/`fact_*` 核心表）都已在 `meta_column_semantics` 登记；未登记的表走兜底分支。
  - 可加一个指标：「概念命中的表数 vs 最终 relevant_tables 表数」，监控覆盖率。


重新写列语义表
/AGENTS 我需要你为C:\\Users\\yhuang\\bank.db这个路径下的每一张表的每一列猜测意思，放进这个路径下的meta_column_semantics这张表中，按照table_name, column_name, business_name, is_measure, temporal_type , is_sensitive, usage_note这个结构来


重新写了业务逻辑表
目前的sql重试生成效果不好
总结可能遇到三种问题
1.使用了未授权的表
2.跨层join阻断
3.业务/计算公式违规
第一个重试sql_generator node是成功不了的，需要让ai评估开放node，新增一个sql_gen_retry_right node或者在sql_generator中增加一个函数，如果error message携带了这类信息就判断是否加进可用表
2，3可以由原node生成但是携带信息会不会太多了一点，2可以用一个node在原sql的基础上加入prompt修改，3需要由原节点携带error message修改，采用瘦身版本

9.9
关于检索出零行数据，开启0行检测，放松条件让ai自查，重试两次
怎么防止误伤

9.10
发现了关键问题， FROM ads_cust_info_d a ... WHERE a.data_dt = '20260331'因为我只导入了历史某一天的表格，所以这个不能限制data_dt,修改一下sql生成和检测关于这方面的限制
