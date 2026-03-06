-- ============================================================================
-- SQL模板: 时间区间聚合查询
-- ============================================================================
-- 适用场景:
--   - 时间范围内的数据聚合
--   - 使用GROUP BY分组统计
--   - 计算count、sum、max、min、avg等
--
-- 示例场景:
--   1. 计算过去30天涨幅
--   2. 统计连续上涨天数
--   3. 查询某时间段的最高/最低价
--   4. 计算区间振幅、换手率等
--
-- 使用说明:
--   - GROUP BY通常按stkcode分组
--   - 可使用聚合函数: count, sum, max, min, avg
--   - 可使用HAVING进行聚合后筛选
--   - 支持使用interval_index等自定义函数
-- ============================================================================

WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",

    -- ========== 聚合字段示例 ==========
    -- 计数类
    -- count(*) AS "交易天数[{{START_DATE}}-{{END_DATE}}]",
    -- count(*) filter(where g0."se001std00016521") AS "涨停天数[{{START_DATE}}-{{END_DATE}}]",

    -- 求和类
    -- sum(g0."se001ntd00009443") AS "累计成交量[{{START_DATE}}-{{END_DATE}}]",
    -- sum(g0."se001ntd00009444") AS "累计成交额[{{START_DATE}}-{{END_DATE}}]",

    -- 最大/最小值
    -- max(g0."se001ntd00009415") AS "最高收盘价[{{START_DATE}}-{{END_DATE}}]",
    -- min(g0."se001ntd00009415") AS "最低收盘价[{{START_DATE}}-{{END_DATE}}]",
    -- max(g0."se001ntd00009433") AS "最大涨跌幅[{{START_DATE}}-{{END_DATE}}]",

    -- 平均值
    -- avg(g0."se001ntd00009443") AS "平均成交量[{{START_DATE}}-{{END_DATE}}]",

    -- 计算涨幅
    -- (max(g0."se001ntd00009415") - min(g0."se001ntd00009415")) /
    --   min(g0."se001ntd00009415") AS "区间涨幅[{{START_DATE}}-{{END_DATE}}]",

    {{AGGREGATION_FIELDS}}
    -- ==================================

    -- 可选：使用自定义区间函数
    -- tbbh_gga1."振幅" AS "振幅[{{START_DATE}}-{{END_DATE}}]"

  FROM {{TABLE_NAME}} as g0

  -- ========== 可选：JOIN自定义区间函数 ==========
  -- LEFT JOIN table(interval_index(
  --   'abs_股票领域',
  --   '区间振幅',
  --   'i_date>=DATE ''{{START_DATE}}'';i_date<=DATE ''{{END_DATE}}'';i_date_exp=0'
  -- )) as tbbh_gga1("stkcode", "agg_date", "振幅")
  --   ON g0."stkcode" = tbbh_gga1."stkcode"
  -- =============================================

  WHERE
    -- ========== 时间范围条件 ==========
    (g0."i_date" >= DATE '{{START_DATE}}'
     AND g0."i_date" <= DATE '{{END_DATE}}'
     AND g0."i_date_exp" = 0)
    -- ==================================

    -- ========== 其他筛选条件 ==========
    {{FILTER_CONDITIONS}}
    -- ==================================

  GROUP BY
    g0."stkcode"
    -- 如果使用了自定义函数，可能需要添加:
    -- ,tbbh_gga1."stkcode", tbbh_gga1."振幅"

  -- ========== HAVING子句（聚合后筛选） ==========
  -- HAVING count(*) filter(where g0."se001std00016521") >= 3  -- 至少3个涨停
  -- HAVING max(g0."se001ntd00009415") > 100  -- 最高价>100
  {{HAVING_CLAUSE}}
  -- ============================================
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

-- ========== 可选：排序和限制 ==========
-- ORDER BY table0."{{SORT_FIELD}}" DESC
-- LIMIT {{LIMIT_NUMBER}}
-- =======================================


-- ============================================================================
-- 完整示例1: 过去30天至少涨停3次的股票
-- ============================================================================

WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    count(*) filter(where g0."se001std00016521") AS "涨停天数[20240925-20241024]",
    max(g0."se001ntd00009415") AS "最高收盘价[20240925-20241024]",
    min(g0."se001ntd00009415") AS "最低收盘价[20240925-20241024]",
    (max(g0."se001ntd00009415") - min(g0."se001ntd00009415")) /
      min(g0."se001ntd00009415") AS "区间涨幅[20240925-20241024]"
  FROM stock_astock_mkt_daily_trans as g0
  WHERE (g0."i_date" >= DATE '2024-09-25'
     AND g0."i_date" <= DATE '2024-10-24'
     AND g0."i_date_exp" = 0)
  GROUP BY g0."stkcode"
  HAVING count(*) filter(where g0."se001std00016521") >= 3
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
ORDER BY table0."涨停天数[20240925-20241024]" DESC



-- ============================================================================
-- 完整示例2: 使用interval_index函数查询区间振幅
-- ============================================================================

WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    max(tbbh_gga1."振幅") as "振幅[20241114-20241209]",
    sum(g0."se001td00009590") AS "累计换手率[20241114-20241209]"
  FROM stock_astock_mkt_daily_trans as g0
  LEFT JOIN table(interval_index(
    'abs_股票领域',
    '区间振幅',
    'i_date>=DATE ''2024-11-14'';i_date<=DATE ''2024-12-09'';i_date_exp=0'
  )) as tbbh_gga1("stkcode", "agg_date", "振幅")
    ON g0."stkcode" = tbbh_gga1."stkcode"
  WHERE (g0."i_date" >= DATE '2024-11-14'
     AND g0."i_date" <= DATE '2024-12-09'
     AND g0."i_date_exp" = 0)
  GROUP BY g0."stkcode"
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

