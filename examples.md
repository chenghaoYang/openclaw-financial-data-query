# Few-Shot学习示例集

本文档提供了从简单到复杂的SQL转换示例，用于Few-Shot学习。

---

## 一、简单查询（Level 1）

### 示例1：指定股票查询

**问句**：同花顺

**SQL**：
```sql
WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码"
  FROM
    stock_astock_basic_info as g0
  WHERE
    g0."stkname" = '同花顺'
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
- 单表查询基本信息
- 简单的名称匹配
- 标准的固定输出字段

---

### 示例2：当前交易日涨停

**问句**：今天涨停的股票

**SQL**：
```sql
WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    g0."se001std00016521" AS "涨停[20240829]",
    g0."se001std00009517" AS "首次涨停时间",
    g0."se001std00009518" AS "最终涨停时间",
    g0."se001td00009526" AS "涨停原因",
    g0."i_date" AS "交易日期"
  FROM
    stock_astock_mkt_daily_trans as g0
  WHERE
    g0."i_date_exp" = 0
    AND g0."se001std00016521"
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
- 使用日行情表
- `i_date_exp = 0` 表示当前交易日
- 布尔字段直接使用，不加 `= true`
- 时间字段标注日期

---

### 示例3：连续涨停天数筛选

**问句**：连续两天涨停，股价低于5元

**SQL**：
```sql
WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    g0."se001td00009595" AS "连续涨停天数",
    g0."se001ntd00009415" AS "收盘价[20250929]",
    g0."se001ntd00009385" AS "开盘价[20250929]",
    g0."se001ntd00009395" AS "最高价[20250929]",
    g0."se001ntd00009405" AS "最低价[20250929]",
    g0."i_date" AS "交易日期"
  FROM
    stock_astock_mkt_daily_trans as g0
  WHERE
    g0."se001td00009595" = 2
    AND g0."i_date_exp" = 0
    AND g0."se001ntd00009415" < 5
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
- 多个AND条件组合
- 数值字段直接比较

---

## 二、中等复杂度（Level 2）

### 示例4：多表关联查询

**问句**：首板涨停，非新股次新股，主板

**SQL**：
```sql
WITH
table1 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    g0."se001btd00016506" AS "首板涨停[20250929]",
    g0."se001std00016477" AS "近5个交易日上市[20250929]",
    g0."se001std00016476" AS "次新股[20250929]",
    g0."i_date" AS "交易日期"
  FROM
    stock_astock_mkt_daily_trans as g0
  WHERE
    g0."se001btd00016506"
    AND g0."i_date_exp" = 0
    AND g0."se001std00016477" = false
    AND g0."se001std00016476" = false
),
table2 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    g0."se001snt00015631" AS "上市板块"
  FROM
    stock_astock_basic_info as g0
  WHERE
    g0."se001snt00015631" = '主板'
)
SELECT
  tb_wide.stkcode as "股票代码",
  tb_wide.stkname as "股票简称",
  tb_wide.se001nnw00035807_new as "最新价",
  tb_wide.se001nnw00035814_new as "最新涨跌幅",
  table1.*,
  table2.*
FROM table1
JOIN table2 ON table1."股票代码" = table2."股票代码"
LEFT JOIN stock_astock_latest_index as tb_wide
  ON tb_wide."stkcode" = table1."股票代码"
```

**要点**：
- 多个CTE分别处理不同的筛选条件
- 使用JOIN实现交集
- 行情表（table1）和基本信息表（table2）的组合

---

### 示例5：RSI 超买筛选 (Level 2)

> 完整 SQL 示例见 `functions/market_analysis_functions.md` 第 1.5 节示例 4。

---

### 示例6：概念筛选

**问句**：属于机器人概念的股票

**SQL**：
```sql
WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    g0."se001snt00015648" AS "所属概念",
    g1."纳入概念原因" AS "纳入概念原因",
    g0."se001snt00015631" AS "上市板块",
    g0."se001snt00015630" AS "上市地点",
    g0."se001snt00015606" AS "所属同花顺行业"
  FROM
    stock_astock_basic_info as g0
  LEFT JOIN (
    SELECT
      g2."stkcode" AS "股票代码",
      array_agg(concat('【', g2."se001snd00011235", '】',
        (CASE WHEN g2."se001snd00011236" is null THEN '' ELSE g2."se001snd00011236" END))
      ) as "纳入概念原因"
    FROM stock_astock_concept as g2
    WHERE g2."se001snd00011235" IN ('机器人概念')
    GROUP BY g2."stkcode"
  ) as g1 ON g0."stkcode" = g1."股票代码"
  WHERE
    contains(g0."se001snt00015648", '机器人概念')
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
- 使用`contains()`函数匹配概念
- 关联概念原因表获取详细信息
- 使用`array_agg`和`concat`合并多个原因

---

## 三、复杂查询（Level 3）

### 示例7：时间序列查询（涨停+次日上涨）

**问句**：近1个月有出现过涨停，且第二天上涨的股票

**SQL**：
```sql
WITH
-- 子查询1：获取近30个交易日内涨停的股票及其涨停日期
table_limit_up AS (
  SELECT
    g0."stkcode" AS "股票代码",
    g0."stkname" AS "股票简称",
    g0."i_date" AS "涨停日期",
    g0."se001std00009517" AS "首次涨停时间",
    g0."se001std00009518" AS "最终涨停时间",
    g0."se001td00009526" AS "涨停原因"
  FROM
    stock_astock_mkt_daily_trans AS g0
  WHERE
    g0."i_date_exp" >= -30
    AND g0."i_date_exp" <= 0
    AND g0."se001std00016521"
),

-- 子查询2：获取涨停次日的行情，筛选次日上涨的股票
table_next_day_rise AS (
  SELECT DISTINCT
    t1."股票代码",
    t1."股票简称",
    t1."涨停日期",
    t1."首次涨停时间",
    t1."最终涨停时间",
    t1."涨停原因",
    g1."i_date" AS "次日日期",
    g1."se001ntd00009433" AS "次日涨跌幅"
  FROM
    table_limit_up AS t1
  INNER JOIN
    stock_astock_mkt_daily_trans AS g1
    ON t1."股票代码" = g1."stkcode"
    AND g1."i_date" = date_add('day', 1, t1."涨停日期")
  WHERE
    g1."se001ntd00009433" > 0
)

-- 最终结果：去重后返回符合条件的股票
SELECT
  tb_wide.stkcode AS "股票代码",
  tb_wide.stkname AS "股票简称",
  tb_wide.se001nnw00035807_new AS "最新价",
  tb_wide.se001nnw00035814_new AS "最新涨跌幅",
  table_next_day_rise."涨停日期",
  table_next_day_rise."首次涨停时间",
  table_next_day_rise."最终涨停时间",
  table_next_day_rise."涨停原因",
  table_next_day_rise."次日日期",
  table_next_day_rise."次日涨跌幅"
FROM
  table_next_day_rise
LEFT JOIN
  stock_astock_latest_index AS tb_wide
  ON tb_wide."stkcode" = table_next_day_rise."股票代码"
ORDER BY
  table_next_day_rise."涨停日期" DESC,
  table_next_day_rise."次日涨跌幅" DESC
```

**要点**：
- 使用多级CTE分步构建逻辑
- 使用`date_add()`函数计算次日日期
- INNER JOIN关联次日数据
- 使用DISTINCT去重
- 最终结果排序

---

### 示例8：多个均线查询 (Level 3)

> 完整 SQL 示例见 `functions/market_analysis_functions.md` 第 1.5 节示例 2。

---

### 示例9：均线上穿形态 (Level 3)

> 完整 SQL 示例见 `functions/market_analysis_functions.md` 第 3.5 节示例 1。

---

### 示例10：复合条件——技术形态组合 (Level 3)

> 完整 SQL 示例见 `functions/market_analysis_functions.md` 第 3.5 节示例 2。

---

## 四、特殊场景

### 示例11：成分股筛选

**问句**：中证500成分股且MACD买入信号且市盈率>0

**SQL**：
```sql
WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    g0."f2f#macd#买入信号" AS "macd买入信号[20250929]",
    g0."se001ntd00035727" AS "市盈率[20250929]",
    g0."i_date" AS "交易日期"
  FROM
    stock_astock_mkt_daily_trans as g0
  WHERE
    g0."stkcode" IN (
      SELECT
        g1."ix999snd00037225" AS "成分代码"
      FROM
        index_constituents as g1
      WHERE
        g1."stkname" = '中证500'
        AND g1."i_date_exp" = 0
    )
    AND g0."i_date_exp" = 0
    AND g0."f2f#macd#买入信号"
    AND g0."se001ntd00035727" > 0
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
- 使用IN子查询筛选成分股
- 成分股表：`index_constituents`
- 成分代码字段：`ix999snd00037225`

---

### 示例12：排序和TOP N

**问句**：机构持仓占比最高的10家公司

**SQL**：
```sql
WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    g0."se001nqt00019664" AS "机构持股占流通股比例[20241231]",
    g0."i_date" AS "报告期截止日"
  FROM
    stock_astock_institutional_stat as g0
  WHERE
    g0."i_date" = DATE '2024-12-31'
    AND g0."i_date_exp" = 0
  ORDER BY
    g0."se001nqt00019664" DESC
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
ORDER BY
  table0."机构持股占流通股比例[20241231]" DESC
```

**要点**：
- CTE内使用ORDER BY + LIMIT实现TOP N
- 最终查询也需要ORDER BY保持排序
- 降序：DESC，升序：ASC

