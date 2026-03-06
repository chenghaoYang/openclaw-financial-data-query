-- ============================================================================
-- SQL模板: 简单查询
-- ============================================================================
-- 适用场景:
--   - 单表查询 + 简单筛选条件
--   - 不涉及多表JOIN
--   - 不涉及复杂聚合
--
-- 示例场景:
--   1. 查询今天涨停的股票
--   2. 市值大于100亿的公司
--   3. 某个行业的所有股票
--   4. 特定概念板块的股票
--
-- 使用说明:
--   将{{占位符}}替换为实际值
-- ============================================================================

WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    g0."stkname" AS "股票简称",
    -- ========== 自定义字段 ==========
    -- 替换为查询需要的具体字段
    -- 示例:
    -- g0."se001std00016521" AS "涨停[{{DATE}}]",
    -- g0."se001td00009575" AS "总市值[{{DATE}}]",
    -- g0."se001snt00015648" AS "所属概念",
    {{CUSTOM_FIELDS}}
    -- ===============================
    g0."i_date" AS "交易日期"
  FROM {{TABLE_NAME}} as g0
  WHERE
    -- ========== 日期条件 ==========
    -- 选项1: 最新交易日
    g0."i_date_exp" = 0
    -- 选项2: 具体日期
    -- g0."i_date" = DATE '{{YYYY-MM-DD}}'
    -- 选项3: 日期范围
    -- (g0."i_date" >= DATE '{{START_DATE}}'
    --  AND g0."i_date" <= DATE '{{END_DATE}}'
    --  AND g0."i_date_exp" = 0)
    -- ===============================

    -- ========== 筛选条件 ==========
    -- 替换为实际筛选条件
    -- 示例:
    -- AND g0."se001std00016521"  -- 涨停
    -- AND g0."se001td00009575" > 10000000000  -- 市值>100亿
    -- AND contains(g0."se001snt00015648", '人工智能')  -- 包含概念
    {{FILTER_CONDITIONS}}
    -- ===============================
)
SELECT
  -- ========== 固定输出字段（必须包含） ==========
  tb_wide.stkcode as "股票代码",
  tb_wide.stkname as "股票简称",
  tb_wide.se001nnw00035807_new as "最新价",
  tb_wide.se001nnw00035814_new as "最新涨跌幅",
  -- ============================================
  table0.*  -- CTE中的所有其他字段
FROM table0
LEFT JOIN stock_astock_latest_index as tb_wide
  ON tb_wide."stkcode" = table0."股票代码"

-- ========== 可选：排序和限制 ==========
-- ORDER BY table0."{{SORT_FIELD}}" DESC
-- LIMIT {{LIMIT_NUMBER}}
-- =======================================


-- ============================================================================
-- 完整示例: 查询今天涨停的股票
-- ============================================================================

WITH table0 AS (
  SELECT
    g0."stkcode" AS "股票代码",
    g0."stkname" AS "股票简称",
    g0."se001std00016521" AS "涨停[20241024]",
    g0."se001std00009517" AS "首次涨停时间",
    g0."se001std00009518" AS "最终涨停时间",
    g0."se001td00009526" AS "涨停原因",
    g0."se001td00009595" AS "连续涨停天数",
    g0."i_date" AS "交易日期"
  FROM stock_astock_mkt_daily_trans as g0
  WHERE g0."i_date_exp" = 0
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
