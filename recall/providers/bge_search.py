"""BGE 语义检索客户端（bge-m3-chatpdf 模型）

封装中台 BGE 向量服务的 HTTP API，提供与 pipeline 兼容的 search() 方法。

架构变更（v2）：
- 向量库只存 id + vector_text，不再存 metadata
- 向量服务返回 (id, score) 列表
- metadata 从本地 docs_meta（BM25 索引共享）查找
- post-filter 在本地完成，与 BM25 共用 filter_utils

接口格式已对齐中台 Arsenal 平台实际 schema（2026-02 确认）。
"""

import logging
import math
from typing import Any, Dict, List, Optional, Set

import httpx

from ..utils.market_taxonomy import frequency_matches, market_matches
from .filter_utils import build_hit_from_meta

logger = logging.getLogger(__name__)

# Default timeout for HTTP requests (seconds)
_DEFAULT_TIMEOUT = 30
_DEFAULT_POOL_SIZE = 10

# 中台固定参数 — 值变更会导致接口不可用
_MODEL_VERSION = "1"
_MODEL_NAME = "bge-m3-chatpdf"
_STORE_TYPE = "es"


class BgeSearchClient:
    """BGE 向量服务语义检索客户端

    向量库只存 id + vector_text（无 metadata），查询返回 (id, score)。
    metadata 通过 load_metadata() 从 BM25 共享的 docs_meta 加载，
    post-filter 和 hit 组装全部在本地完成。
    """

    _SEARCH_ENDPOINT = "/vector/search"
    _STORE_ENDPOINT = "/embedding/store"
    _DELETE_ENDPOINT = "/vector/delete"

    # Fetch caps for vector search — controls how many nearest neighbors
    # we request from the vector service before local post-filtering.
    # These are intentionally generous because post-filter can discard
    # a large fraction of results (e.g. tables are only 0.75% of entries).
    _FETCH_CAP_DEFAULT = 300
    _FETCH_CAP_TABLE = 500       # 470 tables total; 500 covers all of them
    _FETCH_MULTIPLIER_DEFAULT = 3
    _FETCH_MULTIPLIER_SCOPED = 5  # yaml_paths scoped search has higher loss

    def __init__(
        self,
        service_url: str,
        api_key: str = "claudable",
        collection_name: str = "financial_metadata_20260226",
        timeout: int = _DEFAULT_TIMEOUT,
    ):
        self.service_url = service_url.rstrip("/")
        self.api_key = api_key
        self.collection_name = collection_name
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(
                max_connections=_DEFAULT_POOL_SIZE,
                max_keepalive_connections=_DEFAULT_POOL_SIZE,
            ),
        )

        # Local metadata lookup (populated by load_metadata)
        self._meta_by_id: Dict[str, Dict[str, Any]] = {}
        self._meta_loaded = False

        logger.info(
            f"BgeSearchClient initialized (url={self.service_url}, "
            f"collection={self.collection_name})"
        )

    def load_metadata(self, docs_meta: List[Dict[str, Any]]) -> None:
        """从 BM25 共享的 docs_meta 构建 id → metadata 查找表。

        应在 pipeline 初始化时调用一次，与 BM25Retriever 共享同一份数据源。

        Args:
            docs_meta: BM25 索引的 docs_meta.json 内容
        """
        self._meta_by_id = {}
        for meta in docs_meta:
            doc_id = meta.get("id", "")
            if doc_id:
                self._meta_by_id[doc_id] = meta
        self._meta_loaded = True
        logger.info(
            f"BgeSearchClient metadata loaded: {len(self._meta_by_id)} docs"
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    # ------------------------------------------------------------------
    # 公共请求信封
    # ------------------------------------------------------------------

    def _envelope(self, **extra) -> Dict[str, Any]:
        """构建中台要求的请求信封（固定字段 + 额外参数）"""
        base = {
            "model_version": _MODEL_VERSION,
            "model_name": _MODEL_NAME,
            "store_type": _STORE_TYPE,
            "collection": self.collection_name,
        }
        base.update(extra)
        return base

    # ------------------------------------------------------------------
    # 语义搜索
    # ------------------------------------------------------------------

    async def search(
        self,
        query_text: str,
        top_k: int = 50,
        doc_type: Optional[str] = None,
        yaml_paths: Optional[List[str]] = None,
        market: Optional[str] = None,
        frequency: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """语义检索 + 本地 post-filter

        向量服务只返回 (id, score)，metadata 从本地查找表获取。

        Args:
            query_text: 自然语言查询文本（服务端自动向量化）
            top_k: 期望返回的结果数
            doc_type: 文档类型过滤 ("column" | "table")
            yaml_paths: 限定搜索的 YAML 路径列表
            market: 市场过滤（支持同义标签归一化）
            frequency: 频率过滤（支持同义标签归一化；元数据缺失时宽松保留）

        Returns:
            检索结果列表（pipeline hit 格式）
        """
        if not self._meta_loaded:
            logger.warning(
                "BgeSearchClient: metadata not loaded, call load_metadata() first. "
                "Returning empty results."
            )
            return []

        # Over-fetch to compensate for post-filter loss.
        # The cap and multiplier are chosen based on the filter scenario:
        #   - doc_type="table": tables are ~0.75% of entries, so we need
        #     to fetch up to _FETCH_CAP_TABLE to cover the full table set.
        #   - yaml_paths scoped search: higher multiplier because scoped
        #     filtering discards more results than simple type filtering.
        #   - General filtered: moderate multiplier with raised default cap.
        needs_filter = any([doc_type, yaml_paths, market, frequency])
        if doc_type == "table":
            cap = self._FETCH_CAP_TABLE
            multiplier = self._FETCH_MULTIPLIER_SCOPED
        elif yaml_paths:
            cap = self._FETCH_CAP_DEFAULT
            multiplier = self._FETCH_MULTIPLIER_SCOPED
        elif needs_filter:
            cap = self._FETCH_CAP_DEFAULT
            multiplier = self._FETCH_MULTIPLIER_DEFAULT
        else:
            cap = self._FETCH_CAP_DEFAULT
            multiplier = 1
        fetch_n = min(top_k * multiplier, cap)

        try:
            resp = await self._client.post(
                f"{self.service_url}{self._SEARCH_ENDPOINT}",
                json=self._envelope(
                    text=query_text,
                    top_k=str(fetch_n),
                    num_candidates=str(fetch_n),
                ),
                headers={
                    "X-Arsenal-Auth": self.api_key,
                    "Host": "aime-vector-engine-server",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"BGE search HTTP error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(
                "BGE search request failed (%s): %r",
                type(e).__name__,
                e,
            )
            return []

        # 中台响应格式: { "response": { "data": { "items": [...] } } }
        raw_results = (
            data.get("response", {})
            .get("data", {})
            .get("items")
        ) or []
        if not raw_results:
            return []

        # Build filter sets
        yaml_path_set: Optional[Set[str]] = None
        if yaml_paths:
            yaml_path_set = set(yaml_paths)
        market_filter = str(market or "").strip()
        frequency_filter = str(frequency or "").strip()

        # Post-filter using local metadata
        hits: List[Dict[str, Any]] = []
        meta_miss_count = 0
        meta_miss_samples: List[str] = []
        for r in raw_results:
            doc_id = r.get("id", "")
            try:
                score = float(r.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            # 过滤无效分数（NaN / Inf）
            if math.isnan(score) or math.isinf(score):
                continue

            # Look up metadata locally
            meta = self._meta_by_id.get(doc_id)
            if meta is None:
                meta_miss_count += 1
                if len(meta_miss_samples) < 5:
                    meta_miss_samples.append(doc_id)
                continue

            # Apply filters on local metadata
            if doc_type and meta.get("doc_type") != doc_type:
                continue
            if yaml_path_set and meta.get("yaml_path") not in yaml_path_set:
                continue
            if market_filter and not market_matches(meta.get("market"), market_filter):
                continue
            if frequency_filter and not frequency_matches(
                meta.get("frequency"),
                frequency_filter,
                allow_unknown_meta=True,
            ):
                continue

            # Build hit from local metadata + vector score
            # distance 字段由 build_hit_from_meta 统一设置，不重复赋 score
            hit = build_hit_from_meta(meta, distance=score)
            hits.append(hit)
            if len(hits) >= top_k:
                break

        # Log metadata mismatch summary (instead of per-hit warnings)
        if meta_miss_count > 0:
            miss_rate = meta_miss_count / len(raw_results) * 100
            log_fn = logger.error if miss_rate > 50 else logger.warning
            samples_str = ", ".join(meta_miss_samples)
            log_fn(
                f"BGE search: {meta_miss_count}/{len(raw_results)} hits "
                f"({miss_rate:.0f}%) not found in local metadata "
                f"(local_meta={len(self._meta_by_id)}, "
                f"sample_miss_ids=[{samples_str}]). "
                f"Vector collection '{self.collection_name}' and docs_meta.json "
                f"are out of sync — re-run build_bm25_index.py and "
                f"scripts/upload_vectors.py from the same metadata.json."
            )

        return hits

    # ------------------------------------------------------------------
    # 向量存储
    # ------------------------------------------------------------------

    async def store(
        self,
        documents: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """批量存储文档向量

        将文档列表发送到向量存储服务，服务端自动完成向量化和索引。

        Args:
            documents: 文档列表，每个文档包含 id、vector_text、metadata 字段

        Returns:
            服务端响应的完整 JSON
        """
        try:
            resp = await self._client.post(
                f"{self.service_url}{self._STORE_ENDPOINT}",
                json=self._envelope(body=documents),
                headers={
                    "X-Arsenal-Auth": self.api_key,
                    "Host": "aime-vector-engine-server",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"BGE store: uploaded {len(documents)} documents")
            return data
        except httpx.HTTPStatusError as e:
            logger.error(f"BGE store HTTP error: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(
                "BGE store request failed (%s): %r",
                type(e).__name__,
                e,
            )
            raise

    async def delete_collection(self) -> bool:
        """清空整个 collection（删除所有文档）

        用于重建索引前清空旧数据，避免新旧 ID 格式混用导致 metadata miss。

        Returns:
            True 成功，False 失败
        """
        try:
            resp = await self._client.delete(
                f"{self.service_url}{self._DELETE_ENDPOINT}",
                params={
                    "collection": self.collection_name,
                    "store_type": "ES",
                    "delete_key": "id",
                },
                headers={
                    "X-Arsenal-Auth": self.api_key,
                    "Host": "aime-vector-engine-server",
                },
            )
            resp.raise_for_status()
            logger.info(f"Collection '{self.collection_name}' deleted successfully")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Delete collection HTTP error: {e.response.status_code} - {e.response.text[:200]}"
            )
            return False
        except Exception as e:
            logger.error("Delete collection failed (%s): %r", type(e).__name__, e)
            return False

    async def close(self):
        """关闭 HTTP 客户端连接"""
        await self._client.aclose()
        self._meta_by_id = {}
        self._meta_loaded = False
        logger.info("BgeSearchClient closed")
