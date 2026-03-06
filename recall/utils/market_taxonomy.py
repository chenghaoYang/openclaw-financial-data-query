"""Market/frequency taxonomy helpers for indexing and retrieval.

This module centralizes:
1. Canonical market labels and aliases (for both ingestion and query-time filter).
2. Frequency aliases and normalization.
"""

from __future__ import annotations

from typing import Dict, Optional, Set, Tuple


def _clean(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _alias_key(value: Optional[str]) -> str:
    return _clean(value).upper()


# Canonical market labels and aliases.
# NOTE:
# - Keep router/market_rules labels as canonical where possible.
# - Include legacy labels used in historical metadata for backward compatibility.
MARKET_ALIASES_BY_CANONICAL: Dict[str, Set[str]] = {
    "A股": {"A股", "股票"},
    "港股": {"港股"},
    "美股": {"美股"},
    "英股": {"英股"},
    "基金": {"基金"},
    "基金公司": {"基金公司", "基金"},
    "基金经理": {"基金经理", "基金"},
    "指数": {"指数", "全量指数"},
    "市场环境": {"市场环境", "指数"},
    "期货": {"期货"},
    "期货品种": {"期货品种", "期货"},
    "外盘期货": {"外盘期货", "期货"},
    "期权": {"期权"},
    "全量债券": {"全量债券", "债券"},
    "可转债": {"可转债"},
    "新三板": {"新三板"},
    "银行理财": {"银行理财"},
    "同花顺保险": {"同花顺保险", "保险"},
}

MARKET_CANONICAL_BY_ALIAS: Dict[str, str] = {}
for _canonical, _aliases in MARKET_ALIASES_BY_CANONICAL.items():
    for _alias in _aliases:
        # Keep first-write to avoid overriding base canonical labels like:
        # "基金" -> "基金经理", "指数" -> "市场环境", "期货" -> "外盘期货".
        MARKET_CANONICAL_BY_ALIAS.setdefault(_alias_key(_alias), _canonical)


def normalize_market_tag(value: Optional[str]) -> str:
    """Normalize a market tag to canonical label."""
    token = _clean(value)
    if not token:
        return ""
    # Exact canonical label should be stable and never be remapped by aliases.
    if token in MARKET_ALIASES_BY_CANONICAL:
        return token
    return MARKET_CANONICAL_BY_ALIAS.get(_alias_key(token), token)


def market_filter_values(value: Optional[str]) -> Set[str]:
    """Return equivalent market values for filtering."""
    token = _clean(value)
    if not token:
        return set()
    canonical = normalize_market_tag(token)
    aliases = set(MARKET_ALIASES_BY_CANONICAL.get(canonical, {canonical}))
    aliases.add(token)
    return {x for x in aliases if x}


def market_matches(meta_market: Optional[str], requested_market: Optional[str]) -> bool:
    """Whether metadata market matches requested market after alias expansion."""
    requested_values = market_filter_values(requested_market)
    if not requested_values:
        return True
    meta_values = market_filter_values(meta_market)
    if not meta_values:
        return False
    return bool(requested_values & meta_values)


FREQUENCY_ALIASES_BY_CANONICAL: Dict[str, Set[str]] = {
    "日频": {"日频", "日线", "日", "DAILY"},
    "周频": {"周频", "周线", "周", "WEEKLY"},
    "月频": {"月频", "月线", "月", "MONTHLY"},
    "季度": {"季度", "季频", "QUARTERLY"},
    "半年": {"半年", "半年度", "半年频", "HALF_YEAR", "SEMI_YEAR"},
    "年频": {"年频", "年度", "年线", "年", "YEARLY", "ANNUAL"},
    "时序": {"时序", "分时", "分钟", "分钟级", "TIME", "NOW", "INTRADAY", "TICK"},
}

FREQUENCY_CANONICAL_BY_ALIAS: Dict[str, str] = {}
for _canonical, _aliases in FREQUENCY_ALIASES_BY_CANONICAL.items():
    for _alias in _aliases:
        FREQUENCY_CANONICAL_BY_ALIAS[_alias_key(_alias)] = _canonical


def normalize_frequency_tag(value: Optional[str]) -> str:
    """Normalize a frequency tag to canonical label."""
    token = _clean(value)
    if not token:
        return ""
    return FREQUENCY_CANONICAL_BY_ALIAS.get(_alias_key(token), token)


def frequency_filter_values(value: Optional[str]) -> Set[str]:
    """Return equivalent frequency values for filtering."""
    token = _clean(value)
    if not token:
        return set()
    canonical = normalize_frequency_tag(token)
    aliases = set(FREQUENCY_ALIASES_BY_CANONICAL.get(canonical, {canonical}))
    aliases.add(token)
    return {x for x in aliases if x}


def frequency_matches(
    meta_frequency: Optional[str],
    requested_frequency: Optional[str],
    allow_unknown_meta: bool = True,
) -> bool:
    """Whether metadata frequency matches requested frequency.

    When allow_unknown_meta=True, docs with empty frequency are kept.
    """
    requested_values = frequency_filter_values(requested_frequency)
    if not requested_values:
        return True

    meta_values = frequency_filter_values(meta_frequency)
    if not meta_values:
        return allow_unknown_meta
    return bool(requested_values & meta_values)


# ============================================================
# Soft routing: confidence-tiered market expansion
# ============================================================

# 市场邻接图：中等置信度时，主市场 + 邻近市场联合检索
MARKET_ADJACENCY: Dict[str, Tuple[str, ...]] = {
    "A股": ("指数", "可转债"),
    "港股": ("指数", "A股"),
    "美股": ("指数",),
    "英股": ("指数",),
    "基金": ("基金经理", "基金公司", "指数"),
    "基金公司": ("基金", "基金经理"),
    "基金经理": ("基金", "基金公司"),
    "指数": ("A股", "港股", "市场环境"),
    "市场环境": ("指数", "A股"),
    "期货": ("期货品种", "外盘期货"),
    "期货品种": ("期货", "外盘期货"),
    "外盘期货": ("期货", "期货品种"),
    "期权": ("A股", "指数"),
    "全量债券": ("可转债",),
    "可转债": ("A股", "全量债券"),
    "新三板": ("A股",),
    "银行理财": (),
    "同花顺保险": (),
}

# 高置信度阈值：>= 此值使用单市场硬过滤（保持现有行为）
SOFT_ROUTING_HIGH_THRESHOLD: float = 0.7
# 中等置信度阈值：>= 此值使用 主市场+邻近市场 联合过滤
SOFT_ROUTING_MEDIUM_THRESHOLD: float = 0.4


def expand_market_for_soft_routing(
    primary_market: Optional[str],
    confidence: float,
    *,
    high_threshold: float = SOFT_ROUTING_HIGH_THRESHOLD,
    medium_threshold: float = SOFT_ROUTING_MEDIUM_THRESHOLD,
) -> Optional[Set[str]]:
    """根据置信度分层扩展 BM25 市场过滤范围。

    Args:
        primary_market: 主市场标签（如 "A股", "港股"）
        confidence: 路由置信度 0.0-1.0
        high_threshold: 高置信度阈值
        medium_threshold: 中等置信度阈值

    Returns:
        - Set[str]: 需要过滤的市场集合（包含 alias 展开）
        - None: 不过滤（全量池检索）

    行为：
        confidence >= high_threshold  → {primary_market} 单市场（保持现有精度）
        medium <= conf < high         → {primary + adjacent} 联合（扩展覆盖）
        confidence < medium           → None（全量池，让语义排序决定）
    """
    if not primary_market:
        return None

    canonical = normalize_market_tag(primary_market)
    if not canonical:
        return None

    if confidence >= high_threshold:
        # 高置信度：单市场硬过滤（现有行为）
        return market_filter_values(canonical)

    if confidence >= medium_threshold:
        # 中等置信度：主市场 + 邻近市场
        result = market_filter_values(canonical)
        adjacent = MARKET_ADJACENCY.get(canonical, ())
        for adj_market in adjacent:
            result |= market_filter_values(adj_market)
        return result

    # 低置信度：不过滤，全量池
    return None

