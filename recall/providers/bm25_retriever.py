"""BM25 Retriever Provider - 基于 bm25s + jieba 的中文金融领域检索

关键设计决策：
1. 独立于 RetrieverProvider ABC（因为 BM25 用文本查询，不是向量）
2. 返回与 FileRetriever 相同的 hit schema，便于 RRF 融合
3. 单一 tokenize() 函数同时用于索引和查询，确保一致性
4. 支持相同的过滤参数（market, frequency, yaml_paths）
"""

import json
import logging
import re
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

import numpy as np

from ..utils.financial_terms import FINANCIAL_SYNONYMS, REVERSE_SYNONYM_MAP
from .filter_utils import (
    build_filter_indices,
    build_hit_from_meta,
    get_filtered_indices,
    parse_filter_expr,
)

logger = logging.getLogger(__name__)

_BM25_TEMPLATE_PATTERNS = {
    "table_summary": re.compile(r".+数据表，包含金融产品相关的核心指标和维度信息$"),
    "table_description": re.compile(r"^.+ - 金融视图表$"),
    "table_business_meaning": re.compile(r"^金融数据领域视图表：.+，包含.+相关数据$"),
    "column_description": re.compile(
        r"^.+[，,]\s*(?:STRING|DOUBLE|DATE|BOOLEAN|LONG|INTEGER|INT|FLOAT|DECIMAL"
        r"|BIGINT|ARRAY|TIMESTAMP|DATETIME|CHAR|VARCHAR|TEXT)类型$"
    ),
}
_BM25_MAX_EXAMPLE_ITEMS = 20

_RE_BM25_HISTORY_WINDOW = re.compile(
    r"(连续.{0,4}交易日|近\d+[日天周月年]|前天|昨天|\d+日均线|周线|月线|年线|周K|月K|年K|多周期|15分钟|30分钟|60分钟)"
)
_RE_BM25_TECHNICAL_FACT = re.compile(
    r"(MACD|DIF|DEA|KDJ|RSI|BOLL|均线|收盘价|开盘价|最高价|最低价|成交量|成交额|交易额|换手率|放量|缩量|金叉|死叉|涨跌幅|涨幅|跌幅)"
)
_RE_BM25_MULTI_PERIOD = re.compile(r"(周线|月线|年线|周K|月K|年K|多周期)")
_RE_BM25_IPO_PRICE = re.compile(r"(发行价|首发价|IPO发行价|新股发行价|上市发行价)")
_RE_BM25_DIVESTITURE = re.compile(r"(资产剥离|剥离公告|重大资产剥离)")
_RE_BM25_HOLDING_ENTITY = re.compile(
    r"((中央银行|主权基金|养老金|养老基金|贝莱德|高盛|摩根|瑞银|挪威|淡马锡|景顺|富达|社保|保险|QFII|RQFII|刘格菘|张坤|葛兰|傅鹏博|谢治宇)"
    r".{0,8}(新进|加仓|减仓|增持|减持|持仓|持股|买入|卖出))"
)
_RE_BM25_RESEARCH_NORTHBOUND = re.compile(
    r"(机构调研|调研次数).{0,18}(北向资金|陆股通|沪股通|深股通)|(北向资金|陆股通|沪股通|深股通).{0,18}(机构调研|调研次数)"
)
_RE_BM25_SHAREHOLDER_BUYBACK = re.compile(
    r"((股东)?(增减持|增持|减持).{0,12}(回购|回购公告|回购明细)|(回购|回购公告|回购明细).{0,12}(股东)?(增减持|增持|减持))"
)
_RE_BM25_CONCEPT_RANKING = re.compile(
    r"((板块|概念|行业|题材).{0,12}(成交额|交易额|排名|排序|均值|平均|股票|个股))"
)
_RE_BM25_EARNINGS_SURPRISE = re.compile(
    r"(业绩|盈利|净利润|营收|收入).{0,6}(超预期|符合预期|不及预期|低于预期|高于预期|大超预期|可能超预期)"
)
_RE_BM25_CB_REDEMPTION = re.compile(
    r"((可转债|转债).{0,8}(发生|触发|公告|实施)?.{0,6}(赎回|强赎|提前赎回)|(赎回|强赎|提前赎回).{0,8}(可转债|转债))"
)
_RE_BM25_CONTROLLER_PENALTY = re.compile(
    r"(实控人|实际控制人|控股股东|董事长|高管).{0,8}(被查|立案|调查|处罚|罚款|违规)"
)
_RE_BM25_LATEST_FLOW = re.compile(r"(主力资金|资金净流入|资金净流出|大单|特大单)")
_RE_BM25_TOP10_CIRC = re.compile(r"(十大流通股东|前十大流通股东)")
_RE_BM25_MULTI_FACTOR_SCREEN = re.compile(
    r"((流通市值|总市值|市值|停牌|复牌|退市|ST|科创板|创业板).{0,40}(营收|营业收入|净利润|扣非|毛利率|ROE|机构持仓|减持|增持|回购|股东))"
)
_RE_BM25_NO_PLEDGE = re.compile(r"((无|未|没有).{0,3}质押|不含质押|零质押)")
_RE_BM25_NAME_FILTER = re.compile(r"(名字|名称|简称).{0,4}(有|包含|带)")
_RE_BM25_FUND_DIAGNOSIS = re.compile(
    r"((基金|ETF).{0,24}(诊基|夏普|夏普率|排名)|(诊基|夏普|夏普率|排名).{0,24}(基金|ETF))"
)
_RE_BM25_FUND_MONTHLY_DIVIDEND = re.compile(
    r"((基金|ETF).{0,12}(每月|月月|按月).{0,12}(分红|派息)|(分红|派息).{0,12}(每月|月月|按月).{0,12}(基金|ETF))"
)
_RE_BM25_FUND_COMPANY_STAFF = re.compile(r"(基金经理人数|基金经理数量|股票型基金经理人数|经理人数)")
_RE_BM25_FUND_COMPANY_GROWTH = re.compile(r"(规模增长率|管理规模增长率|规模增速|规模增长)")
_RE_BM25_FUND_COMPANY_ASSET = re.compile(
    r"[\u4e00-\u9fffA-Za-z]{2,12}基金.{0,8}(市值|持股市值|股票市值|资产配置)"
)
_RE_BM25_FUND_COMPANY_STOCK_HOLDING = re.compile(
    r"((哪几家|有多少家).{0,4}基金公司.{0,8}(买入|持仓|持有)|(基金公司).{0,8}(买入|持仓|持有))"
)
_RE_BM25_FUND_MANAGER_RANK = re.compile(
    r"((基金经理).{0,12}(最赚钱|收益最差|收益最高|收益最好|收益高|收益低|排名|比较|表现)|(最赚钱|收益最差|收益最高|收益最好|收益高|收益低|排名|比较|表现).{0,12}(基金经理))"
)
_RE_BM25_FUND_MANAGER_SCALE = re.compile(
    r"((基金经理).{0,12}(在管规模|管理规模|年限|任职年限|从业年限|排名)|"
    r"(在管规模|管理规模|基金经理年限|任职年限|从业年限).{0,12}(基金经理))"
)
_RE_BM25_INDEX_HISTORY = re.compile(
    r"((过去\d+年|近\d+年|历年|10年).{0,16}(黄金|指数|上证指数)|(对比).{0,12}(黄金|指数|上证指数))"
)
_RE_BM25_HK_PEV = re.compile(r"(PEV|内含价值)")
_RE_BM25_STOCK_DIVIDEND_GROWTH = re.compile(r"(特别股息|股息|分红).{0,40}(市值).{0,16}(增长|增长率)")
_RE_BM25_FUTURES_OPTION_TECH = re.compile(
    r"(有期权的期货品种|期货品种).{0,24}(分钟|15分钟|30分钟|60分钟).{0,24}(均线|金叉|死叉|斜率)"
)

# ============================================================
# 延迟导入，避免强制依赖
# ============================================================

_import_lock = threading.Lock()
_jieba = None
_bm25s = None


def _has_any_token_id(token_ids: Any) -> bool:
    """检查 token_ids 中是否至少包含一个有效 token id。

    bm25s.get_tokens_ids() 返回 list[ndarray]；此函数兼容嵌套结构。
    """
    if token_ids is None:
        return False
    try:
        if len(token_ids) == 0:
            return False
        for item in token_ids:
            # numpy array 或类似结构：优先用 .size 属性
            item_size = getattr(item, "size", None)
            if item_size is not None:
                if int(item_size) > 0:
                    return True
            else:
                try:
                    if len(item) > 0:
                        return True
                except TypeError:
                    # 无法测量长度，保守返回 True（假设非空）
                    return True
        return False
    except TypeError:
        return True


def _ensure_jieba():
    """延迟加载 jieba"""
    global _jieba
    if _jieba is not None:
        return _jieba
    with _import_lock:
        if _jieba is not None:  # double-check after acquiring lock
            return _jieba
        try:
            import jieba
            _jieba = jieba
        except ImportError:
            raise ImportError("jieba not installed. Run: pip install jieba")
    return _jieba


def _ensure_bm25s():
    """延迟加载 bm25s"""
    global _bm25s
    if _bm25s is not None:
        return _bm25s
    with _import_lock:
        if _bm25s is not None:  # double-check after acquiring lock
            return _bm25s
        try:
            import bm25s
            _bm25s = bm25s
        except ImportError:
            raise ImportError("bm25s not installed. Run: pip install bm25s")
    return _bm25s


# ============================================================
# 金融领域中文 Tokenizer
# ============================================================


class FinancialTokenizer:
    """
    金融领域中文分词器

    使用 jieba.cut_for_search 获得最大召回率
    支持加载用户词典

    关键设计：索引和查询必须使用完全相同的分词逻辑
    - 直接使用 jieba.cut_for_search（不做额外的 Latin/数字提取）
    - 用户词典中的 "5分钟", "QFII", "A股" 等会被 jieba 正确识别
    """

    # 纯标点/空白符号（用于过滤）
    PUNCT_PATTERN = re.compile(r"^[\s\W]+$", re.UNICODE)
    # ASCII schema token (snake_case, ids, etc.)
    ASCII_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_./-]+$")
    ASCII_SPLIT_PATTERN = re.compile(r"[._/\\-]+")
    SHINGLE_SIZES = (4, 5)
    MAX_SHINGLES_PER_TOKEN = 24
    SHINGLE_MIN_LEN = 8

    def __init__(self, userdict_path: Optional[str] = None):
        """
        Args:
            userdict_path: 用户词典路径（UTF-8 编码）
        """
        self._jieba = _ensure_jieba()
        self._initialized = False
        self._userdict_path = userdict_path

    def _ensure_initialized(self):
        """延迟初始化 jieba"""
        if self._initialized:
            return

        # 加载用户词典
        if self._userdict_path and Path(self._userdict_path).exists():
            self._jieba.load_userdict(self._userdict_path)
            logger.info(f"Loaded user dictionary: {self._userdict_path}")
        elif self._userdict_path:
            logger.warning(f"User dictionary not found: {self._userdict_path}")

        self._initialized = True

    def tokenize(self, text: str, deduplicate: bool = False) -> List[str]:
        """
        分词（用于索引和查询）

        使用 cut_for_search 模式：
        - 对长词生成 bigram/trigram 子词
        - 提高召回率（"中国科学院" → ["中国", "科学", "学院", "科学院", "中国科学院"]）
        - 用户词典中的金融术语会被正确识别（如 "5分钟", "QFII", "A股"）

        Args:
            text: 输入文本
            deduplicate: 是否去重。默认 False 以保留 BM25 所需的词频
                         (TF) 信号。查询分词可传 True 去重。

        Returns:
            分词列表
        """
        self._ensure_initialized()

        if not text or not text.strip():
            return []

        tokens = []
        seen: Optional[set] = set() if deduplicate else None

        def _append_token(tok: str):
            if not tok:
                return
            if seen is not None:
                if tok in seen:
                    return
                seen.add(tok)
            tokens.append(tok)

        # 直接使用 jieba.cut_for_search，不做额外处理
        # 用户词典中的混合词（如 "5分钟", "A股"）会被正确识别
        for token in self._jieba.cut_for_search(text):
            token = token.strip()
            # 过滤空白和纯标点
            if not token:
                continue
            if self.PUNCT_PATTERN.match(token):
                continue
            _append_token(token)

            # ASCII token 额外拆分 + shingles（用于 schema / code）
            if self.ASCII_TOKEN_PATTERN.match(token):
                # Add lowercase variant to make acronym matching case-insensitive
                token_lower = token.lower()
                if token_lower != token:
                    _append_token(token_lower)

                # Split by separators to boost recall for snake_case, dotted paths
                for part in self.ASCII_SPLIT_PATTERN.split(token):
                    part = part.strip()
                    if not part:
                        continue
                    if part == token:
                        continue
                    _append_token(part)
                    part_lower = part.lower()
                    if part_lower != part:
                        _append_token(part_lower)

                # Add character shingles for long ASCII tokens
                if len(token_lower) >= self.SHINGLE_MIN_LEN and (
                    re.search(r"\d", token_lower) or "_" in token_lower
                ):
                    shingle_count = 0
                    for k in self.SHINGLE_SIZES:
                        if len(token_lower) < k:
                            continue
                        for i in range(0, len(token_lower) - k + 1):
                            shingle = token_lower[i : i + k]
                            _append_token(shingle)
                            shingle_count += 1
                            if shingle_count >= self.MAX_SHINGLES_PER_TOKEN:
                                break
                        if shingle_count >= self.MAX_SHINGLES_PER_TOKEN:
                            break

        return tokens

    def tokenize_batch(
        self, texts: List[str], max_workers: int = 0
    ) -> List[List[str]]:
        """批量分词（用于索引，不去重以保留 TF 信号）

        Args:
            texts: 待分词文本列表
            max_workers: 并行 worker 数。0 = 自动（>500 文档时启用），
                         1 = 单线程，>1 = 指定线程数。
                         jieba 的 C 扩展在调用时释放 GIL，因此
                         ThreadPoolExecutor 可以获得真实并行加速。
        """
        self._ensure_initialized()

        n = len(texts)
        if max_workers == 0:
            max_workers = min(4, max(1, n // 500)) if n > 500 else 1

        if max_workers > 1 and n > 100:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                return list(pool.map(self.tokenize, texts))

        return [self.tokenize(text, deduplicate=False) for text in texts]


# ============================================================
# BM25 文档文本构建器
# ============================================================


def build_bm25_text(meta: Dict[str, Any]) -> str:
    """
    从 metadata 构建用于 BM25 索引的文本

    设计原则：
    1. 重复关键字段（column_alias, index_name）以提高权重
    2. 包含所有可能的搜索关键词
    3. 加入领域近义词扩展，提高召回
    """
    parts: List[str] = []
    doc_type = meta.get("doc_type", "column")

    if doc_type == "metric":
        metric_name = meta.get("metric_name", "") or meta.get("name", "")
        if metric_name:
            parts.extend([metric_name] * 3)

        metric_synonyms = meta.get("metric_synonyms") or meta.get("synonyms") or []
        if isinstance(metric_synonyms, list):
            parts.extend(metric_synonyms)

        model_alias = meta.get("model_alias", "")
        model_name = meta.get("model", "")
        for token in [model_alias, model_name]:
            if token:
                parts.extend([token] * 2)

        for field in [
            "measure",
            "dimension",
            "time_grain",
            "column_name",
            "description",
        ]:
            val = meta.get(field)
            if val:
                parts.append(str(val))

        for field in ["market", "frequency", "domain"]:
            val = meta.get(field)
            if val:
                parts.append(str(val))

        return " ".join(parts)

    if doc_type == "relationship":
        rel_name = meta.get("relationship_name", "") or meta.get("name", "")
        if rel_name:
            parts.extend([rel_name] * 2)

        for field in [
            "from_model",
            "to_model",
            "from_model_alias",
            "to_model_alias",
        ]:
            val = meta.get(field)
            if val:
                parts.extend([str(val)] * 2)

        join_keys = meta.get("join_keys") or []
        if isinstance(join_keys, list):
            parts.extend(join_keys)

        for field in ["cardinality", "description", "market", "frequency", "domain"]:
            val = meta.get(field)
            if val:
                parts.append(str(val))

        return " ".join(parts)

    # 核心字段：列别名和指标名（高权重）
    # model_field=否 system columns get lower weight (1x vs 3x)
    column_alias = meta.get("column_alias", "")
    model_field = meta.get("model_field", "")
    alias_weight = 1 if model_field == "否" else 3
    if column_alias:
        parts.extend([column_alias] * alias_weight)
        # Disambiguation: compound token for high-frequency aliases
        table_alias_early = meta.get("table_alias", "")
        if table_alias_early:
            parts.append(f"{table_alias_early}的{column_alias}")
        # 近义词扩展（whole-token matching，避免 "监管机构" 误匹配 "机构"）
        jieba = _ensure_jieba()
        alias_tokens = set(jieba.cut(column_alias))
        for key, synonyms in FINANCIAL_SYNONYMS.items():
            if key in alias_tokens or key == column_alias:
                parts.extend(synonyms)

    index_name = meta.get("index_name", "")
    if index_name:
        index_name_clean = index_name.replace("@", " ").replace("(虚拟表)", "")
        parts.extend([index_name_clean] * 3)
        # 近义词扩展（whole-token matching，避免子串误匹配）
        jieba = _ensure_jieba()
        index_tokens = set(jieba.cut(index_name_clean))
        for key, synonyms in FINANCIAL_SYNONYMS.items():
            if key in index_tokens or key == index_name_clean:
                parts.extend(synonyms)

    # 别名扩展（多别名/联接索引）
    column_aliases = meta.get("column_aliases") or []
    if isinstance(column_aliases, list):
        parts.extend(column_aliases)

    linking_index = meta.get("linking_index")
    general_linking_index = meta.get("general_linking_index")
    if linking_index:
        parts.append(str(linking_index))
    if general_linking_index:
        parts.append(str(general_linking_index))

    # example_all: valuable enum values for exact matching (e.g., "上交所;深交所")
    example_all = meta.get("example_all", "")
    if example_all:
        example_items = [x.strip() for x in str(example_all).split(";") if x.strip()]
        parts.extend(example_items[:_BM25_MAX_EXAMPLE_ITEMS])

    # 表别名和表名（中权重，重复 2 次）
    table_alias = meta.get("table_alias", "")
    if table_alias:
        parts.extend([table_alias] * 2)

    table_name = meta.get("table_name", "")
    if table_name:
        parts.append(table_name)

    # 技术字段
    column_name = meta.get("column_name", "")
    if column_name:
        parts.append(column_name)

    # Aggregated column aliases for table-level docs (enriched table text)
    column_aliases_agg = meta.get("column_aliases_agg") or []
    if isinstance(column_aliases_agg, list):
        parts.extend(column_aliases_agg[:30])

    # 标签和维度字段
    for field in [
        "market",
        "frequency",
        "domain",
        "unit",
        "column_description",
        "table_summary",
        "mdl_model",
        "mdl_model_alias",
        "mdl_time_grain",
    ]:
        val = meta.get(field, "")
        if val:
            val_str = str(val)
            pattern = _BM25_TEMPLATE_PATTERNS.get(field)
            if pattern and pattern.match(val_str.strip()):
                continue
            parts.append(val_str)

    mdl_tags = meta.get("mdl_tags") or []
    if isinstance(mdl_tags, list):
        parts.extend(mdl_tags)

    mdl_expose_columns = meta.get("mdl_expose_columns") or []
    if isinstance(mdl_expose_columns, list):
        parts.extend(mdl_expose_columns)

    # Add schema_tokens for entries missing index_name (low-weight 1x supplementary)
    if not meta.get("index_name"):
        for token in meta.get("schema_tokens", []):
            if token and token not in parts:
                parts.append(token)

    # Add query_hints
    for hint in meta.get("query_hints", []):
        if hint and hint not in parts:
            parts.append(hint)

    return " ".join(parts)


# ============================================================
# Vector embedding 文本构建器
# ============================================================

# Pattern for opaque column names (e.g., bd999, se001, f001_se)
_OPAQUE_COLUMN_PATTERN = re.compile(
    r"^[a-z]{1,4}\d{2,4}(?:_[a-z]{1,4}\d{0,4})?$", re.IGNORECASE
)


def build_vector_text(meta: Dict[str, Any]) -> str:
    """从 metadata 构建用于向量嵌入 (embedding) 的富文本。

    与 build_bm25_text() 不同：
    - 不做词频重复（embedding 不依赖 TF）
    - 包含自然语言描述、同义词、别名等
    - 过滤空值、去重、拼接为干净的空格分隔文本
    """
    parts: List[str] = []
    seen: set = set()

    def _add(text: Any) -> None:
        """Add a non-empty, non-duplicate string to parts."""
        if text is None:
            return
        s = str(text).strip()
        if not s:
            return
        if s not in seen:
            seen.add(s)
            parts.append(s)

    doc_type = meta.get("doc_type", "column")

    if doc_type == "metric":
        # Metric entries
        _add(meta.get("metric_name") or meta.get("name"))
        for syn in (meta.get("metric_synonyms") or meta.get("synonyms") or []):
            _add(syn)
        _add(meta.get("model_alias"))
        _add(meta.get("model"))
        for field in ["measure", "dimension", "time_grain", "column_name",
                       "description", "market", "frequency", "domain"]:
            _add(meta.get(field))
        return " ".join(parts)

    if doc_type == "relationship":
        _add(meta.get("relationship_name") or meta.get("name"))
        for field in ["from_model", "to_model", "from_model_alias",
                       "to_model_alias"]:
            _add(meta.get(field))
        for jk in (meta.get("join_keys") or []):
            _add(jk)
        for field in ["cardinality", "description", "market", "frequency",
                       "domain"]:
            _add(meta.get(field))
        return " ".join(parts)

    # ---- column / table entries ----

    # 1. table_alias, table_name
    _add(meta.get("table_alias"))
    _add(meta.get("table_name"))

    # 2. column_alias, column_name (skip opaque column names like bd999)
    column_alias = meta.get("column_alias", "") or ""
    _add(column_alias)
    column_name = meta.get("column_name", "") or ""
    if column_name and not _OPAQUE_COLUMN_PATTERN.match(column_name):
        _add(column_name)

    # 3. index_name
    index_name = meta.get("index_name", "") or ""
    if index_name:
        index_name_clean = index_name.replace("@", " ").replace("(虚拟表)", "")
        _add(index_name_clean)

    # 4. column_description (skip template-like descriptions)
    col_desc = meta.get("column_description", "") or ""
    if col_desc:
        pattern = _BM25_TEMPLATE_PATTERNS.get("column_description")
        if not (pattern and pattern.match(col_desc.strip())):
            _add(col_desc)

    # 5. column_aliases
    for alias in (meta.get("column_aliases") or []):
        _add(alias)

    # 6. Financial synonyms for column_alias (whole-token matching)
    if column_alias:
        jieba = _ensure_jieba()
        alias_tokens = set(jieba.cut(column_alias))
        for key, synonyms in FINANCIAL_SYNONYMS.items():
            if key in alias_tokens or key == column_alias:
                for syn in synonyms:
                    _add(syn)

    # 7. domain, market, frequency
    _add(meta.get("domain"))
    _add(meta.get("market"))
    _add(meta.get("frequency"))

    # 8. query_hints
    for hint in (meta.get("query_hints") or []):
        _add(hint)

    # 9. example_all (split by ";", max 10)
    example_all = meta.get("example_all", "") or ""
    if example_all:
        example_items = [x.strip() for x in str(example_all).split(";") if x.strip()]
        for item in example_items[:10]:
            _add(item)

    # 10. unit
    _add(meta.get("unit"))

    # ---- table-level enrichments ----
    if doc_type == "table":
        # table_summary (skip template-like)
        table_summary = meta.get("table_summary", "") or ""
        if table_summary:
            pattern = _BM25_TEMPLATE_PATTERNS.get("table_summary")
            if not (pattern and pattern.match(table_summary.strip())):
                _add(table_summary)

        # table_business_meaning (skip template-like)
        table_biz = meta.get("table_business_meaning", "") or ""
        if table_biz:
            pattern = _BM25_TEMPLATE_PATTERNS.get("table_business_meaning")
            if not (pattern and pattern.match(table_biz.strip())):
                _add(table_biz)

        # column_aliases_agg (max 30)
        for alias in (meta.get("column_aliases_agg") or [])[:30]:
            _add(alias)

    return " ".join(parts)


# ============================================================
# BM25 Retriever
# ============================================================


class BM25Retriever:
    """
    BM25 检索器

    与 FileRetriever 返回相同的 hit schema，便于 RRF 融合
    """

    def __init__(
        self,
        index_dir: str,
        userdict_path: Optional[str] = None,
        mmap: bool = True,
    ):
        """
        Args:
            index_dir: BM25 索引目录（包含 index/ 和 docs_meta.json）
            userdict_path: 用户词典路径
            mmap: 是否使用内存映射加载（省内存）
        """
        self.index_dir = Path(index_dir)
        self.userdict_path = userdict_path
        self.mmap = mmap

        self._bm25 = None
        self._docs_meta: Optional[List[Dict[str, Any]]] = None
        self._tokenizer: Optional[FinancialTokenizer] = None

        # 过滤索引（与 FileRetriever 一致）
        self._doc_type_indices: Dict[str, Set[int]] = {}
        self._yaml_path_indices: Dict[str, Set[int]] = {}
        self._market_indices: Dict[str, Set[int]] = {}
        self._frequency_indices: Dict[str, Set[int]] = {}

        self._loaded = False
        # None = unknown, True/False = cached result of first attempt
        self._sparse_retrieve_supported: Optional[bool] = None

    def load(self):
        """
        显式加载索引（用于在 pipeline 初始化时验证）

        如果索引目录或文件不存在，会抛出 FileNotFoundError。
        这允许 pipeline 在初始化时 fail-fast，而不是每个查询都出错。
        """
        self._ensure_loaded()

    def _ensure_loaded(self):
        """延迟加载索引"""
        if self._loaded:
            return

        bm25s = _ensure_bm25s()

        index_path = self.index_dir / "index"
        meta_path = self.index_dir / "docs_meta.json"

        if not index_path.exists():
            raise FileNotFoundError(f"BM25 index not found: {index_path}")
        if not meta_path.exists():
            raise FileNotFoundError(f"Docs metadata not found: {meta_path}")

        self._bm25 = bm25s.BM25.load(str(index_path), mmap=self.mmap)

        # Fix: bm25s may contain an empty-string token "" whose ID exceeds
        # the sparse matrix column count, causing ValueError at query time.
        # Remove it defensively on load (build_bm25_index.py also prevents it).
        if "" in self._bm25.vocab_dict:
            empty_id = self._bm25.vocab_dict.pop("")
            if hasattr(self._bm25, "unique_token_ids_set") and self._bm25.unique_token_ids_set is not None:
                self._bm25.unique_token_ids_set.discard(empty_id)
            logger.info(
                f"Removed empty-string token (id={empty_id}) from loaded vocab"
            )

        logger.info(f"Loaded BM25 index from {index_path}")

        # 加载文档元数据
        with open(meta_path, "r", encoding="utf-8") as f:
            self._docs_meta = json.load(f)
        logger.info(f"Loaded docs metadata: {len(self._docs_meta)} records")

        vocab_size = len(self._bm25.vocab_dict)
        logger.info(f"BM25 vocab size: {vocab_size}, docs: {len(self._docs_meta)}")

        # 初始化 tokenizer
        self._tokenizer = FinancialTokenizer(userdict_path=self.userdict_path)

        # 构建过滤索引
        self._build_filter_indices()

        self._loaded = True

    def _build_filter_indices(self):
        """构建过滤索引（与 FileRetriever 一致）"""
        if self._docs_meta is None:
            return
        (
            self._doc_type_indices,
            self._yaml_path_indices,
            self._market_indices,
            self._frequency_indices,
        ) = build_filter_indices(self._docs_meta)

        logger.info(
            f"BM25 filter indices - markets: {list(self._market_indices.keys())}"
        )
        logger.info(
            f"BM25 filter indices - frequencies: {list(self._frequency_indices.keys())}"
        )

    def _get_filtered_indices(
        self,
        doc_type_filter: Optional[str] = None,
        yaml_paths: Optional[List[str]] = None,
        market: "Optional[str | Set[str]]" = None,
        frequency: Optional[str] = None,
    ) -> Optional[Set[int]]:
        """获取符合过滤条件的索引集合

        Args:
            market: 单市场 str 或多市场 Set[str]（软路由扩展），None 不过滤
        """
        return get_filtered_indices(
            doc_type_filter=doc_type_filter,
            yaml_paths=yaml_paths,
            market=market,
            frequency=frequency,
            doc_type_indices=self._doc_type_indices,
            yaml_path_indices=self._yaml_path_indices,
            market_indices=self._market_indices,
            frequency_indices=self._frequency_indices,
        )

    def _parse_filter_expr(self, filter_expr: Optional[str]) -> Optional[str]:
        """解析 filter_expr，提取 doc_type 值"""
        return parse_filter_expr(filter_expr, "column")

    # ------------------------------------------------------------------
    # Query-side synonym expansion
    # ------------------------------------------------------------------

    @staticmethod
    def _expand_query_synonyms(tokens: List[str]) -> List[str]:
        """Bidirectional query-side synonym expansion.

        Uses REVERSE_SYNONYM_MAP which maps *every* member of a synonym
        group to all other members.  This means:
        - "外资"   → adds "北向资金", "陆股通", ...  (forward)
        - "陆股通" → adds "外资", "北向资金", ...    (reverse)

        Complements index-side expansion and closes recall gaps when
        the document alias didn't contain the exact query term.
        """
        expanded = list(tokens)
        seen = set(tokens)
        for token in tokens:
            syns = REVERSE_SYNONYM_MAP.get(token)
            if syns is None:
                continue
            for syn in syns:
                if syn not in seen:
                    expanded.append(syn)
                    seen.add(syn)
        return expanded

    @staticmethod
    def _table_prior_multiplier(query_text: str, table_name: str) -> float:
        query = str(query_text or "")
        table = str(table_name or "")
        multiplier = 1.0

        if _RE_BM25_HISTORY_WINDOW.search(query) and _RE_BM25_TECHNICAL_FACT.search(query):
            if table == "stock_astock_latest_index":
                multiplier *= 0.76
            elif table in {
                "stock_astock_mkt_daily_trans",
                "stock_astock_mkt_week_trans",
                "stock_astock_mkt_month_trans",
                "stock_astock_mkt_year_trans",
                "stock_astock_mkt_min_trans",
            }:
                multiplier *= 1.14

        if _RE_BM25_MULTI_PERIOD.search(query):
            if "年线" in query or "年K" in query:
                if table == "stock_astock_mkt_year_trans":
                    multiplier *= 1.28
            if "月线" in query or "月K" in query:
                if table == "stock_astock_mkt_month_trans":
                    multiplier *= 1.28
            if "周线" in query or "周K" in query:
                if table == "stock_astock_mkt_week_trans":
                    multiplier *= 1.28
            if "多周期" in query and table in {
                "stock_astock_mkt_daily_trans",
                "stock_astock_mkt_week_trans",
                "stock_astock_mkt_month_trans",
                "stock_astock_mkt_year_trans",
            }:
                multiplier *= 1.18

        if _RE_BM25_IPO_PRICE.search(query) and "相对发行价" not in query:
            if table in {"stock_astock_ipo", "stock_astock_new_stock_evaluation"}:
                multiplier *= 1.30
            elif table in {
                "stock_astock_mkt_daily_trans",
                "stock_astock_mkt_month_trans",
                "stock_astock_mkt_year_trans",
                "stock_astock_latest_index",
            }:
                multiplier *= 0.84

        if _RE_BM25_DIVESTITURE.search(query):
            if table == "stock_astock_divestiture":
                multiplier *= 1.34
            elif table in {
                "stock_astock_mergers_acquisitions",
                "stock_astock_backdoor_list",
                "stock_astock_asset_injection",
                "stock_astock_asset_purchase",
                "stock_astock_asset_sale",
            }:
                multiplier *= 0.88

        if _RE_BM25_HOLDING_ENTITY.search(query):
            if table in {"stock_astock_shareholding_insitutions", "stock_astock_institutional_stat"}:
                multiplier *= 1.28
            elif table == "stock_astock_increase_decrease" and re.search(r"(增持|减持|买入|卖出)", query):
                multiplier *= 1.22
            elif table == "stock_astock_company_financial_data":
                multiplier *= 0.88

        if _RE_BM25_RESEARCH_NORTHBOUND.search(query):
            if table in {"stock_astock_charts", "stock_astock_institutional_research_stat"}:
                multiplier *= 1.34
            elif table == "stock_astock_mkt_daily_trans":
                multiplier *= 1.14
            elif table in {
                "stock_astock_company_financial_data",
                "stock_astock_exchange_shares",
                "stock_astock_institutional_stat",
                "stock_astock_share_capital",
                "stock_astock_top10_circulate_shareholders_stat",
            }:
                multiplier *= 0.82

        if _RE_BM25_SHAREHOLDER_BUYBACK.search(query):
            if table in {
                "stock_astock_basic_info",
                "stock_astock_increase_decrease",
                "stock_astock_increase_decrease_plan",
                "stock_astock_repurchase_of_shares",
            }:
                multiplier *= 1.30
            elif table in {
                "stock_astock_top10_shareholders_detail",
                "stock_astock_top10_shareholders_detail_latest",
                "stock_astock_top10_shareholders_stat",
                "stock_astock_top10_circulate_shareholders_detail",
                "stock_astock_top10_circulate_shareholders_detail_latest",
                "stock_astock_top10_circulate_shareholders_stat",
                "stock_astock_num_shareholders_capital_chg",
            }:
                multiplier *= 0.78

        if _RE_BM25_CONCEPT_RANKING.search(query):
            if table in {
                "stock_astock_concept",
                "stock_astock_basic_info",
                "stock_astock_mkt_daily_trans",
                "stock_astock_latest_index",
            }:
                multiplier *= 1.20
            elif table in {
                "stock_astock_exchange_shares",
                "stock_astcok_company_delisted",
                "stock_astock_company_financial_data",
            }:
                multiplier *= 0.84

        if _RE_BM25_EARNINGS_SURPRISE.search(query):
            if table in {
                "stock_astock_company_financial_data",
                "stock_astock_company_performance_forecast",
                "stock_astock_institutional_performance_forcast",
            }:
                multiplier *= 1.22

        if _RE_BM25_CB_REDEMPTION.search(query):
            if table in {
                "convertiblebond_basic_info",
                "convertiblebond_payments_and_redemptions",
                "stock_astock_basic_info",
                "stock_astock_financing",
            }:
                multiplier *= 1.24
            elif table in {
                "convertiblebond_terms",
                "convertiblebond_terms_exercise",
                "convertiblebond_transfer_price_adjustments",
            }:
                multiplier *= 0.84

        if _RE_BM25_CONTROLLER_PENALTY.search(query):
            if table in {"stock_astock_file_an_investigation", "stock_astock_penalties_violations"}:
                multiplier *= 1.30

        if _RE_BM25_LATEST_FLOW.search(query):
            if table == "stock_astock_mkt_daily_trans_latest":
                multiplier *= 1.24
            elif table in {"stock_astock_mkt_daily_trans", "stock_astock_latest_index"}:
                multiplier *= 0.92

        if _RE_BM25_TOP10_CIRC.search(query):
            if table in {
                "stock_astock_top10_circulate_shareholders_detail",
                "stock_astock_top10_circulate_shareholders_detail_latest",
            }:
                multiplier *= 1.24
            elif table == "stock_astock_top10_circulate_shareholders_stat":
                multiplier *= 0.90

        if _RE_BM25_MULTI_FACTOR_SCREEN.search(query):
            if table in {
                "stock_astock_mkt_daily_trans",
                "stock_astock_company_financial_data",
                "stock_astock_company_financial_data_new",
                "stock_astock_shareholding_insitutions",
                "stock_astock_institutional_stat",
            }:
                multiplier *= 1.16

        if _RE_BM25_NO_PLEDGE.search(query):
            if table in {"stock_astock_basic_info", "stock_astock_pledge_stat", "stock_astock_equity_pledge"}:
                multiplier *= 1.30
            elif table in {"stock_astock_exchange_shares", "convertiblebond_analysis"}:
                multiplier *= 0.82

        if _RE_BM25_NAME_FILTER.search(query):
            if table == "stock_astock_basic_info":
                multiplier *= 1.30
            elif table in {"stock_astock_exchange_shares", "stock_astcok_company_delisted"}:
                multiplier *= 0.84

        if _RE_BM25_FUND_DIAGNOSIS.search(query):
            if table in {"fund_mkt_daily_trans", "fund_shares_size", "fund_basic_info"}:
                multiplier *= 1.24
            elif table in {"fund_mkt_daily_trans_latest", "fund_industry_concept_allocation_latest"}:
                multiplier *= 1.14
            elif table == "fund_comprehensive_diagnosis":
                multiplier *= 1.08
            elif table == "fund_mkt_profit_predict":
                multiplier *= 0.82

        if _RE_BM25_FUND_MONTHLY_DIVIDEND.search(query):
            if table in {"fund_dividend_detail", "fund_basic_info", "fund_mkt_daily_trans_latest"}:
                multiplier *= 1.28
            elif table in {"fund_mkt_daily_trans", "fund_mkt_month_trans", "fund_mkt_year_trans"}:
                multiplier *= 0.82

        if _RE_BM25_FUND_COMPANY_STAFF.search(query) and "基金公司" not in query and "基金经理" in query:
            if table in {"fund_company_staff", "fund_company_basic_info", "fund_company_latest_index"}:
                multiplier *= 1.30
            elif table.startswith("fundmanager_") or table.startswith("fund_manager_"):
                multiplier *= 0.82

        if _RE_BM25_FUND_COMPANY_GROWTH.search(query) and "基金经理" not in query:
            if table in {"fund_company_shares_size", "fund_company_shares_size_qoq_rate"}:
                multiplier *= 1.32
            elif table in {"fund_mkt_daily_trans", "fund_basic_info", "fund_mkt_daily_trans_latest"}:
                multiplier *= 0.82

        if _RE_BM25_FUND_COMPANY_ASSET.search(query):
            if table == "fund_company_asset_allocation":
                multiplier *= 1.34
            elif table in {"fund_hold_detail", "fund_asset_allocation"}:
                multiplier *= 0.82

        if _RE_BM25_FUND_COMPANY_STOCK_HOLDING.search(query):
            if table in {"stock_astock_shareholding_insitutions", "stock_astock_latest_index"}:
                multiplier *= 1.30
            elif table in {"fund_company_investment_industry", "fund_company_shares_size"}:
                multiplier *= 0.82

        if _RE_BM25_FUND_MANAGER_RANK.search(query):
            if table in {
                "fund_manager_return_risk_level",
                "fund_manager_performance_stat",
                "fundmanager_latest_index",
            }:
                multiplier *= 1.30
            elif table in {
                "fundmanager_hold_detail_latest",
                "fundmanager_industry_concept_allocation_latest",
                "fund_manager_award",
                "fund_manager_comprehensive_diagnosis",
            }:
                multiplier *= 0.82

        if _RE_BM25_FUND_MANAGER_SCALE.search(query):
            if table in {"fundmanager_asset_allocation", "fund_manager_basic_info", "fundmanager_latest_index"}:
                multiplier *= 1.28
            elif table == "fund_manager_return_risk_level":
                multiplier *= 0.90

        if _RE_BM25_INDEX_HISTORY.search(query):
            if table in {"index_mkt_year_trans", "index_basic_info"}:
                multiplier *= 1.30
            elif table in {"index_mkt_daily_trans", "private_product_nav"}:
                multiplier *= 0.82

        if _RE_BM25_HK_PEV.search(query):
            if table in {"stock_hkstock_basic_info", "stock_hkstock_mkt_year_trans"}:
                multiplier *= 1.30
            elif table in {"stock_astock_pevc_investment", "stock_ustock_pevc"}:
                multiplier *= 0.82

        if _RE_BM25_STOCK_DIVIDEND_GROWTH.search(query):
            if table in {
                "stock_astock_annual_dividend",
                "stock_astock_company_financial_data",
                "stock_astock_mkt_year_trans",
                "stock_astock_mkt_year_trans_qoq_rate",
            }:
                multiplier *= 1.26
            elif table in {
                "fund_mkt_daily_trans",
                "fund_mkt_quarter_trans",
                "fund_mkt_month_trans",
                "fund_basic_info",
            }:
                multiplier *= 0.82

        if _RE_BM25_FUTURES_OPTION_TECH.search(query):
            if table in {
                "futu_contract_info",
                "futu_mkt_minute_quo",
                "futu_mkt_daily_quo",
                "futu_mkt_weekly_quo",
                "futu_mkt_monthly_quo",
                "options_basics",
            }:
                multiplier *= 1.24
            elif table == "futu_variety_risk":
                multiplier *= 0.82

        return multiplier

    @classmethod
    def _apply_query_table_priors(
        cls,
        query_text: str,
        hits: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not hits:
            return hits

        reranked: List[Dict[str, Any]] = []
        for hit in hits:
            multiplier = cls._table_prior_multiplier(
                query_text=query_text,
                table_name=str(hit.get("table_name") or ""),
            )
            if multiplier != 1.0:
                hit["distance"] = float(hit.get("distance", 0.0)) * multiplier
                if hit.get("bm25_score") is not None:
                    hit["bm25_score"] = float(hit.get("bm25_score", 0.0)) * multiplier
                hit["table_prior_multiplier"] = multiplier
            reranked.append(hit)

        reranked.sort(key=lambda item: float(item.get("distance", 0.0)), reverse=True)
        return reranked

    # ------------------------------------------------------------------
    # Sparse retrieve (leverages bm25s pre-computed sparse matrices)
    # ------------------------------------------------------------------

    def _try_sparse_retrieve(
        self, query_tokens: List[str], top_k: int
    ) -> Optional[List[Dict[str, Any]]]:
        """Attempt top-k retrieval via bm25s.retrieve() sparse path.

        bm25s stores pre-computed BM25 scores in scipy sparse matrices.
        ``retrieve()`` performs efficient sparse-matrix operations that
        skip zero-score documents entirely, whereas ``get_scores()``
        materialises a dense array over *all* documents.

        Returns *None* on failure so the caller can fall back to the
        dense ``get_scores()`` path.
        """
        if self._sparse_retrieve_supported is False:
            return None

        if self._bm25 is None or self._docs_meta is None:
            raise RuntimeError("BM25Retriever not initialized: call load() first")
        effective_k = min(top_k, len(self._docs_meta))
        if effective_k <= 0:
            return None

        try:
            results, scores = self._bm25.retrieve(
                [query_tokens], k=effective_k
            )
            if self._sparse_retrieve_supported is None:
                self._sparse_retrieve_supported = True
                logger.info("bm25s sparse retrieve() path activated")

            top_indices = results[0]
            top_scores = scores[0]

            hits: List[Dict[str, Any]] = []
            for idx, score in zip(top_indices, top_scores):
                score_f = float(score)
                if np.isnan(score_f) or np.isinf(score_f) or score_f < 0:
                    continue
                meta = self._docs_meta[int(idx)]
                hit = build_hit_from_meta(
                    meta, distance=score_f, bm25_score=score_f
                )
                hits.append(hit)
            return hits
        except Exception as exc:
            if self._sparse_retrieve_supported is None:
                logger.info(
                    "bm25s sparse retrieve() unavailable with custom tokens, "
                    "using dense get_scores() fallback: %s",
                    exc,
                )
                self._sparse_retrieve_supported = False
            return None

    # ------------------------------------------------------------------
    # Dense scoring fallback (original get_scores path, for filtered queries)
    # ------------------------------------------------------------------

    def _dense_retrieve(
        self,
        query_tokens: List[str],
        top_k: int,
        valid_indices: Optional[Set[int]],
    ) -> List[Dict[str, Any]]:
        """Dense scoring path using get_scores() + argpartition.

        Used when filters restrict the candidate set, or when the sparse
        retrieve() path is not available.
        """
        if self._bm25 is None or self._docs_meta is None:
            raise RuntimeError("BM25Retriever not initialized: call load() first")

        query_ids = self._bm25.get_tokens_ids(query_tokens)
        if not _has_any_token_id(query_ids):
            logger.debug(
                "BM25: query tokens not in vocabulary, returning empty results. "
                "tokens=%s",
                query_tokens,
            )
            return []

        # Safety: filter out token IDs that exceed the sparse matrix column
        # count.  This can happen when bm25s adds an empty-string token with
        # ID = num_columns during index(), and the removal at load time does
        # not fully prevent all edge cases (e.g., stale index files).
        # bm25s stores scores as a dict with 'indptr' key; n_cols = indptr.size - 1.
        # get_tokens_ids() returns a flat list[int] of valid token IDs.
        n_cols = None
        scores_obj = getattr(self._bm25, "scores", None)
        if isinstance(scores_obj, dict):
            indptr = scores_obj.get("indptr")
            if indptr is not None and hasattr(indptr, "size"):
                n_cols = int(indptr.size) - 1
        elif hasattr(scores_obj, "shape"):
            n_cols = scores_obj.shape[1]
        if n_cols is not None and n_cols > 0 and query_ids:
            before_len = len(query_ids)
            query_ids = [tid for tid in query_ids if tid < n_cols]
            dropped = before_len - len(query_ids)
            if dropped > 0:
                logger.warning(
                    "BM25: dropped %d out-of-range token ID(s) (n_cols=%d)",
                    dropped,
                    n_cols,
                )
            if not query_ids:
                logger.debug(
                    "BM25: all query token IDs out of range after filtering, "
                    "returning empty results."
                )
                return []

        all_scores = self._bm25.get_scores(query_ids)

        if valid_indices is not None:
            if not valid_indices:
                return []
            valid_indices_array = np.fromiter(
                valid_indices, dtype=np.int64, count=len(valid_indices)
            )
            subset_scores = all_scores[valid_indices_array]
            if subset_scores.size == 0:
                return []
            effective_top_k = min(top_k, subset_scores.size)
            if effective_top_k < subset_scores.size:
                local_top = np.argpartition(subset_scores, -effective_top_k)[
                    -effective_top_k:
                ]
                local_top = local_top[np.argsort(subset_scores[local_top])[::-1]]
            else:
                local_top = np.argsort(subset_scores)[::-1]
            top_indices = valid_indices_array[local_top[:effective_top_k]]
        else:
            effective_top_k = min(top_k, len(all_scores))
            if effective_top_k < len(all_scores):
                top_indices = np.argpartition(all_scores, -effective_top_k)[
                    -effective_top_k:
                ]
                top_indices = top_indices[np.argsort(all_scores[top_indices])[::-1]]
            else:
                top_indices = np.argsort(all_scores)[::-1]

        hits: List[Dict[str, Any]] = []
        for idx in top_indices:
            score = all_scores[idx]
            if np.isnan(score) or np.isinf(score) or score < 0:
                continue
            meta = self._docs_meta[idx]
            hit = build_hit_from_meta(meta, distance=score, bm25_score=score)
            hits.append(hit)

        return hits

    # ------------------------------------------------------------------
    # Main search entry point
    # ------------------------------------------------------------------

    def search(
        self,
        query_text: str,
        top_k: int = 50,
        filter_expr: Optional[str] = None,
        yaml_paths: Optional[List[str]] = None,
        market: "Optional[str | Set[str]]" = None,
        frequency: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        BM25 检索

        返回与 FileRetriever.search() 相同的 hit schema

        Args:
            query_text: 查询文本（原始中文）
            top_k: 返回数量
            filter_expr: 过滤表达式（如 "doc_type=column"）
            yaml_paths: 限定搜索的 YAML 路径
            market: 市场过滤（str=单市场, Set[str]=多市场联合, None=不过滤）
            frequency: 频率过滤

        Returns:
            hit 列表，包含 id, bm25_score, text, yaml_path, column_name 等
        """
        self._ensure_loaded()

        if self._bm25 is None or self._docs_meta is None or self._tokenizer is None:
            raise RuntimeError("BM25 index not loaded")
        if top_k <= 0:
            return []

        # 1. 分词（查询去重，不需要 TF 信号）
        query_tokens = self._tokenizer.tokenize(query_text, deduplicate=True)
        if not query_tokens:
            return []

        # 2. Query-side synonym expansion (complements index-side expansion)
        query_tokens = self._expand_query_synonyms(query_tokens)

        # 3. 获取过滤索引
        doc_type_filter = self._parse_filter_expr(filter_expr)
        valid_indices = self._get_filtered_indices(
            doc_type_filter=doc_type_filter,
            yaml_paths=yaml_paths,
            market=market,
            frequency=frequency,
        )

        # Skip redundant filter: when the filtered set covers all docs
        # (common case: column-only index filtered by doc_type=column)
        if (
            valid_indices is not None
            and len(valid_indices) >= len(self._docs_meta)
        ):
            valid_indices = None

        # 4. Fast path: no effective filter → sparse retrieve via bm25s
        if valid_indices is None:
            hits = self._try_sparse_retrieve(query_tokens, top_k)
            if hits is not None:
                return self._apply_query_table_priors(query_text, hits)[:top_k]

        # 5. Dense fallback / filtered path
        hits = self._dense_retrieve(query_tokens, top_k, valid_indices)
        return self._apply_query_table_priors(query_text, hits)[:top_k]

    async def close(self):
        """关闭资源"""
        self._bm25 = None
        self._docs_meta = None
        self._tokenizer = None
        self._loaded = False


# ============================================================
# RRF 融合
# ============================================================

def multi_list_reciprocal_rank_fusion(
    ranked_lists: Dict[str, List[Dict[str, Any]]],
    weights: Dict[str, float],
    k: int = 20,
) -> List[Dict[str, Any]]:
    """
    多路 RRF 融合：每路检索独立贡献 rank，保留原始来源信息

    符合 RRF 理论：每个 rank list 来自单一检索系统的原始排序，不混合重排。

    Args:
        ranked_lists: 各路结果，key 为来源名(global/scoped/two_stage/bm25)
        weights: 各路权重
        k: RRF 常数（默认 20）

    Returns:
        融合后的结果（按 RRF 分数降序），保留 _source 为来源列表（如 "global+bm25"）
    """
    from collections import defaultdict

    rrf_scores: Dict[str, float] = defaultdict(float)
    doc_data: Dict[str, Dict[str, Any]] = {}
    doc_sources: Dict[str, List[str]] = defaultdict(list)

    for source_name, hits in ranked_lists.items():
        if not hits:
            continue
        w = weights.get(source_name, 1.0)
        for rank, hit in enumerate(hits, start=1):
            doc_id = hit.get("id", "")
            if not doc_id:
                continue
            rrf_scores[doc_id] += w / (k + rank)
            if doc_id not in doc_data:
                doc_data[doc_id] = hit.copy()
            if source_name not in doc_sources[doc_id]:
                doc_sources[doc_id].append(source_name)

    # 按 RRF 分数排序，设置 _source 为来源组合（保留原始来源信息）
    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

    results = []
    for doc_id in sorted_ids:
        hit = doc_data[doc_id]
        hit["rrf_score"] = rrf_scores[doc_id]
        hit["_source"] = "+".join(sorted(doc_sources[doc_id]))
        results.append(hit)

    return results


def multi_list_linear_fusion(
    scored_lists: Dict[str, List[Dict[str, Any]]],
    weights: Dict[str, float],
    score_fields: Optional[Dict[str, str]] = None,
    score_higher_is_better: Optional[Dict[str, bool]] = None,
    use_convex_combination: bool = True,
    epsilon: float = 1e-12,
) -> List[Dict[str, Any]]:
    """多路线性融合（Linear / Convex Combination）。

    流程：
    1. 每一路按配置字段抽取原始分数；
    2. 在该路内做 MinMax 归一化；
    3. 按权重加权求和（可选归一化为凸组合）。

    Args:
        scored_lists: 各路结果，key 为来源名(global/scoped/two_stage/bm25)
        weights: 各路权重
        score_fields: 各路分数字段映射（默认使用 distance）
        score_higher_is_better: 各路分数方向，True=越大越好
        use_convex_combination: 是否将权重归一化为和为1
        epsilon: MinMax 分母保护

    Returns:
        融合后的结果（按 linear_score 降序），并将 distance 置为融合分数。
    """
    from collections import defaultdict

    score_fields = score_fields or {}
    score_higher_is_better = score_higher_is_better or {}

    # 预先过滤无效路由权重
    active_weights: Dict[str, float] = {}
    for source_name, hits in scored_lists.items():
        if not hits:
            continue
        w = float(weights.get(source_name, 1.0))
        if w <= 0:
            continue
        active_weights[source_name] = w

    if not active_weights:
        return []

    if use_convex_combination:
        weight_sum = sum(active_weights.values())
        if weight_sum > 0:
            active_weights = {
                name: w / weight_sum for name, w in active_weights.items()
            }

    linear_scores: Dict[str, float] = defaultdict(float)
    doc_data: Dict[str, Dict[str, Any]] = {}
    doc_sources: Dict[str, List[str]] = defaultdict(list)

    for source_name, hits in scored_lists.items():
        if source_name not in active_weights or not hits:
            continue
        weight = active_weights[source_name]
        score_field = score_fields.get(source_name, "distance")
        higher_is_better = bool(score_higher_is_better.get(source_name, True))

        # 同一路内同一 doc_id 若出现多次，保留最好分数
        source_doc_scores: Dict[str, float] = {}
        source_doc_hits: Dict[str, Dict[str, Any]] = {}

        for hit in hits:
            doc_id = hit.get("id", "")
            if not doc_id:
                continue
            raw_score = hit.get(score_field, hit.get("distance", 0.0))
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                score = 0.0

            normalized_raw = score if higher_is_better else -score
            prev = source_doc_scores.get(doc_id)
            if prev is None or normalized_raw > prev:
                source_doc_scores[doc_id] = normalized_raw
                source_doc_hits[doc_id] = hit

        if not source_doc_scores:
            continue

        values = list(source_doc_scores.values())
        min_v = min(values)
        max_v = max(values)
        span = max_v - min_v

        for doc_id, normalized_raw in source_doc_scores.items():
            if span <= epsilon:
                normalized_score = 1.0 if len(source_doc_scores) == 1 else 0.5
            else:
                normalized_score = (normalized_raw - min_v) / span

            linear_scores[doc_id] += weight * normalized_score

            if doc_id not in doc_data:
                doc_data[doc_id] = source_doc_hits[doc_id].copy()
            if source_name not in doc_sources[doc_id]:
                doc_sources[doc_id].append(source_name)

    sorted_ids = sorted(linear_scores.keys(), key=lambda x: linear_scores[x], reverse=True)

    results = []
    for doc_id in sorted_ids:
        hit = doc_data[doc_id]
        hit["linear_score"] = linear_scores[doc_id]
        hit["_source"] = "+".join(sorted(doc_sources[doc_id]))
        results.append(hit)

    return results
