#!/usr/bin/env python3
"""
OpenClaw bridge for augmented-financial-data-query.

This runner exposes pure-JSON wrappers around the existing Python modules so
OpenClaw tools do not need to parse human-readable CLI output.
"""

import argparse
import asyncio
import contextlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.fin_sql_executor import download_fin_sql_result, preview_fin_sql_result
from scripts.meta_retriever import MetaRetriever
from scripts.wencai_search import WencaiSearchClient


def _read_payload() -> Dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Tool payload must be a JSON object.")
    return payload


def _result_exit_code(result: Dict[str, Any]) -> int:
    if "success" in result:
        return 0 if result.get("success") else 1
    if result.get("status") == "error":
        return 1
    return 0


async def _run_context_search(payload: Dict[str, Any]) -> Dict[str, Any]:
    timeout = float(payload.get("timeout") or os.getenv("WENCAI_TIMEOUT", "60"))
    days = payload.get("days")
    time_start = None
    time_end = None

    if days is not None:
        now_ts = datetime.now().timestamp()
        time_end = int(now_ts * 1000)
        time_start = int((now_ts - int(days) * 86400) * 1000)

    client = WencaiSearchClient(base_url=payload.get("host"), timeout=timeout)
    try:
        return await client.search(
            query=payload["query"],
            channels=payload.get("channels"),
            preset=payload.get("preset"),
            size=int(payload.get("size", 10)),
            offset=int(payload.get("offset", 0)),
            need_content=bool(payload.get("need_content", False)),
            time_start=time_start,
            time_end=time_end,
            stock_code=payload.get("stock_code"),
        )
    finally:
        await client.close()


async def _run_schema_retrieve(payload: Dict[str, Any]) -> Dict[str, Any]:
    top_k = int(payload.get("top_k", 10))
    retrieval_top_k = int(payload.get("retrieval_top_k", max(top_k, 50)))

    retriever = MetaRetriever(
        enable_router=bool(payload.get("enable_router", True)),
        enable_two_stage=payload.get("enable_two_stage"),
        enable_hybrid=payload.get("enable_hybrid"),
        bm25_index_dir=payload.get("bm25_index_dir"),
        bm25_userdict_path=payload.get("bm25_userdict_path"),
        top_k=top_k,
        retrieval_top_k=retrieval_top_k,
    )
    try:
        routing = payload.get("routing")
        if routing is not None and not isinstance(routing, dict):
            raise ValueError("routing must be a JSON object when provided.")

        result = await retriever.search(
            query=payload["query"],
            top_k=top_k,
            normalized_query=payload.get("normalized_query"),
            market=payload.get("market"),
            frequency=payload.get("frequency"),
            llm_routing=routing,
            core_indicator=payload.get("core_indicator"),
            keywords=payload.get("keywords"),
            time_range=payload.get("time_range"),
            numerical_filters=payload.get("numerical_filters"),
        )
        return result.to_dict()
    finally:
        await retriever.close()


async def _run_sql_execute(payload: Dict[str, Any]) -> Dict[str, Any]:
    sql = payload["sql"]
    action = payload["action"]

    if action == "preview":
        return await preview_fin_sql_result(sql)

    if action == "download":
        project_path = (
            payload.get("project_path")
            or os.getenv("DEFAULT_DOWNLOAD_PROJECT_PATH")
            or str(REPO_ROOT)
        )
        return await download_fin_sql_result(sql, project_path)

    raise ValueError(f"Unsupported action: {action}")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenClaw JSON tool bridge for augmented-financial-data-query"
    )
    parser.add_argument(
        "--tool",
        required=True,
        choices=["context_search", "schema_retrieve", "sql_execute"],
        help="Bridge action to execute",
    )
    args = parser.parse_args()

    try:
        payload = _read_payload()
        with contextlib.redirect_stdout(sys.stderr):
            if args.tool == "context_search":
                result = await _run_context_search(payload)
            elif args.tool == "schema_retrieve":
                result = await _run_schema_retrieve(payload)
            else:
                result = await _run_sql_execute(payload)
    except Exception as exc:
        result = {
            "success": False,
            "tool": args.tool,
            "error": str(exc),
        }
        print(json.dumps(result, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return _result_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
