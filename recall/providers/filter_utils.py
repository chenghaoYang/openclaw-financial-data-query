"""过滤工具 - 索引构建和过滤逻辑

提供文档过滤功能：
- doc_type 过滤（column/table）
- yaml_path 过滤（限定搜索范围）
- market 过滤（A股/港股等）
- frequency 过滤（日频/季度等）
"""

from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


_MDL_PASSTHROUGH_FIELDS = (
    # MDL metric fields
    "metric_name",
    "metric_synonyms",
    "measure",
    "dimension",
    "time_grain",
    "model",
    "model_alias",
    "description",
    # MDL relationship fields
    "relationship_name",
    "from_model",
    "to_model",
    "from_model_alias",
    "to_model_alias",
    "join_keys",
    "cardinality",
    # MDL annotations on column/table docs
    "mdl_model",
    "mdl_model_alias",
    "mdl_time_grain",
    "mdl_tags",
    "mdl_expose_columns",
)

_AUX_PASSTHROUGH_FIELDS = (
    "column_description",
    "table_summary",
    "example_all",
    "column_aliases_agg",
    "model_field",
    "value_source",
    "sql_column_ref",
)


def _yaml_path_variants(path: str) -> List[str]:
    raw = str(path or "").strip()
    if not raw:
        return []
    parts = [p for p in raw.split("/") if p]
    if len(parts) < 2:
        return [raw]
    variants = [raw]
    if len(parts) >= 3 and parts[1] == "元数据增强表":
        variants.append("/".join([parts[0], *parts[2:]]))
    else:
        variants.append("/".join([parts[0], "元数据增强表", *parts[1:]]))
    deduped: List[str] = []
    seen = set()
    for item in variants:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def build_filter_indices(
    metadata: List[Dict[str, Any]],
) -> Tuple[
    Dict[str, Set[int]],
    Dict[str, Set[int]],
    Dict[str, Set[int]],
    Dict[str, Set[int]],
]:
    """构建过滤索引

    Args:
        metadata: 元数据列表

    Returns:
        (doc_type_indices, yaml_path_indices, market_indices, frequency_indices)
    """
    doc_type_indices: Dict[str, Set[int]] = {}
    yaml_path_indices: Dict[str, Set[int]] = {}
    market_indices: Dict[str, Set[int]] = {}
    frequency_indices: Dict[str, Set[int]] = {}

    for idx, meta in enumerate(metadata):
        doc_type = meta.get("doc_type", "column")
        doc_type_indices.setdefault(doc_type, set()).add(idx)

        yaml_path = meta.get("yaml_path", "")
        if yaml_path:
            for path in _yaml_path_variants(str(yaml_path)):
                yaml_path_indices.setdefault(path, set()).add(idx)

        market = meta.get("market", "")
        if market:
            market_indices.setdefault(market, set()).add(idx)

        frequency = meta.get("frequency", "")
        if frequency:
            frequency_indices.setdefault(frequency, set()).add(idx)

    return doc_type_indices, yaml_path_indices, market_indices, frequency_indices


def parse_filter_expr(
    filter_expr: Optional[str],
    default_doc_type_filter: Optional[str],
) -> Optional[str]:
    """解析过滤表达式

    Args:
        filter_expr: 过滤表达式（如 "doc_type=column"）
        default_doc_type_filter: 默认文档类型过滤

    Returns:
        解析后的 doc_type 过滤值
    """
    if filter_expr is None:
        return default_doc_type_filter

    if filter_expr.startswith("doc_type="):
        return filter_expr.split("=", 1)[1].strip()

    return None


def get_filtered_indices(
    *,
    doc_type_filter: Optional[str],
    yaml_paths: Optional[List[str]],
    market: Optional[Union[str, Set[str]]],
    frequency: Optional[str],
    doc_type_indices: Dict[str, Set[int]],
    yaml_path_indices: Dict[str, Set[int]],
    market_indices: Dict[str, Set[int]],
    frequency_indices: Dict[str, Set[int]],
    on_unknown_doc_type: Optional[Callable[[str], None]] = None,
    on_missing_yaml_path: Optional[Callable[[str], None]] = None,
    on_missing_market: Optional[Callable[[str], None]] = None,
    on_missing_frequency: Optional[Callable[[str], None]] = None,
) -> Optional[Set[int]]:
    """获取符合所有过滤条件的索引集合

    使用集合交集实现多条件过滤

    Args:
        doc_type_filter: 文档类型过滤
        yaml_paths: YAML路径列表
        market: 市场过滤（str=单市场, Set[str]=多市场联合, None=不过滤）
        frequency: 频率过滤
        doc_type_indices: 文档类型索引
        yaml_path_indices: YAML路径索引
        market_indices: 市场索引
        frequency_indices: 频率索引
        on_unknown_doc_type: 未知文档类型回调
        on_missing_yaml_path: 缺失YAML路径回调
        on_missing_market: 缺失市场回调
        on_missing_frequency: 缺失频率回调

    Returns:
        符合条件的索引集合，None 表示无过滤条件
    """
    result_set: Optional[Set[int]] = None

    # Single-value filters: doc_type, frequency
    single_filter_specs: List[
        Tuple[Optional[str], Dict[str, Set[int]], str, Optional[Callable[[str], None]]]
    ] = [
        (doc_type_filter, doc_type_indices, "doc_type", on_unknown_doc_type),
        (frequency, frequency_indices, "frequency", on_missing_frequency),
    ]
    for filter_val, index_dict, filter_name, on_missing in single_filter_specs:
        if filter_val is not None:
            if filter_val in index_dict:
                matched_set = index_dict[filter_val]
            else:
                if on_missing:
                    on_missing(filter_val)
                return set()
            result_set = (
                set(matched_set) if result_set is None else result_set & matched_set
            )

    # Market filter: supports both str (single) and Set[str] (multi-market union)
    if market is not None:
        market_values: Set[str] = {market} if isinstance(market, str) else market
        market_matched: Set[int] = set()
        for m in market_values:
            if m in market_indices:
                market_matched |= market_indices[m]
        if not market_matched:
            if on_missing_market:
                on_missing_market(str(market))
            return set()
        result_set = (
            set(market_matched) if result_set is None else result_set & market_matched
        )

    # Multi-value filter: yaml_paths (union of matching paths, then intersect)
    if yaml_paths:
        yaml_path_set: Set[int] = set()
        for path in yaml_paths:
            if path in yaml_path_indices:
                yaml_path_set.update(yaml_path_indices[path])
            else:
                if on_missing_yaml_path:
                    on_missing_yaml_path(path)

        if not yaml_path_set:
            return set()

        result_set = (
            set(yaml_path_set) if result_set is None else result_set & yaml_path_set
        )

    return result_set


def build_hit_from_meta(
    meta: Dict[str, Any],
    distance: float,
    *,
    bm25_score: Optional[float] = None,
) -> Dict[str, Any]:
    """从元数据构建检索结果

    Args:
        meta: 元数据字典
        distance: 相似度分数
        bm25_score: BM25分数（可选）

    Returns:
        检索结果字典
    """
    hit: Dict[str, Any] = {
        "id": meta.get("id", ""),
    }
    if bm25_score is not None:
        hit["bm25_score"] = float(bm25_score)
    hit["distance"] = float(distance)
    hit.update(
        {
            "text": meta.get("text", ""),
            "doc_type": meta.get("doc_type", "column"),
            "yaml_path": meta.get("yaml_path", ""),
            "table_name": meta.get("table_name", ""),
            "table_alias": meta.get("table_alias", ""),
            "column_name": meta.get("column_name", ""),
            "column_alias": meta.get("column_alias", ""),
            "domain": meta.get("domain", ""),
            "storage_type": meta.get("storage_type", ""),
            "market": meta.get("market", ""),
            "frequency": meta.get("frequency", ""),
            "index_name": meta.get("index_name", ""),
            "unit": meta.get("unit", ""),
            "column_type": meta.get("column_type", ""),
        }
    )
    # Preserve MDL metadata so downstream routing/backfill logic can use it.
    for field in _MDL_PASSTHROUGH_FIELDS:
        if field in meta:
            hit[field] = meta.get(field)
    for field in _AUX_PASSTHROUGH_FIELDS:
        if field in meta:
            hit[field] = meta.get(field)
    return hit
