"""配置管理 - Online模式精简配置

专为Online召回服务设计的轻量级配置系统。
"""

import os
import warnings
from dataclasses import dataclass, field
from typing import Optional, Tuple


# ============================================================
# 环境变量读取辅助函数
# ============================================================


def _get_env_float(key: str, default: float) -> float:
    """从环境变量获取浮点数配置"""
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        raise ValueError(
            f"Environment variable {key} must be a float, got: {val!r}"
        )


def _get_env_int(key: str, default: int) -> int:
    """从环境变量获取整数配置"""
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        raise ValueError(
            f"Environment variable {key} must be an integer, got: {val!r}"
        )


def _get_env_bool(key: str, default: bool) -> bool:
    """从环境变量获取布尔配置"""
    val = os.getenv(key)
    if val is None:
        return default
    if val.lower() in ("true", "1", "yes"):
        return True
    if val.lower() in ("false", "0", "no"):
        return False
    raise ValueError(
        f"Environment variable {key} must be a boolean "
        f"(true/false/1/0/yes/no), got: {val!r}"
    )


# ============================================================
# Field helpers - 减少环境变量字段样板代码
# ============================================================


def _env_float(var: str, default: float):
    """创建从环境变量获取默认值的浮点数字段"""
    return field(default_factory=lambda: _get_env_float(var, default))


def _env_int(var: str, default: int):
    """创建从环境变量获取默认值的整数字段"""
    return field(default_factory=lambda: _get_env_int(var, default))


def _env_bool(var: str, default: bool):
    """创建从环境变量获取默认值的布尔字段"""
    return field(default_factory=lambda: _get_env_bool(var, default))


def _default_bm25_index_path() -> str:
    """BM25 索引路径默认值（支持历史环境变量名）"""
    return (
        os.getenv("BM25_INDEX_PATH")
        or os.getenv("BM25_INDEX_DIR")
        or "recall/data/bm25_index"
    )


def _default_bm25_userdict_path() -> str:
    """BM25 用户词典路径默认值"""
    return os.getenv("BM25_USERDICT_PATH", "recall/data/bm25_index/fin_userdict.txt")


# ============================================================
# 子配置类 - 模块化配置管理
# ============================================================


@dataclass
class RouterConfig:
    """Domain Router 配置

    用于领域路由判断，决定查询属于哪个领域。
    """

    enabled: bool = True
    confidence_threshold: float = _env_float("ROUTER_CONFIDENCE_THRESHOLD", 0.7)
    enable_multi_intent: bool = _env_bool("ROUTER_ENABLE_MULTI_INTENT", True)
    max_intents: int = _env_int("ROUTER_MAX_INTENTS", 3)

    def __post_init__(self):
        if not (0.0 <= self.confidence_threshold <= 1.0):
            raise ValueError(
                f"RouterConfig.confidence_threshold must be in [0.0, 1.0], "
                f"got {self.confidence_threshold}"
            )
        if self.max_intents <= 0:
            raise ValueError(
                f"RouterConfig.max_intents must be > 0, got {self.max_intents}"
            )


@dataclass
class QueryCacheConfig:
    """查询缓存配置

    用于缓存查询归一化结果，减少重复调用。
    """

    enabled: bool = _env_bool("ENABLE_QUERY_CACHE", True)
    ttl_seconds: int = _env_int("QUERY_CACHE_TTL", 3600)
    maxsize: int = _env_int("QUERY_CACHE_MAXSIZE", 1000)

    def __post_init__(self):
        if self.ttl_seconds <= 0:
            raise ValueError(
                f"QueryCacheConfig.ttl_seconds must be > 0, got {self.ttl_seconds}"
            )
        if self.maxsize <= 0:
            raise ValueError(
                f"QueryCacheConfig.maxsize must be > 0, got {self.maxsize}"
            )


@dataclass
class QueryRewriteConfig:
    """Query 改写配置

    控制归一化结果如何组装为最终检索 query。
    """

    retrieval_query_mode: str = field(
        default_factory=lambda: os.getenv("RETRIEVAL_QUERY_MODE", "hybrid")
    )
    retrieval_query_max_keywords: int = _env_int("RETRIEVAL_QUERY_MAX_KEYWORDS", 4)
    retrieval_query_include_time_range: bool = _env_bool(
        "RETRIEVAL_QUERY_INCLUDE_TIME_RANGE", True
    )
    retrieval_query_include_numerical_filters: bool = _env_bool(
        "RETRIEVAL_QUERY_INCLUDE_NUMERICAL_FILTERS", True
    )
    retrieval_query_max_numerical_filters: int = _env_int(
        "RETRIEVAL_QUERY_MAX_NUMERICAL_FILTERS", 2
    )
    retrieval_query_append_original: bool = _env_bool(
        "RETRIEVAL_QUERY_APPEND_ORIGINAL", False
    )
    retrieval_query_max_length: int = _env_int("RETRIEVAL_QUERY_MAX_LENGTH", 256)
    retrieval_query_max_router_expansions: int = _env_int("RETRIEVAL_QUERY_MAX_ROUTER_EXPANSIONS", 4)

    def __post_init__(self):
        self.retrieval_query_mode = (
            str(self.retrieval_query_mode or "hybrid").strip().lower()
        )
        if self.retrieval_query_mode not in {"normalized", "hybrid", "original"}:
            raise ValueError(
                "QueryRewriteConfig.retrieval_query_mode must be one of "
                "{'normalized', 'hybrid', 'original'}, "
                f"got {self.retrieval_query_mode!r}"
            )
        if self.retrieval_query_max_keywords <= 0:
            raise ValueError(
                "QueryRewriteConfig.retrieval_query_max_keywords must be > 0, "
                f"got {self.retrieval_query_max_keywords}"
            )
        if self.retrieval_query_max_numerical_filters <= 0:
            raise ValueError(
                "QueryRewriteConfig.retrieval_query_max_numerical_filters must be > 0, "
                f"got {self.retrieval_query_max_numerical_filters}"
            )
        if self.retrieval_query_max_length <= 0:
            raise ValueError(
                "QueryRewriteConfig.retrieval_query_max_length must be > 0, "
                f"got {self.retrieval_query_max_length}"
            )
        if self.retrieval_query_max_router_expansions <= 0:
            raise ValueError(
                f"QueryRewriteConfig.retrieval_query_max_router_expansions must be > 0, "
                f"got {self.retrieval_query_max_router_expansions}"
            )


@dataclass
class TwoStageConfig:
    """Two-Stage Retrieval 配置

    两阶段检索：先召回表级别，再召回列级别。
    默认关闭，与 Best Config (2026-02-06) 和 FinMetaSearchService 对齐。
    如需启用，设置环境变量 ENABLE_TWO_STAGE=true。
    """

    enabled: bool = _env_bool("ENABLE_TWO_STAGE", False)
    table_top_m: int = _env_int("TABLE_TOP_M", 100)
    col_top_k_per_table: int = _env_int("COL_TOP_K_PER_TABLE", 10)
    table_query_concurrency: int = _env_int("TWO_STAGE_CONCURRENCY", 4)

    def __post_init__(self):
        if self.table_top_m <= 0:
            raise ValueError(
                f"TwoStageConfig.table_top_m must be > 0, got {self.table_top_m}"
            )
        if self.col_top_k_per_table <= 0:
            raise ValueError(
                f"TwoStageConfig.col_top_k_per_table must be > 0, "
                f"got {self.col_top_k_per_table}"
            )
        if self.table_query_concurrency <= 0:
            raise ValueError(
                f"TwoStageConfig.table_query_concurrency must be > 0, "
                f"got {self.table_query_concurrency}"
            )


@dataclass
class HybridConfig:
    """Hybrid Retrieval (BM25 + Vector) 配置

    混合检索：结合BM25关键词匹配和向量语义匹配。
    """

    enabled: bool = _env_bool("ENABLE_HYBRID", True)
    fusion_mode: str = field(default_factory=lambda: os.getenv("HYBRID_FUSION_MODE", "rrf"))
    # retrieval_top_k 默认 50，k=20 比 k=60 更能保留头部区分度
    rrf_k: int = _env_int("RRF_K", 20)
    rrf_w_bm25: float = _env_float("RRF_W_BM25", 3.0)
    rrf_w_vector: float = _env_float("RRF_W_VECTOR", 1.0)
    linear_use_cc: bool = _env_bool("LINEAR_USE_CC", True)
    linear_w_global: float = _env_float("LINEAR_W_GLOBAL", 1.0)
    linear_w_scoped: float = _env_float("LINEAR_W_SCOPED", 1.0)
    linear_w_two_stage: float = _env_float("LINEAR_W_TWO_STAGE", 1.0)
    linear_w_bm25: float = _env_float("LINEAR_W_BM25", 3.0)
    linear_vector_score_higher_is_better: bool = _env_bool(
        "LINEAR_VECTOR_SCORE_HIGHER_IS_BETTER", True
    )
    linear_bm25_score_higher_is_better: bool = _env_bool(
        "LINEAR_BM25_SCORE_HIGHER_IS_BETTER", True
    )

    def __post_init__(self):
        self.fusion_mode = str(self.fusion_mode or "rrf").strip().lower()
        if self.fusion_mode == "cc":
            # Alias: cc = convex-combination linear fusion.
            self.fusion_mode = "linear"
        if self.fusion_mode not in {"rrf", "linear"}:
            raise ValueError(
                f"HybridConfig.fusion_mode must be one of "
                f"{{'rrf', 'linear', 'cc'}}, got {self.fusion_mode!r}"
            )
        if self.rrf_k <= 0:
            raise ValueError(
                f"HybridConfig.rrf_k must be > 0, got {self.rrf_k}"
            )
        if self.rrf_w_bm25 < 0:
            raise ValueError(
                f"HybridConfig.rrf_w_bm25 must be >= 0, got {self.rrf_w_bm25}"
            )
        if self.rrf_w_vector < 0:
            raise ValueError(
                f"HybridConfig.rrf_w_vector must be >= 0, got {self.rrf_w_vector}"
            )
        linear_weights = (
            self.linear_w_global,
            self.linear_w_scoped,
            self.linear_w_two_stage,
            self.linear_w_bm25,
        )
        if any(w < 0 for w in linear_weights):
            raise ValueError(
                "HybridConfig linear weights must be >= 0, "
                f"got {linear_weights}"
            )
        if self.fusion_mode == "linear" and sum(linear_weights) <= 0:
            raise ValueError(
                "HybridConfig linear weights sum must be > 0 when fusion_mode=linear, "
                f"got {linear_weights}"
            )


# ============================================================
# 主配置类 - 整合所有配置
# ============================================================


@dataclass
class RecallConfig:
    """增强召回配置 - Online模式

    精简的配置系统，仅包含Online召回服务实际使用的配置项。
    """

    # ========== 子配置模块 ==========
    router: RouterConfig = field(default_factory=RouterConfig)
    two_stage: TwoStageConfig = field(default_factory=TwoStageConfig)
    hybrid: HybridConfig = field(default_factory=HybridConfig)
    query_cache: QueryCacheConfig = field(default_factory=QueryCacheConfig)
    query_rewrite: QueryRewriteConfig = field(default_factory=QueryRewriteConfig)

    # ========== BGE 向量服务配置（必需）==========
    bge_service_url: str = field(
        default_factory=lambda: os.getenv("BGE_SERVICE_URL", "http://192.168.208.168")
    )
    bge_service_key: str = field(
        default_factory=lambda: os.getenv("BGE_SERVICE_KEY", "claudable")
    )
    vector_collection_name: str = field(default_factory=lambda: os.getenv("VECTOR_COLLECTION_NAME", "financial_metadata_20260226"))

    # BM25索引路径（可选，用于混合检索）
    bm25_index_path: str = field(default_factory=_default_bm25_index_path)
    bm25_userdict_path: str = field(default_factory=_default_bm25_userdict_path)

    # ========== 检索参数 ==========
    top_k: int = _env_int("EVAL_TOP_K", 10)
    retrieval_top_k: int = _env_int("EVAL_RETRIEVAL_TOP_K", 50)
    _skip_validation: bool = field(default=False, repr=False)

    def __post_init__(self):
        """验证配置完整性和合理性"""
        if self._skip_validation:
            return
        # BGE 向量服务为可选（辅助召回路径）
        if self.hybrid.enabled and not self.bge_service_url:
            warnings.warn(
                "hybrid.enabled=True but BGE_SERVICE_URL not set. "
                "Vector recall will be unavailable, running BM25-only mode.",
                stacklevel=2,
            )

        # 检索参数验证
        if self.top_k <= 0:
            raise ValueError(f"top_k must be > 0, got {self.top_k}")
        if self.retrieval_top_k <= 0:
            raise ValueError(
                f"retrieval_top_k must be > 0, got {self.retrieval_top_k}"
            )
        if self.retrieval_top_k < self.top_k:
            warnings.warn(
                f"retrieval_top_k ({self.retrieval_top_k}) is less than "
                f"top_k ({self.top_k}); some results may be lost",
                stacklevel=2,
            )

        # BM25 索引路径验证（BM25 为主召回路径，必需）
        if not self.bm25_index_path:
            raise ValueError(
                "bm25_index_path is required (set BM25_INDEX_PATH env var). "
                "BM25 is the primary recall path."
            )

    def resolve_recall_limits(
        self, requested_top_k: Optional[int] = None
    ) -> Tuple[int, int]:
        """解析本次请求的有效 top_k/retrieval_top_k 组合。

        规则：
        1. 最终返回 top_k 使用调用参数（若有）否则使用配置默认值。
        2. retrieval_top_k 至少覆盖 top_k。
        """
        effective_top_k = self.top_k if requested_top_k is None else int(requested_top_k)
        if effective_top_k <= 0:
            raise ValueError(f"top_k must be > 0, got {effective_top_k}")

        effective_retrieval_top_k = max(
            int(self.retrieval_top_k),
            effective_top_k,
        )
        return effective_top_k, effective_retrieval_top_k
