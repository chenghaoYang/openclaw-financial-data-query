#!/usr/bin/env python3
"""
Meta Retriever for augmented-financial-data-query.

CLI entry point for augmented recall (vector + BM25 hybrid retrieval).
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from recall.config import RecallConfig
from recall.pipeline import RecallPipeline


@dataclass
class CandidateColumn:
    doc_id: str
    yaml_path: str
    column_name: str
    column_alias: str
    table_name: str
    table_alias: str
    score: float
    market: str = ""
    frequency: str = ""
    source: str = "unknown"
    sql_column_ref: str = ""
    value_source: str = ""


@dataclass
class CandidateTable:
    yaml_path: str
    table_name: str
    table_alias: str
    market: str = ""
    frequency: str = ""
    columns: List[CandidateColumn] = field(default_factory=list)
    avg_score: float = 0.0
    synthetic: bool = False  # True if injected as companion, not from retrieval


@dataclass
class SearchResult:
    status: str
    query: str
    telemetry: Dict[str, Any]
    decision: Dict[str, Any]
    candidate_columns: List[CandidateColumn]
    candidate_tables: List[CandidateTable]
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "query": self.query,
            "telemetry": self.telemetry,
            "decision": self.decision,
            "candidate_columns": [asdict(c) for c in self.candidate_columns],
            "candidate_tables": [
                {
                    "yaml_path": t.yaml_path,
                    "table_name": t.table_name,
                    "table_alias": t.table_alias,
                    "market": t.market,
                    "frequency": t.frequency,
                    "avg_score": t.avg_score,
                    "synthetic": t.synthetic,
                    "columns": [asdict(c) for c in t.columns],
                }
                for t in self.candidate_tables
            ],
            "error": self.error,
        }


# Companion table map: fact table suffix -> list of companion yaml paths
_COMPANION_TABLE_MAP: Dict[str, List[str]] = {
    "stock_astock_mkt_daily_trans.yaml": [
        "股票/stock_astock_basic_info.yaml",
        "股票/stock_astock_latest_index.yaml",
    ],
    "stock_astock_latest_index.yaml": [
        "股票/stock_astock_mkt_daily_trans.yaml",
        "股票/stock_astock_basic_info.yaml",
    ],
    "stock_astock_company_financial_data.yaml": [
        "股票/stock_astock_basic_info.yaml",
        "股票/stock_astock_mkt_daily_trans.yaml",
        "股票/stock_astock_latest_index.yaml",
    ],
    "stock_astock_company_financial_data_new.yaml": [
        "股票/stock_astock_basic_info.yaml",
        "股票/stock_astock_mkt_daily_trans.yaml",
        "股票/stock_astock_latest_index.yaml",
    ],
    "stock_astock_shareholding_insitutions.yaml": [
        "股票/stock_astock_basic_info.yaml",
        "股票/stock_astock_latest_index.yaml",
    ],
    "stock_astock_institutional_stat.yaml": [
        "股票/stock_astock_basic_info.yaml",
        "股票/stock_astock_latest_index.yaml",
    ],
    "stock_astock_institutional_research_stat.yaml": [
        "股票/stock_astock_charts.yaml",
        "股票/stock_astock_latest_index.yaml",
    ],
    "stock_astock_increase_decrease.yaml": [
        "股票/stock_astock_basic_info.yaml",
        "股票/stock_astock_latest_index.yaml",
        "股票/stock_astock_repurchase_of_shares.yaml",
    ],
    "stock_astock_repurchase_of_shares.yaml": [
        "股票/stock_astock_basic_info.yaml",
        "股票/stock_astock_latest_index.yaml",
        "股票/stock_astock_increase_decrease.yaml",
    ],
    "stock_astock_ipo.yaml": [
        "股票/stock_astock_basic_info.yaml",
        "股票/stock_astock_latest_index.yaml",
    ],
    "stock_astock_divestiture.yaml": [
        "股票/stock_astock_latest_index.yaml",
    ],
    "stock_astock_pledge_stat.yaml": [
        "股票/stock_astock_basic_info.yaml",
    ],
    "convertiblebond_basic_info.yaml": [
        "股票/stock_astock_basic_info.yaml",
        "股票/stock_astock_financing.yaml",
    ],
    "convertiblebond_payments_and_redemptions.yaml": [
        "可转债/convertiblebond_basic_info.yaml",
        "股票/stock_astock_basic_info.yaml",
        "股票/stock_astock_financing.yaml",
    ],
    "stock_hkstock_mkt_daily_trans.yaml": [
        "港股/stock_hkstock_basic_info.yaml",
    ],
    "futu_mkt_daily_quo.yaml": [
        "期货/futu_contract_info.yaml",
    ],
    "futu_mkt_weekly_quo.yaml": [
        "期货/futu_contract_info.yaml",
    ],
    "futu_mkt_monthly_quo.yaml": [
        "期货/futu_contract_info.yaml",
    ],
    "futu_mkt_minute_quo.yaml": [
        "期货/futu_contract_info.yaml",
    ],
    "fund_mkt_daily_trans.yaml": [
        "基金/fund_basic_info.yaml",
    ],
    "fund_shares_size.yaml": [
        "基金/fund_basic_info.yaml",
        "基金/fund_mkt_daily_trans.yaml",
        "基金/fund_mkt_daily_trans_latest.yaml",
    ],
    "fund_comprehensive_diagnosis.yaml": [
        "基金/fund_basic_info.yaml",
        "基金/fund_mkt_daily_trans.yaml",
        "基金/fund_mkt_daily_trans_latest.yaml",
    ],
    "fund_dividend_detail.yaml": [
        "基金/fund_basic_info.yaml",
        "基金/fund_mkt_daily_trans_latest.yaml",
    ],
    "fund_company_staff.yaml": [
        "基金公司/fund_company_basic_info.yaml",
        "基金公司/fund_company_latest_index.yaml",
    ],
    "fund_company_shares_size.yaml": [
        "基金公司/fund_company_basic_info.yaml",
        "基金公司/fund_company_latest_index.yaml",
    ],
    "fund_company_asset_allocation.yaml": [
        "基金公司/fund_company_basic_info.yaml",
        "基金公司/fund_company_latest_index.yaml",
    ],
    "fund_manager_return_risk_level.yaml": [
        "基金经理/fundmanager_latest_index.yaml",
    ],
    "fund_manager_basic_info.yaml": [
        "基金经理/fundmanager_latest_index.yaml",
    ],
}


class MetaRetriever:
    """Augmented recall pipeline for financial metadata retrieval.

    Signature is backward-compatible with financial-data-query's MetaRetriever:
    extra kwargs (embedding_model_path, reranker_model_path, device, etc.) are
    accepted via **kwargs and silently ignored since the augmented pipeline uses
    an online vector service instead of local embedding/reranker models.
    """

    def __init__(
        self,
        enable_router: bool = True,
        enable_two_stage: Optional[bool] = None,
        enable_hybrid: Optional[bool] = None,
        bm25_index_dir: Optional[str] = None,
        bm25_userdict_path: Optional[str] = None,
        top_k: int = 10,
        retrieval_top_k: int = 50,
        # Accept (and ignore) params from financial-data-query's MetaRetriever
        # so FinMetaSearchService can instantiate either skill without TypeError.
        **kwargs,
    ):
        if kwargs:
            _ignored = ", ".join(sorted(kwargs.keys()))
            logger.debug(
                f"Augmented MetaRetriever ignoring kwargs from caller: {_ignored}"
            )
        self.enable_router = enable_router
        self.enable_two_stage = enable_two_stage
        self.enable_hybrid = enable_hybrid
        self.bm25_index_dir = bm25_index_dir
        self.bm25_userdict_path = bm25_userdict_path
        self.top_k = int(top_k)
        self.retrieval_top_k = int(retrieval_top_k)
        self._pipeline: Optional[RecallPipeline] = None
        self._initialized = False

    def _build_config(self) -> RecallConfig:
        config = RecallConfig()

        config.top_k = max(1, self.top_k)
        config.retrieval_top_k = max(self.retrieval_top_k, config.top_k)

        config.router.enabled = self.enable_router
        if self.enable_two_stage is not None:
            config.two_stage.enabled = self.enable_two_stage
        if self.enable_hybrid is not None:
            config.hybrid.enabled = self.enable_hybrid

        if self.bm25_index_dir:
            config.bm25_index_path = self.bm25_index_dir
        if self.bm25_userdict_path:
            config.bm25_userdict_path = self.bm25_userdict_path

        return config

    async def _ensure_initialized(self):
        if self._initialized:
            return

        config = self._build_config()

        self._pipeline = RecallPipeline(config)
        self._initialized = True
        logger.info(
            "Augmented MetaRetriever initialized "
            f"(top_k={config.top_k}, retrieval_top_k={config.retrieval_top_k}, "
            f"two_stage={config.two_stage.enabled}, hybrid={config.hybrid.enabled})"
        )

    async def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        normalized_query: Optional[Union[str, Dict[str, Any]]] = None,
        market: Optional[str] = None,
        frequency: Optional[str] = None,
        llm_routing: Optional[Dict[str, Any]] = None,
        core_indicator: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        time_range: Optional[str] = None,
        numerical_filters: Optional[List[Dict[str, Any]]] = None,
    ) -> SearchResult:
        await self._ensure_initialized()
        if self._pipeline is None:
            return SearchResult(
                status="error",
                query=query,
                telemetry={"total_ms": 0, "vector_available": False},
                decision={
                    "suggested_domain": "",
                    "confidence": "low",
                    "reasoning": "Pipeline not initialized",
                },
                candidate_columns=[],
                candidate_tables=[],
                error="Pipeline not initialized",
            )

        start_time = time.monotonic()
        requested_top_k = self.top_k if top_k is None else max(1, int(top_k))
        try:
            # Normalize the normalized_query parameter:
            # FinMetaSearchService passes dict {"market": ...}, CLI passes str.
            nq_str: Optional[str] = None
            if isinstance(normalized_query, dict):
                # Extract market from dict (FinMetaSearchService compat)
                if not market:
                    market = normalized_query.get("market") or None
                nq_str = normalized_query.get("normalized_query") or None
            elif isinstance(normalized_query, str):
                nq_str = normalized_query.strip() or None

            normalized_info = None
            normalized_query_text: Optional[str] = None
            if nq_str:
                normalized_query_text = nq_str
            elif market or frequency:
                # Even without explicit normalized-query, keep agent-provided
                # market/frequency constraints by building a minimal norm_info.
                normalized_query_text = query

            if normalized_query_text:
                normalized_info = self._build_normalized_info(
                    normalized_query=normalized_query_text,
                    original_query=query,
                    market=market,
                    frequency=frequency,
                    core_indicator=core_indicator,
                    keywords=keywords,
                    time_range=time_range,
                    numerical_filters=numerical_filters,
                )

            raw_results = await self._pipeline.recall(
                query=query,
                top_k=requested_top_k,
                normalized_info=normalized_info,
                llm_routing=llm_routing,
            )
            total_ms = int((time.monotonic() - start_time) * 1000)

            # Extract router-allowed paths from pipeline results
            router_allowed_paths: set = set()
            router_confidence: float = 0.0
            for item in raw_results:
                paths = item.get("_router_allowed_paths", [])
                if paths:
                    router_allowed_paths.update(paths)
                    break  # All items carry the same set

            columns = self._parse_columns(raw_results)
            tables = self._aggregate_by_table(columns, router_allowed_paths=router_allowed_paths)
            tables = self._supplement_companion_tables(tables, columns, router_allowed_paths=router_allowed_paths)
            vector_available = self._has_vector_source(raw_results)

            if not columns:
                return SearchResult(
                    status="unavailable",
                    query=query,
                    telemetry={
                        "total_ms": total_ms,
                        "candidate_count": 0,
                        "top1_score": 0.0,
                        "top10_score": 0.0,
                        "top10_coverage": 0.0,
                        "confidence": "low",
                        "vector_available": vector_available,
                    },
                    decision={
                        "suggested_domain": "",
                        "confidence": "low",
                        "reasoning": "Augmented recall returned no candidates",
                    },
                    candidate_columns=[],
                    candidate_tables=[],
                    error="No candidates returned from augmented recall",
                )

            confidence, quality_info = self._confidence(columns, router_allowed_paths=router_allowed_paths)

            return SearchResult(
                status="success",
                query=query,
                telemetry={
                    "total_ms": total_ms,
                    "candidate_count": len(columns),
                    "top1_score": quality_info["top1_score"],
                    "top10_score": quality_info["top10_score"],
                    "top10_coverage": quality_info["top10_coverage"],
                    "confidence": confidence,
                    "vector_available": vector_available,
                },
                decision={
                    "suggested_domain": "",
                    "confidence": confidence,
                    "reasoning": quality_info["reasoning"],
                },
                candidate_columns=columns[:requested_top_k],
                candidate_tables=tables,
            )
        except Exception as e:
            total_ms = int((time.monotonic() - start_time) * 1000)
            logger.exception(f"Augmented MetaRetriever search failed: {e}")
            return SearchResult(
                status="error",
                query=query,
                telemetry={
                    "total_ms": total_ms,
                    "vector_available": self._initialized,
                },
                decision={
                    "suggested_domain": "",
                    "confidence": "low",
                    "reasoning": f"Error: {e}",
                },
                candidate_columns=[],
                candidate_tables=[],
                error=str(e),
            )

    def _parse_columns(self, raw_results: List[Dict[str, Any]]) -> List[CandidateColumn]:
        columns: List[CandidateColumn] = []
        for idx, item in enumerate(raw_results):
            yaml_path = item.get("table_path", "")
            column_name = item.get("column_name", "")
            doc_id = f"{yaml_path}#{column_name or idx}"
            source = str(item.get("source") or item.get("_source") or "unknown")
            columns.append(
                CandidateColumn(
                    doc_id=doc_id,
                    yaml_path=yaml_path,
                    column_name=column_name,
                    column_alias=item.get("column_alias", ""),
                    table_name=item.get("table_name", ""),
                    table_alias=item.get("table_alias", ""),
                    score=float(item.get("score", 0.0)),
                    market=item.get("market", ""),
                    frequency=item.get("frequency", ""),
                    source=source,
                    sql_column_ref=item.get("sql_column_ref", "") or column_name,
                    value_source=item.get("value_source", ""),
                )
            )
        columns.sort(key=lambda c: c.score, reverse=True)
        return columns

    @staticmethod
    def _has_vector_source(raw_results: List[Dict[str, Any]]) -> bool:
        vector_sources = {"global", "scoped", "two_stage"}
        for item in raw_results:
            source = str(item.get("source") or item.get("_source") or "").strip()
            if not source:
                continue
            if any(token in vector_sources for token in source.split("+")):
                return True
        return False

    def _aggregate_by_table(
        self,
        columns: List[CandidateColumn],
        router_allowed_paths: Optional[set] = None,
    ) -> List[CandidateTable]:
        table_map: Dict[str, CandidateTable] = {}
        score_sum_map: Dict[str, float] = {}
        score_count_map: Dict[str, int] = {}

        for col in columns:
            key = col.yaml_path
            if key not in table_map:
                table_map[key] = CandidateTable(
                    yaml_path=col.yaml_path,
                    table_name=col.table_name,
                    table_alias=col.table_alias,
                    market=col.market,
                    frequency=col.frequency,
                    columns=[],
                )
                score_sum_map[key] = 0.0
                score_count_map[key] = 0

            table_map[key].columns.append(col)
            score_sum_map[key] += col.score
            score_count_map[key] += 1

        tables: List[CandidateTable] = []
        for key, table in table_map.items():
            score_count = score_count_map.get(key, 0)
            table.avg_score = (
                score_sum_map.get(key, 0.0) / score_count if score_count > 0 else 0.0
            )
            # Router alignment boost for table ranking
            # NOTE: pipeline.py already applies 1.20x column-level boost which flows
            # into avg_score. This table-level boost is therefore kept small (1.10x)
            # to avoid compounding (total effective ~1.32x).
            if router_allowed_paths:
                is_aligned = any(
                    table.yaml_path.endswith(p.split("/")[-1]) or table.yaml_path == p
                    for p in router_allowed_paths
                )
                if is_aligned:
                    table.avg_score *= 1.10
            table.columns = sorted(table.columns, key=lambda c: c.score, reverse=True)
            tables.append(table)

        tables.sort(key=lambda t: t.avg_score, reverse=True)
        return tables

    @staticmethod
    def _supplement_companion_tables(
        tables: List[CandidateTable],
        columns: List[CandidateColumn],
        router_allowed_paths: Optional[set] = None,
    ) -> List[CandidateTable]:
        """Inject companion tables when main fact tables are present but companions are missing.

        Trigger conditions (strict):
        - Main fact table is already in results
        - Router allowed paths are present (i.e., routing was confident)
        - Companion table is NOT already in results

        Injected tables are marked synthetic=True for downstream distinction.
        """
        if not router_allowed_paths:
            return tables

        present_suffixes = {t.yaml_path.split("/")[-1] for t in tables}
        min_score = min((c.score for c in columns), default=0.0) if columns else 0.0

        companions_to_add: List[CandidateTable] = []
        for table in tables:
            table_suffix = table.yaml_path.split("/")[-1]
            companion_paths = _COMPANION_TABLE_MAP.get(table_suffix)
            if not companion_paths:
                continue
            for comp_path in companion_paths:
                comp_suffix = comp_path.split("/")[-1]
                if comp_suffix in present_suffixes:
                    continue
                companions_to_add.append(CandidateTable(
                    yaml_path=comp_path,
                    table_name=comp_suffix.replace(".yaml", ""),
                    table_alias="",
                    market=table.market,
                    frequency=table.frequency,
                    columns=[],
                    avg_score=min_score * 0.5,
                    synthetic=True,
                ))
                present_suffixes.add(comp_suffix)

        aligned_present = any(
            any(
                table.yaml_path.endswith(path.split("/")[-1]) or table.yaml_path == path
                for path in router_allowed_paths
            )
            for table in tables
        )
        if aligned_present and len(router_allowed_paths) <= 6:
            for path in sorted(router_allowed_paths):
                path = str(path or "").strip()
                if not path.endswith(".yaml"):
                    continue
                path_suffix = path.split("/")[-1]
                if path_suffix in present_suffixes:
                    continue
                companions_to_add.append(CandidateTable(
                    yaml_path=path,
                    table_name=path_suffix.replace(".yaml", ""),
                    table_alias="",
                    market="",
                    frequency="",
                    columns=[],
                    avg_score=min_score * 0.45,
                    synthetic=True,
                ))
                present_suffixes.add(path_suffix)

        # Research-northbound queries often surface adjacent institutional tables first.
        # When router scope explicitly asks for research/charts, inject them as synthetic
        # companions if neighboring institutional tables were retrieved.
        if {
            "股票/stock_astock_institutional_research_stat.yaml",
            "股票/stock_astock_charts.yaml",
        } & set(router_allowed_paths):
            if present_suffixes & {"stock_astock_institutional_stat.yaml", "stock_astock_share_capital.yaml"}:
                for path in (
                    "股票/stock_astock_institutional_research_stat.yaml",
                    "股票/stock_astock_charts.yaml",
                ):
                    path_suffix = path.split("/")[-1]
                    if path_suffix in present_suffixes:
                        continue
                    companions_to_add.append(CandidateTable(
                        yaml_path=path,
                        table_name=path_suffix.replace(".yaml", ""),
                        table_alias="",
                        market="A股",
                        frequency="",
                        columns=[],
                        avg_score=min_score * 0.45,
                        synthetic=True,
                    ))
                    present_suffixes.add(path_suffix)

        if companions_to_add:
            tables = tables + companions_to_add
            logger.info(
                "Supplemented %d companion tables (synthetic): %s",
                len(companions_to_add),
                [t.yaml_path for t in companions_to_add],
            )
        return tables

    def _confidence(
        self,
        columns: List[CandidateColumn],
        router_allowed_paths: Optional[set] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """Assess recall quality based on top-10 candidates collectively.

        The LLM agent always evaluates multiple candidates in context,
        so confidence reflects the overall quality of the top-10 set,
        not just a top1-vs-top2 comparison.

        Returns:
            (confidence_level, quality_info_dict)
        """
        N = 10
        n = min(N, len(columns))
        if n == 0:
            return "low", {
                "top1_score": 0.0, "top10_score": 0.0, "top10_coverage": 0.0,
                "reasoning": "无候选结果",
            }

        scores = [c.score for c in columns[:n]]
        top1 = scores[0]
        top_n = scores[-1]  # score of the Nth (or last) candidate
        coverage = top_n / top1 if top1 > 0 else 0.0  # how close #N is to #1

        regime = "RRF" if top1 < 1.0 else "BM25"
        fmt = ".4f" if top1 < 1.0 else ".2f"
        info = {
            "top1_score": round(top1, 4),
            "top10_score": round(top_n, 4),
            "top10_coverage": round(coverage, 4),
        }

        # Router alignment: check if top-N candidate tables match expected paths
        path_alignment_ratio = 1.0  # Default: no router info -> assume aligned
        top_n_tables: set = set()
        if router_allowed_paths and n > 0:
            # Deduplicate by table (yaml_path) from top-N columns
            top_n_tables = set()
            for c in columns[:n]:
                top_n_tables.add(c.yaml_path)
            aligned_tables = sum(
                1 for t in top_n_tables
                if any(
                    t.endswith(p.split("/")[-1]) or t == p
                    for p in router_allowed_paths
                )
            )
            path_alignment_ratio = aligned_tables / len(top_n_tables) if top_n_tables else 1.0
            info["path_alignment_ratio"] = round(path_alignment_ratio, 4)

        if top1 <= 0:
            info["reasoning"] = f"Top1 score 为零，请补充更具体的筛选条件 [{regime}]"
            return "low", info

        # RRF/linear fusion scores are < 1.0 (typical 0.01-0.25);
        # raw BM25 scores are >> 1.0 (typical 5-30+).
        if top1 < 1.0:
            # --- RRF regime ---
            # Top-1 BM25-only (w=3.0, k=20): 3.0/21 ≈ 0.143
            # Top-10 BM25-only: 3.0/30 = 0.100
            # high: top-10 candidates form a strong cluster
            if top_n >= 0.06 and top1 >= 0.10:
                if router_allowed_paths and path_alignment_ratio < 0.3:
                    info["reasoning"] = (
                        f"Score cluster high (top1={top1:{fmt}}, top{n}={top_n:{fmt}}), "
                        f"but router alignment low ({path_alignment_ratio:.0%} of "
                        f"{len(top_n_tables)} tables match expected paths). "
                        f"Possible domain mismatch [{regime}]"
                    )
                    return "mid", info
                info["reasoning"] = (
                    f"Top-{n} 候选质量高（top1={top1:{fmt}}, "
                    f"top{n}={top_n:{fmt}}, coverage={coverage:.0%}）[{regime}]"
                )
                return "high", info
            if top1 >= 0.05:
                info["reasoning"] = (
                    f"Top1 中等({top1:{fmt}})，top{n} 较弱({top_n:{fmt}})，"
                    f"建议对候选做人工对比 [{regime}]"
                )
                return "mid", info
        else:
            # --- Raw BM25 regime (no fusion) ---
            # high: top-10 scores are clustered (not just one outlier)
            if coverage >= 0.50 and top1 >= 10.0:
                if router_allowed_paths and path_alignment_ratio < 0.3:
                    info["reasoning"] = (
                        f"Score cluster high (top1={top1:{fmt}}, coverage={coverage:.0%}), "
                        f"but router alignment low ({path_alignment_ratio:.0%} of "
                        f"{len(top_n_tables)} tables match expected paths). "
                        f"Possible domain mismatch [{regime}]"
                    )
                    return "mid", info
                info["reasoning"] = (
                    f"Top-{n} 候选聚集度高（top1={top1:{fmt}}, "
                    f"top{n}={top_n:{fmt}}, coverage={coverage:.0%}）[{regime}]"
                )
                return "high", info
            if top1 >= 5.0:
                info["reasoning"] = (
                    f"Top1({top1:{fmt}})，top{n} 覆盖率 {coverage:.0%}，"
                    f"建议对候选做人工对比 [{regime}]"
                )
                return "mid", info

        info["reasoning"] = (
            f"Top1 score 低({top1:{fmt}})，请补充更具体的筛选条件后重试 [{regime}]"
        )
        return "low", info

    @staticmethod
    def _build_normalized_info(
        normalized_query: str, original_query: str,
        market: Optional[str] = None, frequency: Optional[str] = None,
        core_indicator: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        time_range: Optional[str] = None,
        numerical_filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Build norm_info dict from agent-provided normalized query.

        Still uses rule-based enrichments (time parser, numerical filters, market rules)
        but skips LLM API calls.
        """
        from recall.utils.market_rules import (
            detect_explicit_market_tag,
            market_tag_from_query,
            detect_explicit_frequency_tag,
            infer_frequency_tag,
        )
        from recall.utils.time_parser import TimeParser
        from recall.utils.numerical_filter_extractor import NumericalFilterExtractor

        info: Dict[str, Any] = {
            "normalized_query": normalized_query,
            "original_query": original_query,
            "core_indicator": "",
            "keywords": [],
            "market": market or "",
            "time_range": "",
        }

        import re
        from recall.utils.market_taxonomy import normalize_market_tag
        # Parse structured fields from normalized query format: [市场]keyword1 keyword2 core_indicator time_range
        _NQ_MARKET_RE = re.compile(r"^\[([^\]]+)\]\s*")
        _TIME_PATTERN = re.compile(
            r"^(近\d+[日天周月年]|最新|今[日天年]|昨[日天]|本[周月季年]|"
            r"年初以来|\d{4}年.*|上[周月季年]|过去\d+.*)"
        )
        nq_market = ""
        nq_market_match = _NQ_MARKET_RE.match(normalized_query)
        if nq_market_match:
            nq_market = str(nq_market_match.group(1) or "").strip()
        body = _NQ_MARKET_RE.sub("", normalized_query).strip()
        tokens = body.split()
        if tokens and _TIME_PATTERN.match(tokens[-1]):
            time_from_nq = tokens.pop()
            if not info.get("time_range"):
                info["time_range"] = time_from_nq
        if len(tokens) >= 2:
            info["core_indicator"] = tokens[-1]
            info["keywords"] = tokens[:-1]
        elif len(tokens) == 1:
            info["core_indicator"] = tokens[0]

        # Market from normalized-query prefix: [港股]/[美股]/...
        # Priority: explicit argument > normalized-query prefix > rule fallback.
        if not info["market"] and nq_market:
            info["market"] = normalize_market_tag(nq_market) or nq_market

        # Market rules enrichment
        if not info["market"]:
            explicit = detect_explicit_market_tag(original_query)
            if explicit:
                info["market"] = explicit
            else:
                info["market"] = market_tag_from_query(original_query)

        # Frequency enrichment (agent-provided > explicit tag > inferred)
        if frequency:
            info["frequency"] = frequency
        else:
            explicit_freq = detect_explicit_frequency_tag(original_query)
            if explicit_freq:
                info["frequency"] = explicit_freq
            else:
                info["frequency"] = infer_frequency_tag(original_query) or ""

        # Time range enrichment
        try:
            time_result = TimeParser.parse(original_query)
            if time_result is not None:
                if isinstance(time_result, list):
                    info["time_range_structured"] = [
                        {
                            "raw_text": tr.raw_text,
                            "start_date": tr.start_date,
                            "end_date": tr.end_date,
                            "relative_type": tr.relative_type,
                            "relative_value": tr.relative_value,
                            "is_absolute": tr.is_absolute,
                            "frequency_hint": tr.frequency_hint,
                        }
                        for tr in time_result
                    ]
                    # 用第一个时间段的 raw_text 填充 time_range 字符串字段
                    if time_result and not info.get("time_range"):
                        info["time_range"] = time_result[0].raw_text or ""
                    if not info.get("frequency"):
                        for tr in time_result:
                            if tr.frequency_hint:
                                info["frequency"] = tr.frequency_hint
                                break
                else:
                    tr = time_result
                    info["time_range_structured"] = {
                        "raw_text": tr.raw_text,
                        "start_date": tr.start_date,
                        "end_date": tr.end_date,
                        "relative_type": tr.relative_type,
                        "relative_value": tr.relative_value,
                        "is_absolute": tr.is_absolute,
                        "frequency_hint": tr.frequency_hint,
                    }
                    # 用 raw_text 填充 time_range 字符串字段（如"近3日"）
                    if tr.raw_text and not info.get("time_range"):
                        info["time_range"] = tr.raw_text
                    if tr.frequency_hint and not info.get("frequency"):
                        info["frequency"] = tr.frequency_hint
        except Exception as e:
            logger.warning(f"Time range parsing failed: {e}")

        # Numerical filters enrichment
        try:
            constraints = NumericalFilterExtractor.extract(original_query)
            if constraints:
                info["numerical_filters"] = [
                    {
                        "field": c.field,
                        "operator": c.operator,
                        "value": c.value,
                        "unit": c.unit,
                    }
                    for c in constraints
                ]
        except Exception as e:
            logger.warning(f"Numerical filter extraction failed: {e}")

        # CLI-provided structured fields take priority over parsed ones
        if core_indicator is not None:
            info["core_indicator"] = core_indicator
        if keywords is not None:
            info["keywords"] = keywords
        if time_range is not None:
            info["time_range"] = time_range
        if numerical_filters is not None:
            info["numerical_filters"] = numerical_filters

        info["_enriched"] = True
        return info

    async def close(self):
        if self._pipeline is not None:
            await self._pipeline.close()
            self._pipeline = None
        self._initialized = False


async def main():
    parser = argparse.ArgumentParser(
        description="Augmented Financial Data Query - Meta Retriever Adapter"
    )
    parser.add_argument("--query", "-q", type=str, required=True, help="Query text")
    parser.add_argument("--top-k", "-k", type=int, default=10, help="Top-k results")
    parser.add_argument("--pretty", "-p", action="store_true", help="Pretty JSON")
    parser.add_argument("--normalized-query", "-nq", type=str, default=None,
                        help="Pre-normalized query for retrieval (skips LLM normalization)")
    parser.add_argument("--market", "-m", type=str, default=None,
                        help="Market filter (e.g., A股, 港股, 基金)")
    parser.add_argument("--frequency", "-f", type=str, default=None,
                        help="Frequency filter (e.g., 日频, 周频, 月频, 季度, 年频, 时序)")
    parser.add_argument("--routing-json", "-rj", type=str, default=None,
                        help="LLM-provided routing info as JSON string. Format: "
                             '{"intent":"...","yaml_scopes":[...],"query_expansions":[...],"confidence":0.9,"is_comparison":false}')
    parser.add_argument("--core-indicator", type=str, default=None,
                        help="Core indicator extracted from query (e.g., 涨跌幅, 成交额)")
    parser.add_argument("--keywords", type=str, default=None,
                        help="Comma-separated entity keywords (e.g., 贵州茅台,五粮液)")
    parser.add_argument("--time-range", type=str, default=None,
                        help="Time range expression (e.g., 近3日, 2024年Q1)")
    parser.add_argument("--numerical-filters", type=str, default=None,
                        help='JSON array of numerical filters (e.g., [{"field":"PE","operator":"<","value":20.0}])')
    args = parser.parse_args()

    # Parse LLM routing JSON if provided
    llm_routing = None
    if args.routing_json:
        try:
            llm_routing = json.loads(args.routing_json)
            if not isinstance(llm_routing, dict):
                logger.error(
                    "--routing-json must be a JSON object, got %s",
                    type(llm_routing).__name__,
                )
                sys.exit(1)
            logger.info(f"Parsed LLM routing info: intent={llm_routing.get('intent', 'N/A')}, "
                        f"confidence={llm_routing.get('confidence', 'N/A')}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse --routing-json: {e}")
            sys.exit(1)

    # Parse CLI-provided structured fields
    cli_keywords = None
    if args.keywords is not None:
        cli_keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    cli_numerical_filters = None
    if args.numerical_filters is not None:
        try:
            cli_numerical_filters = json.loads(args.numerical_filters)
        except json.JSONDecodeError:
            logger.warning("Invalid --numerical-filters JSON, ignoring: %s", args.numerical_filters)

    retriever = MetaRetriever(top_k=args.top_k)
    try:
        result = await retriever.search(
            query=args.query,
            top_k=args.top_k,
            normalized_query=args.normalized_query,
            market=args.market,
            frequency=args.frequency,
            llm_routing=llm_routing,
            core_indicator=args.core_indicator,
            keywords=cli_keywords,
            time_range=args.time_range,
            numerical_filters=cli_numerical_filters,
        )
        output = result.to_dict()
        print(
            json.dumps(output, ensure_ascii=False, indent=2 if args.pretty else None)
        )
    finally:
        await retriever.close()


if __name__ == "__main__":
    asyncio.run(main())
