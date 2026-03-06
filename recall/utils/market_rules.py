"""
市场标签规则模块 - 规则优先的市场标签推断

解决 LLM 市场标签误判问题：
- "北向资金/陆股通" 误判为 [港股] → 实际是 [A股]（外资买A股）
- "机构持仓/社保/QFII" 误判为 [基金] → 实际是 [A股]（机构股东）
- "南向资金/港股通" 误判为 [A股] → 实际是 [港股]（内资买港股）

使用确定性规则替代 LLM 推断。

验证来源：
- HKEX Stock Connect Information Booklet (Oct 2024)
- CSRC 第128号令（沪港通/深港通管理办法）
- SSE/SZSE 交易公开信息披露规则
"""

import re
from typing import Optional


# ============================================================
# Pre-compiled regex patterns for detect_explicit_market_tag
# ============================================================
_RE_EXPLICIT_HK = re.compile(r"港股|HK股|恒生|恒指|港币|香港|H股|\.HK", re.IGNORECASE)
_RE_EXPLICIT_US = re.compile(r"美股|美元|NASDAQ|NYSE|纳斯达克|纽交所|标普|道琼斯|\.US", re.IGNORECASE)
_RE_EXPLICIT_A = re.compile(r"A股|沪市|深市|沪深|创业板|科创板", re.IGNORECASE)
_RE_EXPLICIT_BOND = re.compile(
    r"(债券|国债|企业债|公司债|信用债|利率债|城投债|"
    r"(?<![A-Za-z0-9])ABS(?![A-Za-z0-9])|资产支持|中票|短融)",
    re.IGNORECASE,
)
_RE_EXPLICIT_OPTIONS = re.compile(r"(期权|认购期权|认沽期权|看涨期权|看跌期权|行权价|隐含波动率|期权合约|50ETF期权|300ETF期权|沪深300期权)", re.IGNORECASE)
_RE_EXPLICIT_WEALTH = re.compile(r"(银行理财|理财产品|净值型理财|固收理财|银行理财产品)", re.IGNORECASE)
_RE_EXPLICIT_FOREIGN_FUTURES = re.compile(
    r"(外盘期货|伦铜|伦铝|伦锌|伦镍|布伦特|纽约原油|纽约黄金|"
    r"(?<![A-Za-z0-9])WTI(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])COMEX(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])LME(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])NYMEX(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])ICE(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])CME(?:外盘)?(?![A-Za-z0-9]))",
    re.IGNORECASE,
)
_RE_CB_EXCLUDE = re.compile(r"(可转债|转债)")

# ──────────────────────────────────────────────────────────────
# Eval-only patterns and functions below.
# Used by eval/eval_router_accuracy.py; NOT imported by the production pipeline.
# Production code uses domain_router.DomainRouter.route() instead.
# ──────────────────────────────────────────────────────────────

# ============================================================
# Pre-compiled regex patterns for market_tag_from_query
# ============================================================
# Southbound
_RE_SOUTHBOUND_1 = re.compile(r"南向资金")
_RE_SOUTHBOUND_2 = re.compile(r"南下资金")
_RE_SOUTHBOUND_3 = re.compile(r"港股通")

# HK margin/short
_RE_HK_MARGIN_1 = re.compile(r"孖展")
_RE_HK_MARGIN_2 = re.compile(r"沽空")
_RE_HK_MARGIN_3 = re.compile(r"卖空")
_RE_HK_MARGIN_4 = re.compile(r"证券借贷")
_RE_HK_MARGIN_5 = re.compile(r"借货")
_RE_HK_MARGIN_6 = re.compile(r"斩仓")
_RE_HK_MARGIN_7 = re.compile(r"补仓")
_RE_HK_MARGIN_A_CHECK = re.compile(r"A股|沪市|深市|创业板|科创板|北交所")

# Explicit HK (reuse _RE_EXPLICIT_HK)
# Explicit US (reuse _RE_EXPLICIT_US)

# Fund products
_RE_FUND_1 = re.compile(r"基金净值")
_RE_FUND_2 = re.compile(r"申购费")
_RE_FUND_3 = re.compile(r"赎回费")
_RE_FUND_4 = re.compile(r"基金经理业绩")
_RE_FUND_5 = re.compile(r"基金规模")
_RE_FUND_6 = re.compile(r"基金份额")
_RE_FUND_7 = re.compile(r"ETF净值")
_RE_FUND_8 = re.compile(r"ETF规模")
_RE_FUND_9 = re.compile(r"基金分红")
_RE_FUND_10 = re.compile(r"基金评级")
# 基金产品名：汉字2+字符(含数字) + "基金" 但排除"基金持仓"等机构语境
# 例: "华夏红利基金", "嘉实沪深300基金", "易方达中小盘混合基金"
_RE_FUND_PRODUCT = re.compile(r"[\u4e00-\u9fa5][\u4e00-\u9fa5\dA-Za-z]{1,12}基金(?!持仓|持股|买入|卖出|增持|减持)")
# 排除：社保基金、保险基金、养老基金（这些是机构投资者，非基金产品）
_RE_FUND_INST_EXCLUDE = re.compile(r"(社保基金|保险基金|养老基金|企业年金)")

# Index
_RE_INDEX = re.compile(r"指数行情|沪深300|上证指数|深证成指|创业板指|科创50|中证\d+")

# Northbound
_RE_NORTHBOUND_1 = re.compile(r"北向资金")
_RE_NORTHBOUND_2 = re.compile(r"北上资金")
_RE_NORTHBOUND_3 = re.compile(r"陆股通")
_RE_NORTHBOUND_4 = re.compile(r"沪股通")
_RE_NORTHBOUND_5 = re.compile(r"深股通")
_RE_NORTHBOUND_6 = re.compile(r"港资.{0,4}(买入|卖出|净买|流入|流出|持股|增持|减持)")

# Institutional holdings
_RE_INST_1 = re.compile(r"机构持仓")
_RE_INST_2 = re.compile(r"机构持股")
_RE_INST_3 = re.compile(r"社保持股")
_RE_INST_4 = re.compile(r"社保基金.{0,4}(持仓|持股|买入|增持|减持)")
_RE_INST_5 = re.compile(r"QFII", re.IGNORECASE)
_RE_INST_6 = re.compile(r"RQFII", re.IGNORECASE)
_RE_INST_7 = re.compile(r"合格境外")
_RE_INST_8 = re.compile(r"保险持仓")
_RE_INST_9 = re.compile(r"保险持股")
_RE_INST_10 = re.compile(r"券商持仓")
_RE_INST_11 = re.compile(r"券商持股")
_RE_INST_12 = re.compile(r"信托持仓")
_RE_INST_13 = re.compile(r"(社保|保险|券商|QFII).{0,4}(换手|持股|持仓|变动|市值)", re.IGNORECASE)

# A-stock specific
_RE_ASTOCK_1 = re.compile(r"龙虎榜")
_RE_ASTOCK_2 = re.compile(r"营业部")
_RE_ASTOCK_3 = re.compile(r"游资")
_RE_ASTOCK_4 = re.compile(r"机构席位")
_RE_ASTOCK_5 = re.compile(r"两融")
_RE_ASTOCK_6 = re.compile(r"融资融券")
_RE_ASTOCK_7 = re.compile(r"融资余额")
_RE_ASTOCK_8 = re.compile(r"融券余额")
_RE_ASTOCK_9 = re.compile(r"融券余量")
_RE_ASTOCK_10 = re.compile(r"融资买入")
_RE_ASTOCK_11 = re.compile(r"融券卖出")
_RE_ASTOCK_12 = re.compile(r"信用账户")
_RE_ASTOCK_13 = re.compile(r"担保品")
_RE_ASTOCK_14 = re.compile(r"维持担保比例")
_RE_ASTOCK_15 = re.compile(r"(主力资金|散户资金|大单|特大单|小单|中单).{0,4}(流入|流出|净额|买入|卖出)")
_RE_ASTOCK_16 = re.compile(r"(增持|减持|套现)")
_RE_ASTOCK_17 = re.compile(r"限售股")
_RE_ASTOCK_18 = re.compile(r"解禁")
_RE_ASTOCK_19 = re.compile(r"减持公告")

# ============================================================
# Pre-compiled regex patterns for futures market detection
# ============================================================
_RE_FUTURES_1 = re.compile(r"期货|主力合约|合约代码|期货品种")
_RE_FUTURES_2 = re.compile(r"基差|升贴水|期现")
_RE_FUTURES_3 = re.compile(r"仓单|交割|交割月")
_RE_FUTURES_4 = re.compile(r"持仓量|空头持仓|多头持仓|净持仓|未平仓")
_RE_FUTURES_5 = re.compile(r"(螺纹|铁矿|焦煤|焦炭|甲醇|PTA|橡胶|铜|铝|锌|镍|白银|黄金|原油|棕榈油|豆粕|大豆|玉米|棉花|白糖|鸡蛋|苹果|生猪|纯碱|玻璃|沥青)")
_RE_FUTURES_6 = re.compile(r"(IF|IC|IH|IM|TF|TS)\d{4}", re.IGNORECASE)

# Convertible bond detection
_RE_CB_1 = re.compile(r"可转债|转债|可转换债券")
_RE_CB_2 = re.compile(r"转股价|转股溢价|转股价值|下修转股价")
_RE_CB_3 = re.compile(r"强赎|回售|赎回条款")

# 新三板 detection
_RE_THREEBOARD_1 = re.compile(r"新三板|三板市场|北交所|精选层|创新层|基础层")
_RE_THREEBOARD_2 = re.compile(r"做市商|做市转让|协议转让|三板挂牌|挂牌企业")
_RE_THREEBOARD_3 = re.compile(r"转板上市|三板转板|三板定增")

# ============================================================
# Pre-compiled regex patterns for detect_explicit_frequency_tag
# ============================================================
_RE_FREQ_INTRADAY = re.compile(r"\d+\s*分钟|分钟线|分钟K|\d+\s*小时|\d{1,2}:\d{2}|\d{1,2}点\d{1,2}分|分时|tick")
_RE_FREQ_DAILY = re.compile(r"日K|日线|日K线|日频|每日|日数据|按日|逐日")
_RE_FREQ_WEEKLY = re.compile(r"周线|周K|周度|每周|周频|周数据|周报|按周")
_RE_FREQ_MONTHLY = re.compile(r"月线|月K|月度|每月|月频|月报")
_RE_FREQ_QUARTERLY = re.compile(r"季报|季度|季频|Q[1-4]", re.IGNORECASE)
_RE_FREQ_ANNUAL = re.compile(r"年报|年度|年频|每年|年线")

# ============================================================
# Pre-compiled regex patterns for infer_frequency_tag
# ============================================================
_RE_INFER_QUARTERLY = re.compile(r"机构持仓|社保|QFII|持股占比|占流通股比例|持仓变化|季报")
_RE_INFER_WEEKLY = re.compile(r"(本周|上周|下周|近\d+周)")
_RE_INFER_MONTHLY = re.compile(r"(近\d+个?月)")
_RE_INFER_ANNUAL = re.compile(r"(年度分红|近\d+年|历年|年化)")
_RE_INFER_DAILY_EXPLICIT = re.compile(r"(日频|日报|每日|逐日|每天|按天)")
_RE_INFER_DAILY_IMPLICIT = re.compile(r"(龙虎榜|资金流向|主力|大单|特大单|融资融券|两融|涨停|跌停|成交额|换手率|内盘|外盘)")
_RE_INFER_DAILY_NEAR = re.compile(r"近\d+[日天]|最近\d+[日天]|今[日天]|昨[日天]|前\d+[日天]")
# New domain frequency inference patterns
_RE_INFER_DAILY_OPTIONS = re.compile(r"期权.{0,6}(行情|报价|成交|持仓|Greek|波动率|Delta|Gamma)")
_RE_INFER_DAILY_BOND_VALUATION = re.compile(r"债券.{0,6}估值|中债估值|中证估值")
_RE_INFER_DAILY_WEALTH_NAV = re.compile(r"(银行理财|理财产品).{0,6}净值")

# ============================================================
# Pre-grouped pattern tuples for market_tag_from_query
# (avoids recreating lists on every call)
# ============================================================
_SOUTHBOUND_PATTERNS = (_RE_SOUTHBOUND_1, _RE_SOUTHBOUND_2, _RE_SOUTHBOUND_3)
_HK_MARGIN_PATTERNS = (
    _RE_HK_MARGIN_1, _RE_HK_MARGIN_2, _RE_HK_MARGIN_3,
    _RE_HK_MARGIN_4, _RE_HK_MARGIN_5, _RE_HK_MARGIN_6, _RE_HK_MARGIN_7,
)
_FUND_PATTERNS = (
    _RE_FUND_1, _RE_FUND_2, _RE_FUND_3, _RE_FUND_4, _RE_FUND_5,
    _RE_FUND_6, _RE_FUND_7, _RE_FUND_8, _RE_FUND_9, _RE_FUND_10,
    _RE_FUND_PRODUCT,
)
_NORTHBOUND_PATTERNS = (
    _RE_NORTHBOUND_1, _RE_NORTHBOUND_2, _RE_NORTHBOUND_3,
    _RE_NORTHBOUND_4, _RE_NORTHBOUND_5, _RE_NORTHBOUND_6,
)
_INST_PATTERNS = (
    _RE_INST_1, _RE_INST_2, _RE_INST_3, _RE_INST_4, _RE_INST_5,
    _RE_INST_6, _RE_INST_7, _RE_INST_8, _RE_INST_9, _RE_INST_10,
    _RE_INST_11, _RE_INST_12, _RE_INST_13,
)
_ASTOCK_PATTERNS = (
    _RE_ASTOCK_1, _RE_ASTOCK_2, _RE_ASTOCK_3, _RE_ASTOCK_4,
    _RE_ASTOCK_5, _RE_ASTOCK_6, _RE_ASTOCK_7, _RE_ASTOCK_8,
    _RE_ASTOCK_9, _RE_ASTOCK_10, _RE_ASTOCK_11, _RE_ASTOCK_12,
    _RE_ASTOCK_13, _RE_ASTOCK_14, _RE_ASTOCK_15, _RE_ASTOCK_16,
    _RE_ASTOCK_17, _RE_ASTOCK_18, _RE_ASTOCK_19,
)
_FUTURES_PATTERNS = (
    _RE_FUTURES_1, _RE_FUTURES_2, _RE_FUTURES_3,
    _RE_FUTURES_4, _RE_FUTURES_5, _RE_FUTURES_6,
)
_CB_PATTERNS = (_RE_CB_1, _RE_CB_2, _RE_CB_3)
_THREEBOARD_PATTERNS = (_RE_THREEBOARD_1, _RE_THREEBOARD_2, _RE_THREEBOARD_3)


def detect_explicit_market_tag(query: str) -> str:
    q = query or ""
    # Cross-market explicit tags should dominate instrument keywords in mixed queries,
    # e.g. "港股 ... 隐含波动率" should stay in 港股 domain.
    if _RE_EXPLICIT_HK.search(q):
        return "港股"
    if _RE_EXPLICIT_US.search(q):
        return "美股"
    # New domains
    if _RE_EXPLICIT_BOND.search(q) and not _RE_CB_EXCLUDE.search(q):
        return "全量债券"
    if _RE_EXPLICIT_OPTIONS.search(q):
        return "期权"
    if _RE_EXPLICIT_WEALTH.search(q):
        return "银行理财"
    if _RE_EXPLICIT_FOREIGN_FUTURES.search(q):
        return "外盘期货"
    if _RE_EXPLICIT_A.search(q):
        return "A股"
    return ""


def market_tag_from_query(query: str) -> str:
    """
    规则推断市场标签

    优先级（按顺序执行，先匹配先返回）：
    1. 南向资金/港股通 → 港股（内地资金买港股）
    2. 港股卖空术语（孖展/沽空）→ 港股
    3. 显式港股标记（港股/恒生/.HK）→ 港股
    4. 显式美股标记 → 美股
    5. 显式基金产品标记 → 基金
    6. 显式指数标记 → 指数
    7. 北向资金/陆股通 → A股（解决误判）
    8. 机构持仓/社保/QFII → A股（解决误判）
    9. A股特有机制（龙虎榜/两融）→ A股
    10. 默认 A股

    Args:
        query: 原始查询

    Returns:
        市场标签: "A股" | "港股" | "美股" | "基金" | "指数"

    Note: This function is used only by eval scripts, not by the production pipeline.
    """
    # ============================================================
    # 第一优先级：Stock Connect 南向（→ 港股）
    # 南向资金 = 内地投资者通过港股通买卖【香港联交所】股票
    # ============================================================
    for pat in _SOUTHBOUND_PATTERNS:
        if pat.search(query):
            return "港股"

    # ============================================================
    # 第二优先级：港股卖空/保证金术语（→ 港股）
    # 港股使用粤语/繁体金融术语，与A股“融资融券”不同
    # ============================================================
    for pat in _HK_MARGIN_PATTERNS:
        if pat.search(query):
            # 但如果同时有明确A股标记，则不覆盖
            if not _RE_HK_MARGIN_A_CHECK.search(query):
                return "港股"

    # ============================================================
    # 第三优先级：显式港股标记
    # ============================================================
    if _RE_EXPLICIT_HK.search(query):
        return "港股"

    # ============================================================
    # 第四优先级：显式美股标记
    # ============================================================
    if _RE_EXPLICIT_US.search(query):
        return "美股"

    # ============================================================
    # 第五优先级：显式基金产品标记
    # 注意：排除"社保基金""保险基金"等机构投资者语境
    # ============================================================
    for pat in _FUND_PATTERNS:
        m = pat.search(query)
        if m:
            if _RE_FUND_INST_EXCLUDE.search(m.group(0)):
                continue
            return "基金"

    # ============================================================
    # 第五点五优先级：期权（需在指数之前，避免"沪深300期权"被匹配为指数）
    # ============================================================
    if _RE_EXPLICIT_OPTIONS.search(query):
        return "期权"

    # ============================================================
    # 第六优先级：显式指数标记
    # ============================================================
    if _RE_INDEX.search(query):
        return "指数"

    # ============================================================
    # 第七优先级：北向资金/陆股通 → A股
    # 北向资金 = 外资通过沪股通/深股通买卖【沪深交易所】A股
    # 常被 LLM 误判为港股，因为涉及“港”字
    # ============================================================
    for pat in _NORTHBOUND_PATTERNS:
        if pat.search(query):
            return "A股"

    # ============================================================
    # 第八优先级：机构持仓/社保/QFII → A股
    # 这些是 A股上市公司季报中的“前十大股东”数据
    # 常被 LLM 误判为基金数据
    # ============================================================
    for pat in _INST_PATTERNS:
        if pat.search(query):
            return "A股"

    # ============================================================
    # 第八点五优先级：外盘期货（需在国内期货之前，避免被通用期货匹配）
    # ============================================================
    if _RE_EXPLICIT_FOREIGN_FUTURES.search(query):
        return "外盘期货"

    # ============================================================
    # 第九优先级：期货
    # ============================================================
    for pat in _FUTURES_PATTERNS:
        if pat.search(query):
            return "期货"

    # ============================================================
    # 第九点五优先级：全量债券（排除可转债）
    # ============================================================
    if _RE_EXPLICIT_BOND.search(query) and not _RE_CB_EXCLUDE.search(query):
        return "全量债券"

    # ============================================================
    # 第十优先级：可转债
    # ============================================================
    for pat in _CB_PATTERNS:
        if pat.search(query):
            return "可转债"

    # ============================================================
    # 第十点五优先级：新三板
    # ============================================================
    for pat in _THREEBOARD_PATTERNS:
        if pat.search(query):
            return "新三板"

    # ============================================================
    # 第十点六优先级：银行理财
    # ============================================================
    if _RE_EXPLICIT_WEALTH.search(query):
        return "银行理财"

    # ============================================================
    # 第十一优先级：A股特有机制
    # ============================================================
    for pat in _ASTOCK_PATTERNS:
        if pat.search(query):
            return "A股"

    # ============================================================
    # 默认：A股（中国用户绝大部分查询都是 A股）
    # ============================================================
    return "A股"


def detect_explicit_frequency_tag(query: str) -> Optional[str]:
    if not query:
        return None

    # 按粒度从细到粗检测，最细粒度优先
    if _RE_FREQ_INTRADAY.search(query):
        return "时序"
    if _RE_FREQ_DAILY.search(query):
        return "日频"
    if _RE_FREQ_WEEKLY.search(query):
        return "周频"
    if _RE_FREQ_MONTHLY.search(query):
        return "月频"
    if _RE_FREQ_QUARTERLY.search(query):
        return "季度"
    if _RE_FREQ_ANNUAL.search(query):
        return "年频"

    return None


def infer_frequency_tag(query: str) -> Optional[str]:
    """
    推断数据频率标签

    只在高置信度时返回，避免误判

    Args:
        query: 原始查询

    Returns:
        频率标签: "时序" | "季度" | "日频" | None

    Note: This function is used only by eval scripts, not by the production pipeline.
    """
    explicit = detect_explicit_frequency_tag(query)
    if explicit:
        return explicit

    # 机构持仓类 → 季度
    if _RE_INFER_QUARTERLY.search(query):
        return "季度"

    # 周频数据 (avoid matching 周一/周二/周末 etc.)
    if _RE_INFER_WEEKLY.search(query):
        return "周频"

    # 月频数据
    if _RE_INFER_MONTHLY.search(query):
        return "月频"

    # 年频数据 (年度分红/年报/财务等)
    if _RE_INFER_ANNUAL.search(query):
        return "年频"

    # 日频数据 (explicit signals)
    if _RE_INFER_DAILY_EXPLICIT.search(query):
        return "日频"

    # 日频数据 (implicit from resource flow/charts patterns)
    if _RE_INFER_DAILY_IMPLICIT.search(query):
        return "日频"

    # 日频 (near-N-days pattern)
    if _RE_INFER_DAILY_NEAR.search(query):
        return "日频"

    # 期权行情/报价类 → 日频
    if _RE_INFER_DAILY_OPTIONS.search(query):
        return "日频"

    # 债券估值类 → 日频
    if _RE_INFER_DAILY_BOND_VALUATION.search(query):
        return "日频"

    # 银行理财净值类 → 日频
    if _RE_INFER_DAILY_WEALTH_NAV.search(query):
        return "日频"

    # 不确定时返回 None，让检索系统自己判断
    return None


if __name__ == "__main__":
    # Simple test for market_tag_from_query and infer_frequency_tag
    test_queries = [
        "北向资金买入",
        "南向资金流入",
        "机构持仓变动",
        "融资余额",
        "龙虎榜",
        "5分钟换手率",
        "机构持仓季报",
        "国债收益率曲线",
        "50ETF期权行情",
        "银行理财产品净值",
        "伦铜期货价格",
        "可转债转股价值",
    ]

    print("=" * 50)
    print("Market Rules Test")
    print("=" * 50)

    for query in test_queries:
        market = market_tag_from_query(query)
        freq = infer_frequency_tag(query)
        print(f"Query: {query}")
        print(f"  Market: {market}, Frequency: {freq}")
        print()
