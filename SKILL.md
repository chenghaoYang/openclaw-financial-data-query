---
name: financial-data-query
description: "根据自然语言查询股票、基金、指数、期货等金融数据。通过混合召回（BM25 API + BGE 向量服务）匹配数据表，生成 Trino SQL，调用远程 SQL 引擎执行并返回结果。覆盖 20+ 领域 470+ 视图表。"
metadata:
  openclaw:
    emoji: "📊"
    os:
      - darwin
      - linux
    requires:
      env:
        - FIN_SQL_CONTAINER_HOST
        - BGE_SERVICE_URL
        - BM25_INDEX_API_URL
        - YAML_METADATA_API_URL
      bins:
        - python3
    primaryEnv: FIN_SQL_CONTAINER_HOST
---

# Financial Data Query Skill

## 概述

本技能将用户的自然语言金融数据查询转换为 Trino SQL 并执行返回结果。

**核心架构**：
- **召回**：`scripts/meta_retriever.py` 驱动 `recall/pipeline.py`，通过远程 API 进行 BM25 + BGE 向量 4 路并行召回 + RRF 融合
- **SQL 执行**（远程）：通过 `FIN_SQL_CONTAINER_HOST` 调用远程 Trino SQL 引擎
- **问财搜索**（远程，可选）：调用问财综合搜索 API 获取财经新闻/公告/研报

### 适用场景

- **股票数据**：日行情、财务数据、技术指标、涨停分析
- **基金数据**：净值、持仓、业绩比较
- **指数数据**：指数行情、成分股查询
- **期货期权**：合约行情、持仓数据
- **其他**：可转债、债券、港股、美股、新三板、银行理财等

### 数据覆盖

- **20+ 金融领域**，**470 个视图表**
- 市场：A股、港股、美股、基金、指数、期货、期权、可转债、新三板、全量债券、银行理财、外盘期货等 18 个域

### 技能文件结构

```
financial-data-query/
├── SKILL.md                          # 本文档
├── sql_rules.md                      # SQL 生成强制规则
├── examples.md                       # 12 个渐进式 SQL 示例
├── routing_taxonomy.md               # 意图路由分类表（~110 个意图）
├── stock_sql_query_examples.json     # 5121 个 SQL 转换示例
├── scripts/                          # 运行时脚本
│   ├── openclaw_tool_runner.py       # OpenClaw JSON bridge（统一入口）
│   ├── meta_retriever.py             # 混合召回入口（调用远程 BM25 + 向量 API）
│   ├── fin_sql_executor.py           # SQL 执行工具（preview/download）
│   ├── wencai_search.py              # 问财综合搜索
│   └── common_clients.py            # 公共 HTTP 客户端
├── recall/                           # 混合召回编排逻辑（无本地数据）
│   ├── config.py                     # 召回配置（API 地址、阈值等）
│   ├── pipeline.py                   # 4 路并行召回 + RRF 融合编排
│   ├── providers/
│   │   ├── bm25_retriever.py         # BM25 召回（通过 BM25_INDEX_API_URL）
│   │   ├── bge_search.py             # BGE 向量召回（通过 BGE_SERVICE_URL）
│   │   └── filter_utils.py           # 后过滤工具
│   └── utils/
│       ├── domain_router.py          # 领域路由器
│       ├── financial_terms.py        # 金融同义词词典
│       ├── market_taxonomy.py        # 市场/频率分类
│       ├── market_rules.py           # 市场标签规则引擎
│       ├── time_parser.py            # 时间表达式解析
│       └── numerical_filter_extractor.py  # 数值条件提取
├── functions/
│   ├── common_functions.md           # 40 个高频函数速查
│   ├── market_analysis_functions.md  # 行情分析函数（hq_index 系列）
│   ├── statistical_functions.md      # 统计计算函数（interval_index 等）
│   └── functions_full.json           # 完整 627 函数库
└── templates/
    ├── simple_query.sql              # 单表筛选模板
    ├── complex_query.sql             # 多表关联模板
    └── aggregation_query.sql         # 时间区间聚合模板
```

---

## 环境变量

| 变量 | 必需 | 说明 | 默认值 |
|------|------|------|--------|
| `FIN_SQL_CONTAINER_HOST` | 是 | Trino SQL 执行服务地址 | `http://cbas-babel-frontend-prod:10399` |
| `BGE_SERVICE_URL` | 是 | BGE 向量服务地址 | `http://192.168.208.168` |
| `BGE_SERVICE_KEY` | 否 | BGE 向量服务 API Key | `claudable` |
| `VECTOR_COLLECTION_NAME` | 否 | 向量库 collection 名称 | `financial_metadata_20260226` |
| `BM25_INDEX_API_URL` | 是 | BM25 索引检索 API 地址 | *（占位，待实现）* |
| `YAML_METADATA_API_URL` | 是 | YAML 视图表元数据 API 地址 | *（占位，待实现）* |
| `THS_TIER` | 否 | 环境（`dev` 用 mTLS，`prod` 用 HTTP） | `dev` |
| `ENABLE_HYBRID` | 否 | 是否启用向量混合召回 | `true` |

### Python 依赖

```
httpx, aiohttp, numpy, cryptography
```

> 注：`bm25s`、`jieba` 在本地 BM25 模式下需要，API 模式下不需要。

---

## API 端点

本技能依赖 4 个远程 API（其中 2 个待实现）。

### 1. BM25_INDEX_API_URL — BM25 索引检索（占位，待实现）

将查询文本发送到远程 BM25 索引服务，返回关键词匹配的候选字段。

**请求 (POST JSON)**：
```json
{
  "query_text": "[A股]贵州茅台 涨跌幅 近3日",
  "top_k": 50,
  "filter_expr": "doc_type=column",
  "yaml_paths": ["股票/stock_astock_mkt_daily_trans.yaml"],
  "market": "A股",
  "frequency": "日频"
}
```

**响应 (JSON)**：
```json
{
  "success": true,
  "hits": [
    {
      "id": "股票/stock_astock_mkt_daily_trans.yaml#se001ntd00009433",
      "bm25_score": 18.5,
      "text": "涨跌幅 DOUBLE类型 ...",
      "table_path": "股票/stock_astock_mkt_daily_trans.yaml",
      "table_name": "stock_astock_mkt_daily_trans",
      "table_alias": "A股日行情",
      "column_name": "se001ntd00009433",
      "column_alias": "涨跌幅",
      "market": "A股",
      "frequency": "日频",
      "sql_column_ref": "se001ntd00009433",
      "value_source": ""
    }
  ]
}
```

> **对应当前代码**：`recall/providers/bm25_retriever.py` 的 `BM25Retriever.search()` 方法。当前实现读取本地 BM25 索引文件（`.npy` + `docs_meta.json`），未来需改为调用此 API。

### 2. YAML_METADATA_API_URL — YAML 视图表元数据（占位，待实现）

查询视图表的 YAML 定义和字段列表。

**请求 (POST JSON)**：
```json
{
  "action": "get_table_schema",
  "yaml_path": "股票/stock_astock_mkt_daily_trans.yaml"
}
```

**响应 (JSON)**：
```json
{
  "success": true,
  "table_name": "stock_astock_mkt_daily_trans",
  "table_alias": "A股日行情",
  "market": "A股",
  "frequency": "日频",
  "columns": [
    {
      "column_name": "se001ntd00009433",
      "column_alias": "涨跌幅",
      "column_type": "DOUBLE",
      "unit": "%",
      "sql_column_ref": "se001ntd00009433",
      "value_source": "",
      "example_all": null
    }
  ]
}
```

> **对应当前代码**：原技能通过 Grep 搜索 `repo/fin/view_table/` 目录下的 YAML 文件。此 API 提供等价的远程访问能力。用于步骤 3 字段映射时补充 `columnType`、`unit`、`example_all` 等信息。

### 3. BGE_SERVICE_URL — BGE 向量语义检索（已实现）

远程 BGE 向量服务，由 `recall/providers/bge_search.py` 调用。接口已对齐中台 Arsenal 平台。

### 4. FIN_SQL_CONTAINER_HOST — Trino SQL 执行（已实现）

远程 SQL 执行服务，由 `scripts/fin_sql_executor.py` 调用。

---

## 工具调用说明

本技能提供统一的 JSON bridge `scripts/openclaw_tool_runner.py`，通过 stdin 传入 JSON payload，stdout 输出 JSON 结果。也可直接调用各脚本的 CLI。

### 工具 1：混合召回（schema_retrieve）

编排 BM25 + BGE 向量 4 路并行召回，返回候选表和字段。

**统一入口调用**：
```bash
echo '{
  "query": "贵州茅台近3日涨跌幅",
  "normalized_query": "[A股]贵州茅台 涨跌幅 近3日",
  "market": "A股",
  "frequency": "日频",
  "top_k": 20,
  "routing": {
    "intent": "astock_daily_quote",
    "yaml_scopes": ["股票/stock_astock_mkt_daily_trans.yaml"],
    "query_expansions": ["股价", "行情", "涨跌幅"],
    "confidence": 0.85,
    "is_comparison": false
  }
}' | python3 scripts/openclaw_tool_runner.py --tool schema_retrieve
```

**CLI 直接调用**：
```bash
python3 scripts/meta_retriever.py \
  --query "贵州茅台近3日涨跌幅" \
  --normalized-query "[A股]贵州茅台 涨跌幅 近3日" \
  --market "A股" \
  --frequency "日频" \
  --top-k 20 \
  --routing-json '{"intent":"astock_daily_quote","yaml_scopes":["股票/stock_astock_mkt_daily_trans.yaml"],"query_expansions":["股价","行情","涨跌幅"],"confidence":0.85,"is_comparison":false}' \
  --pretty
```

**响应 JSON**：
```json
{
  "status": "success|unavailable|error",
  "telemetry": {
    "confidence": "high|mid|low",
    "top1_score": 0.143,
    "top10_score": 0.100,
    "top10_coverage": 0.70,
    "vector_available": true
  },
  "candidate_columns": [
    {
      "column_name": "se001ntd00009433",
      "column_alias": "涨跌幅",
      "table_name": "stock_astock_mkt_daily_trans",
      "table_alias": "A股日行情",
      "score": 0.85,
      "market": "A股",
      "frequency": "日频",
      "source": "bm25",
      "sql_column_ref": "se001ntd00009433",
      "value_source": ""
    }
  ],
  "candidate_tables": [
    {
      "table_name": "stock_astock_mkt_daily_trans",
      "table_alias": "A股日行情",
      "yaml_path": "股票/stock_astock_mkt_daily_trans.yaml",
      "market": "A股",
      "frequency": "日频",
      "avg_score": 0.82,
      "columns": ["..."]
    }
  ]
}
```

### 工具 2：SQL 执行（sql_execute）

调用远程 `FIN_SQL_CONTAINER_HOST` 执行 Trino SQL。

**统一入口调用**：
```bash
# 预览
echo '{"sql": "WITH table0 AS (...) SELECT ...", "action": "preview"}' \
  | python3 scripts/openclaw_tool_runner.py --tool sql_execute

# 下载
echo '{"sql": "...", "action": "download"}' \
  | python3 scripts/openclaw_tool_runner.py --tool sql_execute
```

**CLI 直接调用**：
```bash
python3 scripts/fin_sql_executor.py --action preview --sql "<SQL语句>"
python3 scripts/fin_sql_executor.py --action download --sql "<SQL语句>" --project-path /path/to/project
```

### 工具 3：问财搜索（context_search，可选）

调用远程问财综合搜索 API，获取财经新闻、公告、研报等。

**统一入口调用**：
```bash
echo '{
  "query": "浙金中心暴雷",
  "preset": "event",
  "days": 30
}' | python3 scripts/openclaw_tool_runner.py --tool context_search
```

**CLI 直接调用**：
```bash
python3 scripts/wencai_search.py --query "浙金中心暴雷" --preset event --days 30
```

**预设方案**：`event`(事件) / `company`(公司) / `market`(市场) / `policy`(政策) / `research`(研报) / `quick`(快讯) / `comprehensive`(综合)

---

## 混合召回系统架构

BM25 始终作为主路径强制执行；向量服务可选（`ENABLE_HYBRID=true` 时自动混合，不可达时降级为纯 BM25）。

**召回链路**（4 路并行，由 `recall/pipeline.py` 编排）：
```
Query + Normalized Query
  → Domain Router (规则路由 + LLM 路由 Ensemble)
  → 4 路并行召回：
    ① BM25 检索（BM25_INDEX_API_URL，强制，主路径，权重 3.0）
    ② Global 向量检索（BGE_SERVICE_URL，可选，全局语义）
    ③ Scoped 向量检索（BGE_SERVICE_URL，可选，路由限定范围）
    ④ Two-Stage 检索（可选，先表后列）
  → RRF / Linear 融合
  → Top-K 候选输出
```

**自动降级机制**：
- 向量服务不可用 → 降级为 BM25 单路召回
- BM25 market 过滤无结果 → 回退到全局搜索
- LLM 路由 confidence < 0.7 → 降级为规则路由

> **注意**：`recall/` 目录包含召回编排逻辑代码，不包含数据文件。BM25 索引数据和 YAML 视图表元数据均通过远程 API 获取。当前 `bm25_retriever.py` 实现仍依赖本地索引文件，待 `BM25_INDEX_API_URL` 实现后需适配为 API 调用。

---

## 工作流程

### 步骤 0：时事背景增强（条件执行）

**执行条件**（满足任一才执行，纯数据查询直接跳到步骤 1）：
- 查询涉及具体事件/新闻/公告
- 查询有模糊指代（"这些公司"、"相关股票"）
- 用户明确需要背景分析

**双路搜索策略**：
1. **通用搜索**：使用 WebSearch 获取事件背景
2. **问财搜索**：调用 `scripts/wencai_search.py` 获取专业金融资讯

从搜索结果提取：公司名称 -> 股票代码、事件时间 -> 查询日期范围。

---

### 步骤 1：查询理解与归一化

分析用户自然语言问句，提取以下要素：

**必须提取的字段**：
- **core_indicator**: 核心指标（涨跌幅、成交额、净值、市盈率等）
- **keywords**: 关键实体词（股票名/基金名，最多 3 个）
- **market**: 市场标签（A股/港股/美股/基金/指数/期货/期权/可转债等 18 个域，默认 A股）
- **time_range**: 时间范围（近3日、今年以来、2024年Q1 等）
- **frequency**: 数据频率（日频/周频/月频/季度/年频/时序）
- **numerical_filters**（可选）: `[{"field":"PE","operator":"<","value":20.0,"unit":null}]`

**归一化查询构造**：格式 `[市场] 实体关键词 核心指标 时间范围`

| 用户查询 | core_indicator | keywords | market | time_range | 归一化查询 |
|---------|---------------|----------|--------|-----------|-----------|
| 贵州茅台近3日涨跌幅 | 涨跌幅 | 贵州茅台 | A股 | 近3日 | `[A股]贵州茅台 涨跌幅 近3日` |
| 港股通最新成交额排名 | 成交额 | 港股通 | 港股 | 最新 | `[港股]港股通 成交额 最新` |
| 沪深300指数年初以来表现 | 指数表现 | 沪深300 | 指数 | 年初以来 | `[指数]沪深300 指数表现 年初以来` |
| 比较茅台和五粮液市盈率 | 市盈率 | 茅台, 五粮液 | A股 | （空） | `[A股]茅台 五粮液 市盈率` |
| 最近一周换手率超过10%的股票 | 换手率 | （空） | A股 | 最近一周 | `[A股]换手率 最近一周` |

**改写约束**：
- 保留原始 query 中的区分性术语（不要抽象成泛词）
- 保留时间语义（最新/近N日）
- 保留特有形态词（如 青龙取水、强中选强）

**路由信息提取**（与归一化同时完成）：

参照 `routing_taxonomy.md` 确定查询的领域意图和检索范围。

```json
{
  "intent": "astock_daily_quote",
  "yaml_scopes": ["股票/stock_astock_mkt_daily_trans.yaml", "股票/stock_astock_latest_index.yaml"],
  "query_expansions": ["股价", "行情", "涨跌幅"],
  "confidence": 0.85,
  "is_comparison": false
}
```

**路由决策规则**：
- 意图明确、单市场 → confidence 0.85-0.95
- 意图模糊但市场明确 → confidence 0.70-0.80
- 对比类查询 → is_comparison=true，合并两个市场的 yaml_scopes
- 完全无法判断 → intent=`global`，yaml_scopes=[]，confidence 0.0-0.3

**Ensemble 路由机制**：pipeline 采用 ensemble 融合（LLM 路由 + 规则路由同时运行，结果合并）。高 confidence (>= 0.7) 的 LLM 路由可以扩 scope、覆盖主 intent；低 confidence 以规则路由为准。market 以规则路由为锚点（基于 regex，无幻觉）。

**常用快速参考**（完整列表见 `routing_taxonomy.md`）：

> **A股**：
> - 日行情/涨跌幅 → `astock_daily_quote`: `股票/stock_astock_mkt_daily_trans.yaml`
> - 财务数据 → `astock_financial`: `股票/stock_astock_company_financial_data.yaml`
> - 技术指标 → `technical_*`: `股票/stock_astock_mkt_daily_trans.yaml`
> - 龙虎榜 → `lhb_foreign_trade`: `股票/stock_astock_charts.yaml`
> - 概念板块 → `astock_concept`: `股票/stock_astock_concept.yaml`
>
> **港股**：日行情 → `hk_daily_quote`: `港股/stock_hkstock_mkt_daily_trans.yaml`
> **美股**：日行情 → `us_daily_quote`: `美股/stock_ustock_mkt_daily_trans.yaml`
> **基金**：净值 → `fund_nav`: `基金/fund_mkt_daily_trans.yaml`
> **指数**：行情 → `index_quote`: `全量指数/index_mkt_daily_trans.yaml`
> **期货**：日行情 → `futures_daily_quote`: `期货/futu_mkt_daily_quo.yaml`
> **可转债**：行情 → `cb_market`: `可转债/convertiblebond_market.yaml`

**边缘情况**：
- 跨市场对比：拆分为多个单市场查询，分别调用召回
- 无明确 core_indicator：保留主体词，提示用户补充指标
- market 不确定：默认 A股

---

### 步骤 2：选择数据表（调用混合召回）

将步骤 1 的归一化查询传入 `meta_retriever.py`：

```bash
python3 scripts/meta_retriever.py \
  --query "原始用户查询" \
  --normalized-query "[A股]贵州茅台 涨跌幅 近3日" \
  --market "A股" \
  --frequency "日频" \
  --top-k 20 \
  --routing-json '{"intent":"astock_daily_quote","yaml_scopes":["股票/stock_astock_mkt_daily_trans.yaml","股票/stock_astock_latest_index.yaml"],"query_expansions":["股价","行情","涨跌幅"],"confidence":0.85,"is_comparison":false}' \
  --pretty
```

**参数说明**：
- `--query`: 原始用户查询（用于 Domain Router 分析）
- `--normalized-query`: 归一化查询（用于向量/BM25 检索，**必须提供**）
- `--market`: 市场标签（用于候选过滤）
- `--frequency`: 数据频率（可选但推荐）
- `--top-k`: 建议 **20**，留足余量
- `--routing-json`: 路由信息 JSON（**必须提供**）

**评估候选结果**（`status=success` 时）：
1. **语义匹配度**：`column_alias` 是否与查询核心指标一致
2. **表域匹配度**：`table_alias` 所属领域是否正确
3. **市场/频率匹配**：`market`/`frequency` 是否一致
4. **分数参考**：`score` 越高相关性越强

从候选中选择最合适的 1-3 个表和对应字段。

**关键字段说明**：

| 字段 | 含义 |
|------|------|
| `telemetry.confidence` | 召回置信度（`high`/`mid`/`low`） |
| `telemetry.vector_available` | 是否有向量召回参与 |
| `candidate_columns[].sql_column_ref` | **SQL 中引用字段的正确编码** |
| `candidate_columns[].value_source` | 空=普通字段，`行情形态`/`行情指标`=f2f 语法 |
| `candidate_columns[].source` | 候选来源（`bm25`/`global`/`scoped` 等） |

**失败处理**：
- `status=success` → 正常使用候选结果
- `status=unavailable` → 补充更具体的查询条件后重试
- `status=error` 且包含 `timeout` → 重试一次
- `status=error` 其他情况 → 终止并向用户报错

**严格禁止**：
- 跳过召回直接凭经验选表
- 在 `status=error` 时继续生成 SQL
- 在没有候选对比理由时直接选表

---

### 步骤 3：字段映射

**字段引用规则**：生成 SQL 时一律使用 `sql_column_ref`，不要使用 `column_name`。

- `value_source` 为空 → 普通字段
- `value_source` = `行情形态` → f2f 语法：`"f2f##<形态名>"`
- `value_source` = `行情指标` → 指标值用 `column_name`，信号用 `"f2f#<指标名>#<信号名>"`

> 完整 f2f 语法规则见 `sql_rules.md` 2.4 节。

**补充字段信息**（如需 `columnType`、`unit`、`example_all`）：

通过 `YAML_METADATA_API_URL` 查询视图表 YAML 定义：
```bash
curl -s -X POST "$YAML_METADATA_API_URL" \
  -H "Content-Type: application/json" \
  -d '{"action": "get_table_schema", "yaml_path": "股票/stock_astock_mkt_daily_trans.yaml"}' | jq .
```

**探查字段取值**（针对 STRING/ARRAY 分类字段）：

```bash
python3 scripts/fin_sql_executor.py --action preview \
  --sql "SELECT DISTINCT {字段名}, COUNT(*) as cnt FROM {表名} WHERE {字段名} LIKE '%关键词%' GROUP BY {字段名} ORDER BY cnt DESC LIMIT 20"
```

---

### 步骤 4：SQL 设计前检查

在编写 SQL 前思考：
1. 字段记录的是快照值还是累计统计？
2. 用户问的时间跨度与字段类型是否匹配？
3. 如不匹配，是否需要使用 `interval_index` 等统计函数？

参考：`functions/common_functions.md`、`functions/statistical_functions.md`

---

### 步骤 5：生成 SQL

**优先策略：模板匹配**

| 查询类型 | 模板文件 | 特征 |
|---------|---------|------|
| 单表简单筛选 | `templates/simple_query.sql` | 单个表、简单 WHERE |
| 多表关联查询 | `templates/complex_query.sql` | JOIN 多个表 |
| 时间区间聚合 | `templates/aggregation_query.sql` | GROUP BY + 聚合函数 |

**降级策略：规则生成**

不匹配模板时，参考以下文件从头生成：
- `sql_rules.md` - CTE 结构、固定输出字段、时间处理、筛选条件等强制规则
- `examples.md` - 12 个渐进式示例
- `stock_sql_query_examples.json` - 5121 个 SQL 转换示例

**函数使用（四层结构）**：
1. `functions/common_functions.md` - 40 个高频函数（覆盖 90% 场景）
2. `functions/market_analysis_functions.md` - hq_index 系列（技术指标）
3. `functions/statistical_functions.md` - interval_index 等（统计分析）
4. `functions/functions_full.json` - 完整 627 函数库

---

### 步骤 6：预执行验证

通过 preview 验证 SQL 正确性（控制在 2 次以内）：

```bash
python3 scripts/fin_sql_executor.py --action preview --sql "<SQL语句>"
```

- 第 1 次：验证日期和数据可用性
- 第 2 次：验证完整 SQL 逻辑（LIMIT 100）

---

### 步骤 7：执行并返回结果

```bash
python3 scripts/fin_sql_executor.py --action download --sql "<完整SQL语句>" --project-path .
```

向用户展示：
- 查询结果数据
- 使用的表和字段说明
- SQL 查询语句（供参考）

---

## 待实现事项

以下是技能完整运行前需要完成的工作：

### 1. BM25_INDEX_API_URL 服务实现

将当前 `recall/providers/bm25_retriever.py` 的本地索引检索能力封装为 HTTP API。

**核心逻辑**（已在 `bm25_retriever.py` 中实现）：
- jieba 中文分词 + 金融同义词扩展
- bm25s 稀疏检索
- market/frequency/yaml_paths 后过滤
- 返回 hit 列表（id, score, metadata）

**部署需求**：
- BM25 索引文件（`*.npy` + `docs_meta.json` + `fin_userdict.txt`，约 158MB）
- Python 依赖：`bm25s`, `jieba`, `numpy`

### 2. YAML_METADATA_API_URL 服务实现

将 `repo/fin/view_table/` 下 470+ YAML 视图表定义封装为 HTTP 查询接口。

**核心功能**：
- 按 `yaml_path` 返回表定义和字段列表
- 支持按关键词搜索字段（Grep 替代）
- 返回 `columnType`、`unit`、`example_all` 等字段元数据

### 3. recall/ 代码适配

当 API 实现后，需修改以下文件：
- `recall/providers/bm25_retriever.py` — 从读本地文件改为调用 `BM25_INDEX_API_URL`
- `recall/providers/bge_search.py` 的 `load_metadata()` — 从读本地 `docs_meta.json` 改为通过 API 获取

---

## 参考文件索引

| 文件 | 说明 |
|------|------|
| `sql_rules.md` | SQL 生成强制规则（CTE 结构、时间处理、字段命名等） |
| `examples.md` | 12 个从简单到复杂的 SQL 示例 |
| `routing_taxonomy.md` | ~110 个意图分类及对应 YAML 路径 |
| `stock_sql_query_examples.json` | 5121 个自然语言到 SQL 的转换示例 |
| `functions/common_functions.md` | 40 个高频函数速查 |
| `functions/market_analysis_functions.md` | 技术指标函数（MA/MACD/KDJ 等） |
| `functions/statistical_functions.md` | 统计函数（区间统计/同比环比/极值） |
| `functions/functions_full.json` | 完整 627 函数库 |
| `templates/*.sql` | 3 个 SQL 查询模板 |
