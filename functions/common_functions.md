# 高频函数速查表

> 基于5121条实际SQL查询统计生成

---

## 概览

- 总查询数: 5121
- 发现条目: 64 个（含关键字/别名；下表仅保留 28 个可调用函数）
- 函数调用总数: 9676 次

## 高频可调用函数

> 已移除非函数条目（`table`、`tbbh_index*`、`tbbh_gga*`、`tbbh_hq1`、`over`、`filter` 等关键字/别名）。

| 排名 | 函数名 | 使用次数 | 说明 |
|------|--------|----------|------|
| 1 | `contains` | 1094 | 判断数组中是否包含指定值 |
| 2 | `hq_index` | 601 | 获取技术指标值（MA/MACD/KDJ等） → 见 market_analysis_functions.md |
| 3 | `array_agg` | 529 | 将多行值聚合为数组 |
| 4 | `concat` | 529 | 拼接字符串或数组元素 |
| 5 | `nullif` | 500 | 若两值相等则返回 null，否则返回第一个值 |
| 6 | `cast` | 495 | 显式类型转换 |
| 7 | `abs` | 448 | 返回绝对值 |
| 8 | `hq_index_ss` | 291 | 技术形态选股（金叉、死叉、均线方向等） → 见 market_analysis_functions.md |
| 9 | `count` | 281 | 统计非 null 值的个数 |
| 10 | `interval_index` | 255 | 获取 150+ 区间统计指标 → 见 statistical_functions.md |
| 11 | `every` | 239 | 所有值均为 true 时返回 true |
| 12 | `hq_calc_ss` | 176 | 指标比较选股（上穿、下穿） → 见 market_analysis_functions.md |
| 13 | `if` | 127 | 条件表达式，条件为真返回第一个值，否则返回第二个值 |
| 14 | `first_value` | 102 | 返回窗口帧中的第一个值 |
| 15 | `sum` | 93 | 求和聚合 |
| 16 | `hq_value` | 93 | 行情取值函数（文档待补充，详见 functions_full.json） |
| 17 | `greatest` | 62 | 返回给定值中的最大值 |
| 18 | `dense_rank` | 46 | 密集排名窗口函数 |
| 19 | `max` | 45 | 返回最大值 |
| 20 | `avg` | 32 | 计算平均值 |
| 21 | `record_high` | 30 | 创新高判断 → 见 statistical_functions.md |
| 22 | `min` | 18 | 返回最小值 |
| 23 | `substring` | 18 | 截取子字符串 |
| 24 | `lag` | 15 | 返回当前行之前指定偏移行的值 |
| 25 | `row_number` | 15 | 为每行返回唯一的顺序编号 |
| 26 | `median` | 13 | 计算中位数 |
| 27 | `power` | 11 | 幂运算 |
| 28 | `record_low` | 8 | 创新低判断 → 见 statistical_functions.md |

---


**注意**: 详细函数说明需要结合`functions_full.json`查看。

