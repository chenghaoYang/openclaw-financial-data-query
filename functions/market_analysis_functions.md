# 行情分析函数使用指南

> **适用场景**：技术指标计算、形态识别、趋势判断

---

## 概述

本文档介绍3个行情分析自定义函数（`hq_*` 系列），专门用于技术指标查询和技术形态选股。这些函数是Trino查询引擎的扩展，必须通过`table()`包装使用。

### 函数列表

| 函数 | 功能 | 典型应用 |
|------|------|---------|
| `hq_index` | 获取技术指标值 | 查询MA、MACD、KDJ、RSI等指标数值 |
| `hq_index_ss` | 技术形态选股 | 识别金叉、死叉、均线上移下移走平 |
| `hq_calc_ss` | 指标比较选股 | 判断均线上穿下穿、指标交叉 |

### 与统计函数的区别

| 文档 | 函数特点 | 主要场景 |
|------|---------|---------|
| **本文档**<br>`market_analysis_functions.md` | 基于**行情数据**的**技术分析** | MA均线、MACD金叉、KDJ指标、趋势判断 |
| **统计函数**<br>`statistical_functions.md` | 基于**时间区间**的**统计计算** | 营收增长率、同比环比、创新高低、区间统计 |

### 通用规则

**强制要求**：
- 所有函数必须使用 `table()` 包装
- 必须为返回的列指定别名
- 所有函数关联查询建议使用 LEFT JOIN（保留未匹配行）或 JOIN/INNER JOIN（仅保留匹配行），根据业务需求选择
- 关联条件必须同时匹配股票代码和日期

---

## 一、hq_index - 技术指标值提取函数

### 1.1 函数签名

```sql
hq_index(domain, field, cond)
```

### 1.2 参数说明

| 参数名 | 类型 | 说明 | 示例 |
|-------|------|------|------|
| domain | VARCHAR | 领域标识 | `'abs_股票领域'` （固定值） |
| field | VARCHAR | 指标名称 | `'ma'`、`'macd'`、`'kdj_k值'`、`'rsi'` 等 |
| cond | VARCHAR | 条件参数 | `'ndays=5;i_date_exp=0'` |

### 1.3 返回值

返回3列数据（必须为这3列指定别名）：

1. `stkcode` - 股票代码
2. `hq_date` - 行情日期
3. 指标值列 - 指标的具体数值（列名自定义）

### 1.4 条件参数（cond）

**可用参数**：
- `ndays` - 周期参数（如：MA的N日）
- `i_date` - 指定具体日期
- `i_date_exp` - 时间偏移
- `tech_period_unit` - 周期单位（MIN/DAY/WEEK/MONTH/QUARTER/YEAR）
- `period_length` - 周期长度

**参数组合规则**：

```sql
-- 当前交易日的5日均线
'ndays=5;i_date_exp=0'

-- 指定日期的20日均线
'ndays=20;i_date=DATE ''2024-12-09'';i_date_exp=0'

-- 周期为60日的BOLL
'ndays=60;i_date_exp=0'
```

### 1.5 使用示例

#### 示例1：获取5日均线

**问句**：查询当前5日均线

**SQL**：

```sql
SELECT
  g0."stkcode" AS "股票代码",
  tbbh_index1."ma5" AS "ma5[20250929]",
  g0."se001ntd00009415" AS "收盘价[20250929]",
  g0."i_date" AS "交易日期"
FROM
  stock_astock_mkt_daily_trans as g0
LEFT JOIN table(hq_index('abs_股票领域', 'ma', 'ndays=5;i_date_exp=0'))
  as tbbh_index1("stkcode", "hq_date", "ma5")
  ON g0."stkcode" = tbbh_index1."stkcode"
  AND g0."i_date" = tbbh_index1."hq_date"
WHERE
  g0."i_date_exp" = 0
```

**要点**：

- 返回列别名：`("stkcode", "hq_date", "ma5")`
- 关联条件：同时匹配股票代码和日期
- 指标别名：`ma5` 可自定义

#### 示例2：获取多个周期均线

**问句**：查询5日、10日、20日均线

**SQL**：

```sql
SELECT
  g0."stkcode" AS "股票代码",
  tbbh_index1."ma5" AS "ma5[20241209]",
  tbbh_index2."ma10" AS "ma10[20241209]",
  tbbh_index3."ma20" AS "ma20[20241209]",
  g0."i_date" AS "交易日期"
FROM
  stock_astock_mkt_daily_trans as g0
LEFT JOIN table(hq_index('abs_股票领域', 'ma', 'ndays=5;i_date=DATE ''2024-12-09'';i_date_exp=0'))
  as tbbh_index1("stkcode", "hq_date", "ma5")
  ON g0."stkcode" = tbbh_index1."stkcode" AND g0."i_date" = tbbh_index1."hq_date"
LEFT JOIN table(hq_index('abs_股票领域', 'ma', 'ndays=10;i_date=DATE ''2024-12-09'';i_date_exp=0'))
  as tbbh_index2("stkcode", "hq_date", "ma10")
  ON g0."stkcode" = tbbh_index2."stkcode" AND g0."i_date" = tbbh_index2."hq_date"
LEFT JOIN table(hq_index('abs_股票领域', 'ma', 'ndays=20;i_date=DATE ''2024-12-09'';i_date_exp=0'))
  as tbbh_index3("stkcode", "hq_date", "ma20")
  ON g0."stkcode" = tbbh_index3."stkcode" AND g0."i_date" = tbbh_index3."hq_date"
WHERE
  g0."i_date" = DATE '2024-12-09'
  AND g0."i_date_exp" = 0
```

**要点**：

- 多个指标使用多个LEFT JOIN
- 别名递增：`tbbh_index1`, `tbbh_index2`, `tbbh_index3`
- 参数中的日期需要转义单引号：`DATE ''2024-12-09''`

#### 示例3：获取KDJ指标

**问句**：查询KDJ的K值

**SQL**：

```sql
SELECT
  g0."stkcode" AS "股票代码",
  tbbh_index1."kdj_k值" AS "kdj_k值[20250929]",
  g0."i_date" AS "交易日期"
FROM
  stock_astock_mkt_daily_trans as g0
LEFT JOIN table(hq_index('abs_股票领域', 'kdj_k值', 'i_date_exp=0'))
  as tbbh_index1("stkcode", "hq_date", "kdj_k值")
  ON g0."stkcode" = tbbh_index1."stkcode"
  AND g0."i_date" = tbbh_index1."hq_date"
WHERE
  g0."i_date_exp" = 0
```

#### 示例4：RSI大于90

**问句**：查询RSI大于90的股票

**SQL**：

```sql
WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    tbbh_index1."rsi" AS "rsi[20240829]",
    g0."i_date" AS "交易日期"
  FROM
    stock_astock_mkt_daily_trans as g0
  LEFT JOIN table(hq_index('abs_股票领域', 'rsi', 'i_date=DATE ''2024-08-29'';i_date_exp=0'))
    as tbbh_index1("stkcode", "hq_date", "rsi")
    ON g0."stkcode" = tbbh_index1."stkcode"
    AND g0."i_date" = tbbh_index1."hq_date"
  WHERE
    g0."i_date" = DATE '2024-08-29'
    AND g0."i_date_exp" = 0
    AND tbbh_index1."rsi" > 90
)
SELECT
  tb_wide.stkcode as "股票代码",
  tb_wide.stkname as "股票简称",
  tb_wide.se001nnw00035807_new as "最新价",
  tb_wide.se001nnw00035814_new as "最新涨跌幅",
  table0.*
FROM table0
LEFT JOIN stock_astock_latest_index as tb_wide
  ON tb_wide."stkcode" = table0."股票代码"
```

### 1.6 常用技术指标

| 指标类型 | field值 | ndays参数 | 说明 |
|---------|---------|----------|------|
| 移动平均线 | `'ma'` | 5, 10, 20, 30, 60, 120, 250 | 各周期均线 |
| MACD | `'macd'` | 无 | MACD指标 |
| KDJ | `'kdj_k值'`, `'kdj_d值'`, `'kdj_j值'` | 无 | KDJ三值 |
| RSI | `'rsi'` | 无 | 相对强弱指标 |
| BOLL | `'boll'` | 20, 26 | 布林线 |
| TRIX | `'trix'` | 无 | 三重指数平滑移动平均 |
| VR | `'vr'` | 无 | 成交量变异率 |
| WR | `'wr1值'`, `'wr2值'` | 无 | 威廉指标 |
| DPO | `'dpo'` | 无 | 区间震荡线 |
| ADTM | `'adtm'` | 无 | 动态买卖气指标 |
| CCI | `'cci'` | 无 | 顺势指标 |
| ASI | `'asi'` | 无 | 振动升降指标 |

---

## 二、hq_index_ss - 技术形态选股函数

### 2.1 函数签名

```sql
hq_index_ss(domain, field, signal, cond)
```

### 2.2 参数说明

| 参数名 | 类型 | 说明 | 示例 |
|-------|------|------|------|
| domain | VARCHAR | 领域标识 | `'abs_股票领域'` （固定值） |
| field | VARCHAR | 指标名称 | `'macd'`、`'ma'` |
| signal | VARCHAR | 形态名称 | `'金叉'`、`'死叉'`、`'上移'`、`'下移'`、`'走平'` |
| cond | VARCHAR | 条件参数 | `'ndays=5;i_date_exp=0'` |

### 2.3 返回值

返回2列数据（必须为这2列指定别名）：

1. `stkcode` - 股票代码
2. `hq_date` - 行情日期

### 2.4 可用形态（signal）

| 形态名 | 说明 | 适用指标 |
|-------|------|---------|
| `'金叉'` | 快线上穿慢线 | MACD、KDJ等双线指标 |
| `'死叉'` | 快线下穿慢线 | MACD、KDJ等双线指标 |
| `'上移'` | 指标向上运动 | MA、MACD等 |
| `'下移'` | 指标向下运动 | MA、MACD等 |
| `'走平'` | 指标横盘整理 | MA等 |

### 2.5 使用示例

#### 示例1：MACD金叉

**问句**：查询MACD金叉的股票

**SQL**：

```sql
SELECT
  g0."stkcode" AS "股票代码",
  g0."i_date" AS "交易日期"
FROM
  stock_astock_mkt_daily_trans as g0
JOIN table(hq_index_ss('abs_股票领域', 'macd', '金叉', 'i_date_exp=0'))
  as tbbh_index1("stkcode", "hq_date")
  ON g0."stkcode" = tbbh_index1."stkcode"
  AND g0."i_date" = tbbh_index1."hq_date"
WHERE
  g0."i_date_exp" = 0
```

**要点**：

- 返回列别名：`("stkcode", "hq_date")`（固定2列）
- 使用JOIN而不是LEFT JOIN（只要有形态的股票）
- signal参数：`'金叉'`

#### 示例2：25日均线上移

**问句**：查询25日均线上移的股票

**SQL**：

```sql
SELECT
  g0."stkcode" AS "股票代码",
  CASE WHEN tbbh_index1."stkcode" is not null THEN '是' ELSE '否' END as "ma25上移[20250929]",
  g0."i_date" AS "交易日期"
FROM
  stock_astock_mkt_daily_trans as g0
LEFT JOIN table(hq_index_ss('abs_股票领域', 'ma', '上移', 'ndays=25;i_date_exp=0'))
  as tbbh_index1("stkcode", "hq_date")
  ON g0."stkcode" = tbbh_index1."stkcode"
  AND g0."i_date" = tbbh_index1."hq_date"
WHERE
  g0."i_date_exp" = 0
  AND tbbh_index1."stkcode" is not null  -- 只要有形态的
```

**要点**：

- 需要指定`ndays`参数
- 使用CASE WHEN转换为是/否
- 通过`is not null`判断是否存在形态

#### 示例3：99日均线走平或向上

**问句**：99日均线走平或向上的股票

**SQL**：

```sql
WITH table0 AS (
  (
    -- 走平
    SELECT
      g0."stkcode" AS "股票代码",
      CASE WHEN tbbh_index1."stkcode" is not null THEN '是' ELSE '否' END as "ma99走平[20250929]",
      g0."i_date" AS "交易日期"
    FROM
      stock_astock_mkt_daily_trans as g0
    LEFT JOIN table(hq_index_ss('abs_股票领域', 'ma', '走平', 'ndays=99;i_date_exp=0'))
      as tbbh_index1("stkcode", "hq_date")
      ON g0."stkcode" = tbbh_index1."stkcode"
      AND g0."i_date" = tbbh_index1."hq_date"
    WHERE
      g0."i_date_exp" = 0
      AND tbbh_index1."stkcode" is not null
  )
  UNION
  (
    -- 上移
    SELECT
      g0."stkcode" AS "股票代码",
      CASE WHEN tbbh_index2."stkcode" is not null THEN '是' ELSE '否' END as "ma99走平[20250929]",
      g0."i_date" AS "交易日期"
    FROM
      stock_astock_mkt_daily_trans as g0
    LEFT JOIN table(hq_index_ss('abs_股票领域', 'ma', '上移', 'ndays=99;i_date_exp=0'))
      as tbbh_index2("stkcode", "hq_date")
      ON g0."stkcode" = tbbh_index2."stkcode"
      AND g0."i_date" = tbbh_index2."hq_date"
    WHERE
      g0."i_date_exp" = 0
      AND tbbh_index2."stkcode" is not null
  )
)
SELECT ... FROM table0 ...
```

**要点**：

- 使用UNION组合多个形态
- 每个形态单独查询后合并

---

## 三、hq_calc_ss - 指标比较选股函数

### 3.1 函数签名

```sql
hq_calc_ss(domain, signal, signalCond, index1, cond1, index2, cond2)
```

### 3.2 参数说明

| 参数名 | 类型 | 说明 | 示例 |
|-------|------|------|------|
| domain | VARCHAR | 领域标识 | `'abs_股票领域'` |
| signal | VARCHAR | 比较形态 | `'上穿'`、`'下穿'` |
| signalCond | VARCHAR | 形态条件 | `'i_date_exp=0'` |
| index1 | VARCHAR | 第一个指标 | `'ma'` |
| cond1 | VARCHAR | 第一个指标条件 | `'ndays=5'` |
| index2 | VARCHAR | 第二个指标 | `'ma'` |
| cond2 | VARCHAR | 第二个指标条件 | `'ndays=10'` |

### 3.3 返回值

返回2列数据（必须为这2列指定别名）：

1. `stkcode` - 股票代码
2. `hq_date` - 行情日期

### 3.4 可用比较形态

| 形态名 | 说明 | 示例 |
|-------|------|------|
| `'上穿'` | index1上穿index2 | 5日线上穿10日线 |
| `'下穿'` | index1下穿index2 | 5日线下穿10日线 |

### 3.5 使用示例

#### 示例1：5日均线上穿10日均线

**问句**：5日均线上穿10日均线的股票

**SQL**：

```sql
SELECT
  g0."stkcode" AS "股票代码",
  g0."i_date" AS "交易日期"
FROM
  stock_astock_mkt_daily_trans as g0
JOIN table(
    hq_calc_ss(
      'abs_股票领域',
      '上穿',
      'i_date_exp=0',
      'ma',
      'ndays=5',
      'ma',
      'ndays=10'
    )
  ) as tbbh_index1("stkcode", "hq_date")
  ON g0."stkcode" = tbbh_index1."stkcode"
  AND g0."i_date" = tbbh_index1."hq_date"
WHERE
  g0."i_date_exp" = 0
```

**要点**：

- signalCond：`'i_date_exp=0'` 表示当前交易日
- cond1：`'ndays=5'` 5日均线
- cond2：`'ndays=10'` 10日均线

#### 示例2：25日均线上穿99日均线，且25日均线上移

**问句**：25日均线上穿99日均线，且25日均线上移的股票

**SQL**：

```sql
WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    CASE WHEN tbbh_index1."stkcode" is not null THEN '是' ELSE '否' END as "ma25上穿ma99[20250929]",
    CASE WHEN tbbh_index2."stkcode" is not null THEN '是' ELSE '否' END as "ma25上移[20250929]",
    g0."i_date" AS "交易日期"
  FROM
    stock_astock_mkt_daily_trans as g0
  -- 25日线上穿99日线
  LEFT JOIN table(
      hq_calc_ss(
        'abs_股票领域',
        '上穿',
        'i_date_exp=0',
        'ma',
        'ndays=25',
        'ma',
        'ndays=99'
      )
    ) as tbbh_index1("stkcode", "hq_date")
    ON g0."stkcode" = tbbh_index1."stkcode"
    AND g0."i_date" = tbbh_index1."hq_date"
  -- 25日线上移
  LEFT JOIN table(hq_index_ss('abs_股票领域', 'ma', '上移', 'ndays=25;i_date_exp=0'))
    as tbbh_index2("stkcode", "hq_date")
    ON g0."stkcode" = tbbh_index2."stkcode"
    AND g0."i_date" = tbbh_index2."hq_date"
  WHERE
    tbbh_index1."stkcode" is not null
    AND g0."i_date_exp" = 0
    AND tbbh_index2."stkcode" is not null
)
SELECT ... FROM table0 ...
```

**要点**：

- 组合使用 `hq_calc_ss` 和 `hq_index_ss`
- 两个条件都必须满足（AND）

---

## 四、注意事项与最佳实践

### 4.1 禁止操作

1. 不能直接SELECT函数（必须通过JOIN）
2. 不能省略别名
3. 不能只关联股票代码（必须同时关联日期）

### 4.2 性能优化

**建议**：

1. 只查询需要的指标（避免JOIN过多指标表）
2. 优先在WHERE中过滤，再JOIN指标表
3. 对于复杂查询，使用CTE分步骤构建

**示例**：

```sql
-- 不好的写法（先JOIN再WHERE）
SELECT ...
FROM stock_astock_mkt_daily_trans as g0
LEFT JOIN table(hq_index(...)) ...
WHERE g0."i_date_exp" = 0  -- 应该先过滤

-- 好的写法（先WHERE再JOIN）
WITH base AS (
  SELECT ... FROM stock_astock_mkt_daily_trans
  WHERE "i_date_exp" = 0  -- 先过滤
)
SELECT ...
FROM base
LEFT JOIN table(hq_index(...)) ...  -- 再JOIN
```

### 4.3 错误处理

**常见错误**：

```sql
-- ❌ 错误1：缺少table()包装
LEFT JOIN hq_index('abs_股票领域', 'ma', 'ndays=5') ...

-- ✅ 正确
LEFT JOIN table(hq_index('abs_股票领域', 'ma', 'ndays=5')) as tbbh_index1(...) ...

-- ❌ 错误2：缺少别名
LEFT JOIN table(hq_index(...))

-- ✅ 正确
LEFT JOIN table(hq_index(...)) as tbbh_index1("stkcode", "hq_date", "ma5")

-- ❌ 错误3：只关联股票代码
ON g0."stkcode" = tbbh_index1."stkcode"

-- ✅ 正确
ON g0."stkcode" = tbbh_index1."stkcode" AND g0."i_date" = tbbh_index1."hq_date"

-- ❌ 错误4：单引号未转义
'i_date=DATE '2024-08-29';i_date_exp=0'

-- ✅ 正确
'i_date=DATE ''2024-08-29'';i_date_exp=0'
```

### 4.4 调试技巧

**步骤1**：先测试函数返回

```sql
-- 单独测试函数
SELECT * FROM table(hq_index('abs_股票领域', 'ma', 'ndays=5;i_date_exp=0'))
  as tbbh_index1("stkcode", "hq_date", "ma5")
LIMIT 10
```

**步骤2**：再关联主表

```sql
-- 确认关联逻辑
SELECT g0."stkcode", g0."i_date", tbbh_index1.*
FROM stock_astock_mkt_daily_trans as g0
LEFT JOIN table(hq_index(...)) as tbbh_index1(...)
  ON g0."stkcode" = tbbh_index1."stkcode"
  AND g0."i_date" = tbbh_index1."hq_date"
WHERE g0."i_date_exp" = 0
LIMIT 10
```

**步骤3**：添加筛选条件

```sql
-- 最终查询
WHERE ... AND tbbh_index1."ma5" > 10
```

---

## 五、快速参考

### 5.1 函数对比表

| 函数 | 用途 | 返回列数 | 典型场景 |
|------|------|---------|---------|
| `hq_index` | 获取技术指标值 | 3列 | 查询具体指标数值、指标比较 |
| `hq_index_ss` | 技术形态筛选 | 2列 | 金叉死叉、均线方向 |
| `hq_calc_ss` | 指标间比较 | 2列 | 均线上穿下穿 |

### 5.2 模板速查

## 模板1：获取单个指标

```sql
LEFT JOIN table(hq_index('abs_股票领域', '指标名', 'ndays=N;i_date_exp=0'))
  as tbbh_index1("stkcode", "hq_date", "指标别名")
  ON g0."stkcode" = tbbh_index1."stkcode"
  AND g0."i_date" = tbbh_index1."hq_date"
```

## 模板2：形态选股

```sql
LEFT JOIN table(hq_index_ss('abs_股票领域', '指标名', '形态名', 'ndays=N;i_date_exp=0'))
  as tbbh_index1("stkcode", "hq_date")
  ON g0."stkcode" = tbbh_index1."stkcode"
  AND g0."i_date" = tbbh_index1."hq_date"
WHERE tbbh_index1."stkcode" is not null
```

## 模板3：指标比较

```sql
LEFT JOIN table(
    hq_calc_ss(
      'abs_股票领域',
      '上穿/下穿',
      'i_date_exp=0',
      '指标1',
      'ndays=N1',
      '指标2',
      'ndays=N2'
    )
  ) as tbbh_index1("stkcode", "hq_date")
  ON g0."stkcode" = tbbh_index1."stkcode"
  AND g0."i_date" = tbbh_index1."hq_date"
WHERE tbbh_index1."stkcode" is not null
```

---

**版本**：v1.0
**更新日期**：2026-03-02
**适用引擎**：Trino查询引擎扩展函数
