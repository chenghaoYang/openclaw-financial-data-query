# SQL转换核心规则手册

## 一、基础架构规则

### 1.1 CTE结构（WITH语句）

**强制规则**：

- 所有SQL必须使用CTE结构（WITH语句）组织查询逻辑
- 简单查询使用 `WITH table0 AS (...)`
- 复杂查询使用 `WITH table1 AS (...), table2 AS (...), table3 AS (...)`
- CTE命名规范：`table0`, `table1`, `table2`, ...（按序递增）

**示例模式**：

```sql
-- 单表查询
WITH table0 AS (
  SELECT ...
  FROM stock_astock_mkt_daily_trans as g0
  WHERE ...
)
SELECT ... FROM table0 LEFT JOIN stock_astock_latest_index ...

-- 多表关联
WITH
table1 AS (...),  -- 第一个筛选条件
table2 AS (...),  -- 第二个筛选条件
table3 AS (...)   -- 第三个筛选条件
SELECT ... FROM table1
JOIN table2 ON ...
JOIN table3 ON ...
```

### 1.2 表别名规范

**强制规则**：

- 主表统一使用别名 `g0`
- 辅助表使用 `g1`, `g2`, `g3` ... 递增
- 技术指标表使用 `tbbh_index1`, `tbbh_index2` ...
- 聚合区间表使用 `tbbh_gga1`, `tbbh_gga2` ...
- 最新行情表固定使用 `tb_wide`

### 1.3 固定输出字段

**强制规则**：
所有查询的SELECT必须包含以下固定字段（顺序不可变）：

```sql
SELECT
  tb_wide.stkcode as "股票代码",
  tb_wide.stkname as "股票简称",
  tb_wide.se001nnw00035807_new as "最新价",
  tb_wide.se001nnw00035814_new as "最新涨跌幅",
  table0.*  -- 或 table1.*, table2.*, ...
FROM ...
LEFT JOIN stock_astock_latest_index as tb_wide
  ON tb_wide."stkcode" = table0."股票代码"
```

## 二、字段命名规则

### 2.1 字段别名格式

**强制规则**：

1. **双引号包裹**：所有字段别名必须使用双引号包裹，无论是中文还是英文
   - ✅ 正确：`AS "股票代码"`, `AS "close_price"`, `AS "Price"`
   - ❌ 错误：`AS 股票代码`, `AS close_price`, `AS 'Price'`
2. **中文字段名**：所有字段必须有中文别名
3. **时间标注格式**：带时间属性的字段必须标注日期
   - 格式：`字段名[YYYYMMDD]`
   - 示例：`"涨跌幅[20241209]"`, `"收盘价[20231231]"`
4. **区间标注格式**：区间统计字段
   - 格式：`字段名[开始日期-结束日期]`
   - 示例：`"振幅[20221114-20221209]"`

**字段别名示例**：

```sql
g0."se001ntd00009433" AS "涨跌幅[20250929]"
g0."se001std00016521" AS "涨停[20250929]"
g0."i_date" AS "交易日期"
max(g0."se001ntd00009447") as "振幅[20240823-20240829]"
```

### 2.2 保留字段

**强制规则**：
以下字段必须在查询中保留：

- `i_date` → 始终别名为 `"交易日期"` 或 `"报告期截止日"`
- `stkcode` → 始终别名为 `"股票代码"`
- `stkname` → 始终别名为 `"股票简称"`

### 2.3 股票代码格式规范

**强制规则**：

所有表中存储的股票代码格式统一为：`代码.市场后缀`

| 市场 | 后缀 | 示例 | 说明 |
|------|------|------|------|
| 上海A股 | `.SH` | `600460.SH` | 上交所主板 |
| 深圳A股 | `.SZ` | `301077.SZ` | 深交所（含主板/创业板/中小板） |
| 香港股市 | `.HK` | `0700.HK` | 港交所 |
| 美国股市 | `.O` | `NVDA.O` | 纳斯达克/纽交所 |

**示例**：
```sql
-- 查询指定股票
WHERE g0."stkcode" = '600460.SH'  -- 上海A股
WHERE g0."stkcode" = '301077.SZ'  -- 深圳A股
WHERE g0."stkcode" = '0700.HK'    -- 港股
WHERE g0."stkcode" = 'NVDA.O'     -- 美股
```

### 2.4 公式字段引用规则（f2f 语法）

**强制规则**：

行情形态和行情指标信号类字段使用特殊的 `f2f` 前缀引用，**不能**使用原始的 `se001xxx` 编码。

**语法格式**：

1. **行情形态**（BOOLEAN，K线/量价形态）：
   ```sql
   -- 格式：f2f##<形态中文名>
   g0."f2f##长上影线"
   g0."f2f##十字星"
   g0."f2f##放量假阴线"
   ```

2. **行情指标信号**（BOOLEAN，技术指标的买卖信号）：
   ```sql
   -- 格式：f2f#<指标名>#<信号名>
   g0."f2f#macd#买入信号"
   g0."f2f#kdj#金叉"
   g0."f2f#boll#突破上轨"
   ```

3. **行情指标值**（DOUBLE，指标数值本身，如macd值）：
   ```sql
   -- 使用标准 columnName
   g0."se001ntd00016223"
   ```

**判断方法**：召回结果的 `sql_column_ref` 已预计算正确引用，直接使用即可。

**常见指标名**：macd, kdj, cci, boll, rsi, sar, wr, obv, bbi, dma, emv, skdj, lwr, 收盘价

**常见信号名**：买入信号, 卖出信号, 金叉, 死叉, 即将金叉, 底背离, 顶背离, 低位, 高位, 超卖, 翻红, 红柱放大, 绿柱缩短, 开口张开, 开口缩小, 突破上轨, 突破下轨, 突破中轨

> **注意**：f2f 字段均为 BOOLEAN 类型，在 WHERE 中直接使用（不加 `= true`），如：`WHERE g0."f2f##长上影线"`

**常见错误**：
```sql
-- ❌ 错误：使用 columnName 引用形态字段 → "指标配置不存在"
WHERE g0."se001ntd00017042"

-- ✅ 正确：使用 f2f## 引用
WHERE g0."f2f##长上影线"
```

## 三、时间处理规范

### 3.1 i_date_exp（时间偏移）

**强制规则**：
1. **当前交易日**：`i_date_exp = 0`
2. **近N个交易日**：`i_date_exp >= -N and i_date_exp <= 0`
   - 近1个月：`i_date_exp >= -30 and i_date_exp <= 0`
   - 近3个月：`i_date_exp >= -90 and i_date_exp <= 0`
3. **单边区间**：只支持右闭区间
   - ✅ 正确：`i_date_exp >= -10` （自动补充 `and i_date_exp <= 0`）
   - ❌ 错误：`i_date_exp <= 0` （不支持左无限）

### 3.2 i_date（具体日期）

**强制规则**：
1. **DATE类型**：使用 `DATE 'YYYY-MM-DD'` 格式
   ```sql
   g0."i_date" = DATE '2024-08-29'
   g0."i_date" >= DATE '2024-01-01' and g0."i_date" <= DATE '2024-12-31'
   ```

2. **TIMESTAMP类型**：用于分钟级数据
   ```sql
   g0."i_date" = TIMESTAMP '2024-08-29 14:30:00'
   g0."i_date" >= TIMESTAMP '2024-08-29 14:30' and g0."i_date" <= TIMESTAMP '2024-08-29 15:00'
   ```

3. **时间范围**：仅支持闭区间（`>=` 和 `<=`），不支持开区间（`>` 和 `<`）。这是数据平台的优化要求，使用开区间可能导致查询性能下降或结果不准确。
   - ✅ 正确：`i_date >= DATE '2024-01-01' and i_date <= DATE '2024-12-31'`
   - ❌ 错误：`i_date > DATE '2024-01-01' and i_date < DATE '2024-12-31'` （不支持开区间）

4. **⚠️ 关键限制（CRITICAL）**：时间序列表必须传有效的 `i_date` 过滤

   **适用**：所有时间序列表（`TRADE_DAILY`、`TRADE_MINUTE` 等），不包括基本信息表（`NO_TIME`）

   **有效的 i_date 过滤**：
   - ✅ `i_date >= DATE '2023-01-01' and i_date <= DATE '2025-12-31'`
   - ✅ `i_date = DATE '2024-08-29'`
   - ❌ `YEAR(i_date) IN (2023, 2024)` （函数表达式无效，只返回最新交易日）

   **按年份筛选的正确做法**：
   ```sql
   WHERE g0."i_date" >= DATE '2023-01-01' AND g0."i_date" <= DATE '2025-12-31'  -- WHERE 用日期范围
   GROUP BY EXTRACT(YEAR FROM g0."i_date")  -- GROUP BY 可以用函数
   ```

### 3.3 日期计算函数

**可用函数**：
- `date_add('day', N, date)` - 日期加N天
- `date_add('month', N, date)` - 日期加N月
- `date_add('year', N, date)` - 日期加N年

**示例**：
```sql
-- 涨停的第二天
g1."i_date" = date_add('day', 1, t1."涨停日期")

-- 一年后的前一天
i_date <= date_add('day', -1, date_add('year', 1, DATE '2022-01-01'))
```

### 3.4 时间搭配规则

**强制规则**：
- `i_date` 范围边界和 `i_date_exp` 范围边界**不能混用**（即不能用一个做左边界、另一个做右边界）
- `i_date_exp = 0`（等值条件，非范围）**可以**作为补充过滤条件与 `i_date` 范围搭配使用，这是标准模式
- ✅ 正确：`i_date >= DATE '2024-01-01' and i_date <= DATE '2024-12-31'`
- ✅ 正确：`i_date_exp >= -30 and i_date_exp <= 0`
- ✅ 正确：`i_date >= DATE '2024-01-01' and i_date <= DATE '2024-12-31' and i_date_exp = 0` （i_date 定范围，i_date_exp = 0 补充过滤当前交易日）
- ❌ 错误：`i_date >= DATE '2024-01-01' and i_date_exp <= 0` （混用两套范围边界）

## 四、筛选条件规则

### 4.1 布尔类型字段

**强制规则**：
- 直接使用字段名（不需要 `= true`）
- 否定使用 `= false` （不使用 `NOT`）

**示例**：
```sql
-- 正确写法
WHERE g0."se001std00016521"  -- 涨停
WHERE g0."se001std00016477" = false  -- 非新股

-- 错误写法
WHERE g0."se001std00016521" = true  -- 冗余
WHERE NOT g0."se001std00016477"  -- 不推荐
```

### 4.2 文本匹配

**强制规则**：
1. **包含匹配**：使用 `contains()`
   ```sql
   WHERE contains(g0."se001snt00015648", '机器人')
   WHERE contains(g0."se001ont00065569", '北证') = false
   ```

2. **模糊匹配**：使用 `LIKE`
   ```sql
   WHERE g0."stkname" not like '%st%'  -- 排除ST股票
   WHERE g0."stkcode" LIKE '%88'  -- 股票代码以88结尾
   WHERE g0."i_rpt" LIKE '%年报'  -- 年报数据
   ```

3. **精确匹配**：使用 `=` 或 `IN`
   ```sql
   WHERE g0."se001snt00015631" = '主板'
   WHERE g0."stkcode" = '000001.SZ'
   WHERE g0."se001snt00015631" IN ('主板', '科创板')
   ```

### 4.3 数值比较

**强制规则**：
1. **百分比转换**：涨跌幅等字段已转换为小数
   ```sql
   -- 涨跌幅 > 5% 应写为
   WHERE g0."se001ntd00009433" > 0.05

   -- 机构持股比例 >= 10% 应写为
   WHERE g0."se001nqt00019664" >= 0.1
   ```

2. **区间比较**：使用 `BETWEEN AND`
   ```sql
   WHERE g0."se001ntd00009415" BETWEEN 5 AND 6  -- 股价在5-6元
   ```

3. **字段比较**：技术指标比较
   ```sql
   WHERE g0."se001ntd00009405" < tbbh_index1."ma55"  -- 最低价 < 55日均线
   WHERE g0."se001ntd00009415" > tbbh_index1."ma55"  -- 收盘价 > 55日均线
   ```

### 4.4 多条件组合

**强制规则**：
1. **AND优先**：条件平级使用AND
   ```sql
   WHERE g0."se001std00016521"  -- 涨停
     AND g0."se001std00016477" = false  -- 非新股
     AND g0."stkname" not like '%st%'  -- 非ST
   ```

2. **OR使用括号**：多个OR条件必须用括号
   ```sql
   WHERE (g0."stkcode" = '300007.SZ' OR g0."stkcode" = '300585.SZ' OR g0."stkcode" = '300757.SZ')
   ```

3. **UNION场景**：复杂OR逻辑可拆分为UNION
   ```sql
   (SELECT ... WHERE contains(g0."se001snt00015647", '上证A股'))
   UNION
   (SELECT ... WHERE contains(g0."se001snt00015647", '深证A股'))
   ```

## 五、JOIN规则

### 5.1 JOIN类型选择

**强制规则**：
1. **LEFT JOIN**：用于关联最新行情表
   ```sql
   LEFT JOIN stock_astock_latest_index as tb_wide
     ON tb_wide."stkcode" = table0."股票代码"
   ```

2. **INNER JOIN / JOIN**：用于多个筛选条件的交集
   ```sql
   FROM table1
   JOIN table2 ON table1."股票代码" = table2."股票代码"
   JOIN table3 ON table1."股票代码" = table3."股票代码"
   ```

3. **LEFT JOIN**：用于技术指标表
   ```sql
   LEFT JOIN table(hq_index(...)) as tbbh_index1(...)
     ON g0."stkcode" = tbbh_index1."stkcode"
     AND g0."i_date" = tbbh_index1."hq_date"
   ```

### 5.2 JOIN条件

**强制规则**：
- 主键关联：始终使用 `"股票代码"` 或 `"stkcode"` 关联
- 时间关联：技术指标表必须同时关联代码和日期

**示例**：
```sql
-- CTE之间的关联
JOIN table2 ON table1."股票代码" = table2."股票代码"

-- 技术指标表关联
LEFT JOIN table(hq_index('abs_股票领域', 'ma', 'ndays=5;i_date_exp=0'))
  as tbbh_index1("stkcode", "hq_date", "ma5")
  ON g0."stkcode" = tbbh_index1."stkcode"
  AND g0."i_date" = tbbh_index1."hq_date"

-- 次日数据关联
INNER JOIN stock_astock_mkt_daily_trans as g1
  ON t1."股票代码" = g1."stkcode"
  AND g1."i_date" = date_add('day', 1, t1."涨停日期")
```

## 六、聚合与排序规则

### 6.1 聚合函数

**可用聚合**：
```sql
-- 计数
COUNT(*) filter(WHERE condition) AS "数量"

-- 求和/平均/最大/最小
SUM(g0."field") AS "总和"
AVG(g0."field") AS "平均值"
MAX(g0."field") AS "最大值"
MIN(g0."field") AS "最小值"

-- 数组聚合
array_agg(concat('【', g0."field", '】', g0."desc")) as "原因列表"
```

**GROUP BY规则**：
```sql
GROUP BY g0."stkcode"  -- 按股票分组
GROUP BY g0."stkcode", g0."i_date"  -- 按股票和日期分组
```

### 6.2 排序（ORDER BY）

**强制规则**：
1. **最终查询排序**：在最外层SELECT后添加
   ```sql
   SELECT ... FROM table0 ...
   ORDER BY table0."涨跌幅[20250929]" DESC
   ```

2. **多字段排序**：主次排序
   ```sql
   ORDER BY
     table0."涨停日期" DESC,
     table0."次日涨跌幅" DESC
   ```

3. **CTE内排序**：与LIMIT配合使用
   ```sql
   table1 AS (
     SELECT ... FROM ...
     WHERE ...
     ORDER BY g0."se001ntd00009433" DESC
     LIMIT 10
   )
   ```

### 6.3 LIMIT

**强制规则**：
- LIMIT只能用在CTE内或最外层SELECT
- 与ORDER BY配合，实现TOP N查询

**示例**：
```sql
-- CTE内限制
table0 AS (
  SELECT ... FROM ... ORDER BY ... LIMIT 10
)

-- 最外层限制
SELECT ... FROM table0 ...
ORDER BY table0."字段" DESC
LIMIT 10
```

## 七、特殊场景规则

### 7.1 指定股票代码查询

> **股票代码格式规范**：参见 `2.3 股票代码格式规范`

**单个股票**：
```sql
-- 按代码查询
WHERE g0."stkcode" = '000001.SZ'
WHERE g0."stkcode" = '600460.SH'
WHERE g0."stkcode" = '0700.HK'

-- 按名称查询
WHERE g0."stkname" = '同花顺'
```

**多个股票**：
```sql
-- 方式1：OR连接
WHERE (g0."stkcode" = '300007.SZ' OR g0."stkcode" = '300585.SZ' OR ...)

-- 方式2：UNION
(SELECT ... WHERE g0."stkcode" = '300007.SZ')
UNION
(SELECT ... WHERE g0."stkcode" = '300585.SZ')
```

### 7.2 成分股查询

**强制规则**：
```sql
WHERE g0."stkcode" IN (
  SELECT g1."ix999snd00037225" AS "成分代码"
  FROM index_constituents as g1
  WHERE g1."stkname" = '中证500'
    AND g1."i_date_exp" = 0
)
```

### 7.3 概念/行业筛选

**规则**：
1. **主表筛选**：使用 `contains()`
   ```sql
   WHERE contains(g0."se001snt00015648", '机器人')
   ```

2. **关联原因表**：需要展示纳入原因
   ```sql
   LEFT JOIN (
     SELECT g2."stkcode" AS "股票代码",
       array_agg(concat('【', g2."se001snd00011235", '】',
         (CASE WHEN g2."se001snd00011236" is null THEN '' ELSE g2."se001snd00011236" END))
       ) as "纳入概念原因"
     FROM stock_astock_concept as g2
     WHERE g2."se001snd00011235" IN ('机器人', '神经网络')
     GROUP BY g2."stkcode"
   ) as g1 ON g0."stkcode" = g1."股票代码"
   ```

### 7.4 排除与常见过滤条件

以下过滤条件频繁出现在用户查询中，**必须使用指定的写法**而非猜测字段：

| 过滤需求 | ✅ 正确写法 | ❌ 错误写法 | 原因 |
|---------|-----------|-----------|------|
| 排除ST股 | `stkname NOT LIKE '%ST%'` | `JOIN basic_info ON se001snt00015698` | `se001snt00015698`（st布尔字段）在数据服务层**不可用**，会报"指标配置不存在" |
| 仅ST股 | `stkname LIKE '%ST%'` | 同上 | 同上 |
| 排除退市股 | `stkname NOT LIKE '%退%'` | — | 退市股简称通常含"退"字 |
| 按行业筛选 | 用召回结果中的行业字段（如 `se001snt00015607`～`se001snt00015615`），`=` 或 `IN` 精确匹配 | `LIKE '%行业名%'` | 行业名是精确枚举值，不需要模糊匹配 |
| 按概念筛选 | JOIN `stock_astock_concept` 表，用 `se001snd00011235 = '概念名称'` 精确匹配 | — | 概念是明细表，每行一个概念 |

> **关键规则**：`stkname`（股票简称）字段在所有 A股 行情表中都存在，可直接用于 ST/退市过滤，**无需 JOIN 额外表**。

**其他常见排除**：
```sql
-- 排除创业板
WHERE g0."se001snt00015631" <> '创业板'

-- 排除北交所
WHERE g0."se001snt00015650" <> '北交所'

-- 排除新股次新股
WHERE g0."se001std00016477" = false  -- 非近5日上市
  AND g0."se001std00016476" = false  -- 非次新股

-- 排除科创板和创业板
WHERE g0."se001snt00015631" NOT IN ('创业板', '科创板')

-- 排除北证
WHERE contains(g0."se001ont00065569", '北证') = false
```

### 7.5 已知不可用字段

数据服务已配置 schema 但执行层缺失的字段，使用会报 **"指标配置不存在"**：

| 表名 | 字段 | 别名 | 类型 | 状态 | 替代方案 |
|------|------|------|------|------|---------|
| `stock_astock_basic_info` | `se001snt00015698` | st | BOOLEAN | ❌ 不可用 | `stkname LIKE '%ST%'` |

> 遇到 SQL 执行报错 **"指标配置不存在"** 时，首先检查是否使用了上表中的不可用字段。

## 八、错误处理

### 8.1 常见错误

❌ **错误1**：时间范围边界混用
```sql
-- 错误：i_date 做左边界、i_date_exp 做右边界
WHERE i_date >= DATE '2024-01-01' and i_date_exp <= 0

-- 正确：i_date 定范围，i_date_exp = 0 作为补充等值过滤
WHERE i_date >= DATE '2024-01-01' and i_date <= DATE '2024-12-31' and i_date_exp = 0
```

❌ **错误2**：缺少时间筛选
```sql
-- 错误
SELECT ... FROM stock_astock_mkt_daily_trans as g0
WHERE g0."se001std00016521"

-- 正确
SELECT ... FROM stock_astock_mkt_daily_trans as g0
WHERE g0."se001std00016521"
  AND g0."i_date_exp" = 0  -- 必须指定时间范围
```

❌ **错误3**：时间序列表使用函数表达式过滤（CRITICAL！）
```sql
-- ❌ 错误：函数表达式不是有效的 i_date 过滤，只返回最新交易日
WHERE YEAR(i_date) IN (2023, 2024, 2025)
WHERE EXTRACT(YEAR FROM i_date) IN (2023, 2024, 2025)
WHERE MONTH(i_date) = 10

-- ✅ 正确：WHERE 用日期范围，GROUP BY 可以用函数
SELECT EXTRACT(YEAR FROM g0."i_date") AS "年份", MAX(g0."ix999ntd00037231") AS "最高价"
FROM index_mkt_daily_trans as g0
WHERE g0."i_date" >= DATE '2023-01-01' AND g0."i_date" <= DATE '2025-12-31'
GROUP BY EXTRACT(YEAR FROM g0."i_date")
```

> 其他常见错误：开区间（见 §3.2）、百分比未转换（见 §4.3）

### 8.2 生成前检查清单

**在输出SQL前，必须逐项检查**：

- [ ] 1. 是否使用了WITH语句（CTE）
- [ ] 2. ⚠️ **是否使用标准日期范围过滤**（`i_date >= DATE 'xxx' AND i_date <= DATE 'xxx'` 或 `i_date_exp >= -N AND i_date_exp <= 0`）
- [ ] 3. ⚠️ **是否避免在WHERE中使用年份函数**（禁止 `YEAR(i_date) IN (...)` 或 `EXTRACT(YEAR FROM i_date) IN (...)`）
- [ ] 4. 是否包含固定输出字段（股票代码、股票简称、最新价、最新涨跌幅）
- [ ] 5. 所有字段是否都有中文别名
- [ ] 6. 时间字段是否标注了日期（如 `[20241209]`）
- [ ] 7. 是否正确关联了最新行情表（tb_wide）
- [ ] 8. JOIN条件是否完整（代码+日期）
- [ ] 9. 百分比是否转换为小数（5% = 0.05）
- [ ] 10. 布尔字段是否直接使用（不加 `= true`）
- [ ] 11. 技术指标函数是否用`table()`包装且指定别名

---

**版本**：v1.1
**更新日期**：2026-03-05
**适用范围**：Trino查询引擎 (ANSI SQL标准)
