-- ============================================================================
-- SQL模板: 复杂查询（多表关联）
-- ============================================================================
-- 适用场景:
--   - 多表JOIN查询
--   - 需要关联不同数据源
--   - 组合多个筛选条件
--
-- 示例场景:
--   1. 对比股票与大盘表现
--   2. 关联财务数据和行情数据
--   3. 查询指数成分股的行情
--   4. 多个时间维度的数据对比
--
-- 使用说明:
--   - 根据需要使用table1、table2、table3...
--   - 每个CTE负责一个独立的查询逻辑
--   - 最后通过JOIN组合结果
-- ============================================================================

WITH
-- ========== CTE 1: 第一个查询逻辑 ==========
table1 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    -- 第一个查询的字段
    {{TABLE1_FIELDS}}
    g0."i_date" AS "交易日期"
  FROM {{TABLE1_NAME}} as g0
  WHERE
    {{TABLE1_CONDITIONS}}
),

-- ========== CTE 2: 第二个查询逻辑 ==========
table2 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    -- 第二个查询的字段
    {{TABLE2_FIELDS}}
    g0."i_date" AS "交易日期"
  FROM {{TABLE2_NAME}} as g0
  WHERE
    {{TABLE2_CONDITIONS}}
),

-- ========== CTE 3: 第三个查询逻辑（可选） ==========
table3 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    -- 第三个查询的字段
    {{TABLE3_FIELDS}}
    g0."i_date" AS "交易日期"
  FROM {{TABLE3_NAME}} as g0
  WHERE
    {{TABLE3_CONDITIONS}}
)

-- ========== 最终SELECT：组合所有CTE ==========
SELECT
  tb_wide.stkcode as "股票代码",
  tb_wide.stkname as "股票简称",
  tb_wide.se001nnw00035807_new as "最新价",
  tb_wide.se001nnw00035814_new as "最新涨跌幅",
  table1.*,
  table2.*
  -- table3.*  -- 如果使用table3
FROM table1
INNER JOIN table2 ON table1."股票代码" = table2."股票代码"
-- LEFT JOIN table3 ON table1."股票代码" = table3."股票代码"  -- 如果使用table3
LEFT JOIN stock_astock_latest_index as tb_wide
  ON tb_wide."stkcode" = table1."股票代码"

-- ========== 可选：最终筛选和排序 ==========
-- WHERE ...
-- ORDER BY ...
-- LIMIT ...
-- ===========================================


-- ============================================================================
-- 完整示例: 查询过去30天跑输大盘的股票
-- ============================================================================

WITH
-- 计算每只股票30天涨幅
table1 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    -- 注意: 此公式计算区间振幅而非实际涨跌幅。如需精确涨跌幅请使用 interval_index 函数
    (max(g0."se001ntd00009415") - min(g0."se001ntd00009415")) / min(g0."se001ntd00009415") as "涨幅_30天"
  FROM stock_astock_mkt_daily_trans as g0
  WHERE g0."i_date_exp" >= -30
    AND g0."i_date_exp" <= 0
  GROUP BY g0."stkcode"
),

-- 计算大盘30天涨幅
table2 AS (
  SELECT
    -- 注意: 此公式计算区间振幅而非实际涨跌幅。如需精确涨跌幅请使用 interval_index 函数
    (max(g0."ix999ntd00037231") - min(g0."ix999ntd00037231")) / min(g0."ix999ntd00037231") as "大盘涨幅_30天"
  FROM index_mkt_daily_trans as g0
  WHERE g0."stkcode" = '000001.SH'  -- 上证指数
    AND g0."i_date_exp" >= -30
    AND g0."i_date_exp" <= 0
)

SELECT
  tb_wide.stkcode as "股票代码",
  tb_wide.stkname as "股票简称",
  tb_wide.se001nnw00035807_new as "最新价",
  tb_wide.se001nnw00035814_new as "最新涨跌幅",
  table1."涨幅_30天",
  table2."大盘涨幅_30天"
FROM table1
CROSS JOIN table2
LEFT JOIN stock_astock_latest_index as tb_wide
  ON tb_wide."stkcode" = table1."股票代码"
WHERE table1."涨幅_30天" < table2."大盘涨幅_30天"
ORDER BY table1."涨幅_30天" ASC



-- ============================================================================
-- 完整示例2: 中证500成分股且MACD买入信号
-- ============================================================================

WITH
-- 成分股列表
table1 AS (
  SELECT
    g0."ix999snd00037225" AS "股票代码"
  FROM index_constituents as g0
  WHERE g0."stkname" = '中证500'
),

-- MACD买入信号
table2 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    g0."f2f#macd#买入信号" AS "macd买入信号[20241024]",
    g0."se001ntd00035727" AS "市盈率[20241024]",
    g0."i_date" AS "交易日期"
  FROM stock_astock_mkt_daily_trans as g0
  WHERE g0."i_date_exp" = 0
    AND g0."f2f#macd#买入信号"
    AND g0."se001ntd00035727" > 0
)

SELECT
  tb_wide.stkcode as "股票代码",
  tb_wide.stkname as "股票简称",
  tb_wide.se001nnw00035807_new as "最新价",
  tb_wide.se001nnw00035814_new as "最新涨跌幅",
  table2.*
FROM table1
INNER JOIN table2 ON table1."股票代码" = table2."股票代码"
LEFT JOIN stock_astock_latest_index as tb_wide
  ON tb_wide."stkcode" = table1."股票代码"
