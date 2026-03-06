# 统计计算函数使用指南

> **适用场景**：增长分析、极值统计、区间对比、同比环比计算

---

## 概述

本文档介绍11个统计计算自定义函数，用于对金融数据进行时间维度的增长分析和极值计算。这些函数是Trino查询引擎的扩展，必须通过`table()`包装使用。

### 函数分类

| 分类 | 函数数量 | 主要用途 | 典型场景 | 使用频率 |
|------|---------|---------|---------|---------|
| **区间指标** | 1个 | 150+预定义区间统计指标 | 区间换手率、资金流向、历史极值 | 255次 (#13) |
| **极值函数** | 2个 | 判断创新高、创新低 | 突破前高、跌破支撑 | 38次 (#29/#40) |
| **增长率/增长值** | 8个 | 计算区间、同比、环比、复合增长 | 营收增长率、业绩对比 | <8次 |

**排序依据**：基于5121条实际SQL查询的使用频率统计（参见 common_functions.md）

### 通用规则

**强制要求**：
1. 所有函数必须使用 `table()` 包装
2. 必须为返回的列指定别名
3. 必须通过 LEFT JOIN 关联到主查询
4. 时间表达式必须符合 sql_rules.md 的日期过滤规则

---

## 一、区间指标计算 (interval_index)

**使用频率**：255次（排名 #13）

### 1.1 核心价值：理解快照值与历史极值的区别

#### 问题场景

在金融数据分析中，经常遇到两类不同性质的查询：

**场景A：查询当前状态**
- "今天哪只股票连续涨停天数最多？"
- "当前换手率是多少？"
- "最新的市盈率是多少？"

**场景B：查询历史极值**
- "哪只股票连板最多？"（隐含：整个历史上）
- "历史最高价是多少？"
- "从上市以来最大换手率是多少？"

这两类查询看似相似，但数据来源和查询方式**完全不同**。

---

#### 核心概念：快照值 vs 历史极值

| 对比维度 | 快照值（Snapshot） | 历史极值（Historical Extremum） |
|---------|-------------------|------------------------------|
| **定义** | 某个时间点上的数据状态 | 跨越时间区间的最大/最小/累计值 |
| **时间跨度** | 单个时间点 | 整个时间区间 |
| **数据特性** | 随时间更新，只反映当前状态 | 需要回溯历史，计算区间统计 |
| **存储位置** | 表中字段直接记录 | 需要跨行计算或预计算 |
| **查询方式** | 直接查询字段 | 使用聚合函数或interval_index |
| **典型问句** | "今天XX是多少？" | "历史最大XX是多少？" |

---

#### 真实案例：为什么需要interval_index？

**案例背景**：2024-11-04实际查询失败案例

**用户问题**："历史最多连板股票，除st"

**第一次尝试（错误）**：
```sql
-- ❌ 只查到今天连板数最大的股票
SELECT stkcode, stkname, se001td00009595 AS "连续涨停天数"
FROM stock_astock_mkt_daily_trans
WHERE i_date_exp = 0  -- 只查今天的数据
  AND stkname NOT LIKE '%ST%'
ORDER BY se001td00009595 DESC
LIMIT 10
```

**错误原因**：
- `se001td00009595` 字段记录的是**每个交易日当天**的连续涨停天数（快照值）
- `i_date_exp = 0` 只筛选了今天的数据
- 结果：只能得到"今天连板数最多的股票"（如：10连板）

**正确理解**：
- 用户问的"历史最多连板"，指的是"从有A股以来，哪只股票曾经达到过的最大连续涨停天数"
- 这不是查询今天的快照值，而是查询**跨越整个历史的极值**

**第二次尝试（正确）**：
```sql
-- ✅ 查询历史上曾达到过的最大连板数
WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    g0."stkname" AS "股票简称",
    tbbh_gga1."区间最大连续涨停天数" AS "历史最大连续涨停天数",
    tbbh_gga1."agg_date" AS "统计截止日期"
  FROM stock_astock_mkt_daily_trans as g0
  LEFT JOIN table(
    interval_index(
      'abs_股票领域',
      '区间最大连续涨停天数',
      'i_date>=DATE ''1990-01-01'';i_date<=DATE ''2025-12-31'';i_date_exp=0'
    )
  ) as tbbh_gga1("stkcode", "agg_date", "区间最大连续涨停天数")
    ON g0."stkcode" = tbbh_gga1."stkcode"
  WHERE g0."i_date_exp" = 0
    AND g0."stkname" NOT LIKE '%ST%'
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
ORDER BY table0."历史最大连续涨停天数" DESC
LIMIT 200
```

**正确结果**：
- 西南证券（600369.SH）历史上曾45连板（2008-01-28）
- 瑞茂通（600180.SH）历史上曾30连板（2009-07-08）

**结果对比**：

| 查询方式 | 查询到的值 | 时间跨度 | 数据含义 |
|---------|----------|---------|---------|
| **错误方式**<br>（快照值） | 10连板 | 2024-11-04当天 | 今天连板数最多的股票 |
| **正确方式**<br>（历史极值） | 45连板 | 1990-2025整个历史 | 历史上曾达到的最大连板数 |

**关键差异**：相差35个涨停板！

---

#### interval_index的作用

**解决什么问题？**
1. **自动计算跨时间区间的统计值**：避免手工编写复杂的窗口函数和GROUP BY
2. **提供150+预计算指标**：覆盖历史极值、累计值、日均值等复杂业务逻辑
3. **保证计算准确性**：统一的计算逻辑，避免各种边界情况的错误

**何时使用interval_index？**

判断标准：
1. ✅ 需要**跨时间区间**统计：如"整个历史"、"过去X年"、"从上市以来"
2. ✅ 需要**极值或累计值**：如"最大"、"最高"、"最低"、"累计"、"日均"
3. ✅ 现有字段是**快照值**：只记录当前状态，无法直接得到历史极值
4. ✅ 问句中隐含**历史回溯**：如"曾经"、"出现过"、"达到过"

**不需要interval_index的情况**：
- ❌ 查询今天/当前的值 → 直接查询字段即可
- ❌ 简单的单日数据筛选 → 使用WHERE条件
- ❌ 可以用简单GROUP BY实现的 → 不需要复杂函数

---

### 1.2 函数签名

```sql
interval_index(domain varchar, indexName varchar, cond varchar)
```

### 1.3 参数说明

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| domain | VARCHAR | 领域标识 | `'abs_股票领域'` （固定值） |
| indexName | VARCHAR | 区间指标名称 | `'区间最大连续涨停天数'`, `'区间资金流向'` |
| cond | VARCHAR | 时间表达式 | `'i_date>=DATE ''2023-01-01'';i_date<=DATE ''2023-12-31'';i_date_exp=0'` |

### 1.4 返回值

返回3列数据（必须为这3列指定别名）：

1. `stkcode` - 股票代码
2. `agg_date` - 聚合日期
3. 指标值列 - 指标的具体数值（列名自定义）

### 1.5 使用示例

**示例1：2024年区间换手率**

> `区间最大连续涨停天数` 的完整示例已在上方 1.1 节给出，此处改用不同指标避免重复。

**问句**：查询2024年全年区间换手率

**SQL**：
```sql
WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    tbbh_gga1."区间换手率" AS "区间换手率[2024]",
    tbbh_gga1."agg_date" AS "统计截止日期"
  FROM stock_astock_mkt_daily_trans as g0
  LEFT JOIN table(
    interval_index(
      'abs_股票领域',
      '区间换手率',
      'i_date>=DATE ''2024-01-01'';i_date<=DATE ''2024-12-31'';i_date_exp=0'
    )
  ) as tbbh_gga1("stkcode", "agg_date", "区间换手率")
    ON g0."stkcode" = tbbh_gga1."stkcode"
  WHERE g0."i_date_exp" = 0
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
ORDER BY table0."区间换手率[2024]" DESC
```

**示例2：区间振幅**

**问句**：查询2024年11月至12月的区间振幅

**SQL**：
```sql
WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    tbbh_gga1."振幅" as "振幅[20241114-20241209]",
    sum(g0."se001td00009590") AS "累计换手率[20241114-20241209]"
  FROM stock_astock_mkt_daily_trans as g0
  LEFT JOIN table(
    interval_index(
      'abs_股票领域',
      '区间振幅',
      'i_date>=DATE ''2024-11-14'';i_date<=DATE ''2024-12-09'';i_date_exp=0'
    )
  ) as tbbh_gga1("stkcode", "agg_date", "振幅")
    ON g0."stkcode" = tbbh_gga1."stkcode"
  WHERE (g0."i_date" >= DATE '2024-11-14'
     AND g0."i_date" <= DATE '2024-12-09'
     AND g0."i_date_exp" = 0)
  GROUP BY g0."stkcode", tbbh_gga1."振幅"
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
ORDER BY table0."振幅[20241114-20241209]" DESC
```

**要点**：
- 返回列别名：`("stkcode", "agg_date", "指标名")`
- 关联条件：只关联股票代码（不关联日期）
- 时间表达式：必须使用 `i_date>=DATE 'xxx';i_date<=DATE 'xxx';i_date_exp=0` 格式

---

### 1.6 支持的150+区间指标

#### A. 涨停跌停相关（10个）
- 区间最大连续涨停天数
- 区间涨停次数(非一字)
- 涨停次数
- 跌停次数

#### B. 价格极值（10个）
- 区间最低价:前复权
- 区间最高价:前复权
- 区间最低价:后复权
- 区间最高价:后复权
- 区间最高收盘价
- 区间最低收盘价
- 分时区间最高价:前复权
- 分时区间最低价:前复权
- 历史最高价不复权
- 历史最低价不复权

#### C. 资金流向（30个）
- 区间资金流向
- 区间资金流入inner
- 区间资金流出inner
- 区间主力资金流向
- 区间主力净流入
- 区间主力净流出
- 区间主力流出inter
- 区间主力流入inter
- 区间主力买入金额
- 区间主力卖出金额
- 区间特大单买入金额
- 区间特大单卖出金额
- 区间特大单净额
- 区间大单买入金额
- 区间大单卖出金额
- 区间中单买入金额
- 区间中单卖出金额
- 区间中单净额
- 区间小单买入金额
- 区间小单卖出金额
- 区间小单净额
- 区间dde大单买入金额
- 区间dde大单卖出金额
- 区间dde大单净额
- 区间小单净流入量
- 区间中单净流入量
- 区间特大单净流入量

#### D. 陆股通/沪深股通（40个）
- 区间陆股通买入金额
- 区间陆股通卖出金额
- 区间陆股通成交金额
- 区间陆股通净买入额
- 区间陆股通持股量
- 区间陆股通净买入量
- 区间陆股通成交量
- 陆股通区间成本
- 区间沪股通买入金额
- 区间沪股通卖出金额
- 区间沪股通成交金额
- 区间沪股通成交量
- 区间沪股通净买入量
- 区间沪股通净买入额
- 沪股通区间成本
- 区间深股通买入金额
- 区间深股通卖出金额
- 区间深股通净买入额
- 区间深股通净买入量
- 区间深股通成交金额
- 区间深股通成交量
- 深股通区间成本
- 日均陆股通买入金额
- 日均陆股通卖出金额
- 日均陆股通净买入额
- 日均陆股通净买入量
- 日均陆股通持股量
- 日均陆股通持股占流通a股比
- 日均陆股通持股占总股本比
- 日均陆股通持股市值
- 日均陆股通净买入比例
- 日均陆股通持股盈亏

#### E. 融资融券（15个）
- 区间融资买入量
- 区间融资买入额
- 区间融资偿还额
- 区间融资偿还量
- 区间融资净买入额
- 区间融券卖出额
- 区间融券卖出量
- 区间融券偿还量
- 区间融券偿还额
- 区间融券净卖出量
- 区间融券净卖出额
- 区间融资融券交易量
- 区间融资融券交易额
- 区间融资融券交易量差值
- 区间融资融券交易额差值

#### F. 估值指标（15个）
- 区间日均市盈率(pe)
- 区间日均市净率(pb)
- 区间日均市销率(ps)
- 区间日均静态市盈率(扣非)
- pe区间最高值
- pe区间最低值
- pb区间最高值
- pb区间最低值
- 历史最高市盈率
- 历史最低市盈率
- 历史最高市净率
- 历史最低市净率

#### G. 成交量额（15个）
- 区间成交量
- 区间成交额
- 区间最高成交量
- 区间最低成交量
- 区间最高成交额
- 区间最低成交额
- 区间外盘成交量
- 历史最高成交量
- 历史最低成交量
- 历史最高成交额
- 历史最低成交额

#### H. 市值与换手（10个）
- 区间最低总市值
- 区间最高总市值
- 区间最低流通市值
- 区间最高流通市值
- 区间换手率
- 区间最高换手率
- 区间最低换手率
- 区间日均换手率
- 区间日均量比
- 区间日均振幅

#### I. 其他统计（15个）
- 区间交易天数
- 区间上涨天数
- 区间下跌天数
- 区间平盘天数
- 区间停牌天数
- 区间复牌次数
- 区间日均涨跌幅
- 区间平均收盘价
- 区间股价创历史新高
- 区间股价创历史新低
- 区间研究报告数量
- 市场关注度
- 问财关注度
- 雪球关注度

**说明**：以上仅列出部分常用指标，完整列表包含150+指标。

---

## 二、极值函数（2个）

**使用频率**：record_high 30次（#29），record_low 8次（#40）

### 2.1 创新高 (RECORD_HIGH)

#### 函数签名
```sql
RECORD_HIGH(table varchar, field varchar, op_cond varchar, calc_cond varchar)
```

#### 参数说明

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| table | VARCHAR | 字段所在表 | `'A股日行情'` |
| field | VARCHAR | 字段名 | `'收盘价:不复权'`, `'收盘价:前复权'` |
| op_cond | VARCHAR | 创新高的观察周期 | `'i_date_exp >=-9;i_date_exp<=0'` （过去10天） |
| calc_cond | VARCHAR | 判断创新高的时间点 | `'i_date_exp=-1'` （昨天） |

#### 返回值

返回1列数据：
- `股票代码` (stkcode) - 只返回满足创新高条件的股票

#### 使用示例

**示例1：昨天收盘价创10日新高**

**问句**：查询昨天收盘价创10日新高的股票

**SQL**：
```sql
WITH table0 AS (
  SELECT
    t1."股票代码"
  FROM table(
    RECORD_HIGH(
      'A股日行情',
      '收盘价:不复权',
      'i_date_exp >=-9;i_date_exp<=0',  -- 过去10天（包括今天）
      'i_date_exp=-1'  -- 昨天创新高
    )
  ) as t1("股票代码")
)
SELECT
  tb_wide.stkcode as "股票代码",
  tb_wide.stkname as "股票简称",
  tb_wide.se001nnw00035807_new as "最新价",
  tb_wide.se001nnw00035814_new as "最新涨跌幅"
FROM table0
LEFT JOIN stock_astock_latest_index as tb_wide
  ON tb_wide."stkcode" = table0."股票代码"
```

**示例2：今日创20日新高**

**SQL**：
```sql
WITH table0 AS (
  SELECT
    t1."股票代码"
  FROM table(
    RECORD_HIGH(
      'A股日行情',
      '收盘价:前复权',
      'i_date_exp >=-19;i_date_exp<=0',  -- 过去20天
      'i_date_exp=0'  -- 今天创新高
    )
  ) as t1("股票代码")
)
SELECT
  tb_wide.stkcode as "股票代码",
  tb_wide.stkname as "股票简称",
  tb_wide.se001nnw00035807_new as "最新价",
  tb_wide.se001nnw00035814_new as "最新涨跌幅"
FROM table0
LEFT JOIN stock_astock_latest_index as tb_wide
  ON tb_wide."stkcode" = table0."股票代码"
```

**要点**：
- `op_cond`：观察周期（过去N天的数据范围）
- `calc_cond`：判断时间点（哪一天创新高）
- 只返回股票代码，不返回具体数值
- 通常用于形态突破、趋势判断

---

### 2.2 创新低 (RECORD_LOW)

#### 函数签名
```sql
RECORD_LOW(table varchar, field varchar, op_cond varchar, calc_cond varchar)
```

#### 参数说明

与 `RECORD_HIGH` 相同，但判断的是创新低。

#### 使用示例

**示例：昨天收盘价创10日新低**

**问句**：查询昨天收盘价创10日新低的股票

**SQL**：
```sql
WITH table0 AS (
  SELECT
    t1."股票代码"
  FROM table(
    RECORD_LOW(
      'A股日行情',
      '收盘价:不复权',
      'i_date_exp >=-9;i_date_exp<=0',  -- 过去10天
      'i_date_exp=-1'  -- 昨天创新低
    )
  ) as t1("股票代码")
)
SELECT
  tb_wide.stkcode as "股票代码",
  tb_wide.stkname as "股票简称",
  tb_wide.se001nnw00035807_new as "最新价",
  tb_wide.se001nnw00035814_new as "最新涨跌幅"
FROM table0
LEFT JOIN stock_astock_latest_index as tb_wide
  ON tb_wide."stkcode" = table0."股票代码"
```

**要点**：
- 用于判断支撑位破位、下跌趋势
- 常与止损策略配合使用

---

### 极值函数应用场景

| 场景 | 函数 | 参数示例 | 说明 |
|------|------|---------|------|
| 突破前高 | RECORD_HIGH | op_cond: 过去20天<br>calc_cond: 今天 | 今日突破20日新高 |
| 跌破支撑 | RECORD_LOW | op_cond: 过去30天<br>calc_cond: 今天 | 今日跌破30日新低 |
| 阶段新高 | RECORD_HIGH | op_cond: 过去60天<br>calc_cond: 近5天 | 近5天内创60日新高 |
| 止损信号 | RECORD_LOW | op_cond: 过去10天<br>calc_cond: 今天 | 今日创10日新低（可能止损） |

---

## 三、增长率与增长值函数（8个）

**使用频率**：<8次（未进入TOP 40）

### 3.1 区间增长值 (INTERVAL_VALUE)

#### 函数签名
```sql
INTERVAL_VALUE(table varchar, field varchar, cond varchar)
```

#### 参数说明

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| table | VARCHAR | 字段所在表（中文表名） | `'A股日行情'`, `'A股财务数据'` |
| field | VARCHAR | 字段名（中文字段名） | `'营业收入'`, `'收盘价:前复权'` |
| cond | VARCHAR | 时间表达式 | `'i_date BETWEEN DATE ''2023-01-01'' AND DATE ''2023-12-31'';i_date_exp=0'` |

#### 返回值

返回2列数据：
1. `股票代码` (stkcode)
2. `calc_value` - 增长值（需要自定义别名）

#### 使用示例

**示例1：2023年营收增长值**

**问句**：计算2023年营业收入增长值

**SQL**：
```sql
WITH table0 AS (
  SELECT
    t1."股票代码",
    t1."calc_value" AS "营业收入增长值[2023]"
  FROM table(
    INTERVAL_VALUE(
      'A股财务数据',
      '营业收入',
      'i_date BETWEEN DATE ''2023-01-01'' AND date_add(''day'', -1, date_add(''year'', 1, DATE ''2023-01-01''));i_date_exp=-1'
    )
  ) as t1("股票代码", "calc_value")
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

**要点**：
- 时间表达式使用 `BETWEEN ... AND ...`
- 日期计算使用 `date_add()` 函数
- 返回列别名：`("股票代码", "calc_value")`

---

### 3.2 区间增长率 (INTERVAL_RATE)

#### 函数签名
```sql
INTERVAL_RATE(table varchar, field varchar, cond varchar)
```

#### 参数说明

与 `INTERVAL_VALUE` 相同，但返回的是增长率（百分比已转换为小数）。

#### 返回值

返回2列数据：
1. `股票代码` (stkcode)
2. `calc_value` - 增长率（小数形式，如 0.5 表示 50%）

#### 使用示例

**示例1：2022年营收增长率大于50%**

**问句**：查询2022年营业收入增长率大于50%的股票

**SQL**：
```sql
WITH table0 AS (
  SELECT
    t1."股票代码",
    t1."calc_value" AS "营业收入增长率[2022]"
  FROM table(
    INTERVAL_RATE(
      'A股财务数据',
      '营业收入',
      'i_date BETWEEN DATE ''2022-01-01'' AND date_add(''day'', -1, date_add(''year'', 1, DATE ''2022-01-01''));i_date_exp=0'
    )
  ) as t1("股票代码", "calc_value")
  WHERE t1."calc_value" > 0.5  -- 50% = 0.5
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

**示例2：本周区间涨跌幅前十**

**问句**：查询本周涨跌幅前10名的股票

**SQL**：
```sql
WITH table0 AS (
  SELECT
    t1."股票代码",
    t1."calc_value" AS "本周涨跌幅"
  FROM table(
    INTERVAL_RATE(
      'A股日行情',
      '收盘价:前复权',
      'i_date BETWEEN date_trunc(''week'', current_date) AND current_date;i_date_exp=0'
    )
  ) as t1("股票代码", "calc_value")
  ORDER BY t1."calc_value" DESC
  LIMIT 10
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
ORDER BY table0."本周涨跌幅" DESC
```

**要点**：
- 使用 `date_trunc('week', current_date)` 获取本周开始日期
- 增长率以小数形式返回（0.5 = 50%）
- CTE内使用ORDER BY + LIMIT筛选TOP N

---

### 3.3 同比增长值 (YOY_VALUE)

#### 函数签名
```sql
YOY_VALUE(table varchar, field varchar, cond varchar)
```

#### 参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| table | 字段所在表 | `'A股财务数据'` |
| field | 字段名 | `'净利润'`, `'营业收入'` |
| cond | 时间表达式 | `'i_date_exp=0'` （当前报告期） |

#### 说明

**同比增长值** = 当期值 - 去年同期值

适用于财务数据的年度对比分析。

#### 使用示例

**示例：净利润同比增长值**

**问句**：查询净利润同比增长值

**SQL**：
```sql
WITH table0 AS (
  SELECT
    t1."股票代码",
    t1."calc_value" AS "净利润同比增长值"
  FROM table(
    YOY_VALUE('A股财务数据', '净利润', 'i_date_exp=0')
  ) as t1("股票代码", "calc_value")
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

---

### 3.4 环比增长值 (QOQ_VALUE)

#### 函数签名
```sql
QOQ_VALUE(table varchar, field varchar, cond varchar)
```

#### 说明

**环比增长值** = 当期值 - 上期值

适用于财务数据的季度对比分析（如Q2与Q1对比）。

#### 使用示例

**示例：净利润环比增长值**

**SQL**：
```sql
WITH table0 AS (
  SELECT
    t1."股票代码",
    t1."calc_value" AS "净利润环比增长值"
  FROM table(
    QOQ_VALUE('A股财务数据', '净利润', 'i_date_exp=0')
  ) as t1("股票代码", "calc_value")
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

---

### 3.5 同比增长率 (YOY_RATE)

#### 函数签名
```sql
YOY_RATE(table varchar, field varchar, cond varchar)
```

#### 说明

**同比增长率** = (当期值 - 去年同期值) / 去年同期值

返回值为小数形式（0.5 = 50%）。

#### 使用示例

**示例：净利润同比增长率**

**SQL**：
```sql
WITH table0 AS (
  SELECT
    t1."股票代码",
    t1."calc_value" AS "净利润同比增长率"
  FROM table(
    YOY_RATE('A股财务数据', '净利润', 'i_date_exp=0')
  ) as t1("股票代码", "calc_value")
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

---

### 3.6 环比增长率 (QOQ_RATE)

#### 函数签名
```sql
QOQ_RATE(table varchar, field varchar, cond varchar)
```

#### 说明

**环比增长率** = (当期值 - 上期值) / 上期值

返回值为小数形式（0.5 = 50%）。

#### 使用示例

**示例：净利润环比增长率**

**SQL**：
```sql
WITH table0 AS (
  SELECT
    t1."股票代码",
    t1."calc_value" AS "净利润环比增长率"
  FROM table(
    QOQ_RATE('A股财务数据', '净利润', 'i_date_exp=0')
  ) as t1("股票代码", "calc_value")
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

---

### 3.7 复合增长值 (CINCV)

#### 函数签名
```sql
CINCV(table varchar, field varchar, cond varchar)
```

#### 说明

**复合增长值**：计算多期复合增长的绝对值。

> **WARNING**: 此函数用法尚未经过生产验证。使用前请先在测试环境确认参数和返回值。

---

### 3.8 复合增长率 (CINCR)

#### 函数签名
```sql
CINCR(table varchar, field varchar, cond varchar)
```

#### 说明

**复合增长率（CAGR）**：Compound Annual Growth Rate

计算公式：CAGR = (期末值 / 期初值)^(1/年数) - 1

> **WARNING**: 此函数用法尚未经过生产验证。使用前请先在测试环境确认参数和返回值。

---

### 增长函数对比表

| 函数 | 计算公式 | 返回类型 | 典型场景 |
|------|---------|---------|---------|
| INTERVAL_VALUE | 期末值 - 期初值 | 绝对值 | 营收增长XXX万元 |
| INTERVAL_RATE | (期末值 - 期初值) / 期初值 | 比率(小数) | 本周涨跌幅XX% |
| YOY_VALUE | 当期值 - 去年同期值 | 绝对值 | 净利润同比增长XXX万元 |
| YOY_RATE | (当期值 - 去年同期值) / 去年同期值 | 比率(小数) | 营收同比增长XX% |
| QOQ_VALUE | 当期值 - 上期值 | 绝对值 | Q2较Q1增长XXX万元 |
| QOQ_RATE | (当期值 - 上期值) / 上期值 | 比率(小数) | 环比增长XX% |
| CINCV | 复合增长绝对值 | 绝对值 | 多年复合增长值 |
| CINCR | 复合年均增长率 | 比率(小数) | 3年CAGR为XX% |

---

## 四、使用场景对比

### 场景1：计算营收增长

| 需求 | 推荐函数 | 原因 |
|------|---------|------|
| 2023年营收增长了多少钱？ | INTERVAL_VALUE | 返回绝对值（单位：元） |
| 2023年营收增长了百分之多少？ | INTERVAL_RATE | 返回增长率（百分比） |
| 今年营收比去年同期增长多少？ | YOY_VALUE 或 YOY_RATE | 自动对比去年同期 |
| Q2营收比Q1增长多少？ | QOQ_VALUE 或 QOQ_RATE | 自动对比上一季度 |

### 场景2：判断突破形态

| 需求 | 推荐函数 | 原因 |
|------|---------|------|
| 今天收盘价创20日新高 | RECORD_HIGH | 专门用于判断新高 |
| 今天收盘价跌破30日新低 | RECORD_LOW | 专门用于判断新低 |
| 近5天内有创60日新高的 | RECORD_HIGH (calc_cond用范围) | 支持范围判断 |

### 场景3：区间统计

| 需求 | 推荐函数 | 原因 |
|------|---------|------|
| 历史最大连续涨停天数 | interval_index | 150+预定义指标 |
| 区间资金流向 | interval_index | 复杂聚合计算 |
| 区间换手率 | interval_index | 日均、累计等多维度 |
| 陆股通区间成本 | interval_index | 特殊业务逻辑 |

---

## 五、注意事项与最佳实践

### 5.1 强制规则

✅ **必须遵守**：

1. 函数调用必须用 `table()` 包装
2. 必须为返回列指定别名
3. 必须通过 LEFT JOIN 关联
4. 时间表达式必须符合日期过滤规则（参考 sql_rules.md）

❌ **禁止操作**：

1. 不能直接SELECT函数（必须通过JOIN）
2. 不能省略别名
3. 不能在时间表达式中使用函数（如 YEAR(i_date)）

### 5.2 时间表达式规范

**正确写法**：
```sql
-- INTERVAL_RATE, YOY_RATE等函数
'i_date BETWEEN DATE ''2023-01-01'' AND DATE ''2023-12-31'';i_date_exp=0'

-- interval_index 函数
'i_date>=DATE ''2023-01-01'';i_date<=DATE ''2023-12-31'';i_date_exp=0'

-- RECORD_HIGH, RECORD_LOW 函数
'i_date_exp >=-19;i_date_exp<=0'  -- op_cond
'i_date_exp=0'  -- calc_cond
```

**错误写法**：
```sql
-- ❌ 使用函数表达式（只会返回最新交易日）
'YEAR(i_date) = 2023'

-- ❌ 使用开区间
'i_date > DATE ''2023-01-01'' AND i_date < DATE ''2023-12-31'''
```

### 5.3 表名和字段名规范

**使用中文名**：
```sql
-- ✅ 正确
INTERVAL_RATE('A股日行情', '营业收入', '...')
INTERVAL_RATE('A股财务数据', '净利润', '...')

-- ❌ 错误（不要使用表的物理名）
INTERVAL_RATE('stock_astock_mkt_daily_trans', 'se001ntd00009415', '...')
```

**如何确认中文表名和字段名**：
- 查看元数据YAML文件中的 `tableName` 和字段的中文别名
- 或者参考 examples.md 中的示例

### 5.4 性能优化

> 通用的"先过滤再JOIN"等优化模式见 `market_analysis_functions.md` 第 4.2 节。
> 统计函数同样适用这些规则，不再重复。

---

## 六、常见错误与调试

### 6.1 常见错误

> 通用的 `table()` 包装、别名等错误模式见 `market_analysis_functions.md` 第 4.3 节。
> 本节仅列出统计函数特有的错误。

**错误1：时间表达式中单引号未转义**
```sql
-- ❌ 错误
'i_date BETWEEN DATE '2023-01-01' AND DATE '2023-12-31''

-- ✅ 正确
'i_date BETWEEN DATE ''2023-01-01'' AND DATE ''2023-12-31'';i_date_exp=0'
```

**错误2：使用了表的物理名**
```sql
-- ❌ 错误
INTERVAL_RATE('stock_astock_mkt_daily_trans', 'se001ntd00009415', '...')

-- ✅ 正确
INTERVAL_RATE('A股日行情', '收盘价:前复权', '...')
```

> 百分比未转换：见 sql_rules.md §4.3

### 6.2 调试技巧

**步骤1：先测试函数返回**

```sql
-- 单独测试函数
SELECT * FROM table(
  INTERVAL_RATE(
    'A股日行情',
    '收盘价:前复权',
    'i_date BETWEEN DATE ''2024-01-01'' AND DATE ''2024-12-31'';i_date_exp=0'
  )
) as t1("股票代码", "calc_value")
LIMIT 10
```

**步骤2：检查时间表达式**

```sql
-- 验证时间范围是否有数据
SELECT COUNT(*), MIN(i_date), MAX(i_date)
FROM stock_astock_mkt_daily_trans
WHERE i_date >= DATE '2024-01-01'
  AND i_date <= DATE '2024-12-31'
  AND i_date_exp = 0
```

**步骤3：添加筛选条件**

```sql
-- 最终查询
WHERE t1."calc_value" > 0.5
ORDER BY t1."calc_value" DESC
```

---

## 七、快速参考

### 函数选择决策树

```
需要计算增长？
├─ 是 → 需要绝对值还是比率？
│       ├─ 绝对值 → 区间？同比？环比？
│       │          ├─ 区间 → INTERVAL_VALUE
│       │          ├─ 同比 → YOY_VALUE
│       │          └─ 环比 → QOQ_VALUE
│       └─ 比率 → 区间？同比？环比？
│                  ├─ 区间 → INTERVAL_RATE
│                  ├─ 同比 → YOY_RATE
│                  └─ 环比 → QOQ_RATE
│
├─ 否 → 需要判断极值？
│       ├─ 创新高 → RECORD_HIGH
│       └─ 创新低 → RECORD_LOW
│
└─ 否 → 需要区间统计指标？
        └─ interval_index（150+预定义指标）
```

### 模板速查

**模板1：增长率/增长值**
```sql
WITH table0 AS (
  SELECT
    t1."股票代码",
    t1."calc_value" AS "指标别名"
  FROM table(
    FUNCTION_NAME('表名', '字段名', '时间表达式')
  ) as t1("股票代码", "calc_value")
)
SELECT ... FROM table0 ...
```

**模板2：创新高/创新低**
```sql
WITH table0 AS (
  SELECT
    t1."股票代码"
  FROM table(
    RECORD_HIGH/RECORD_LOW('表名', '字段名', '观察周期', '判断时点')
  ) as t1("股票代码")
)
SELECT ... FROM table0 ...
```

**模板3：区间指标计算**
```sql
WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    tbbh_gga1."指标名" AS "指标别名"
  FROM stock_astock_mkt_daily_trans as g0
  LEFT JOIN table(
    interval_index('abs_股票领域', '指标名', '时间表达式')
  ) as tbbh_gga1("stkcode", "agg_date", "指标名")
    ON g0."stkcode" = tbbh_gga1."stkcode"
  WHERE g0."i_date_exp" = 0
)
SELECT ... FROM table0 ...
```

---

**版本**：v1.0
**更新日期**：2026-03-02
**适用引擎**：Trino查询引擎扩展函数
