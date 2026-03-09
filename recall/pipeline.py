"""召回Pipeline - Online模式

核心流程：
Query → (agent-provided normalization) → 多路并行召回 → RRF/Linear 融合 → Score排序 → Top-K

召回路径（4路并行）：
1. BM25 Retrieval:    关键词全文检索（强制，主召回路径，jieba 分词 + 金融同义词扩展）
2. Global Retrieval:  全局 BGE 向量语义检索（可选，hybrid 模式下启用）
3. Scoped Retrieval:  基于 Domain Router 限定范围的 BGE 向量检索（可选，高置信路由时启用）
4. Two-Stage Retrieval: 先召回表级别，再在候选表内召回列（可选，enable_two_stage=True 时启用）

融合方式：RRF（默认，BM25 权重 3.0，向量权重 1.0）或 Linear/Convex-Combination。
"""

import asyncio
import logging
from dataclasses import replace
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Type
from functools import lru_cache

from .providers.bge_search import BgeSearchClient
from .utils.domain_router import DomainRouter, RouterOutput
from .utils.market_taxonomy import (
    expand_market_for_soft_routing,
    market_filter_values,
    normalize_frequency_tag,
    normalize_market_tag,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _lazy_import_bm25() -> Tuple[Optional[Type], Optional[Any], Optional[Any]]:
    """懒加载 BM25 相关依赖，使用 lru_cache 缓存结果"""
    try:
        from .providers.bm25_retriever import (
            BM25Retriever,
            multi_list_reciprocal_rank_fusion,
            multi_list_linear_fusion,
        )
        return BM25Retriever, multi_list_reciprocal_rank_fusion, multi_list_linear_fusion
    except ImportError:
        return None, None, None


class RecallPipeline:
    """增强召回Pipeline - BM25 为主，向量为辅

    完整流程：(agent-provided normalization) → BM25（强制）+ 向量多路召回（可选）→ RRF融合 → Score排序 → Top-K
    """

    def __init__(self, config):
        """初始化Pipeline

        Args:
            config: RecallConfig实例
        """
        self.config = config

        # 初始化各个组件
        self._rewrite_cfg = getattr(config, "query_rewrite", None)
        self._hybrid_cfg = getattr(config, "hybrid", None)
        self._two_stage_cfg = getattr(config, "two_stage", None)
        skill_root = Path(__file__).resolve().parent.parent
        self.enable_hybrid = bool(getattr(self._hybrid_cfg, "enabled", True))
        self.enable_two_stage = bool(getattr(self._two_stage_cfg, "enabled", False))

        # ===== BM25 Retriever: 强制加载（主召回路径）=====
        self.bm25_retriever = None
        bm25_index_dir = self._resolve_path(
            skill_root,
            getattr(config, "bm25_index_path", None)
            or getattr(config, "bm25_index_dir", None),
        )
        bm25_userdict_path = self._resolve_path(
            skill_root,
            getattr(config, "bm25_userdict_path", None),
        )
        if not bm25_index_dir:
            raise ValueError(
                "BM25 索引路径未配置！\n"
                "请设置环境变量 BM25_INDEX_PATH 或配置 bm25_index_path"
            )

        BM25Retriever_cls, _, _ = _lazy_import_bm25()
        if BM25Retriever_cls is None:
            raise ImportError(
                "BM25 依赖未安装（需要 bm25s, jieba）。\n"
                "请执行: pip install bm25s jieba"
            )
        try:
            self.bm25_retriever = BM25Retriever_cls(
                index_dir=bm25_index_dir,
                userdict_path=bm25_userdict_path,
                mmap=True,
            )
            self.bm25_retriever.load()
            logger.info(f"BM25 retriever loaded (mandatory): {bm25_index_dir}")
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"BM25 index not found: {e}. Check bm25_index_path/BM25_INDEX_PATH."
            ) from e

        # ===== BGE 向量服务: 可选加载（辅助召回，hybrid 模式下启用）=====
        # 向量库只存 id+vector_text，metadata 从 BM25 共享的 docs_meta 查找。
        self.vector_retriever = None
        if self.enable_hybrid and config.bge_service_url:
            try:
                self.vector_retriever = BgeSearchClient(
                    service_url=config.bge_service_url,
                    api_key=config.bge_service_key,
                    collection_name=config.vector_collection_name,
                )
                # Share BM25's docs_meta with vector client for local metadata lookup
                if self.bm25_retriever is not None and self.bm25_retriever._docs_meta:
                    self.vector_retriever.load_metadata(self.bm25_retriever._docs_meta)
                else:
                    logger.warning(
                        "BM25 docs_meta not available for vector client metadata lookup. "
                        "Vector post-filter will return empty results."
                    )
                logger.info(
                    f"Vector retriever initialized (auxiliary): "
                    f"url={config.bge_service_url}, collection={config.vector_collection_name}"
                )
            except Exception as e:
                logger.warning(f"Vector service init failed: {e}. Running BM25-only mode.")
        elif not self.enable_hybrid:
            logger.info("Hybrid mode disabled, running BM25-only mode")
        elif not config.bge_service_url:
            logger.warning("BGE_SERVICE_URL not configured, running BM25-only mode")

        # ===== Domain Router（读取配置阈值 + 多意图支持）=====
        self._router_cfg = getattr(config, "router", None)
        router_enabled = bool(getattr(self._router_cfg, "enabled", True))
        router_threshold = float(
            getattr(self._router_cfg, "confidence_threshold", 0.7)
        )
        router_enable_multi_intent = bool(
            getattr(self._router_cfg, "enable_multi_intent", True)
        )
        router_max_intents = int(
            getattr(self._router_cfg, "max_intents", 3)
        )
        if router_enabled:
            self.router = DomainRouter(
                confidence_threshold=router_threshold,
                enable_multi_intent=router_enable_multi_intent,
                max_intents=router_max_intents,
            )
            logger.info(
                f"DomainRouter initialized (confidence_threshold={router_threshold}, "
                f"multi_intent={router_enable_multi_intent}, max_intents={router_max_intents})"
            )
        else:
            self.router = None
            logger.info("DomainRouter disabled by config")

        logger.info(
            "RecallPipeline initialized "
            f"(bm25=mandatory, vector={'enabled' if self.vector_retriever else 'disabled'}, "
            f"two_stage={self.enable_two_stage})"
        )

    @staticmethod
    def _resolve_path(skill_root: Path, path_value: Optional[str]) -> Optional[str]:
        if not path_value:
            return None
        raw = str(path_value).strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = skill_root / path
        return str(path)

    async def recall(
        self, query: str, top_k: Optional[int] = None,
        normalized_info: Optional[Dict[str, Any]] = None,
        llm_routing: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """执行多路召回

        Args:
            query: 用户查询
            top_k: 返回结果数（可选，默认使用config.top_k）
            normalized_info: 由调用方（agent）提供的查询归一化信息字典（可选）

        Returns:
            召回结果列表，每个结果包含：
            - rank: 排名
            - table_path: 表元数据路径 (yaml_path)
            - table_alias: 表中文名
            - column_name: 字段编码
            - column_alias: 字段中文名
            - score: 相关性分数
        """
        # 验证查询是否为空
        if not query or not query.strip():
            logger.warning("Empty query provided, returning empty results")
            return []

        query = query.strip()

        top_k, retrieval_top_k = self.config.resolve_recall_limits(top_k)
        if (
            top_k != self.config.top_k
            or retrieval_top_k != self.config.retrieval_top_k
        ):
            logger.info(
                "Adjusted recall limits for this request: "
                f"top_k={top_k}, retrieval_top_k={retrieval_top_k}"
            )

        logger.info(f"Starting multi-path recall for query: '{query}' (top_k={top_k})")

        try:
            # Step 1: Use agent-provided normalization
            if normalized_info is not None:
                norm_info = normalized_info
                normalized_query = norm_info.get("normalized_query", query)
                bm25_query, vector_query = self._build_retrieval_queries(query, norm_info)
                logger.info(f"Using agent-provided normalization: {normalized_query}")
            else:
                # Fallback: use query as-is (no LLM normalization)
                norm_info = {"normalized_query": query, "original_query": query, "core_indicator": "", "keywords": [], "market": "", "time_range": ""}
                normalized_query = query
                bm25_query = query
                vector_query = query
                logger.info(f"No normalization provided, using raw query: {query}")

            if bm25_query != normalized_query or vector_query != normalized_query:
                logger.debug(
                    f"Decoupled retrieval queries: bm25='{bm25_query}', vector='{vector_query}'"
                )

            # Step 2: Domain routing (ensemble: rule-based + LLM)
            # Always run rule-based router, then fuse with LLM routing if available.
            logger.info("Step 2: Ensemble domain routing...")
            rule_router_output = self._route_query(query)
            if rule_router_output.intent == "global" and normalized_query != query:
                normalized_router_output = self._route_query(normalized_query)
                if normalized_router_output.intent != "global":
                    rule_router_output = normalized_router_output
                    logger.debug(
                        "Rule router improved via normalized query: %s",
                        normalized_query,
                    )
            logger.info(
                "  Rule router: intent=%s, market=%s, confidence=%.2f, paths=%d",
                rule_router_output.intent,
                rule_router_output.market,
                rule_router_output.confidence,
                len(rule_router_output.allowed_yaml_paths),
            )

            llm_router_output = self._build_llm_router_output(llm_routing, norm_info)
            if llm_router_output is not None:
                logger.info(
                    "  LLM router: intent=%s, market=%s, confidence=%.2f, paths=%d",
                    llm_router_output.intent,
                    llm_router_output.market,
                    llm_router_output.confidence,
                    len(llm_router_output.allowed_yaml_paths),
                )

            router_output = self._ensemble_routing(
                llm_output=llm_router_output,
                rule_output=rule_router_output,
                norm_info=norm_info,
            )
            if router_output.is_multi_intent:
                logger.info(
                    f"Router output (multi-intent): intents={list(router_output.intents)}, "
                    f"markets={list(router_output.markets)}, "
                    f"confidence={router_output.confidence:.2f}, "
                    f"paths={len(router_output.allowed_yaml_paths)}"
                )
            else:
                logger.info(
                    f"Router output: intent={router_output.intent}, "
                    f"market={router_output.market}, "
                    f"confidence={router_output.confidence:.2f}"
                )

            bm25_query_expanded = self._append_router_expansions(
                bm25_query,
                router_output.query_expansions,
            )
            vector_query_expanded = self._append_router_expansions(
                vector_query,
                router_output.query_expansions,
            )
            if bm25_query_expanded != bm25_query or vector_query_expanded != vector_query:
                logger.debug(
                    "Retrieval queries expanded with router terms: "
                    "bm25='%s'->'%s', vector='%s'->'%s'",
                    bm25_query, bm25_query_expanded,
                    vector_query, vector_query_expanded,
                )
            bm25_query = bm25_query_expanded
            vector_query = vector_query_expanded

            # Step 3: 多路召回（并行执行）
            logger.info("Step 3: Multi-path retrieval (parallel)...")
            all_candidates: Dict[str, Dict[str, Any]] = {}
            candidate_sources: Dict[str, int] = {}
            scoped_enabled = bool(
                self.vector_retriever is not None
                and self.router is not None
                and self.router.should_use_scoped_retrieval(router_output)
            )
            scoped_yaml_paths: List[str] = []
            scoped_market: Optional[str] = None
            scoped_frequency: Optional[str] = None
            if scoped_enabled:
                scoped_yaml_paths = self._expand_yaml_paths_for_filter(
                    router_output.allowed_yaml_paths
                )
                # 多意图对比查询（可能跨市场/频率）不强制 market/frequency 过滤，
                # 单意图高置信路由才下推二级过滤条件以减少噪声。
                # 优先使用 agent 提供的 normalized_info 中的 market/frequency（更准确），
                # fallback 到 router 推断的值。
                if not router_output.is_multi_intent:
                    agent_market = normalize_market_tag(norm_info.get("market"))
                    router_market = normalize_market_tag(router_output.market)
                    if agent_market and router_market and agent_market != router_market:
                        logger.debug(
                            "Scoped market mismatch (agent=%s, router=%s), fallback to router market",
                            agent_market,
                            router_market,
                        )
                        scoped_market = router_market
                    else:
                        scoped_market = agent_market or router_market or router_output.market

                    agent_frequency = normalize_frequency_tag(norm_info.get("frequency"))
                    router_frequency = normalize_frequency_tag(router_output.frequency)
                    if (
                        agent_frequency
                        and router_frequency
                        and agent_frequency != router_frequency
                    ):
                        logger.debug(
                            "Scoped frequency mismatch (agent=%s, router=%s), fallback to router frequency",
                            agent_frequency,
                            router_frequency,
                        )
                        scoped_frequency = router_frequency
                    else:
                        scoped_frequency = (
                            agent_frequency or router_frequency or router_output.frequency
                        )

            # 构建并行任务
            async def _global_recall():
                if self.vector_retriever is None:
                    return []
                return await self.vector_retriever.search(
                    query_text=vector_query,
                    top_k=retrieval_top_k,
                    doc_type="column",
                )

            async def _scoped_recall():
                if not scoped_enabled:
                    return None
                return await self.vector_retriever.search(
                    query_text=vector_query,
                    top_k=retrieval_top_k,
                    doc_type="column",
                    yaml_paths=scoped_yaml_paths or None,
                    market=scoped_market,
                    frequency=scoped_frequency,
                )

            async def _two_stage_recall():
                if not self.enable_two_stage or self.vector_retriever is None:
                    return None
                return await self._two_stage_retrieval(
                    query_text=vector_query,
                    router_output=router_output,
                    max_candidates=retrieval_top_k,
                )

            async def _bm25_recall():
                if self.bm25_retriever is None:
                    return None
                # BM25 软路由层：根据路由置信度分层控制 market 过滤范围。
                # - 高置信度 (>=0.7): 单市场硬过滤（精准场景）
                # - 中置信度 (0.4-0.7): 主市场+邻近市场联合过滤（扩展覆盖）
                # - 低置信度 (<0.4): 无市场过滤（全量池，让语义排序决定）
                bm25_market_filter = None  # Optional[str | Set[str]]
                if self.router is not None and router_output.market and not router_output.is_multi_intent:
                    primary_market = (
                        scoped_market
                        or normalize_market_tag(norm_info.get("market"))
                        or normalize_market_tag(router_output.market)
                        or None
                    )
                    if primary_market:
                        bm25_market_filter = expand_market_for_soft_routing(
                            primary_market, router_output.confidence
                        )
                        if bm25_market_filter is not None:
                            logger.debug(
                                "BM25 soft routing: primary=%s, confidence=%.2f, expanded_markets=%s",
                                primary_market,
                                router_output.confidence,
                                bm25_market_filter,
                            )
                loop = asyncio.get_running_loop()

                def _run_bm25() -> List[Dict[str, Any]]:
                    """BM25 检索（soft-routing market 过滤 → global 回退）。"""
                    hits = self._bm25_search(
                        bm25_query,
                        retrieval_top_k,
                        market=bm25_market_filter,
                    )
                    if hits:
                        return hits
                    # market 过滤无结果时回退到全局搜索
                    if bm25_market_filter is not None:
                        hits = self._bm25_search(
                            bm25_query,
                            retrieval_top_k,
                        )
                        if hits:
                            logger.info(
                                "BM25 fallback (drop_market): %d candidates",
                                len(hits),
                            )
                    return hits

                return await loop.run_in_executor(None, _run_bm25)

            global_hits, scoped_hits, two_stage_hits, bm25_hits_raw = await asyncio.gather(
                _global_recall(), _scoped_recall(), _two_stage_recall(), _bm25_recall()
            )
            if scoped_enabled and scoped_hits:
                global_hits = self._prune_global_hits_for_scoped(
                    global_hits=global_hits,
                    scoped_hits=scoped_hits,
                )

            # Merge global hits
            for hit in global_hits:
                doc_id = hit.get("id", "")
                if doc_id and doc_id not in all_candidates:
                    all_candidates[doc_id] = {**hit, "_source": "global"}
            candidate_sources["global"] = len(global_hits)
            logger.info(f"    Global recall: {len(global_hits)} candidates")

            # Merge scoped hits
            if scoped_hits is not None:
                new_scoped = 0
                for hit in scoped_hits:
                    doc_id = hit.get("id", "")
                    if doc_id and doc_id not in all_candidates:
                        all_candidates[doc_id] = {**hit, "_source": "scoped"}
                        new_scoped += 1
                candidate_sources["scoped"] = len(scoped_hits)
                candidate_sources["scoped_new"] = new_scoped
                logger.info(f"    Scoped recall: {len(scoped_hits)} candidates ({new_scoped} new)")

            # Merge two-stage hits
            if two_stage_hits is not None:
                new_two_stage = 0
                for hit in two_stage_hits:
                    doc_id = hit.get("id", "")
                    if doc_id and doc_id not in all_candidates:
                        all_candidates[doc_id] = {**hit, "_source": "two_stage"}
                        new_two_stage += 1
                candidate_sources["two_stage"] = len(two_stage_hits)
                candidate_sources["two_stage_new"] = new_two_stage
                logger.info(f"    Two-stage recall: {len(two_stage_hits)} candidates ({new_two_stage} new)")

            # Merge BM25 hits
            bm25_hits = bm25_hits_raw or []
            if bm25_hits:
                new_bm25 = 0
                for hit in bm25_hits:
                    doc_id = hit.get("id", "")
                    if doc_id and doc_id not in all_candidates:
                        all_candidates[doc_id] = {**hit, "_source": "bm25"}
                        new_bm25 += 1
                candidate_sources["bm25"] = len(bm25_hits)
                candidate_sources["bm25_new"] = new_bm25
                logger.info(f"    BM25 recall: {len(bm25_hits)} candidates ({new_bm25} new)")

            # Federated search for multi-intent queries (parallel per-market BM25)
            federated_results = await self._federated_multi_intent_recall(
                router_output=router_output,
                norm_info=norm_info,
                bm25_query=bm25_query,
                retrieval_top_k=retrieval_top_k,
            )
            federated_all_hits: List[Dict[str, Any]] = []
            if federated_results:
                for fed_label, fed_hits in federated_results.items():
                    new_fed = 0
                    for hit in fed_hits:
                        doc_id = hit.get("id", "")
                        if doc_id and doc_id not in all_candidates:
                            all_candidates[doc_id] = {**hit, "_source": fed_label}
                            new_fed += 1
                    federated_all_hits.extend(fed_hits)
                    candidate_sources[fed_label] = len(fed_hits)
                    candidate_sources[f"{fed_label}_new"] = new_fed

            # Step 4: Hybrid Fusion（RRF / Linear-CC）
            has_vector_hits = any([global_hits, scoped_hits, two_stage_hits])
            if has_vector_hits and bm25_hits and self.bm25_retriever is not None:
                fusion_mode = self._hybrid_cfg.fusion_mode

                logger.info(f"Step 4: Multi-list hybrid fusion (mode={fusion_mode})...")
                _, multi_list_rrf, multi_list_linear = _lazy_import_bm25()

                ranked_lists = {
                    "global": global_hits,
                    "scoped": scoped_hits or [],
                    "two_stage": two_stage_hits or [],
                    "bm25": bm25_hits,
                }
                # Include federated per-market hits in fusion (treated as BM25 weight)
                if federated_results:
                    for fed_label, fed_hits in federated_results.items():
                        if fed_hits:
                            ranked_lists[fed_label] = fed_hits

                if fusion_mode == "linear" and multi_list_linear is not None:
                    weights = {
                        "global": float(
                            getattr(
                                self._hybrid_cfg,
                                "linear_w_global",
                                getattr(self._hybrid_cfg, "rrf_w_vector", 1.0),
                            )
                        ),
                        "scoped": float(
                            getattr(
                                self._hybrid_cfg,
                                "linear_w_scoped",
                                getattr(self._hybrid_cfg, "rrf_w_vector", 1.0),
                            )
                        ),
                        "two_stage": float(
                            getattr(
                                self._hybrid_cfg,
                                "linear_w_two_stage",
                                getattr(self._hybrid_cfg, "rrf_w_vector", 1.0),
                            )
                        ),
                        "bm25": float(
                            getattr(
                                self._hybrid_cfg,
                                "linear_w_bm25",
                                getattr(self._hybrid_cfg, "rrf_w_bm25", 1.0),
                            )
                        ),
                    }
                    score_fields = {
                        "global": "distance",
                        "scoped": "distance",
                        "two_stage": "distance",
                        "bm25": "bm25_score",
                    }
                    vector_higher_is_better = bool(
                        getattr(
                            self._hybrid_cfg,
                            "linear_vector_score_higher_is_better",
                            True,
                        )
                    )
                    bm25_higher_is_better = bool(
                        getattr(
                            self._hybrid_cfg,
                            "linear_bm25_score_higher_is_better",
                            True,
                        )
                    )
                    score_higher_is_better = {
                        "global": vector_higher_is_better,
                        "scoped": vector_higher_is_better,
                        "two_stage": vector_higher_is_better,
                        "bm25": bm25_higher_is_better,
                    }
                    # Add federated legs to linear fusion (same weight/score as BM25)
                    if federated_results:
                        for fed_label in federated_results:
                            if fed_label in ranked_lists:
                                weights[fed_label] = weights["bm25"]
                                score_fields[fed_label] = "bm25_score"
                                score_higher_is_better[fed_label] = bm25_higher_is_better
                    use_cc = bool(getattr(self._hybrid_cfg, "linear_use_cc", True))
                    candidates = multi_list_linear(
                        scored_lists=ranked_lists,
                        weights=weights,
                        score_fields=score_fields,
                        score_higher_is_better=score_higher_is_better,
                        use_convex_combination=use_cc,
                    )
                    candidate_sources["linear_fused"] = len(candidates)
                    logger.info(
                        "  Multi-list linear fused: "
                        f"{len(candidates)} candidates (use_cc={use_cc})"
                    )
                    if not candidates:
                        logger.warning(
                            "Linear fusion returned no candidates, fallback to merged candidates."
                        )
                        candidates = list(all_candidates.values())
                else:
                    if fusion_mode == "linear":
                        logger.warning(
                            "Linear fusion function unavailable, fallback to RRF."
                        )
                    if multi_list_rrf is not None:
                        w_bm25 = float(getattr(self._hybrid_cfg, "rrf_w_bm25", 1.0))
                        w_vector = float(getattr(self._hybrid_cfg, "rrf_w_vector", 1.0))
                        rrf_k = int(getattr(self._hybrid_cfg, "rrf_k", 20))
                        weights = {
                            "global": w_vector,
                            "scoped": w_vector,
                            "two_stage": w_vector,
                            "bm25": w_bm25,
                        }
                        # Add federated legs to RRF fusion (same weight as BM25)
                        if federated_results:
                            for fed_label in federated_results:
                                if fed_label in ranked_lists:
                                    weights[fed_label] = w_bm25
                        candidates = multi_list_rrf(
                            ranked_lists=ranked_lists,
                            weights=weights,
                            k=rrf_k,
                        )
                        candidate_sources["rrf_fused"] = len(candidates)
                        logger.info(
                            f"  Multi-list RRF fused: {len(candidates)} candidates"
                        )
                        if not candidates:
                            logger.warning(
                                "RRF fusion returned no candidates, fallback to merged candidates."
                            )
                            candidates = list(all_candidates.values())
                    else:
                        candidates = list(all_candidates.values())
            else:
                candidates = list(all_candidates.values())

            logger.info(
                f"Multi-path recall completed: {len(candidates)} total candidates "
                f"(sources: {candidate_sources})"
            )

            if not candidates:
                logger.warning("No candidates found, returning empty results")
                return []

            # 融合后已按分数排序，避免冗余重排
            from_fusion = (
                has_vector_hits
                and bm25_hits
                and self.bm25_retriever is not None
                and any(
                    c.get("rrf_score") is not None
                    or c.get("linear_score") is not None
                    for c in candidates
                )
            )
            candidates = self._truncate_candidates(
                candidates=candidates,
                max_candidates=retrieval_top_k,
                already_sorted=from_fusion,
            )

            # Soft Boosting: graduated score adjustment based on router alignment.
            # Instead of hard filtering, apply 3-tier multipliers:
            #   Tier 1 (aligned): candidate yaml_path in router's allowed_yaml_paths → boost
            #   Tier 2 (same market): same market as router, but different table → neutral
            #   Tier 3 (cross market): different market entirely → penalty
            # This preserves recall for long-tail queries where the router may be wrong.
            candidates = self._apply_soft_boosting(
                candidates, router_output, norm_info
            )

            # Step 5: Sort by retrieval score (no LLM reranking)
            logger.info("Step 5: Sorting by retrieval score (agent handles reranking)...")
            ranked_results = [
                {"index": i, "relevance_score": self._candidate_sort_score(c)}
                for i, c in enumerate(candidates)
            ]
            ranked_results.sort(key=lambda x: x["relevance_score"], reverse=True)

            # Step 6: Build final results
            logger.info(f"Step 6: Building top-{top_k} results...")
            final_results = []
            seen_indices = set()
            skipped_invalid_count = 0
            skipped_duplicate_count = 0
            for ranked_item in ranked_results:
                if len(final_results) >= top_k:
                    break
                original_idx = ranked_item.get("index", -1)
                if (
                    not isinstance(original_idx, int)
                    or original_idx < 0
                    or original_idx >= len(candidates)
                ):
                    logger.warning(
                        f"Invalid index {original_idx} (candidates length: {len(candidates)}), skipping"
                    )
                    skipped_invalid_count += 1
                    continue

                if original_idx in seen_indices:
                    skipped_duplicate_count += 1
                    continue

                candidate = candidates[original_idx]
                seen_indices.add(original_idx)
                result = {
                    "rank": len(final_results) + 1,
                    "table_path": candidate.get("yaml_path", ""),
                    "table_alias": candidate.get("table_alias", ""),
                    "column_name": candidate.get("column_name", ""),
                    "column_alias": candidate.get("column_alias", ""),
                    "sql_column_ref": candidate.get("sql_column_ref", "") or candidate.get("column_name", ""),
                    "value_source": candidate.get("value_source", ""),
                    "score": ranked_item["relevance_score"],
                    # 保留额外信息用于调试
                    "table_name": candidate.get("table_name", ""),
                    "domain": candidate.get("domain", ""),
                    "market": candidate.get("market", ""),
                    "frequency": candidate.get("frequency", ""),
                    "text": candidate.get("text", ""),
                    "source": candidate.get("_source", "unknown"),
                    "_router_allowed_paths": list(router_output.allowed_yaml_paths),
                    "negation_terms": list(getattr(router_output, "negation_terms", ())),
                }
                final_results.append(result)

            if skipped_invalid_count > 0 or skipped_duplicate_count > 0:
                logger.warning(
                    "Skipped rerank items: "
                    f"invalid={skipped_invalid_count}, duplicate={skipped_duplicate_count}. "
                    f"Returned {len(final_results)} results (requested top_k={top_k})."
                )

            logger.info(f"Multi-path recall completed: {len(final_results)} results")
            return final_results

        except Exception:
            logger.error(f"Recall failed for query '{query}'", exc_info=True)
            raise

    def _route_query(self, query: str) -> RouterOutput:
        """使用 Domain Router 分析查询（支持多意图）"""
        if self.router is None:
            return RouterOutput(
                intent="global",
                query_expansions=[],
                allowed_yaml_paths=[],
                confidence=0.0,
            )
        return self.router.route(query)

    def _build_llm_router_output(
        self, llm_routing: Optional[Dict[str, Any]], norm_info: Dict[str, Any]
    ) -> Optional[RouterOutput]:
        """Construct a RouterOutput from LLM-provided routing info.

        Returns None if llm_routing is missing or structurally invalid.
        """
        if not llm_routing:
            return None

        if not isinstance(llm_routing, dict):
            logger.warning(
                "Invalid llm_routing type (%s), falling back to rule-based router",
                type(llm_routing).__name__,
            )
            return None

        def _to_optional_text(value: Any) -> Optional[str]:
            text = str(value or "").strip()
            return text or None

        def _to_text_tuple(value: Any) -> Tuple[str, ...]:
            if value is None:
                return ()
            if isinstance(value, str):
                text = value.strip()
                return (text,) if text else ()
            if not isinstance(value, (list, tuple, set)):
                return ()
            result: List[str] = []
            seen = set()
            for item in value:
                text = str(item or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                result.append(text)
            return tuple(result)

        def _to_bool(value: Any) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
            if isinstance(value, str):
                token = value.strip().lower()
                if token in {"1", "true", "yes", "y", "on"}:
                    return True
                if token in {"0", "false", "no", "n", "off", ""}:
                    return False
            return bool(value)

        raw_confidence = llm_routing.get("confidence", 0)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid llm_routing confidence (%r), falling back to rule-based router",
                raw_confidence,
            )
            return None
        if confidence < 0.0 or confidence > 1.0:
            logger.warning(
                "Out-of-range llm_routing confidence (%s), clamping into [0.0, 1.0]",
                confidence,
            )
            confidence = max(0.0, min(1.0, confidence))

        # NOTE: In ensemble mode, we no longer reject low-confidence LLM routing here.
        # The ensemble method uses the confidence value to weight LLM vs rule router.
        # We only reject structurally invalid routing (no yaml_scopes).
        intent = _to_optional_text(llm_routing.get("intent")) or "llm_provided"
        yaml_scopes = _to_text_tuple(llm_routing.get("yaml_scopes"))
        if not yaml_scopes:
            logger.info(
                "LLM routing has no valid yaml_scopes, skipping LLM routing"
            )
            return None
        query_expansions = _to_text_tuple(llm_routing.get("query_expansions"))
        is_comparison = _to_bool(llm_routing.get("is_comparison", False))
        market = _to_optional_text(llm_routing.get("market")) or _to_optional_text(
            norm_info.get("market")
        )
        frequency = _to_optional_text(
            llm_routing.get("frequency")
        ) or _to_optional_text(norm_info.get("frequency"))

        # Build intents/markets/frequencies tuples for multi-intent support
        intents = _to_text_tuple(llm_routing.get("intents")) or (intent,)
        markets = _to_text_tuple(llm_routing.get("markets")) or (
            (market,) if market else ()
        )
        frequencies = _to_text_tuple(llm_routing.get("frequencies")) or (
            (frequency,) if frequency else ()
        )
        if len(intents) > 1 or len(markets) > 1 or len(frequencies) > 1:
            is_comparison = True

        return RouterOutput(
            intent=intent,
            query_expansions=query_expansions,
            allowed_yaml_paths=yaml_scopes,
            market=market,
            frequency=frequency,
            confidence=confidence,
            fallback_strategy="merge",
            intents=intents if is_comparison else (intent,),
            markets=markets if is_comparison else ((market,) if market else ()),
            frequencies=(
                frequencies if is_comparison else ((frequency,) if frequency else ())
            ),
        )

    def _ensemble_routing(
        self,
        llm_output: Optional[RouterOutput],
        rule_output: RouterOutput,
        norm_info: Dict[str, Any],
    ) -> RouterOutput:
        """Ensemble LLM routing with rule-based routing.

        Strategy:
        - Rule router is the anchor for market detection (regex-based, no hallucination).
        - LLM routing provides yaml_scopes and semantic intent understanding.
        - query_expansions are merged from both sources (deduplicated).
        - Confidence is adjusted based on agreement between the two routers.
        - yaml_scopes are cross-validated: agreement boosts confidence, disagreement
          triggers union (broader search) with reduced confidence.
        """
        # Case 1: No LLM routing available → use rule router as-is
        if llm_output is None:
            logger.info("  Ensemble: LLM routing unavailable, using rule router only")
            return rule_output

        merged_negation_terms = tuple(
            dict.fromkeys(
                [
                    *getattr(rule_output, "negation_terms", ()),
                    *getattr(llm_output, "negation_terms", ()),
                ]
            )
        )

        def _copy_output(output: RouterOutput, **overrides: Any) -> RouterOutput:
            if "negation_terms" not in overrides:
                overrides["negation_terms"] = merged_negation_terms
            return replace(output, **overrides)

        def _ordered_unique(items: Tuple[str, ...], *more_items: Tuple[str, ...]) -> Tuple[str, ...]:
            ordered: List[str] = []
            seen = set()
            for group in (items, *more_items):
                for item in group:
                    token = str(item or "").strip()
                    if not token or token in seen:
                        continue
                    seen.add(token)
                    ordered.append(token)
            return tuple(ordered)

        def _canonical_path_set(paths: Tuple[str, ...]) -> set:
            result = set()
            for path in paths:
                canonical = self._canonicalize_yaml_path(path)
                if canonical:
                    result.add(canonical)
            return result

        # Retrieve confidence threshold for reference
        try:
            conf_threshold = float(
                getattr(self._router_cfg, "confidence_threshold", 0.7)
            )
        except (TypeError, ValueError):
            conf_threshold = 0.7

        llm_meets_threshold = llm_output.confidence >= conf_threshold

        # Case 2: Rule router returned global (no opinion) → use LLM routing
        # but cap confidence if LLM is below threshold (no rule-based validation)
        if rule_output.intent == "global" and not rule_output.allowed_yaml_paths:
            final_conf = llm_output.confidence
            if llm_output.confidence < conf_threshold:
                # Low-confidence LLM with no rule backup → further reduce
                final_conf = llm_output.confidence * 0.8
                logger.info(
                    "  Ensemble: rule router has no opinion, LLM confidence low (%.2f < %.2f), reducing to %.2f",
                    llm_output.confidence, conf_threshold, final_conf,
                )
            else:
                logger.info(
                    "  Ensemble: rule router has no opinion (global), using LLM routing (intent=%s, confidence=%.2f)",
                    llm_output.intent, llm_output.confidence,
                )
            return _copy_output(
                llm_output,
                confidence=max(0.0, min(1.0, final_conf)),
            )

        # Case 3: Both have opinions → fuse them
        # 3a. Market: rule router is anchor (regex-based, highly reliable)
        rule_market = normalize_market_tag(rule_output.market)
        llm_market = normalize_market_tag(llm_output.market)
        agent_market = normalize_market_tag(norm_info.get("market"))

        # Priority: rule_router > agent-provided > LLM routing
        if rule_market:
            final_market = rule_market
        elif agent_market:
            final_market = agent_market
        else:
            final_market = llm_market

        market_agreement = (
            not rule_market
            or not llm_market
            or rule_market == llm_market
        )
        if not market_agreement:
            logger.info(
                "  Ensemble: market disagreement (rule=%s, llm=%s), "
                "using rule router market=%s as anchor",
                rule_market,
                llm_market,
                rule_market,
            )

        # 3b. yaml_scopes: cross-validate
        llm_paths = _ordered_unique(llm_output.allowed_yaml_paths)
        rule_paths = _ordered_unique(rule_output.allowed_yaml_paths)
        llm_canonical_paths = _canonical_path_set(llm_paths)
        rule_canonical_paths = _canonical_path_set(rule_paths)
        overlap_canonical_paths = llm_canonical_paths & rule_canonical_paths

        if overlap_canonical_paths:
            final_paths = tuple(
                path for path in _ordered_unique(rule_paths, llm_paths)
                if self._canonicalize_yaml_path(path) in overlap_canonical_paths
            )
            scope_strategy = "intersection"
            confidence_delta = 0.10 if llm_meets_threshold else 0.0
        elif llm_meets_threshold:
            final_paths = _ordered_unique(rule_paths, llm_paths)
            scope_strategy = "union"
            confidence_delta = -0.10
        else:
            final_paths = rule_paths
            scope_strategy = "rule_only"
            confidence_delta = 0.0
            logger.info(
                "  Ensemble: low-confidence LLM routing (%.2f < %.2f) disagrees with rule scope, keeping rule router scope",
                llm_output.confidence,
                conf_threshold,
            )

        # 3c. query_expansions: merge both (deduplicated, order-preserving)
        seen_expansions: set = set()
        merged_expansions: list = []
        # Rule router expansions first (domain-specific, more reliable)
        for exp in rule_output.query_expansions:
            if exp not in seen_expansions:
                seen_expansions.add(exp)
                merged_expansions.append(exp)
        llm_expansions_allowed = llm_meets_threshold or bool(overlap_canonical_paths)
        if llm_expansions_allowed:
            for exp in llm_output.query_expansions:
                if exp not in seen_expansions:
                    seen_expansions.add(exp)
                    merged_expansions.append(exp)
        elif llm_output.query_expansions:
            logger.info(
                "  Ensemble: suppressed %d low-confidence LLM expansions due to scope disagreement",
                len(llm_output.query_expansions),
            )

        # 3d. Confidence: base on max of both, adjust by agreement
        base_confidence = (
            max(llm_output.confidence, rule_output.confidence)
            if llm_meets_threshold
            else rule_output.confidence
        )
        if llm_meets_threshold and not market_agreement:
            confidence_delta -= 0.05
        final_confidence = max(0.0, min(1.0, base_confidence + confidence_delta))

        # 3e. Frequency
        rule_freq = normalize_frequency_tag(rule_output.frequency)
        llm_freq = normalize_frequency_tag(llm_output.frequency)
        agent_freq = normalize_frequency_tag(norm_info.get("frequency"))
        final_frequency = rule_freq or agent_freq or llm_freq

        # 3f. Multi-intent: low-confidence LLM cannot force the query into multi-intent mode.
        is_multi = rule_output.is_multi_intent or (
            llm_output.is_multi_intent and llm_meets_threshold
        )

        # Build merged intents/markets/frequencies tuples
        all_intents: list = []
        seen_intents: set = set()
        metadata_sources = (rule_output, llm_output) if llm_meets_threshold else (rule_output,)
        for src in metadata_sources:
            for i in (src.intents if src.intents else (src.intent,)):
                if i and i not in seen_intents and i != "global":
                    seen_intents.add(i)
                    all_intents.append(i)
        if not all_intents:
            all_intents = [rule_output.intent or llm_output.intent]

        all_markets: list = []
        seen_markets: set = set()
        for src in metadata_sources:
            for m in (src.markets if src.markets else ((src.market,) if src.market else ())):
                nm = normalize_market_tag(m)
                if nm and nm not in seen_markets:
                    seen_markets.add(nm)
                    all_markets.append(nm)
        if final_market and final_market not in seen_markets:
            all_markets.insert(0, final_market)

        prefer_llm_intent = (
            llm_meets_threshold
            and llm_output.intent not in {"", "global", "llm_provided"}
        )
        primary_intent = (
            llm_output.intent
            if prefer_llm_intent
            else (rule_output.intent if rule_output.intent != "global" else llm_output.intent)
        )

        logger.info(
            "  Ensemble result: intent=%s, market=%s, confidence=%.2f (base=%.2f, delta=%+.2f), "
            "scope=%s (%d paths), expansions=%d (rule=%d + llm=%d)",
            primary_intent,
            final_market,
            final_confidence,
            base_confidence,
            confidence_delta,
            scope_strategy,
            len(final_paths),
            len(merged_expansions),
            len(rule_output.query_expansions),
            len(llm_output.query_expansions),
        )

        return RouterOutput(
            intent=primary_intent,
            query_expansions=tuple(merged_expansions),
            allowed_yaml_paths=final_paths,
            market=final_market,
            frequency=final_frequency,
            confidence=final_confidence,
            fallback_strategy="merge",
            intents=tuple(all_intents) if is_multi else (primary_intent,),
            markets=tuple(all_markets) if is_multi else (
                (final_market,) if final_market else ()
            ),
            frequencies=tuple(
                set(filter(None, [
                    *(
                        llm_output.frequencies
                        if llm_meets_threshold else ()
                    ),
                    *(rule_output.frequencies or ()),
                ]))
            ) if is_multi else ((final_frequency,) if final_frequency else ()),
            negation_terms=merged_negation_terms,
        )

    @staticmethod
    def _canonicalize_yaml_path(yaml_path: str) -> str:
        parts = [p for p in str(yaml_path or "").split("/") if p]
        if len(parts) >= 3 and parts[1] == "元数据增强表":
            return "/".join([parts[0], *parts[2:]])
        return "/".join(parts)

    def _expand_yaml_paths_for_filter(self, yaml_paths: List[str]) -> List[str]:
        """扩展 YAML 路径变体，兼容有/无“元数据增强表”两种路径格式。"""
        if not yaml_paths:
            return []
        expanded: List[str] = []
        seen = set()
        for raw_path in yaml_paths:
            path = str(raw_path or "").strip()
            if not path:
                continue
            canonical = self._canonicalize_yaml_path(path)
            variants = [path]
            if canonical:
                variants.append(canonical)
                parts = [p for p in canonical.split("/") if p]
                if len(parts) >= 2:
                    variants.append("/".join([parts[0], "元数据增强表", *parts[1:]]))
            for variant in variants:
                v = variant.strip()
                if not v or v in seen:
                    continue
                seen.add(v)
                expanded.append(v)
        return expanded

    def _prune_global_hits_for_scoped(
        self,
        global_hits: List[Dict[str, Any]],
        scoped_hits: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """当 scoped 命中存在时，移除 global 中与 scoped 实际命中重叠的候选。"""
        if not global_hits or not scoped_hits:
            return global_hits

        scoped_doc_ids = {
            str(hit.get("id") or "").strip()
            for hit in scoped_hits
            if str(hit.get("id") or "").strip()
        }
        scoped_domains_by_path: Dict[str, set] = {}
        for hit in scoped_hits:
            raw_path = str(hit.get("yaml_path") or "").strip()
            if not raw_path:
                continue
            canonical_path = self._canonicalize_yaml_path(raw_path)
            if not canonical_path:
                continue
            hit_market = normalize_market_tag(hit.get("market")) or ""
            hit_frequency = normalize_frequency_tag(hit.get("frequency")) or ""
            # market/frequency 都缺失时不做路径级裁剪，避免误删补充候选。
            if not hit_market and not hit_frequency:
                continue
            scoped_domains_by_path.setdefault(canonical_path, set()).add(
                (hit_market, hit_frequency)
            )

        pruned_hits: List[Dict[str, Any]] = []
        dropped = 0
        for hit in global_hits:
            doc_id = str(hit.get("id") or "").strip()
            if doc_id and doc_id in scoped_doc_ids:
                dropped += 1
                continue

            in_scoped_domain = False
            raw_path = str(hit.get("yaml_path") or "").strip()
            canonical_path = self._canonicalize_yaml_path(raw_path)
            if canonical_path and canonical_path in scoped_domains_by_path:
                hit_market = normalize_market_tag(hit.get("market")) or ""
                hit_frequency = normalize_frequency_tag(hit.get("frequency")) or ""
                for scoped_market, scoped_frequency in scoped_domains_by_path[canonical_path]:
                    market_match = (
                        scoped_market == hit_market if scoped_market else True
                    )
                    frequency_match = (
                        scoped_frequency == hit_frequency if scoped_frequency else True
                    )
                    if market_match and frequency_match:
                        in_scoped_domain = True
                        break

            if in_scoped_domain:
                dropped += 1
                continue

            pruned_hits.append(hit)

        if dropped > 0:
            logger.info(
                "Pruned %d redundant global vector hits overlapped with scoped domain",
                dropped,
            )
        return pruned_hits

    def _build_retrieval_queries(
        self,
        original_query: str,
        norm_info: Dict[str, Any],
    ) -> Tuple[str, str]:
        """构建解耦的 BM25 和 Vector 检索查询。

        BM25 和 Dense Vector 对文本的偏好相反：
        - BM25：喜欢干净的关键词集合，去掉停用词和废话。
        - Vector (BGE)：喜欢连贯的自然语言描述，厌恶硬接的数学符号（如 >10）。

        因此为两路检索分别生成最优查询：
        - bm25_query: normalized_query + keywords + hypothetical_fields（纯关键词堆叠）
        - vector_query: [市场域前缀] + normalized_query + 字段名（连贯语义，无算术符号）

        Returns:
            (bm25_query, vector_query)
        """
        normalized_query = str(norm_info.get("normalized_query") or "").strip()
        if not normalized_query:
            normalized_query = original_query

        cfg = self._rewrite_cfg
        mode = cfg.retrieval_query_mode
        if mode == "original":
            return original_query, original_query
        if mode != "hybrid":
            return normalized_query, normalized_query

        max_length = max(1, int(getattr(cfg, "retrieval_query_max_length", 256)))

        # --- Shared: extract keywords ---
        max_keywords = max(1, int(getattr(cfg, "retrieval_query_max_keywords", 4)))
        raw_keywords = norm_info.get("keywords", [])
        if isinstance(raw_keywords, str):
            raw_keywords = [raw_keywords]
        keywords: List[str] = []
        if isinstance(raw_keywords, (list, tuple)):
            for item in raw_keywords:
                if len(keywords) >= max_keywords:
                    break
                keyword = str(item or "").strip()
                if not keyword:
                    continue
                if keyword in normalized_query:
                    continue
                keywords.append(keyword)

        # --- Shared: extract numerical filter field names ---
        max_num_filters = max(
            1,
            int(getattr(cfg, "retrieval_query_max_numerical_filters", 2)),
        )
        numerical_filters = norm_info.get("numerical_filters", [])
        filter_field_names: List[str] = []
        if isinstance(numerical_filters, list):
            for item in numerical_filters:
                if len(filter_field_names) >= max_num_filters:
                    break
                if not isinstance(item, dict):
                    continue
                field_name = str(item.get("field") or "").strip()
                if field_name and field_name not in filter_field_names:
                    filter_field_names.append(field_name)

        # --- Shared: hypothetical_fields from LLM expansion ---
        hy_fields_raw = norm_info.get("hypothetical_fields", [])
        if isinstance(hy_fields_raw, str):
            hy_fields_raw = [hy_fields_raw]
        hy_fields: List[str] = []
        if isinstance(hy_fields_raw, (list, tuple)):
            for item in hy_fields_raw:
                f = str(item or "").strip()
                if f and f not in hy_fields:
                    hy_fields.append(f)

        # ===== Build BM25 Query (keyword stacking) =====
        # BM25 benefits from clean keyword tokens: normalized_query + keywords +
        # hypothetical_fields + filter field names. No operator symbols.
        bm25_parts: List[str] = []
        bm25_seen: set = set()

        def _bm25_append(part: Any) -> bool:
            token = str(part or "").strip()
            if not token or token in bm25_seen:
                return False
            bm25_seen.add(token)
            bm25_parts.append(token)
            return True

        _bm25_append(normalized_query)
        for kw in keywords:
            _bm25_append(kw)
        for hf in hy_fields:
            _bm25_append(hf)
        if bool(getattr(cfg, "retrieval_query_include_numerical_filters", True)):
            for fn in filter_field_names:
                _bm25_append(fn)
        if bool(getattr(cfg, "retrieval_query_include_time_range", True)):
            _bm25_append(norm_info.get("time_range"))

        bm25_query = self._truncate_query_parts(bm25_parts, max_length) or normalized_query

        # ===== Build Vector Query (coherent natural language) =====
        # Vector (BGE) benefits from fluent text. Add domain soft-prompting prefix
        # and field names (without operator/value) to boost attention on relevant fields.
        vector_parts: List[str] = []
        vector_seen: set = set()

        def _vector_append(part: Any) -> bool:
            token = str(part or "").strip()
            if not token or token in vector_seen:
                return False
            vector_seen.add(token)
            vector_parts.append(token)
            return True

        # Domain soft-prompting: prepend market tag as BGE is sensitive to domain prefixes
        market = str(norm_info.get("market") or "").strip()
        if market:
            _vector_append(f"[{market}]")

        _vector_append(normalized_query)

        for kw in keywords:
            _vector_append(kw)

        # Only append field names (no operator symbols like >10 that pollute semantic space)
        if bool(getattr(cfg, "retrieval_query_include_numerical_filters", True)):
            for fn in filter_field_names:
                _vector_append(fn)

        if bool(getattr(cfg, "retrieval_query_include_time_range", True)):
            _vector_append(norm_info.get("time_range"))

        if bool(getattr(cfg, "retrieval_query_append_original", False)):
            _vector_append(original_query)

        vector_query = self._truncate_query_parts(vector_parts, max_length) or normalized_query

        return bm25_query, vector_query

    @staticmethod
    def _truncate_query_parts(parts: List[str], max_length: int) -> str:
        """Join parts with space, truncating to max_length at part boundaries."""
        if not parts:
            return ""
        query_text = " ".join(parts)
        if len(query_text) <= max_length:
            return query_text

        truncated_parts: List[str] = []
        used = 0
        for part in parts:
            sep = 1 if truncated_parts else 0
            next_len = used + sep + len(part)
            if next_len > max_length:
                break
            if sep:
                used += 1
            truncated_parts.append(part)
            used += len(part)

        if truncated_parts:
            return " ".join(truncated_parts)
        return query_text[:max_length].rstrip()

    def _append_router_expansions(
        self,
        base_query: str,
        query_expansions: Tuple[str, ...],
    ) -> str:
        """Append router expansion terms into retrieval query with de-dup and length cap."""
        query_text = str(base_query or "").strip()
        if not query_text or not query_expansions:
            return query_text

        cfg = self._rewrite_cfg
        max_expansions = max(
            1,
            int(getattr(cfg, "retrieval_query_max_router_expansions", 4)),
        )
        max_length = max(1, int(getattr(cfg, "retrieval_query_max_length", 256)))
        if len(query_text) >= max_length:
            return query_text

        expansions: List[str] = []
        seen = set()
        for item in query_expansions:
            token = str(item or "").strip()
            if not token:
                continue
            if token in query_text:
                continue
            if token in seen:
                continue
            seen.add(token)
            expansions.append(token)
            if len(expansions) >= max_expansions:
                break

        if not expansions:
            return query_text

        merged_parts = [query_text]
        used_length = len(query_text)
        for token in expansions:
            next_len = used_length + 1 + len(token)
            if next_len > max_length:
                break
            merged_parts.append(token)
            used_length = next_len

        return " ".join(merged_parts)

    @staticmethod
    def _candidate_sort_score(candidate: Dict[str, Any]) -> float:
        """候选排序分数（优先使用融合分数，fallback 到原始 distance）。"""
        score = candidate.get("rrf_score")
        if score is None:
            score = candidate.get("linear_score")
        if score is None:
            score = candidate.get("distance", 0.0)
        try:
            return float(score)
        except (TypeError, ValueError):
            return 0.0

    def _truncate_candidates(
        self,
        candidates: List[Dict[str, Any]],
        max_candidates: int,
        already_sorted: bool = False,
    ) -> List[Dict[str, Any]]:
        """限制候选池大小。

        Args:
            candidates: 候选列表
            max_candidates: 最大保留数量
            already_sorted: 若 True（如 RRF 融合后），跳过冗余排序
        """
        if max_candidates <= 0:
            return []
        if len(candidates) <= max_candidates:
            return candidates

        if already_sorted:
            truncated = candidates[:max_candidates]
        else:
            truncated = sorted(
                candidates, key=self._candidate_sort_score, reverse=True
            )[:max_candidates]

        logger.debug(
            "Candidate pool truncated: "
            f"{len(candidates)} -> {max_candidates}"
        )
        return truncated

    def _apply_soft_boosting(
        self,
        candidates: List[Dict[str, Any]],
        router_output: RouterOutput,
        norm_info: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Apply graduated score adjustments based on router alignment.

        3-tier multiplier system (Soft Boosting):
          Tier 1 (aligned):      yaml_path ∈ router allowed_yaml_paths → aligned_boost (default 1.30x)
          Tier 2 (same market):  same market, different table            → same_market_factor (default 1.0x)
          Tier 3 (cross market): different market entirely               → cross_market_penalty (default 0.5x)

        For multi-intent queries (is_multi_intent=True), cross-market penalty is
        disabled since multiple markets are expected (e.g., "A股和美股对比").

        This replaces hard filtering with preference signals, ensuring that even if the
        router misroutes, semantically correct candidates can still surface via their
        raw retrieval score.
        """
        if not candidates:
            return candidates

        # Check activation conditions
        router_cfg = self._router_cfg
        min_confidence = float(getattr(router_cfg, "boost_min_confidence", 0.4))
        if router_output.confidence < min_confidence:
            return candidates
        if router_output.intent == "global" and not router_output.allowed_yaml_paths:
            return candidates

        aligned_boost = float(getattr(router_cfg, "aligned_boost", 1.30))
        same_market_factor = float(getattr(router_cfg, "same_market_factor", 1.0))
        cross_market_penalty = float(getattr(router_cfg, "cross_market_penalty", 0.5))

        # Interpolate factors toward 1.0 as confidence drops toward min_confidence.
        # At confidence == 1.0: full factor. At confidence == min_confidence: factor → 1.0.
        conf_range = 1.0 - min_confidence
        if conf_range > 0:
            t = (router_output.confidence - min_confidence) / conf_range
        else:
            t = 1.0
        effective_boost = 1.0 + (aligned_boost - 1.0) * t
        effective_same = 1.0 + (same_market_factor - 1.0) * t
        effective_penalty = 1.0 + (cross_market_penalty - 1.0) * t

        # Build aligned path set (with expanded variants)
        _aligned_paths: set = set()
        if router_output.allowed_yaml_paths:
            _aligned_paths.update(router_output.allowed_yaml_paths)
            _aligned_paths.update(
                self._expand_yaml_paths_for_filter(router_output.allowed_yaml_paths)
            )

        # Determine router market(s) for cross-market penalty.
        # For multi-intent queries, collect ALL expected markets to avoid
        # penalizing the "other" market in a comparison query.
        router_markets: set = set()
        if router_output.is_multi_intent and router_output.markets:
            for m in router_output.markets:
                nm = normalize_market_tag(m)
                if nm:
                    router_markets.add(nm)
        else:
            single_market = normalize_market_tag(
                norm_info.get("market") or router_output.market
            )
            if single_market:
                router_markets.add(single_market)

        counts = {"aligned": 0, "same_market": 0, "cross_market": 0}
        for c in candidates:
            c_path = c.get("yaml_path", "")
            is_aligned = (
                bool(_aligned_paths)
                and (
                    c_path in _aligned_paths
                    or any(
                        c_path.endswith(p.split("/")[-1])
                        for p in _aligned_paths
                        if "/" in p
                    )
                )
            )

            if is_aligned:
                factor = effective_boost
                counts["aligned"] += 1
            elif not router_markets:
                # No market info → no penalty
                continue
            else:
                c_market = normalize_market_tag(c.get("market"))
                if not c_market or c_market in router_markets:
                    factor = effective_same
                    counts["same_market"] += 1
                else:
                    factor = effective_penalty
                    counts["cross_market"] += 1

            if abs(factor - 1.0) < 1e-9:
                continue
            for score_key in ("rrf_score", "linear_score", "distance"):
                if c.get(score_key) is not None:
                    c[score_key] = c[score_key] * factor
                    break

        if any(v > 0 for v in counts.values()):
            logger.info(
                "Soft boosting (confidence=%.2f, t=%.2f, multi_intent=%s): "
                "aligned=%d (×%.2f), same_market=%d (×%.2f), cross_market=%d (×%.2f)",
                router_output.confidence,
                t,
                router_output.is_multi_intent,
                counts["aligned"],
                effective_boost,
                counts["same_market"],
                effective_same,
                counts["cross_market"],
                effective_penalty,
            )

        return candidates

    async def _federated_multi_intent_recall(
        self,
        router_output: RouterOutput,
        norm_info: Dict[str, Any],
        bm25_query: str,
        retrieval_top_k: int,
    ) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        """Federated search for multi-intent queries: run parallel per-market retrieval.

        When a query involves multiple markets (e.g., "A股和美股科技股涨幅对比"),
        instead of mixing all markets into a single retrieval pool (where one market's
        longer descriptions can crowd out the other), we run independent BM25 searches
        per market and merge the results with guaranteed minimum representation.

        Returns:
            Dict mapping source label to hit list, or None if federated search is
            not applicable (single intent, disabled, etc.).
        """
        router_cfg = self._router_cfg
        if not bool(getattr(router_cfg, "enable_federated_search", True)):
            return None
        if not router_output.is_multi_intent:
            return None

        # Deduplicate markets (preserve order) to avoid redundant parallel searches
        seen_markets: set = set()
        markets: List[str] = []
        for m in (router_output.markets or ()):
            nm = normalize_market_tag(m) or m
            if nm and nm not in seen_markets:
                seen_markets.add(nm)
                markets.append(nm)
        if len(markets) < 2:
            return None

        if self.bm25_retriever is None:
            return None

        min_per_leg = int(getattr(router_cfg, "federated_min_per_leg", 3))
        per_leg_top_k = max(min_per_leg, retrieval_top_k // len(markets))

        logger.info(
            "Federated search: %d markets %s, per_leg_top_k=%d",
            len(markets),
            markets,
            per_leg_top_k,
        )

        loop = asyncio.get_running_loop()

        async def _search_market_leg(market: str) -> List[Dict[str, Any]]:
            market_filter = market_filter_values(market) or {market}

            def _run():
                return self._bm25_search(
                    bm25_query,
                    per_leg_top_k,
                    market=market_filter,
                )

            hits = await loop.run_in_executor(None, _run)
            for hit in hits:
                hit["_federated_market"] = market
            return hits

        leg_results = await asyncio.gather(
            *(_search_market_leg(m) for m in markets)
        )

        result: Dict[str, List[Dict[str, Any]]] = {}
        for market, hits in zip(markets, leg_results):
            label = f"federated_{market}"
            result[label] = hits
            logger.info(
                "  Federated leg %s: %d candidates",
                market,
                len(hits),
            )

        return result

    async def _two_stage_retrieval(
        self,
        query_text: str,
        router_output: RouterOutput,
        max_candidates: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """两阶段检索：先召回表，再在表内召回列"""
        # 只从子配置读取，不再回退到不存在的顶层字段
        table_top_m = int(getattr(self._two_stage_cfg, "table_top_m", 100))
        col_top_k_per_table = int(
            getattr(self._two_stage_cfg, "col_top_k_per_table", 5)
        )
        if max_candidates is None:
            max_candidates = table_top_m * col_top_k_per_table
        max_candidates = int(max_candidates)
        if max_candidates <= 0:
            return []

        # 确定候选表的 yaml_paths（按 canonical table 分组，组内保存路径变体）
        # 这样可避免同一表（canonical 相同）被重复检索两次，降低时延并避免重复结果提前占满配额。
        candidate_table_path_filters: List[List[str]] = []
        table_path_variants_by_canonical: Dict[str, List[str]] = {}
        table_path_seen_by_canonical: Dict[str, set] = {}

        def _add_yaml_path(path: str):
            raw_path = str(path or "").strip()
            if not raw_path:
                return
            canonical = self._canonicalize_yaml_path(raw_path) or raw_path
            variants = self._expand_yaml_paths_for_filter([raw_path]) or [raw_path]

            if canonical not in table_path_variants_by_canonical:
                table_path_variants_by_canonical[canonical] = []
                table_path_seen_by_canonical[canonical] = set()
                candidate_table_path_filters.append(
                    table_path_variants_by_canonical[canonical]
                )

            variant_list = table_path_variants_by_canonical[canonical]
            seen = table_path_seen_by_canonical[canonical]
            for variant in variants:
                v = str(variant or "").strip()
                if not v or v in seen:
                    continue
                seen.add(v)
                variant_list.append(v)

        # 如果 router 已经限定了路径，直接使用
        if router_output.allowed_yaml_paths:
            for yaml_path in self._expand_yaml_paths_for_filter(
                router_output.allowed_yaml_paths
            ):
                _add_yaml_path(yaml_path)

        # Stage A: 表级检索
        table_hits = await self.vector_retriever.search(
            query_text=query_text,
            top_k=table_top_m,
            doc_type="table",
        )

        for hit in table_hits:
            yaml_path = hit.get("yaml_path", "")
            _add_yaml_path(yaml_path)

        if not candidate_table_path_filters:
            return []

        # Stage B: 分批并发检索列（并发提速 + 保留提前截断，避免无效请求）
        search_concurrency = int(getattr(self._two_stage_cfg, "table_query_concurrency", 4))
        search_concurrency = max(1, search_concurrency)

        async def _search_columns_in_table(yaml_paths: List[str]) -> List[Dict[str, Any]]:
            try:
                return await self.vector_retriever.search(
                    query_text=query_text,
                    top_k=col_top_k_per_table,
                    doc_type="column",
                    yaml_paths=yaml_paths,
                )
            except Exception as e:
                logger.warning(
                    "Two-stage column search failed for %s: %s",
                    ",".join(yaml_paths[:2]) if yaml_paths else "<empty>",
                    e,
                )
                return []

        def _hit_score(hit: Dict[str, Any]) -> float:
            try:
                return float(hit.get("distance", 0.0))
            except (TypeError, ValueError):
                return 0.0

        deduped_hits_by_id: Dict[str, Dict[str, Any]] = {}
        for start in range(0, len(candidate_table_path_filters), search_concurrency):
            batch_path_filters = candidate_table_path_filters[start : start + search_concurrency]
            column_hits_by_table = await asyncio.gather(
                *(
                    _search_columns_in_table(yaml_paths)
                    for yaml_paths in batch_path_filters
                )
            )
            for column_hits in column_hits_by_table:
                if not column_hits:
                    continue
                for hit in column_hits:
                    doc_id = hit.get("id", "")
                    if not doc_id:
                        continue
                    previous = deduped_hits_by_id.get(doc_id)
                    if previous is None or _hit_score(hit) > _hit_score(previous):
                        deduped_hits_by_id[doc_id] = hit
                if len(deduped_hits_by_id) >= max_candidates:
                    sorted_hits = sorted(
                        deduped_hits_by_id.values(),
                        key=_hit_score,
                        reverse=True,
                    )
                    return sorted_hits[:max_candidates]

        sorted_hits = sorted(
            deduped_hits_by_id.values(),
            key=_hit_score,
            reverse=True,
        )
        return sorted_hits[:max_candidates]

    def _bm25_search(
        self,
        query_text: str,
        top_k: int,
        yaml_paths: Optional[List[str]] = None,
        market: "Optional[str | set[str]]" = None,
        frequency: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """BM25 检索（支持 Router 过滤条件下推，market 支持多市场软路由）"""
        if self.bm25_retriever is None:
            return []

        try:
            hits = self.bm25_retriever.search(
                query_text=query_text,
                top_k=top_k,
                filter_expr="doc_type=column",
                yaml_paths=yaml_paths,
                market=market,
                frequency=frequency,
            )
            if yaml_paths:
                logger.info(
                    f"BM25 scoped search: {len(hits)} hits "
                    f"(yaml_paths={len(yaml_paths)}, market={market}, freq={frequency})"
                )
            return hits
        except Exception as e:
            logger.warning(f"BM25 search failed: {e}")
            return []

    async def close(self):
        """关闭所有客户端连接"""
        # 关闭向量检索客户端
        if hasattr(self.vector_retriever, "close"):
            await self.vector_retriever.close()

        # 关闭BM25 retriever
        if self.bm25_retriever is not None and hasattr(self.bm25_retriever, "close"):
            close_result = self.bm25_retriever.close()
            if asyncio.iscoroutine(close_result):
                await close_result

        logger.info("RecallPipeline closed (all components)")
