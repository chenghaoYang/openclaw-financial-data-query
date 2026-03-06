"""
数值过滤条件提取器 - Numerical Filter Extractor

从中文金融查询中提取数值约束条件，用于后续数据过滤。
支持中英文混合表达、范围区间、中文单位（亿/万/%）、
中文运算符（大于/小于/不超过）。

使用场景：
- 用户查询 "PE小于20的股票" → 提取 PE < 20
- 用户查询 "市值大于100亿" → 提取 market_cap > 10000000000
- 用户查询 "换手率3%-35%" → 提取 turnover_rate >= 0.03 AND turnover_rate <= 0.35

用法：
    >>> from recall.utils.numerical_filter_extractor import NumericalFilterExtractor
    >>> constraints = NumericalFilterExtractor.extract("PE小于20且市值大于100亿")
    >>> for c in constraints:
    ...     print(f"{c.field} {c.operator} {c.value}")
    PE < 20.0
    market_cap > 10000000000.0
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class NumericalConstraint:
    """数值约束条件

    Attributes:
        field: 规范化字段名（如 "PE", "market_cap"）
        operator: 比较运算符（">" | "<" | ">=" | "<=" | "=" | "!="）
        value: 数值（已乘以单位系数，如 100亿 → 1e10）
        unit: 原始单位文本（如 "亿", "%"），无单位时为 None
    """
    field: str
    operator: str
    value: float
    unit: Optional[str] = None


# ============================================================
# 字段别名映射
# ============================================================

# 中文/英文名称 → 规范化字段名
FIELD_ALIASES: Dict[str, str] = {
    # 估值指标
    "市盈率": "PE",
    "PE": "PE",
    "pe": "PE",
    "P/E": "PE",
    "市净率": "PB",
    "PB": "PB",
    "pb": "PB",
    "P/B": "PB",
    "市销率": "PS",
    "PS": "PS",
    "ps": "PS",
    "P/S": "PS",
    # 市值
    "市值": "total_market_cap",
    "总市值": "total_market_cap",
    "流通市值": "float_market_cap",
    "流通盘": "float_market_cap",
    # 成交
    "成交额": "volume_amount",
    "日成交额": "volume_amount",
    "成交量": "volume",
    # 涨跌
    "涨幅": "change_pct",
    "涨跌幅": "change_pct",
    "跌幅": "change_pct",
    # 换手
    "换手率": "turnover_rate",
    # 财务
    "净利润": "net_profit",
    "归母净利润": "net_profit",
    "营收": "revenue",
    "营业收入": "revenue",
    "收入": "revenue",
    # 盈利能力
    "ROE": "ROE",
    "roe": "ROE",
    "净资产收益率": "ROE",
    # 股息
    "股息率": "dividend_yield",
    "分红率": "dividend_yield",
}

# 构建字段名正则表达式（按长度降序排列，避免短词优先匹配）
_FIELD_NAMES_SORTED = sorted(FIELD_ALIASES.keys(), key=len, reverse=True)
_FIELD_PATTERN = "|".join(re.escape(name) for name in _FIELD_NAMES_SORTED)

# ============================================================
# 运算符映射
# ============================================================

# 中文运算符 → 标准运算符
OPERATOR_MAP: Dict[str, str] = {
    "大于": ">",
    "小于": "<",
    "高于": ">",
    "低于": "<",
    "不超过": "<=",
    "不低于": ">=",
    "不少于": ">=",
    "不高于": "<=",
    "不大于": "<=",
    "不小于": ">=",
    "超过": ">",
    "达到": ">=",
    "等于": "=",
    "为": "=",
}

# 中文运算符正则（按长度降序）
_OPERATOR_NAMES_SORTED = sorted(OPERATOR_MAP.keys(), key=len, reverse=True)
_CN_OPERATOR_PATTERN = "|".join(re.escape(op) for op in _OPERATOR_NAMES_SORTED)

# ============================================================
# 单位系数
# ============================================================

UNIT_MULTIPLIERS: Dict[str, float] = {
    "亿": 1e8,
    "万亿": 1e12,
    "万": 1e4,
    "百万": 1e6,
    "千万": 1e7,
    "%": 1.0,  # percentage stored as face value in database (3% → 3.0)
    "倍": 1.0,
}

# 单位正则（按长度降序，"万亿"必须在"万"之前）
_UNIT_NAMES_SORTED = sorted(UNIT_MULTIPLIERS.keys(), key=len, reverse=True)
_UNIT_PATTERN = "|".join(re.escape(u) for u in _UNIT_NAMES_SORTED)

# ============================================================
# 预编译正则表达式
# ============================================================

# 数值模式：整数或小数
_NUM = r"(-?\d+(?:\.\d+)?)"

# 模式 1: 字段名 + 符号运算符 + 数值 + 可选单位
# 例如: "PE<20", "市值>100亿", "涨幅>=5%", "ROE!=10%"
_RE_FIELD_SYMBOL_VALUE = re.compile(
    rf"({_FIELD_PATTERN})\s*(>=|<=|!=|>|<|=)\s*{_NUM}\s*({_UNIT_PATTERN})?"
)

# 模式 2: 字段名 + 中文运算符 + 数值 + 可选单位
# 例如: "PE小于20", "市值大于100亿", "换手率不超过5%"
_RE_FIELD_CN_OP_VALUE = re.compile(
    rf"({_FIELD_PATTERN})\s*({_CN_OPERATOR_PATTERN})\s*{_NUM}\s*({_UNIT_PATTERN})?"
)

# 更精确的范围模式：支持负数、百分号、中文单位
_RE_FIELD_RANGE = re.compile(
    rf"({_FIELD_PATTERN})\s*"
    rf"(-?\d+(?:\.\d+)?)\s*({_UNIT_PATTERN})?\s*"
    rf"[-—~至到]\s*"
    rf"(-?\d+(?:\.\d+)?)\s*({_UNIT_PATTERN})?"
)

# 模式 4: 数值 + 单位 + 符号 + 字段名（反向表达）
# 例如: "100亿以上市值"、"20以下PE"
_RE_VALUE_UNIT_DIR_FIELD = re.compile(
    rf"{_NUM}\s*({_UNIT_PATTERN})?\s*(以上|以下|以内)\s*的?\s*({_FIELD_PATTERN})"
)


# ============================================================
# 提取器
# ============================================================

class NumericalFilterExtractor:
    """数值过滤条件提取器

    从中文金融查询文本中提取所有数值约束条件。
    所有方法均为静态方法，无需实例化。

    提取优先级：
    1. 范围模式（"换手率3%-35%"、"流通市值25-2000亿"）
    2. 字段 + 符号运算符 + 数值（"PE<20"）
    3. 字段 + 中文运算符 + 数值（"PE小于20"）
    4. 反向表达（"100亿以上市值"）
    """

    @staticmethod
    def extract(query: str) -> List[NumericalConstraint]:
        """从查询文本提取数值约束条件

        Args:
            query: 中文金融查询文本

        Returns:
            NumericalConstraint 列表，无约束时返回空列表
        """
        if not query or not query.strip():
            return []

        query = query.strip()
        constraints: List[NumericalConstraint] = []

        # 已匹配的文本区间，用于避免重复提取
        matched_spans: List[Tuple[int, int]] = []

        # 1. 范围模式（最高优先级，因为可能包含运算符子模式）
        constraints.extend(
            NumericalFilterExtractor._extract_ranges(query, matched_spans)
        )

        # 2. 字段 + 符号运算符 + 数值
        constraints.extend(
            NumericalFilterExtractor._extract_symbol_ops(query, matched_spans)
        )

        # 3. 字段 + 中文运算符 + 数值
        constraints.extend(
            NumericalFilterExtractor._extract_cn_ops(query, matched_spans)
        )

        # 4. 反向表达
        constraints.extend(
            NumericalFilterExtractor._extract_reverse(query, matched_spans)
        )

        if constraints:
            logger.debug(
                f"Extracted {len(constraints)} constraints from: '{query}'"
            )
            for c in constraints:
                logger.debug(f"  {c.field} {c.operator} {c.value} (unit={c.unit})")

        return constraints

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    @staticmethod
    def _overlaps(span: Tuple[int, int], existing: List[Tuple[int, int]]) -> bool:
        """检查新匹配区间是否与已有区间重叠"""
        for s, e in existing:
            if span[0] < e and span[1] > s:
                return True
        return False

    @staticmethod
    def _resolve_field(raw_name: str) -> Optional[str]:
        """将原始字段名映射为规范化名称"""
        return FIELD_ALIASES.get(raw_name)

    @staticmethod
    def _apply_unit(value: float, unit_text: Optional[str]) -> Tuple[float, Optional[str]]:
        """应用单位系数

        Args:
            value: 原始数值
            unit_text: 单位文本（如 "亿", "%"）

        Returns:
            (换算后数值, 单位文本)
        """
        if not unit_text:
            return value, None
        multiplier = UNIT_MULTIPLIERS.get(unit_text, 1.0)
        return value * multiplier, unit_text

    @staticmethod
    def _extract_ranges(
        query: str, matched_spans: List[Tuple[int, int]]
    ) -> List[NumericalConstraint]:
        """提取范围模式: "换手率3%-35%", "流通市值25-2000亿" """
        results: List[NumericalConstraint] = []

        for m in _RE_FIELD_RANGE.finditer(query):
            span = m.span()
            if NumericalFilterExtractor._overlaps(span, matched_spans):
                continue

            field_raw = m.group(1)
            low_str = m.group(2)
            low_unit = m.group(3)
            high_str = m.group(4)
            high_unit = m.group(5)

            field = NumericalFilterExtractor._resolve_field(field_raw)
            if not field:
                continue

            try:
                low_val = float(low_str)
                high_val = float(high_str)
            except ValueError:
                continue

            # 确定单位：每个值优先使用自己的单位，
            # 如果自身没有单位则继承另一端的单位。
            # 例: "25万-2000亿" → low_unit="万", high_unit="亿" → 各自独立
            # 例: "25-2000亿" → low_unit=None, high_unit="亿" → 低位继承"亿"
            effective_low_unit = low_unit or high_unit
            effective_high_unit = high_unit or low_unit
            low_val, low_unit_resolved = NumericalFilterExtractor._apply_unit(
                low_val, effective_low_unit
            )
            high_val, high_unit_resolved = NumericalFilterExtractor._apply_unit(
                high_val, effective_high_unit
            )

            # 确保 low <= high
            if low_val > high_val:
                low_val, high_val = high_val, low_val
                low_unit_resolved, high_unit_resolved = high_unit_resolved, low_unit_resolved

            matched_spans.append(span)

            results.append(NumericalConstraint(
                field=field,
                operator=">=",
                value=low_val,
                unit=low_unit_resolved,
            ))
            results.append(NumericalConstraint(
                field=field,
                operator="<=",
                value=high_val,
                unit=high_unit_resolved,
            ))

        return results

    @staticmethod
    def _extract_symbol_ops(
        query: str, matched_spans: List[Tuple[int, int]]
    ) -> List[NumericalConstraint]:
        """提取符号运算符模式: "PE<20", "市值>100亿", "涨幅>=5%" """
        results: List[NumericalConstraint] = []

        for m in _RE_FIELD_SYMBOL_VALUE.finditer(query):
            span = m.span()
            if NumericalFilterExtractor._overlaps(span, matched_spans):
                continue

            field_raw = m.group(1)
            operator = m.group(2)
            value_str = m.group(3)
            unit_text = m.group(4)

            field = NumericalFilterExtractor._resolve_field(field_raw)
            if not field:
                continue

            # 验证运算符合法性
            if operator not in (">", "<", ">=", "<=", "=", "==", "!="):
                continue
            if operator == "==":
                operator = "="

            try:
                value = float(value_str)
            except ValueError:
                continue

            value, unit = NumericalFilterExtractor._apply_unit(value, unit_text)
            matched_spans.append(span)

            results.append(NumericalConstraint(
                field=field,
                operator=operator,
                value=value,
                unit=unit,
            ))

        return results

    @staticmethod
    def _extract_cn_ops(
        query: str, matched_spans: List[Tuple[int, int]]
    ) -> List[NumericalConstraint]:
        """提取中文运算符模式: "PE小于20", "市值大于100亿" """
        results: List[NumericalConstraint] = []

        for m in _RE_FIELD_CN_OP_VALUE.finditer(query):
            span = m.span()
            if NumericalFilterExtractor._overlaps(span, matched_spans):
                continue

            field_raw = m.group(1)
            cn_operator = m.group(2)
            value_str = m.group(3)
            unit_text = m.group(4)

            field = NumericalFilterExtractor._resolve_field(field_raw)
            if not field:
                continue

            operator = OPERATOR_MAP.get(cn_operator)
            if not operator:
                continue

            try:
                value = float(value_str)
            except ValueError:
                continue

            value, unit = NumericalFilterExtractor._apply_unit(value, unit_text)
            matched_spans.append(span)

            results.append(NumericalConstraint(
                field=field,
                operator=operator,
                value=value,
                unit=unit,
            ))

        return results

    @staticmethod
    def _extract_reverse(
        query: str, matched_spans: List[Tuple[int, int]]
    ) -> List[NumericalConstraint]:
        """提取反向表达: "100亿以上市值", "20以下PE" """
        results: List[NumericalConstraint] = []

        for m in _RE_VALUE_UNIT_DIR_FIELD.finditer(query):
            span = m.span()
            if NumericalFilterExtractor._overlaps(span, matched_spans):
                continue

            value_str = m.group(1)
            unit_text = m.group(2)
            direction = m.group(3)
            field_raw = m.group(4)

            field = NumericalFilterExtractor._resolve_field(field_raw)
            if not field:
                continue

            # 方向词映射
            direction_map = {
                "以上": ">=",
                "以下": "<=",
                "以内": "<=",
            }
            operator = direction_map.get(direction)
            if not operator:
                continue

            try:
                value = float(value_str)
            except ValueError:
                continue

            value, unit = NumericalFilterExtractor._apply_unit(value, unit_text)
            matched_spans.append(span)

            results.append(NumericalConstraint(
                field=field,
                operator=operator,
                value=value,
                unit=unit,
            ))

        return results


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    test_queries = [
        # 符号运算符
        "PE<20",
        "PE>30的股票",
        "市值>100亿",
        "涨幅>=5%",
        "ROE!=10%",
        # 中文运算符
        "PE小于20",
        "市值大于100亿",
        "换手率不超过5%",
        "营收不低于50亿",
        "市盈率低于15",
        # 范围
        "换手率3%-35%",
        "流通市值25-2000亿",
        "PE10-30",
        # 反向表达
        "100亿以上市值",
        "20以下PE",
        # 多条件
        "PE小于20且市值大于100亿",
        "换手率3%-35%的涨幅>5%股票",
        # 无数值
        "贵州茅台近3日外资买入额",
        # 空字符串
        "",
    ]

    print("\n" + "=" * 70)
    print("NumericalFilterExtractor Test")
    print("=" * 70)

    for query in test_queries:
        constraints = NumericalFilterExtractor.extract(query)
        print(f"\n  Query: '{query}'")
        if not constraints:
            print("  Result: 无约束条件")
        else:
            for c in constraints:
                print(
                    f"  Result: {c.field} {c.operator} {c.value}"
                    f"{f' (unit={c.unit})' if c.unit else ''}"
                )
