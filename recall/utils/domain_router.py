"""
Domain Router - 领域路由器 (Enhanced v2)

基于规则的查询路由，将隐式领域知识显式化。
例如：用户说"外资卖出金额" → 实际需要查"龙虎榜"表的"境外游资"类型

核心思路：
1. 规则优先级排序，first-match wins（单意图模式）
2. 多意图模式：收集所有匹配规则，合并输出（用于对比类查询）
3. 输出搜索范围限定 (allowed_yaml_paths) + 查询扩展 (query_expansions)
4. 始终保留全局搜索兜底 (fallback_strategy)

覆盖市场：A股、港股、美股、基金、基金经理、基金公司、期货、期货品种、可转债、指数、新三板、
         全量债券、期权、银行理财、外盘期货、市场环境、同花顺保险、英股
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Pattern, Set, Dict, Tuple

from .financial_terms import TERM_FOREIGN_TRADER, TERM_LHB
from .market_rules import detect_explicit_market_tag

logger = logging.getLogger(__name__)


# ============================================================
# 路由输出 - 支持多意图
# ============================================================


@dataclass(frozen=True)
class RouterOutput:
    """路由输出结果（支持多意图扩展）

    保持向后兼容：intent/market/frequency 为主意图信息。
    intents/markets/frequencies 为多意图扩展字段。
    """

    intent: str  # 主意图标识，如 "lhb_foreign_trade"
    query_expansions: Tuple[str, ...]  # 追加到 query 的 tokens（用于检索增强）
    allowed_yaml_paths: Tuple[str, ...]  # 限制搜索范围
    market: Optional[str] = None  # 主市场过滤：A股/港股/基金...
    frequency: Optional[str] = None  # 主频率过滤：日频/季度...
    confidence: float = 0.0  # 整体置信度 0.0 - 1.0
    fallback_strategy: str = "global_only"  # "merge" | "global_only"

    # ---- 多意图扩展字段（向后兼容，默认为空元组）----
    intents: tuple = ()  # 所有匹配到的意图标识  # Used for logging only
    markets: tuple = ()  # 所有匹配到的市场标签  # Used for logging only
    frequencies: tuple = ()  # 所有匹配到的频率标签  # Used for logging only

    negation_terms: tuple = ()  # 否定条件透传，如 ("ST", "质押")

    @property
    def is_multi_intent(self) -> bool:
        """是否为多意图路由"""
        return len(self.intents) > 1


# ============================================================
# 路由规则定义
# ============================================================


@dataclass
class RouterRule:
    """路由规则定义"""

    intent: str  # 意图标识
    priority: int  # 优先级（越大越优先）
    pattern: str  # 正则匹配模式
    allowed_yaml_paths: List[str]  # 限制的 yaml 路径
    query_expansions: List[str] = field(default_factory=list)  # 查询扩展词
    negative_pattern: Optional[str] = None  # 负向匹配（命中则不触发）
    market: Optional[str] = None
    frequency: Optional[str] = None
    confidence: float = 0.85
    fallback_strategy: str = "merge"

    _compiled_pattern: Optional[Pattern[str]] = field(
        default=None, repr=False, compare=False
    )
    _compiled_negative: Optional[Pattern[str]] = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self):
        # 编译正则表达式
        self._compiled_pattern = re.compile(self.pattern, re.IGNORECASE)
        if self.negative_pattern:
            self._compiled_negative = re.compile(self.negative_pattern, re.IGNORECASE)

    def matches(self, query: str) -> bool:
        """检查 query 是否匹配此规则"""
        if not self._compiled_pattern:
            return False

        # 正向匹配
        if not self._compiled_pattern.search(query):
            return False

        # 负向匹配（如果命中负向模式则不触发）
        if self._compiled_negative and self._compiled_negative.search(query):
            return False

        return True


# ============================================================
# 多意图检测 - 比较/对比类 query 关键词
# ============================================================

_RE_COMPARISON = re.compile(
    r"(对比|PK|VS|vs|"
    r"和.{0,4}(?:比较|对比|PK)|"
    r"与.{0,4}(?:比较|对比|相比)|"
    # "比较" 仅在非程度副词语境下匹配（排除 "比较大/多/高/低/强/弱/好/差/快/慢/贵" 等）
    r"比较(?![大小多少高低强弱好差快慢贵便宜长短深浅重轻])"
    r")",
    re.IGNORECASE,
)
_RE_MULTI_MARKET_SEPARATOR = re.compile(
    r"(和|与|及|跟|vs|VS|/|对比|比较|PK|pk)",
    re.IGNORECASE,
)

# “非北交所/剔除北交所”否定语义，避免新三板规则误触发。
_NEG_BJ_EXCLUSION_PATTERN = (
    r"(?:非|剔除|去除|排除|不含|除外).{0,3}北交所|"
    r"北交所.{0,3}(?:除外|剔除|排除|不含|去除)"
)

# ============================================================
# A股 专属 Jargon 集合 (同花顺自创形态/指标名)
# 用于 Fallback 层检测：当精确规则均不命中时，若 query 包含
# 此集合中的任意术语，则推断为 A股 查询。
# TODO: 未来可从 YAML schema 的 f2f## 列名自动提取更新。
# ============================================================

ASTOCK_JARGON_SET: frozenset = frozenset({
    # ---- 同花顺自创 K线/技术形态 (f2f## 列名) ----
    "青龙取水", "龙腾四海", "空方炮", "多方炮", "仙人指路",
    "三元联动", "强中选强", "黑客点击", "高开出逃形", "上升回档",
    "上升尽头线", "下降尽头线", "底部堆量连阳", "倍量中阳", "放量反包",
    "放量阳包阴", "回调缩量", "冲高回落", "高开高走", "低开高走",
    "三重底", "三重顶", "头肩底", "头肩顶",
    "底部放量", "高位放量", "地量十字星", "缩量十字星",
    "曙光初现", "穿头破脚", "身怀六甲",
    "圆弧底", "圆弧顶", "旗形整理", "楔形整理",
    "龙出红海", "扬帆起航", "金针探底", "两阳夹一阴",
    "两阴夹一阳", "蛟龙出海", "断头铡刀", "老鸭头",
    "均线将死不死", "均线将金不金", "突破粘合均线",
    # ---- 同花顺特色指标/信号名 ----
    "主力进攻", "主力拉升", "主力出逃", "主力控盘",
    "尾盘抢筹", "尾盘砸盘", "资金进场", "资金出逃",
    "人气龙头", "短线超跌", "超跌反弹",
    "筹码集中", "筹码分散", "主力持仓成本",
    "暗盘资金",
    # ---- EMV 等自有技术指标信号 ----
    "EMV下行", "EMV下移", "EMV上行", "EMV上移",
    "EMV买入信号", "EMV卖出信号",
    # ---- 近期 dry-run 发现的遗漏形态 ----
    "吊颈线", "长上影线", "长下影线",
})


# A股 隐式特征检测正则 —— 用于 Fallback 层
# 当 141 条精确规则全部 miss 后，若 query 命中以下信号之一，
# 则推断该 query 属于 A股 领域，避免退化为 global_only。
_ASTOCK_IMPLICIT_SIGNALS: Pattern[str] = re.compile(
    r"(涨停|跌停|连板|封板|炸板|打板|"
    r"龙头股?|妖股|牛散|游资|"
    r"主力|控盘|增仓|减仓|抢筹|出货|"
    r"金叉|死叉|均线|MACD|KDJ|RSI|BOLL|布林|EMV|MAEMV|"
    r"融资|融券|两融|"
    r"北向|陆股通|沪股通|深股通|"
    r"概念股?|板块|行业龙头|成[份分]股|"
    r"热度|人气|买入信号|卖出信号|"
    r"ST|退市|摘帽|戴帽|"
    r"商誉|质押|解禁|限售|增减持|"
    r"年报|季报|半年报|一季报|中报|三季报|"
    r"大阳|大阴|放量|缩量|十字星|"
    r"个股|股价|收盘价|开盘价|涨跌幅|涨幅|跌幅|"
    r"筹码|资金流|净流入|净流出|委比|换手率|量比|"
    r"上穿|下穿|突破|支撑|压力|阻力|"
    r"A股|沪市|深市|创业板|科创板|主板|"
    r"复牌|停牌|冻结|"
    r"龙虎榜|大宗交易|回购|"
    r"分红|派息|送转|股息|股利|"
    r"十大股东|流通股东|大股东|"
    r"市盈率|市净率|市销率|PB|PE|"
    r"成交量|成交额|换手|"
    r"威廉指数|WR|OBV|CCI|DMI|TRIX|"
    r"资金进入|资金撤出|实时资金|"
    r"信号|热度排名|人气排名|控盘度)",
    re.IGNORECASE,
)


# ---------- 跨域信号检测（用于隐式多意图路由）----------
_FINANCIAL_DOMAIN_KW = re.compile(
    r"(财报|财务|营收|营业收入|净利润|归母净利|扣非|毛利|毛利率|EPS|ROE|ROA|"
    r"资产负债|现金流|利润表|负债率|每股收益|每股净资产|总资产|总负债|"
    r"经营现金流|研发费用|销售费用|管理费用|财务费用|应收账款|存货|商誉)",
    re.IGNORECASE,
)

_MARKET_DOMAIN_KW = re.compile(
    r"(涨跌幅|涨幅|跌幅|股价|收盘价|开盘价|最高价|最低价|成交量|成交额|"
    r"换手率|涨停|跌停|连板|行情|K线|均线|MACD|量比|委比)",
    re.IGNORECASE,
)


# ---------- 否定条件抽取 ----------
_RE_NEGATION = re.compile(
    r"(?:不含|不包含|剔除|排除|去除|非|没有|无|除了|除去)\s*"
    r"(ST|退市|亏损|质押|停牌|B股|北交所|新三板|创业板|科创板|次新股|"
    r"基金|期货|可转债|指数|银行|证券|保险)",
    re.IGNORECASE,
)

_RE_SHORT_THEME_QUERY = re.compile(r"^[\u4e00-\u9fff]{2,8}$")
_RE_COMPANY_LIKE_SUFFIX = re.compile(
    r"(股份|科技|电子|制药|药业|集团|银行|证券|保险|电器|能源|材料|化工|通信|信息|控股|实业|医药|锂业)$"
)


def extract_negation_terms(query: str) -> tuple:
    """Extract negated entities from query for downstream post-filtering.

    Examples:
        "不含ST" -> ("ST",)
        "无质押" -> ("质押",)
        "剔除北交所" -> ("北交所",)
    """
    return tuple(m.group(1) for m in _RE_NEGATION.finditer(query))


# 显式市场关键词，用于对比类查询下的多市场补全。
_MARKET_PATTERNS: Dict[str, Pattern[str]] = {
    "A股": re.compile(r"(A股|沪市|深市|创业板|科创板)", re.IGNORECASE),
    "港股": re.compile(r"(港股|H股|恒生指数|恒指|\.HK|HK股|港股通|南向资金)", re.IGNORECASE),
    "美股": re.compile(r"(美股|纳斯达克|纽交所|NASDAQ|NYSE|\.US|标普|道琼斯)", re.IGNORECASE),
    "基金经理": re.compile(r"基金经理", re.IGNORECASE),
    "基金公司": re.compile(r"(基金公司|管理人|管理公司)", re.IGNORECASE),
    "基金": re.compile(r"(基金|ETF|LOF|QDII|公募|私募)", re.IGNORECASE),
    "期货": re.compile(
        r"(期货|合约|主力合约|基差|升贴水|仓单|交割|IF\d{4}|IH\d{4}|IC\d{4}|IM\d{4})",
        re.IGNORECASE,
    ),
    "可转债": re.compile(r"(可转债|转债|可转换债券|转股价|转股溢价)", re.IGNORECASE),
    "指数": re.compile(r"(指数|沪深300|上证指数|深证成指|创业板指|科创50|中证\d+)"),
    "新三板": re.compile(r"(新三板|三板|北交所|精选层|创新层|基础层)"),
    "全量债券": re.compile(r"(债券|国债|企业债|公司债|信用债|利率债|城投债|ABS|资产支持)"),
    "期权": re.compile(r"(期权|认购期权|认沽期权|看涨|看跌|行权|隐含波动率|Greek|Delta|Gamma|Vega|Theta)"),
    "银行理财": re.compile(r"(银行理财|理财产品|净值型理财|固收|固定收益)"),
    "外盘期货": re.compile(r"(外盘期货|伦铜|伦铝|伦锌|伦镍|WTI|布伦特|COMEX|LME|NYMEX|ICE|CME外盘)"),
    "市场环境": re.compile(r"(交易日历|经济事件|市场温度|市场情绪|大盘情绪|新财富|旅游资金)"),
}

# 对比类查询中，当规则无法命中某个显式市场时，使用市场兜底路径补齐多意图输出。
_MARKET_FALLBACKS: Dict[str, Dict[str, object]] = {
    "A股": {
        "intent": "price_change",
        "allowed_yaml_paths": [
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        "query_expansions": ["A股", "行情", "涨跌"],
        "market": "A股",
        "frequency": "日频",
        "confidence": 0.68,
    },
    "港股": {
        "intent": "hk_daily_quote",
        "allowed_yaml_paths": [
            "港股/stock_hkstock_mkt_daily_trans.yaml",
            "港股/stock_hkstock_mkt_trans_latest.yaml",
        ],
        "query_expansions": ["港股", "行情", "涨跌"],
        "market": "港股",
        "frequency": "日频",
        "confidence": 0.78,
    },
    "美股": {
        "intent": "us_daily_quote",
        "allowed_yaml_paths": [
            "美股/stock_ustock_mkt_daily_trans.yaml",
            "美股/stock_ustock_mkt_daily_trans_latest.yaml",
        ],
        "query_expansions": ["美股", "行情", "涨跌"],
        "market": "美股",
        "frequency": "日频",
        "confidence": 0.78,
    },
    "基金": {
        "intent": "fund_nav",
        "allowed_yaml_paths": [
            "基金/fund_mkt_daily_trans_latest.yaml",
            "基金/fund_mkt_daily_trans.yaml",
            "基金/fund_basic_info.yaml",
        ],
        "query_expansions": ["基金", "净值"],
        "market": "基金",
        "frequency": "日频",
        "confidence": 0.80,
    },
    "期货": {
        "intent": "futures_daily_quote",
        "allowed_yaml_paths": [
            "期货/futu_mkt_daily_quo_latest.yaml",
            "期货/futu_mkt_daily_quo.yaml",
        ],
        "query_expansions": ["期货", "主力合约", "行情"],
        "market": "期货",
        "frequency": "日频",
        "confidence": 0.80,
    },
    "可转债": {
        "intent": "cb_market",
        "allowed_yaml_paths": [
            "可转债/convertiblebond_market.yaml",
            "可转债/convertiblebond_market_new.yaml",
        ],
        "query_expansions": ["可转债", "行情"],
        "market": "可转债",
        "frequency": "日频",
        "confidence": 0.80,
    },
    "指数": {
        "intent": "index_quote",
        "allowed_yaml_paths": [
            "全量指数/index_mkt_daily_trans.yaml",
            "全量指数/index_latest_index.yaml",
        ],
        "query_expansions": ["指数", "行情"],
        "market": "指数",
        "frequency": "日频",
        "confidence": 0.78,
    },
    "新三板": {
        "intent": "threeboard_daily_quote",
        "allowed_yaml_paths": [
            "新三板/stock_threeboard_mkt_daily_trans.yaml",
            "新三板/stock_threeboard_mkt_trans_latest.yaml",
        ],
        "query_expansions": ["新三板", "三板", "行情"],
        "market": "新三板",
        "frequency": "日频",
        "confidence": 0.78,
    },
    "基金公司": {
        "intent": "fund_company_info",
        "allowed_yaml_paths": ["基金公司/fund_company_basic_info.yaml", "基金公司/fund_company_latest_index.yaml"],
        "query_expansions": ["基金公司", "管理规模"],
        "market": "基金公司",
        "frequency": "",
        "confidence": 0.78,
    },
    "基金经理": {
        "intent": "fund_manager_performance",
        "allowed_yaml_paths": ["基金经理/fundmanager_latest_index.yaml", "基金经理/fund_manager_basic_info.yaml"],
        "query_expansions": ["基金经理", "业绩"],
        "market": "基金经理",
        "frequency": "",
        "confidence": 0.78,
    },
    "期货品种": {
        "intent": "futures_variety",
        "allowed_yaml_paths": ["期货品种/futu_pdt_info.yaml", "期货品种/futu_pdt_trade_info.yaml"],
        "query_expansions": ["期货品种", "品种"],
        "market": "期货品种",
        "frequency": "",
        "confidence": 0.78,
    },
    "全量债券": {
        "intent": "bond_quote",
        "allowed_yaml_paths": ["全量债券/bond_mkt_quo.yaml", "全量债券/bond_basic_info.yaml"],
        "query_expansions": ["债券", "行情"],
        "market": "全量债券",
        "frequency": "日频",
        "confidence": 0.78,
    },
    "期权": {
        "intent": "options_quote",
        "allowed_yaml_paths": ["期权/options_mkt_daily.yaml", "期权/options_basics.yaml"],
        "query_expansions": ["期权", "行情"],
        "market": "期权",
        "frequency": "日频",
        "confidence": 0.78,
    },
    "银行理财": {
        "intent": "bwmp_nav",
        "allowed_yaml_paths": ["银行理财/bwmp_daily_market_data.yaml", "银行理财/bwmp_basic_info.yaml"],
        "query_expansions": ["银行理财", "理财产品"],
        "market": "银行理财",
        "frequency": "日频",
        "confidence": 0.78,
    },
    "外盘期货": {
        "intent": "foreign_futures_general",
        "allowed_yaml_paths": [
            "外盘期货/futu_mkt_daily_quo_foris.yaml",
            "外盘期货/futu_contract_info_foris.yaml",
        ],
        "query_expansions": ["外盘期货"],
        "market": "外盘期货",
        "frequency": "日频",
        "confidence": 0.60,
    },
    "市场环境": {
        "intent": "market_env_general",
        "allowed_yaml_paths": [
            "市场环境/pub_sec_mkt_trade_calendar.yaml",
            "市场环境/pub_sec_mkt_trade_performance.yaml",
        ],
        "query_expansions": ["市场环境"],
        "market": "市场环境",
        "frequency": "",
        "confidence": 0.60,
    },
    "同花顺保险": {
        "intent": "insurance_product",
        "allowed_yaml_paths": [
            "同花顺保险/insurance_basic.yaml",
            "同花顺保险/insurance_protection_plan.yaml",
        ],
        "query_expansions": ["保险产品", "保险"],
        "market": "同花顺保险",
        "frequency": "",
        "confidence": 0.55,
    },
    "英股": {
        "intent": "uk_stock_ipo",
        "allowed_yaml_paths": [
            "英股/stock_ukstock_ipo.yaml",
        ],
        "query_expansions": ["英股", "IPO"],
        "market": "英股",
        "frequency": "",
        "confidence": 0.55,
    },
}


# ============================================================
# 预定义路由规则 - 按市场分组、优先级排序
# ============================================================

DEFAULT_ROUTER_RULES: List[RouterRule] = [

    # ===========================================================
    #  A股规则 (priority 45 ~ 100)
    # ===========================================================

    # Rule: 外资买卖（个股级）→ 龙虎榜（最高优先级）
    RouterRule(
        intent="lhb_foreign_trade",
        priority=100,
        pattern=r"外资.{0,5}(买入|卖出|买卖|净买入|净卖出|流入|流出|金额|资金)",
        negative_pattern=r"(持股|持仓|占比|变动|比例|季度)",
        allowed_yaml_paths=["股票/stock_astock_charts.yaml"],
        query_expansions=[TERM_LHB, TERM_FOREIGN_TRADER, "营业部类型"],
        market="A股",
        frequency="日频",
        confidence=0.90,
    ),
    # Rule: 北向资金/陆股通买卖（个股级）→ 龙虎榜
    RouterRule(
        intent="lhb_northbound_trade",
        priority=95,
        pattern=r"(北向资金|陆股通|沪股通|深股通|港资).{0,5}(买入|卖出|净买入|净卖出|流入|流出|金额|资金流向)",
        negative_pattern=r"(持股比例|持仓占比|季度|年度|占流通)",
        allowed_yaml_paths=["股票/stock_astock_charts.yaml"],
        query_expansions=[TERM_LHB, TERM_FOREIGN_TRADER],
        market="A股",
        frequency="日频",
        confidence=0.85,
    ),
    # Rule: 机构买卖/资金流向（个股级）→ 龙虎榜
    RouterRule(
        intent="lhb_institution_trade",
        priority=90,
        pattern=r"机构.{0,5}(买入|卖出|净买入|席位|资金|流向)",
        negative_pattern=r"(持股|持仓|调研|评级|季度)",
        allowed_yaml_paths=["股票/stock_astock_charts.yaml"],
        query_expansions=[TERM_LHB, "机构席位", "机构专用", "机构买入"],
        market="A股",
        frequency="日频",
        confidence=0.85,
    ),
    # Rule: 龙虎榜直接提及
    RouterRule(
        intent="lhb_direct",
        priority=85,
        pattern=r"龙虎榜",
        allowed_yaml_paths=[
            "股票/stock_astock_charts.yaml",
            "股票/stock_astock_charts_stat.yaml",
        ],
        query_expansions=[],
        market="A股",
        frequency="日频",
        confidence=0.95,
    ),
    # Rule: 北向/陆股通成交排行
    RouterRule(
        intent="northbound_ranking",
        priority=84,
        pattern=r"(北向资金|陆股通|沪股通|深股通|沪港通|深港通).{0,8}(排行|排名|榜|成交|成交量|成交额|净买入|净流入)",
        negative_pattern=r"(持股比例|持仓占比|季度|年度|占流通)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_basic_info.yaml",
        ],
        query_expansions=["北向资金", "陆股通成交额", "沪股通", "深股通", "股票代码"],
        market="A股",
        frequency="日频",
        confidence=0.88,
    ),
    # Rule: 分时/分钟级行情
    RouterRule(
        intent="intraday_timesharing",
        priority=82,
        pattern=r"(分时|逐笔|盘口|分钟|5分钟|15分钟|30分钟|60分钟|分钟级|集合竞价|竞价匹配|开盘竞价|收盘竞价)",
        negative_pattern=r"(日线|周线|月线|年线|年度|港股|美股|美元|H股|\.HK|\.US|NASDAQ|NYSE|(?<![A-Za-z])ETF(?![A-Za-z]))",
        allowed_yaml_paths=[
            "股票/stock_astock_time_sharing_market.yaml",
            "股票/stock_astock_mkt_min_trans.yaml",
        ],
        query_expansions=["分时行情", "分钟行情", "时序"],
        market="A股",
        frequency="时序",
        confidence=0.90,
    ),
    # Rule: 外资/QFII 持仓 → 机构持仓表
    RouterRule(
        intent="foreign_holdings",
        priority=80,
        pattern=r"(外资|QFII|合格境外).{0,5}(持股|持仓|占比|变动|比例|市值|换手)",
        allowed_yaml_paths=["股票/stock_astock_shareholding_insitutions.yaml"],
        query_expansions=["外资持股", "QFII", "机构持仓"],
        market="A股",
        confidence=0.85,
    ),
    # Rule: 机构持仓（社保/保险/券商/信托等）
    RouterRule(
        intent="institutional_holdings",
        priority=78,
        pattern=r"(社保|保险|券商|QFII|RQFII|信托|基金|机构).{0,5}(持仓|持股|换手|市值|变动|占比|比例|数量)",
        negative_pattern=r"(基金净值|基金经理|基金规模|基金市值|基金公司|ETF净值|ETF规模|基金持仓|基金重仓|基金十大|ETF持仓|ETF重仓)",
        allowed_yaml_paths=[
            "股票/stock_astock_shareholding_insitutions.yaml",
            "股票/stock_astock_institutional_stat.yaml",
        ],
        query_expansions=["机构持仓", "持仓变动"],
        market="A股",
        frequency="季度",
        confidence=0.85,
    ),
    # Rule: A股机构持股统计（避免误路由到基金产品持仓）
    RouterRule(
        intent="stock_institution_holding",
        priority=236,
        pattern=(
            r"(基金重仓股|社保基金重仓|"
            r"(?:基金|社保基金|保险|QFII|RQFII).{0,6}(?:持股|持仓).{0,6}"
            r"(?:家数|数量|市值|占比|比例|变动|统计|明细))"
        ),
        negative_pattern=r"(基金经理|基金公司|基金产品|基金净值|基金业绩|ETF净值|ETF业绩)",
        allowed_yaml_paths=[
            "股票/stock_astock_shareholding_insitutions.yaml",
            "股票/stock_astock_institutional_stat.yaml",
        ],
        query_expansions=["机构持仓", "基金持股", "社保基金持股"],
        market="A股",
        frequency="季度",
        confidence=0.88,
    ),
    # Rule: 多因子选股（行情筛选 + 财务/机构维度）
    RouterRule(
        intent="astock_multi_factor_screen",
        priority=234,
        pattern=(
            r"("
            r"(流通市值|总市值|市值|停牌|复牌|退市|ST|科创板|创业板|交易日|收盘价|均线|涨跌幅|成交额|交易额)"
            r".{0,40}"
            r"(营收|营业收入|净利润|扣非|毛利率|ROE|机构持仓|机构调研|北向资金|减持|增持|回购|股东)"
            r"|"
            r"(营收|营业收入|净利润|扣非|毛利率|ROE|机构持仓|机构调研|北向资金|减持|增持|回购|股东)"
            r".{0,40}"
            r"(流通市值|总市值|市值|停牌|复牌|退市|ST|科创板|创业板|交易日|收盘价|均线|涨跌幅|成交额|交易额)"
            r")"
        ),
        negative_pattern=r"(港股|美股|基金净值|ETF净值|期货|可转债|指数基金|债券)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_company_financial_data.yaml",
            "股票/stock_astock_company_financial_data_new.yaml",
            "股票/stock_astock_shareholding_insitutions.yaml",
            "股票/stock_astock_institutional_stat.yaml",
            "股票/stock_astock_basic_info.yaml",
        ],
        query_expansions=["选股", "行情筛选", "财务数据", "机构持仓"],
        market="A股",
        frequency="日频",
        confidence=0.90,
    ),
    # Rule: 机构调研 + 北向资金联合筛选
    RouterRule(
        intent="research_northbound_screen",
        priority=232,
        pattern=(
            r"("
            r"(机构调研|调研次数).{0,18}(北向资金|陆股通|沪股通|深股通).{0,12}(增持|持股|净买入|净流入|比例|占比)"
            r"|"
            r"(北向资金|陆股通|沪股通|深股通).{0,18}(机构调研|调研次数).{0,12}(增持|持股|净买入|净流入|比例|占比)?"
            r")"
        ),
        negative_pattern=r"(港股|美股|基金|ETF|期货|可转债|新三板)",
        allowed_yaml_paths=[
            "股票/stock_astock_institutional_research_stat.yaml",
            "股票/stock_astock_charts.yaml",
            "股票/stock_astock_mkt_daily_trans.yaml",
        ],
        query_expansions=["机构调研", "调研统计", "北向资金", "持股变化"],
        market="A股",
        frequency="日频",
        confidence=0.92,
    ),
    # Rule: 指定机构/外资主体增减持事件
    RouterRule(
        intent="institutional_entity_position_change",
        priority=231,
        pattern=(
            r"(中央银行|主权基金|养老金|养老基金|贝莱德|高盛|摩根|瑞银|挪威|淡马锡|景顺|富达|社保|保险|QFII|RQFII)"
            r".{0,10}(增持|减持|买入|卖出)"
        ),
        negative_pattern=r"(基金净值|基金业绩|基金经理排名|ETF净值|基金规模|港股|美股|期货|可转债)",
        allowed_yaml_paths=[
            "股票/stock_astock_shareholding_insitutions.yaml",
            "股票/stock_astock_institutional_stat.yaml",
            "股票/stock_astock_increase_decrease.yaml",
        ],
        query_expansions=["机构持仓", "增减持", "持股变动"],
        market="A股",
        frequency="季度",
        confidence=0.91,
    ),
    # Rule: 指定机构/外资主体新进增减持
    RouterRule(
        intent="institutional_entity_holding",
        priority=231,
        pattern=(
            r"(中央银行|主权基金|养老金|养老基金|贝莱德|高盛|摩根|瑞银|挪威|淡马锡|景顺|富达|社保|保险|QFII|RQFII)"
            r".{0,8}(新进|增持|减持|持仓|持股|买入|卖出)"
        ),
        negative_pattern=r"(基金净值|基金业绩|基金经理排名|ETF净值|基金规模|港股|美股|期货|可转债)",
        allowed_yaml_paths=[
            "股票/stock_astock_shareholding_insitutions.yaml",
            "股票/stock_astock_institutional_stat.yaml",
        ],
        query_expansions=["机构持仓", "新进", "持股变动"],
        market="A股",
        frequency="季度",
        confidence=0.90,
    ),
    # Rule: 人名/机构名 + 加仓/减仓/新进
    RouterRule(
        intent="named_holder_position_change",
        priority=230,
        pattern=r"[\u4e00-\u9fffA-Za-z]{2,20}(加仓|减仓|新进)$",
        negative_pattern=r"(基金净值|基金产品|基金经理收益|基金经理排名|ETF|期货|可转债|港股|美股|指数)",
        allowed_yaml_paths=[
            "股票/stock_astock_shareholding_insitutions.yaml",
            "股票/stock_astock_institutional_stat.yaml",
        ],
        query_expansions=["机构持仓", "新进", "增持"],
        market="A股",
        frequency="季度",
        confidence=0.74,
    ),
    # Rule: 业绩预告/预警
    RouterRule(
        intent="performance_forecast",
        priority=76,
        pattern=r"(业绩预告|业绩预警|业绩报坏|业绩报好|预亏|预增|预减|预盈|预警)",
        negative_pattern=r"(快报|年报|季报|财报)",
        allowed_yaml_paths=["股票/stock_astock_company_performance_forecast.yaml"],
        query_expansions=["业绩预告", "报告期", "报告期截止日"],
        market="A股",
        frequency="季度",
        confidence=0.90,
    ),
    # Rule: 业绩超预期/符合预期
    RouterRule(
        intent="earnings_expectation",
        priority=75,
        pattern=(
            r"(业绩|盈利|净利润|营收|收入).{0,6}"
            r"(超预期|符合预期|不及预期|低于预期|高于预期|大超预期|可能超预期)"
        ),
        negative_pattern=r"(港股|美股|期货|基金|可转债|新三板|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_company_financial_data.yaml",
            "股票/stock_astock_company_performance_forecast.yaml",
            "股票/stock_astock_institutional_performance_forcast.yaml",
        ],
        query_expansions=["业绩预期", "盈利预测", "业绩超预期"],
        market="A股",
        frequency="季度",
        confidence=0.90,
    ),
    # Rule: 基本资料/概念/市场类型
    RouterRule(
        intent="basic_info_profile",
        priority=74,
        pattern=r"(所属概念|概念股|所属行业|行业分类|行业成[份分]股|所属板块|股票市场类型|市场类型|证券市场|上市日期|上市天数|上市公司|新上市|主营业务|所属地区|注册地址)",
        allowed_yaml_paths=[
            "股票/stock_astock_basic_info.yaml",
            "股票/stock_astock_mkt_daily_trans.yaml",
        ],
        query_expansions=["基本资料", "股票代码", "股票简称", "所属概念"],
        market="A股",
        confidence=0.90,
    ),
    # Rule: 板块/概念/行业 + 成交额/交易额/排序
    RouterRule(
        intent="concept_turnover_ranking",
        priority=73,
        pattern=(
            r"((板块|概念|行业|题材).{0,12}(股票|个股|成分股|成交额|交易额|排名|排序|均值|平均))"
            r"|"
            r"((成交额|交易额|排名|排序|均值|平均).{0,12}(板块|概念|行业|题材))"
        ),
        negative_pattern=r"(港股|美股|基金|ETF|期货|可转债|债券)",
        allowed_yaml_paths=[
            "股票/stock_astock_concept.yaml",
            "股票/stock_astock_basic_info.yaml",
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["概念板块", "所属概念", "行业", "成交额"],
        market="A股",
        frequency="日频",
        confidence=0.86,
    ),
    # Rule: 融资融券
    RouterRule(
        intent="margin_trading",
        priority=75,
        pattern=r"(融资|融券).{0,5}(买入|卖出|净买入|净卖出|余额|金额)",
        allowed_yaml_paths=["股票/stock_astock_mkt_daily_trans.yaml"],
        query_expansions=["融资融券", "两融"],
        market="A股",
        frequency="日频",
        confidence=0.85,
    ),
    # Rule: 增减持/套现
    RouterRule(
        intent="increase_decrease",
        priority=72,
        pattern=r"(减持|增持|套现|高管(买|卖)|股东(买|卖|减|增)).{0,6}(金额|比例|股数|数量)?",
        negative_pattern=r"(仓位|加仓|减仓|建仓|清仓|平仓)",
        allowed_yaml_paths=[
            "股票/stock_astock_increase_decrease.yaml",
            "股票/stock_astock_increase_decrease_plan.yaml",
        ],
        query_expansions=["增减持", "股东变动", "减持金额"],
        market="A股",
        confidence=0.85,
    ),
    # Rule: 股东增持/减持 + 回购组合
    RouterRule(
        intent="shareholder_buyback_combo",
        priority=74,
        pattern=(
            r"("
            r"(股东)?(增减持|增持|减持).{0,12}(回购|回购公告|回购明细)"
            r"|"
            r"(回购|回购公告|回购明细).{0,12}(股东)?(增减持|增持|减持)"
            r"|"
            r"股东(增减持|增持|减持)或回购明细"
            r")"
        ),
        negative_pattern=r"(逆回购|国债逆回购|仓位|加仓基金|减仓基金)",
        allowed_yaml_paths=[
            "股票/stock_astock_basic_info.yaml",
            "股票/stock_astock_increase_decrease.yaml",
            "股票/stock_astock_increase_decrease_plan.yaml",
            "股票/stock_astock_repurchase_of_shares.yaml",
        ],
        query_expansions=["股东增持", "回购明细", "回购股份"],
        market="A股",
        confidence=0.90,
    ),
    # --- 无/未质押 ---
    RouterRule(
        intent="astock_no_pledge",
        priority=69,
        pattern=r"((无|未|没有).{0,3}质押|不含质押|零质押)",
        negative_pattern=r"(新三板|可转债|债券)",
        allowed_yaml_paths=[
            "股票/stock_astock_basic_info.yaml",
            "股票/stock_astock_pledge_stat.yaml",
            "股票/stock_astock_equity_pledge.yaml",
        ],
        query_expansions=["股权质押", "零质押"],
        market="A股",
        confidence=0.88,
    ),
    # --- 名称/简称包含字样的股票 ---
    RouterRule(
        intent="astock_name_keyword_filter",
        priority=69,
        pattern=r"(名字|名称|简称).{0,4}(有|包含|带).{0,3}[\u4e00-\u9fffA-Za-z0-9].{0,8}(股票|个股)?",
        negative_pattern=r"(基金|ETF|港股|美股|期货|可转债)",
        allowed_yaml_paths=[
            "股票/stock_astock_basic_info.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["股票简称", "股票名称", "基本资料"],
        market="A股",
        confidence=0.88,
    ),
    # Rule: 主力资金流向
    RouterRule(
        intent="main_force_flow",
        priority=70,
        pattern=r"主力.{0,5}(流入|流出|净流入|净流出|资金|买入|卖出|拉升|增仓|减仓|控盘|进攻|建仓|出货|成本|吸筹|洗盘|资金弱势|资金强势)",
        allowed_yaml_paths=["股票/stock_astock_mkt_daily_trans.yaml"],
        query_expansions=["主力资金", "资金流向"],
        market="A股",
        frequency="日频",
        confidence=0.75,
    ),
    # Rule: 大单/特大单
    RouterRule(
        intent="large_order_flow",
        priority=65,
        pattern=r"(大单|特大单|中单|小单).{0,5}(流入|流出|净流入|净额|买入|卖出)",
        allowed_yaml_paths=["股票/stock_astock_mkt_daily_trans.yaml"],
        query_expansions=["资金流向", "DDE"],
        market="A股",
        frequency="日频",
        confidence=0.75,
    ),
    # Rule: 内盘外盘/主动买卖
    RouterRule(
        intent="active_passive_trade",
        priority=63,
        pattern=r"(内盘|外盘|内外盘|主动(买入|卖出|成交)|被动(买入|卖出|成交)|挂单)",
        allowed_yaml_paths=["股票/stock_astock_mkt_daily_trans.yaml"],
        query_expansions=["主动成交", "内盘", "外盘"],
        market="A股",
        frequency="日频",
        confidence=0.80,
    ),
    # Rule: 涨停/跌停/连板 — A股日行情 + 最新指标
    RouterRule(
        intent="limit_up_down",
        priority=64,
        pattern=r"(涨停|跌停|连板|涨停板|跌停板|一字涨停|一字跌停|封板|开板|炸板|连续涨停|连续跌停|涨停封单|涨停价|跌停价|涨停开板|封板率)",
        negative_pattern=r"(港股|美股|期货|可转债|基金|新三板|指数|期权|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["涨停", "涨停板", "跌停", "封板", "连板"],
        market="A股",
        frequency="日频",
        confidence=0.90,
    ),
    # Rule: A股日行情/股价 (通用 — 匹配"股价""收盘价""成交量""换手率"等)
    RouterRule(
        intent="astock_daily_quote",
        priority=62,
        pattern=r"(股价|收盘价|开盘价|最高价|最低价|成交量|成交额|换手率|量价|今日价格|最新价|盘中|盘后|复权价)",
        negative_pattern=r"(港股|美股|美元|期货|可转债|基金净值|新三板|指数|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["股价", "行情", "日K"],
        market="A股",
        frequency="日频",
        confidence=0.80,
    ),
    # Rule: 股价变动/涨跌幅
    RouterRule(
        intent="price_change",
        priority=60,
        pattern=r"(涨跌幅|涨幅|跌幅|阶段涨幅|阶段跌幅|阶段涨跌|区间涨幅|区间跌幅|增长率|涨了多少|跌了多少|表现|行情)",
        negative_pattern=r"(港股|美股|美元|期货|基金|指数|新三板|可转债|H股|\.HK|\.US|NASDAQ|NYSE|上证指数|深证成指|恒生|恒指)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["价格变动", "行情", "涨跌"],
        market="A股",
        frequency="日频",
        confidence=0.70,
    ),
    # Rule: 股息/分红金额 → 年度分红表
    RouterRule(
        intent="annual_dividend",
        priority=58,
        pattern=r"(股息支付|股息金额|分红金额|年度分红|派息金额|现金分红|每股股利|股利合计|每股派息)",
        allowed_yaml_paths=[
            "股票/stock_astock_annual_dividend.yaml",
        ],
        query_expansions=["股息支付金额", "年度分红", "分红"],
        market="A股",
        confidence=0.90,
    ),
    # Rule: 公司债券发行
    RouterRule(
        intent="corporate_bond",
        priority=57,
        pattern=r"(发行)?债券.{0,5}(规模|金额|利率|期限|发行)|发行债券",
        negative_pattern=r"(可转债|转债)",
        allowed_yaml_paths=["股票/stock_astock_comporate_bond.yaml"],
        query_expansions=["债券发行", "公司债"],
        market="A股",
        confidence=0.85,
    ),
    # Rule: 分红送转 (general)
    RouterRule(
        intent="dividend",
        priority=55,
        pattern=r"(分红|派息|送转|股息)",
        negative_pattern=r"(股息支付|股息金额|分红金额|派息金额|现金分红|基金分红|可转债|(?<![A-Za-z])ETF(?![A-Za-z])|港股|美股|H股)",
        allowed_yaml_paths=[
            "股票/stock_astock_annual_dividend.yaml",
            "股票/stock_astock_dividend_status.yaml",
        ],
        query_expansions=["分红送转", "利润分配"],
        market="A股",
        confidence=0.85,
    ),
    # Rule: 限售解禁
    RouterRule(
        intent="unlock_shares",
        priority=53,
        pattern=r"(解禁|限售股|限售解禁).{0,5}(数量|金额|日期|时间)?",
        allowed_yaml_paths=["股票/stock_astock_unlock_shareholds.yaml"],
        query_expansions=["限售解禁", "解禁股"],
        market="A股",
        confidence=0.85,
    ),
    # Rule: 连续交易日数据
    RouterRule(
        intent="continuous_days",
        priority=50,
        pattern=r"连续.{1,3}(个)?交易日",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_charts.yaml",
        ],
        query_expansions=["日频", "每日", "明细"],
        market="A股",
        frequency="日频",
        confidence=0.70,
    ),
    # Rule: 控股股东/实际控制人
    RouterRule(
        intent="controller_info",
        priority=45,
        pattern=r"(控股股东|实际控制人|大股东).{0,6}(是谁|信息|变更|变动)",
        negative_pattern=r"(减持|增持|套现|买入|卖出)",
        allowed_yaml_paths=["股票/stock_astock_controller.yaml"],
        query_expansions=["控股股东", "实际控制人"],
        market="A股",
        confidence=0.80,
    ),

    # --- A股财务数据 ---
    RouterRule(
        intent="astock_financial",
        priority=77,
        pattern=r"(财报|财务|营收|营业收入|净利润|归母净利|扣非|毛利|毛利率|EPS|ROE|ROA|资产负债|现金流|利润表|负债率|资产|负债|净资产|每股收益|每股净资产|总资产|总负债|经营现金流|投资收益|研发费用|销售费用|管理费用|财务费用|所得税|应收账款|应付账款|存货|商誉|流动资产|流动负债)",
        negative_pattern=(
            r"(港股|美股|香港|期货|基金|可转债|新三板|H股|\.HK|\.US|NASDAQ|NYSE|美元|"
            r"资产置换|资产出售|资产注入|资产购买|资产剥离|并购|重组|"
            r"净利润增速|利润增速|盈利预测|业绩预测)"
        ),
        allowed_yaml_paths=[
            "股票/stock_astock_company_financial_data.yaml",
            "股票/stock_astock_company_financial_data_new.yaml",
        ],
        query_expansions=["财务数据", "财报"],
        market="A股",
        frequency="季度",
        confidence=0.85,
    ),
    # --- A股盈利预测/业绩预测 ---
    RouterRule(
        intent="astock_profit_forecast",
        priority=76,
        pattern=(
            r"((预测|预期|预计).{0,8}(净利润|利润|业绩|营收|收入|增速|增长率)|"
            r"(净利润|利润|业绩).{0,8}(增速|增长率).{0,8}(预测|预期|预计)|"
            r"盈利预测|业绩预测)"
        ),
        negative_pattern=r"(港股|美股|期货|基金|可转债|新三板|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_institutional_performance_forcast.yaml",
        ],
        query_expansions=["盈利预测", "业绩预测", "净利润增速"],
        market="A股",
        frequency="季度",
        confidence=0.85,
    ),
    # --- A股十大股东 ---
    RouterRule(
        intent="astock_top_shareholders",
        priority=73,
        pattern=r"(十大股东|前十大股东|流通股东|十大流通|股东变动|股东户数|股东人数|股东增减|股东名单|控股股东)",
        negative_pattern=r"(港股|美股|新三板|可转债|基金|筹码)",
        allowed_yaml_paths=[
            "股票/stock_astock_top10_shareholders_detail.yaml",
            "股票/stock_astock_top10_shareholders_detail_latest.yaml",
            "股票/stock_astock_top10_shareholders_stat.yaml",
            "股票/stock_astock_top10_circulate_shareholders_detail.yaml",
            "股票/stock_astock_top10_circulate_shareholders_detail_latest.yaml",
            "股票/stock_astock_top10_circulate_shareholders_stat.yaml",
            "股票/stock_astock_num_shareholders_capital_chg.yaml",
        ],
        query_expansions=["十大股东", "流通股东", "股东变动"],
        market="A股",
        frequency="季度",
        confidence=0.85,
    ),
    # --- 实控人/高管被查或被处罚 ---
    RouterRule(
        intent="controller_investigation_penalty",
        priority=72,
        pattern=r"(实控人|实际控制人|控股股东|董事长|高管).{0,8}(被查|立案|调查|处罚|罚款|违规)",
        negative_pattern=r"(港股|美股|基金|期货|可转债|新三板)",
        allowed_yaml_paths=[
            "股票/stock_astock_file_an_investigation.yaml",
            "股票/stock_astock_penalties_violations.yaml",
            "股票/stock_astock_basic_info.yaml",
        ],
        query_expansions=["立案调查", "处罚违规", "实控人"],
        market="A股",
        confidence=0.90,
    ),
    # --- A股研报/评级/机构调研 ---
    RouterRule(
        intent="astock_research",
        priority=71,
        pattern=r"(研报|研究报告|评级|目标价|分析师|机构调研|调研|盈利预测|一致预期|买入评级|卖出评级|增持评级)",
        negative_pattern=r"(港股|美股|基金|可转债|新三板)",
        allowed_yaml_paths=[
            "股票/stock_astock_research_report_rating.yaml",
            "股票/stock_astock_institutional_research.yaml",
            "股票/stock_astock_institutional_research_stat.yaml",
            "股票/stock_astock_institutional_performance_forcast.yaml",
        ],
        query_expansions=["研报", "评级", "分析师"],
        market="A股",
        confidence=0.82,
    ),
    # --- A股股权质押 ---
    RouterRule(
        intent="astock_pledge",
        priority=68,
        pattern=r"(股权质押|质押率|质押比例|质押股份|质押数量|解质押|质押风险|公告.{0,2}质押|质押占)",
        negative_pattern=r"(新三板)",
        allowed_yaml_paths=[
            "股票/stock_astock_equity_pledge.yaml",
            "股票/stock_astock_pledge_stat.yaml",
            "股票/stock_astock_pledgor_stituation.yaml",
        ],
        query_expansions=["股权质押", "质押"],
        market="A股",
        confidence=0.85,
    ),
    # --- 大股东冻结（股东维度） ---
    RouterRule(
        intent="astock_major_shareholder_freeze",
        priority=67,
        pattern=r"(大股东|股东).{0,6}(冻结|股份冻结|司法冻结)",
        negative_pattern=r"(港股|美股|新三板|可转债|基金)",
        allowed_yaml_paths=[
            "股票/stock_astock_top10_shareholders_detail.yaml",
            "股票/stock_astock_top10_shareholders_detail_latest.yaml",
            "股票/stock_astock_top10_shareholders_stat.yaml",
        ],
        query_expansions=["大股东", "冻结"],
        market="A股",
        confidence=0.82,
    ),
    # --- A股并购重组/资产重组 ---
    RouterRule(
        intent="astock_ma",
        priority=66,
        pattern=r"(并购|重组|收购|借壳|资产注入|资产购买|资产出售|资产置换|吸收合并|要约收购|股权转让|资产剥离)",
        negative_pattern=r"(港股|美股|新三板)",
        allowed_yaml_paths=[
            "股票/stock_astock_mergers_acquisitions.yaml",
            "股票/stock_astock_asset_injection.yaml",
            "股票/stock_astock_asset_purchase.yaml",
            "股票/stock_astock_asset_sale.yaml",
            "股票/stock_astock_asset_replacement.yaml",
            "股票/stock_astock_backdoor_list.yaml",
            "股票/stock_astock_equity_transfer.yaml",
            "股票/stock_astock_tender_offer.yaml",
            "股票/stock_astock_divestiture.yaml",
        ],
        query_expansions=["并购重组", "收购"],
        market="A股",
        confidence=0.82,
    ),
    # --- A股资产剥离（专表优先） ---
    RouterRule(
        intent="astock_divestiture",
        priority=67,
        pattern=r"(资产剥离|剥离公告|重大资产剥离|公告资产剥离)",
        negative_pattern=r"(港股|美股|新三板)",
        allowed_yaml_paths=[
            "股票/stock_astock_divestiture.yaml",
        ],
        query_expansions=["资产剥离", "剥离公告", "重大资产剥离"],
        market="A股",
        confidence=0.92,
    ),
    # --- A股IPO/定增/再融资 ---
    RouterRule(
        intent="astock_equity_financing",
        priority=63,
        pattern=(
            r"(IPO|首次公开发行|首发|新股(?:上市|发行|申购|中签)?|打新|申购|中签率|"
            r"发行价|定增|定向增发|配股|增发|再融资|募集资金|上市(?:审核|辅导|进度|首日|发行))"
        ),
        negative_pattern=r"(港股|美股|新三板|基金|可转债|上市公司名单|上市公司数量|上市天数|上市日期)",
        allowed_yaml_paths=[
            "股票/stock_astock_ipo.yaml",
            "股票/stock_astock_seo.yaml",
            "股票/stock_astock_sright_issue.yaml",
            "股票/stock_astock_financing.yaml",
            "股票/stock_astock_new_stock_evaluation.yaml",
            "股票/stock_astock_participart_in_new_stock.yaml",
        ],
        query_expansions=["IPO", "定增", "再融资"],
        market="A股",
        confidence=0.82,
    ),
    # --- A股发行价 / 首发价格 ---
    RouterRule(
        intent="astock_ipo_price",
        priority=64,
        pattern=r"(发行价|首发价|IPO发行价|新股发行价|上市发行价)",
        negative_pattern=r"(相对发行价|发行价格上限|发行价格下限|预案发行价格|港股|美股|基金|债券|可转债)",
        allowed_yaml_paths=[
            "股票/stock_astock_ipo.yaml",
            "股票/stock_astock_new_stock_evaluation.yaml",
        ],
        query_expansions=["IPO", "发行价", "首发价格"],
        market="A股",
        confidence=0.92,
    ),
    # --- A股主营构成/收入结构 ---
    RouterRule(
        intent="astock_revenue_composition",
        priority=61,
        pattern=r"(主营业务构成|收入构成|收入结构|营收结构|主营构成|产品构成|业务构成|分产品|分地区|分行业收入)",
        negative_pattern=r"(港股|美股|新三板)",
        allowed_yaml_paths=[
            "股票/stock_astock_main_business_composition.yaml",
            "股票/stock_astock_main_business_composition_latest.yaml",
            "股票/stock_astock_cost_structure.yaml",
        ],
        query_expansions=["主营构成", "收入结构"],
        market="A股",
        frequency="季度",
        confidence=0.82,
    ),
    # --- A股股权激励 ---
    RouterRule(
        intent="astock_equity_incentive",
        priority=59,
        pattern=r"(股权激励|期权激励|限制性股票|员工持股计划|ESOP|股票期权|激励计划)",
        negative_pattern=r"(新三板)",
        allowed_yaml_paths=[
            "股票/stock_astock_equity_incentives.yaml",
            "股票/stock_astock_employee_stock_ownership_plan.yaml",
        ],
        query_expansions=["股权激励", "激励计划"],
        market="A股",
        confidence=0.85,
    ),
    # --- A股大宗交易 ---
    RouterRule(
        intent="astock_block_trading",
        priority=56,
        pattern=r"(大宗交易|大宗|折价|溢价交易|协议转让)",
        negative_pattern=r"(港股|美股|新三板|期货|基金)",
        allowed_yaml_paths=[
            "股票/stock_astock_block_trading.yaml",
            "股票/stock_astock_block_trading_stat.yaml",
        ],
        query_expansions=["大宗交易"],
        market="A股",
        confidence=0.82,
    ),
    # --- A股回购 ---
    RouterRule(
        intent="astock_buyback",
        priority=54,
        pattern=r"(回购|股票回购|回购股份|回购金额|回购数量|回购预案|回购计划)",
        negative_pattern=r"(港股|美股|债券|逆回购|国债逆回购)",
        allowed_yaml_paths=["股票/stock_astock_repurchase_of_shares.yaml"],
        query_expansions=["回购", "股票回购"],
        market="A股",
        confidence=0.82,
    ),
    # --- A股股本/股份结构 ---
    RouterRule(
        intent="astock_share_capital",
        priority=48,
        pattern=r"(总股本|流通股本|股本结构|股份变动|限售股|流通市值|总市值|市值)",
        negative_pattern=r"(港股|美股|美元|新三板|基金|指数|ETF|解禁|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_share_capital.yaml",
            "股票/stock_astock_tequity_structure.yaml",
            "股票/stock_astock_mkt_daily_trans.yaml",
        ],
        query_expansions=["股本", "总股本"],
        market="A股",
        confidence=0.78,
    ),
    # --- A股概念板块（概念相关触发词）---
    RouterRule(
        intent="astock_concept",
        priority=47,
        pattern=r"(概念板块|同花顺概念|概念成[份分]|板块个股|板块轮动)",
        negative_pattern=r"(港股|美股|基金|指数|ETF)",
        allowed_yaml_paths=[
            "股票/stock_astock_concept.yaml",
            "股票/stock_astock_basic_info.yaml",
        ],
        query_expansions=["概念", "板块"],
        market="A股",
        confidence=0.78,
    ),
    # --- A股行业分类（行业相关触发词）---
    RouterRule(
        intent="astock_industry",
        priority=46,
        pattern=r"(行业板块|产业链|行业成[份分]|成[份分]股|行业龙头)",
        negative_pattern=r"(港股|美股|基金|指数|ETF|概念)",
        allowed_yaml_paths=[
            "股票/stock_astock_basic_info.yaml",
            "股票/pub_sec_mkt_industrial.yaml",
            "股票/pub_sec_mkt_industrial_chain.yaml",
        ],
        query_expansions=["行业", "行业分类", "所属行业"],
        market="A股",
        confidence=0.80,
    ),

    # ===========================================================
    #  A股 补充规则 — 覆盖 Dry-run 中发现的高频 False Negative
    # ===========================================================

    # Rule: 北向资金/陆股通持股变动（加仓/减仓）→ 沪深港通持股表
    RouterRule(
        intent="northbound_connect_holding",
        priority=86,
        pattern=r"(北向资金|陆股通|沪股通|深股通|沪港通|深港通).{0,8}(加仓|减仓|增持|减持|调仓|增减仓|持股变动|持仓变动|持股)",
        negative_pattern=r"(买入|卖出|成交额|龙虎榜|净买入|净流入|排名|排行|榜)",
        allowed_yaml_paths=[
            "股票/stock_astock_stock_connect.yaml",
        ],
        query_expansions=["北向资金", "陆股通持股", "加仓", "减仓"],
        market="A股",
        frequency="日频",
        confidence=0.88,
    ),
    # Rule: 资金流入/流出/进场（无"主力"前缀的通用资金流向）
    RouterRule(
        intent="astock_fund_flow_generic",
        priority=69,
        pattern=(
            r"(净流入金额|净流出金额|资金流入|资金流出|资金流向|资金流$|"
            r"资金进场|资金出逃|资金进入|资金撤出|今日资金|今天资金|"
            r"实时资金|暗盘资金|暗盘|当前资金)"
        ),
        negative_pattern=r"(港股|美股|期货|基金净值|可转债|新三板|指数|北向资金|陆股通)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["资金流向", "资金"],
        market="A股",
        frequency="日频",
        confidence=0.78,
    ),
    # Rule: 股权冻结
    RouterRule(
        intent="astock_equity_freeze",
        priority=66,
        pattern=r"(股权冻结|股份冻结|司法冻结|公告.{0,2}冻结)",
        negative_pattern=r"(港股|美股|期货|基金|可转债|新三板|指数|账户冻结)",
        allowed_yaml_paths=[
            "股票/stock_astock_equity_freeze.yaml",
        ],
        query_expansions=["股权冻结", "冻结"],
        market="A股",
        confidence=0.82,
    ),
    # Rule: 散户资金流向/增减仓
    RouterRule(
        intent="astock_retail_flow",
        priority=58,
        pattern=r"散户.{0,5}(流入|流出|增仓|减仓|资金|买入|卖出|净买入|净卖出)",
        negative_pattern=r"(港股|美股|期货|基金|可转债|新三板)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
        ],
        query_expansions=["散户", "散户资金"],
        market="A股",
        frequency="日频",
        confidence=0.78,
    ),
    # Rule: 热度/人气/排名
    RouterRule(
        intent="astock_popularity",
        priority=52,
        pattern=(
            r"(个股热度|人气排名|热度排名|同花顺人气|人气热度|"
            r"人气龙头|人气指标|热度指标|个股人气|市场人气|"
            r".{2,4}热度$|.{2,4}热度排名|.{2,4}人气$)"
        ),
        negative_pattern=r"(港股|美股|期货|基金|可转债|新三板|指数)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["热度", "人气", "排名"],
        market="A股",
        frequency="日频",
        confidence=0.82,
    ),
    # Rule: 买入/卖出信号
    RouterRule(
        intent="astock_trading_signal",
        priority=51,
        pattern=r"(买入信号|卖出信号|买入.{0,3}卖出.{0,3}信号|交易信号|买卖信号)",
        negative_pattern=r"(港股|美股|期货|基金|可转债|新三板|指数)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["买入信号", "卖出信号"],
        market="A股",
        frequency="日频",
        confidence=0.82,
    ),
    # Rule: 估值指标（市净率/市盈率/市销率，排除指数估值和港美股）
    RouterRule(
        intent="astock_valuation",
        priority=49,
        pattern=r"(市净率|市盈率|市销率|PEG)",
        negative_pattern=r"(港股|美股|期货|基金净值|可转债|新三板|指数.{0,3}估值|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["估值", "市盈率", "市净率"],
        market="A股",
        frequency="日频",
        confidence=0.78,
    ),
    # Rule: 公告事件（复牌/停牌/停复牌/开盘时间）
    RouterRule(
        intent="astock_announcement_event",
        priority=49,
        pattern=(
            r"(公告.{0,2}(?:复牌|停牌|停复牌)|"
            r"(?:复牌|停牌|停复牌).{0,2}公告|"
            r"什么时候.{0,4}(?:开盘|复牌|停牌)|"
            r"公告事件)"
        ),
        negative_pattern=r"(港股|美股|期货|基金|可转债|新三板|指数)",
        allowed_yaml_paths=[
            "股票/stock_astock_economic_events.yaml",
            "股票/stock_astock_trading_suspended_resumed.yaml",
        ],
        query_expansions=["公告", "复牌", "停牌"],
        market="A股",
        confidence=0.82,
    ),
    # Rule: 牛散持股/跟踪
    RouterRule(
        intent="astock_cattle_track",
        priority=46,
        pattern=r"(牛散|超级散户|知名散户|知名股东).{0,6}(持股|持仓|跟踪|买入|卖出|名单)?",
        allowed_yaml_paths=[
            "股票/stock_astock_most_cattletrack.yaml",
        ],
        query_expansions=["牛散", "牛散持股", "超级散户"],
        market="A股",
        frequency="季度",
        confidence=0.88,
    ),

    # ===========================================================
    #  可转债规则 (priority 150 ~ 180)
    # ===========================================================

    # Rule: 可转债基本信息/发行
    RouterRule(
        intent="cb_basic",
        priority=175,
        pattern=r"(可转债|转债).{0,5}(基本|信息|发行|条款|规模|期限|利率|票面)",
        allowed_yaml_paths=[
            "可转债/convertiblebond_basic_info.yaml",
            "可转债/convertiblebond_issue_info.yaml",
            "可转债/convertiblebond_terms.yaml",
        ],
        query_expansions=["可转债", "发行信息"],
        market="可转债",
        confidence=0.88,
    ),
    # Rule: 可转债行情/价格
    RouterRule(
        intent="cb_market",
        priority=170,
        pattern=r"(可转债|转债).{0,5}(行情|价格|涨跌|成交|溢价|收盘|开盘)",
        allowed_yaml_paths=[
            "可转债/convertiblebond_market.yaml",
            "可转债/convertiblebond_market_new.yaml",
        ],
        query_expansions=["可转债行情", "转股溢价率"],
        market="可转债",
        frequency="日频",
        confidence=0.88,
    ),
    # Rule: 可转债赎回事件
    RouterRule(
        intent="cb_redemption_event",
        priority=166,
        pattern=(
            r"("
            r"(可转债|转债).{0,8}(发生|触发|公告|实施)?.{0,6}(赎回|强赎|提前赎回)"
            r"|"
            r"(赎回|强赎|提前赎回).{0,8}(可转债|转债)"
            r")"
        ),
        negative_pattern=r"(A股|港股|美股)",
        allowed_yaml_paths=[
            "可转债/convertiblebond_basic_info.yaml",
            "可转债/convertiblebond_payments_and_redemptions.yaml",
            "股票/stock_astock_basic_info.yaml",
            "股票/stock_astock_financing.yaml",
        ],
        query_expansions=["可转债赎回", "强赎", "债券基本信息"],
        market=None,
        confidence=0.90,
    ),
    # Rule: 转股/下修/回售/赎回
    RouterRule(
        intent="cb_conversion",
        priority=165,
        pattern=r"(转股|转股价|下修|回售|强赎|赎回).{0,3}(价格|条件|触发|公告)?",
        negative_pattern=r"(A股|港股|美股)",
        allowed_yaml_paths=[
            "可转债/convertiblebond_terms.yaml",
            "可转债/convertiblebond_terms_exercise.yaml",
            "可转债/convertiblebond_transfer_price_adjustments.yaml",
            "可转债/convertiblebond_payments_and_redemptions.yaml",
        ],
        query_expansions=["转股价", "下修", "回售"],
        market="可转债",
        confidence=0.85,
    ),
    # Rule: 可转债评级/信用
    RouterRule(
        intent="cb_rating",
        priority=160,
        pattern=r"(可转债|转债).{0,5}(评级|信用|AAA|AA|评分)",
        allowed_yaml_paths=[
            "可转债/convertiblebond_credit_rating.yaml",
            "可转债/convertiblebond_credit_rating_new.yaml",
            "可转债/convertiblebond_entity_rating.yaml",
        ],
        query_expansions=["信用评级", "债券评级"],
        market="可转债",
        confidence=0.85,
    ),
    # Rule: 可转债持仓/持有人
    RouterRule(
        intent="cb_holder",
        priority=155,
        pattern=r"(可转债|转债).{0,5}(持仓|持有|持有人|机构|前十)",
        allowed_yaml_paths=[
            "可转债/convertiblebond_holder.yaml",
            "可转债/convertiblebond_holder_statistics.yaml",
            "可转债/convertiblebond_institutional_purchase.yaml",
        ],
        query_expansions=["持有人", "机构持仓"],
        market="可转债",
        frequency="季度",
        confidence=0.85,
    ),

    # ===========================================================
    #  全量指数规则 (priority 180 ~ 200)
    # ===========================================================

    # Rule: 指数行情/点位
    RouterRule(
        intent="index_quote",
        priority=195,
        pattern=r"(指数|沪深300|上证指数|深证成指|创业板指|科创50|中证\d+).{0,5}(行情|点位|涨跌|收盘|开盘|成交|K线|走势)",
        negative_pattern=r"(基金|ETF|跟踪|期货|合约|主力)",
        allowed_yaml_paths=[
            "全量指数/index_mkt_daily_trans.yaml",
            "全量指数/index_latest_index.yaml",
        ],
        query_expansions=["指数行情", "点位"],
        market="指数",
        frequency="日频",
        confidence=0.88,
    ),
    # Rule: 指数长期表现/历史对比
    RouterRule(
        intent="index_historical_performance",
        priority=194,
        pattern=(
            r"("
            r"(过去\d+年|近\d+年|历年|10年).{0,16}(黄金|指数|上证指数).{0,12}(表现|涨跌|股价|走势)"
            r"|"
            r"(对比).{0,12}(黄金|指数|上证指数).{0,12}(表现|涨跌|股价|走势)"
            r")"
        ),
        negative_pattern=r"(基金|ETF|期货)",
        allowed_yaml_paths=[
            "全量指数/index_basic_info.yaml",
            "全量指数/index_mkt_year_trans.yaml",
            "全量指数/index_latest_index.yaml",
        ],
        query_expansions=["指数历史表现", "长期走势", "年线"],
        market="指数",
        frequency="年频",
        confidence=0.90,
    ),
    # Rule: 指数基本信息/成分股
    RouterRule(
        intent="index_info",
        priority=190,
        pattern=r"(指数|沪深300|上证指数|深证成指|创业板指|科创50|中证\d+).{0,5}(基本|成[份分]|权重|样本|编制|简介)",
        allowed_yaml_paths=[
            "全量指数/index_basic_info.yaml",
            "全量指数/index_constituents.yaml",
        ],
        query_expansions=["成分股", "指数信息", "权重"],
        market="指数",
        confidence=0.88,
    ),
    # Rule: 指数估值/PE/PB
    RouterRule(
        intent="index_valuation",
        priority=185,
        pattern=r"(指数|沪深300|上证指数|深证成指|创业板指|科创50|中证\d+).{0,5}(PE|PB|估值|市盈率|市净率|盈利)",
        allowed_yaml_paths=[
            "全量指数/index_fin_data.yaml",
            "全量指数/index_ttm_data.yaml",
        ],
        query_expansions=["指数PE", "指数PB", "估值"],
        market="指数",
        confidence=0.88,
    ),

    # ===========================================================
    #  基金规则 (priority 200 ~ 250)
    # ===========================================================

    # Rule: 基金净值
    RouterRule(
        intent="fund_nav",
        priority=245,
        pattern=r"(基金|ETF).{0,5}(净值|单位净值|累计净值)",
        negative_pattern=r"(基金经理|基金公司|管理人)",
        allowed_yaml_paths=[
            "基金/fund_mkt_daily_trans_latest.yaml",
            "基金/fund_mkt_daily_trans.yaml",
            "基金/fund_basic_info.yaml",
        ],
        query_expansions=["净值", "单位净值", "累计净值"],
        market="基金",
        frequency="日频",
        confidence=0.92,
    ),
    # Rule: 基金筛选/诊基/夏普
    RouterRule(
        intent="fund_diagnosis_screen",
        priority=244,
        pattern=(
            r"("
            r"(基金|ETF).{0,24}(诊基|夏普|夏普率|排名前?\d+%?|排名前?\d+|回撤|波动)"
            r"|"
            r"(诊基|夏普|夏普率|排名前?\d+%?|排名前?\d+|回撤|波动).{0,24}(基金|ETF)"
            r")"
        ),
        negative_pattern=r"(基金经理|基金公司|管理人|港股|美股|期货|可转债)",
        allowed_yaml_paths=[
            "基金/fund_basic_info.yaml",
            "基金/fund_mkt_daily_trans.yaml",
            "基金/fund_mkt_daily_trans_latest.yaml",
            "基金/fund_shares_size.yaml",
            "基金/fund_comprehensive_diagnosis.yaml",
            "基金/fund_industry_concept_allocation_latest.yaml",
        ],
        query_expansions=["基金", "诊基", "sharpe", "基金规模"],
        market="基金",
        confidence=0.90,
    ),
    # Rule: 每月/按月分红 ETF
    RouterRule(
        intent="fund_monthly_dividend",
        priority=243,
        pattern=(
            r"("
            r"(基金|ETF).{0,12}(每月|月月|按月).{0,12}(分红|派息)"
            r"|"
            r"(每月|月月|按月).{0,12}(分红|派息).{0,12}(基金|ETF)"
            r"|"
            r"(分红|派息).{0,12}(每月|月月|按月).{0,12}(基金|ETF)"
            r")"
        ),
        negative_pattern=r"(基金经理|基金公司|管理人)",
        allowed_yaml_paths=[
            "基金/fund_basic_info.yaml",
            "基金/fund_dividend_detail.yaml",
            "基金/fund_mkt_daily_trans_latest.yaml",
        ],
        query_expansions=["基金分红", "按月分红", "ETF"],
        market="基金",
        confidence=0.90,
    ),
    # Rule: 基金收益/业绩/回报
    RouterRule(
        intent="fund_performance",
        priority=240,
        pattern=r"(基金|ETF).{0,5}(收益|业绩|回报|涨幅|涨跌|夏普|波动|最大回撤|年化|排名)",
        negative_pattern=r"(基金经理|基金公司|管理人)",
        allowed_yaml_paths=[
            "基金/fund_history_statistics.yaml",
            "基金/fund_mkt_daily_trans_latest.yaml",
            "基金/fund_comprehensive_diagnosis.yaml",
        ],
        query_expansions=["收益率", "业绩", "涨幅"],
        market="基金",
        confidence=0.90,
    ),
    # Rule: 股票/ETF 分红 + 特别股息 + 年度市值增长
    RouterRule(
        intent="stock_dividend_growth_screen",
        priority=239,
        pattern=(
            r"("
            r"(股票|ETF).{0,40}(股息|特别股息|分红).{0,40}(市值).{0,16}(增长|增长率)"
            r"|"
            r"(特别股息|分红).{0,40}(市值).{0,16}(增长|增长率)"
            r")"
        ),
        negative_pattern=r"(基金经理|基金公司|管理人|港股|美股|期货|可转债)",
        allowed_yaml_paths=[
            "股票/stock_astock_annual_dividend.yaml",
            "股票/stock_astock_company_financial_data.yaml",
            "股票/stock_astock_mkt_year_trans.yaml",
            "股票/stock_astock_mkt_year_trans_qoq_rate.yaml",
        ],
        query_expansions=["股息", "特别股息", "年度市值增长"],
        market="A股",
        frequency="年频",
        confidence=0.90,
    ),
    # Rule: 基金持仓/重仓/资产配置
    RouterRule(
        intent="fund_holdings",
        priority=235,
        pattern=r"(基金|ETF).{0,5}(持仓|重仓|十大|资产配置|持股|仓位|股票配置|债券配置)",
        negative_pattern=r"(基金经理|基金公司|管理人|机构持仓|基金持股家数|基金持股数量|基金持股市值|社保基金持股|保险持股|QFII持股|基金重仓股|社保基金重仓)",
        allowed_yaml_paths=[
            "基金/fund_hold_detail.yaml",
            "基金/fund_hold_detail_latest.yaml",
            "基金/fund_asset_allocation.yaml",
        ],
        query_expansions=["持仓", "重仓股", "十大重仓"],
        market="基金",
        frequency="季度",
        confidence=0.88,
    ),
    # Rule: 基金分红
    RouterRule(
        intent="fund_dividend",
        priority=230,
        pattern=r"(基金|ETF).{0,5}(分红|派息|红利|分红记录)",
        allowed_yaml_paths=[
            "基金/fund_dividend_detail.yaml",
            "基金/fund_annual_dividend.yaml",
        ],
        query_expansions=["基金分红", "分红记录"],
        market="基金",
        confidence=0.90,
    ),
    # Rule: 基金申购/赎回
    RouterRule(
        intent="fund_subscription",
        priority=225,
        pattern=r"(基金|ETF).{0,5}(申购|赎回|申赎|购买|卖出|认购)",
        allowed_yaml_paths=[
            "基金/fund_subscription_redemption.yaml",
            "基金/fund_subscription_redemption_rate.yaml",
        ],
        query_expansions=["申购赎回", "申赎"],
        market="基金",
        confidence=0.85,
    ),
    # Rule: 基金规模/份额
    RouterRule(
        intent="fund_size",
        priority=220,
        pattern=r"(基金|ETF).{0,5}(规模|份额|资产|总资产|AUM)",
        negative_pattern=r"(基金经理|基金公司|管理人)",
        allowed_yaml_paths=[
            "基金/fund_shares_size.yaml",
            "基金/fund_basic_info.yaml",
        ],
        query_expansions=["基金规模", "份额", "资产规模"],
        market="基金",
        confidence=0.88,
    ),
    # Rule: 基金费率
    RouterRule(
        intent="fund_rate",
        priority=215,
        pattern=r"(基金|ETF).{0,5}(费率|管理费|托管费|申购费|赎回费|销售服务费)",
        allowed_yaml_paths=[
            "基金/fund_rate.yaml",
            "基金/fund_rate_stat.yaml",
        ],
        query_expansions=["费率", "管理费率"],
        market="基金",
        confidence=0.88,
    ),
    # Rule: 基金行业/概念配置
    RouterRule(
        intent="fund_industry_allocation",
        priority=210,
        pattern=r"(基金|ETF).{0,5}(行业配置|概念配置|行业分布|板块配置|行业持仓)",
        allowed_yaml_paths=[
            "基金/fund_industry_concept_allocation.yaml",
            "基金/fund_industry_concept_allocation_latest.yaml",
        ],
        query_expansions=["行业配置", "概念配置"],
        market="基金",
        frequency="季度",
        confidence=0.85,
    ),
    # Rule: 基金基本信息（兜底）
    RouterRule(
        intent="fund_basic_info",
        priority=205,
        pattern=r"(基金|ETF).{0,5}(基本|信息|简介|成立|类型|投资策略|托管|管理)",
        negative_pattern=r"(基金经理|基金公司|管理人)",
        allowed_yaml_paths=[
            "基金/fund_basic_info.yaml",
        ],
        query_expansions=["基金信息", "基金类型"],
        market="基金",
        confidence=0.82,
    ),

    # ===========================================================
    #  基金经理规则 (priority 250 ~ 280)
    # ===========================================================

    # Rule: 基金经理收益/排名（支持“最赚钱的基金经理”语序）
    RouterRule(
        intent="fund_manager_rank",
        priority=279,
        pattern=(
            r"("
            r"(基金经理).{0,12}(最赚钱|收益最差|收益最高|收益最好|收益高|收益低|排名|比较|表现)"
            r"|"
            r"(最赚钱|收益最差|收益最高|收益最好|收益高|收益低|排名|比较|表现).{0,12}(基金经理)"
            r")"
        ),
        allowed_yaml_paths=[
            "基金经理/fundmanager_latest_index.yaml",
            "基金经理/fund_manager_return_risk_level.yaml",
            "基金经理/fund_manager_performance_stat.yaml",
        ],
        query_expansions=["基金经理", "收益排名", "业绩"],
        market="基金经理",
        confidence=0.92,
    ),
    # Rule: 基金经理在管规模/年限
    RouterRule(
        intent="fund_manager_scale_tenure",
        priority=280,
        pattern=(
            r"("
            r"(基金经理).{0,12}(在管规模|管理规模|年限|任职年限|从业年限)"
            r"|"
            r"(在管规模|管理规模|基金经理年限|任职年限|从业年限).{0,12}(基金经理)"
            r")"
        ),
        allowed_yaml_paths=[
            "基金经理/fund_manager_basic_info.yaml",
            "基金经理/fundmanager_asset_allocation.yaml",
            "基金经理/fundmanager_latest_index.yaml",
        ],
        query_expansions=["基金经理", "在管规模", "任职年限"],
        market="基金经理",
        confidence=0.90,
    ),
    # Rule: 基金经理业绩/排名
    RouterRule(
        intent="fund_manager_performance",
        priority=275,
        pattern=r"基金经理.{0,5}(业绩|收益|回报|排名|夏普|回撤|表现|评分)",
        allowed_yaml_paths=[
            "基金经理/fundmanager_latest_index.yaml",
            "基金经理/fund_manager_return_risk_level.yaml",
            "基金经理/fund_manager_performance_stat.yaml",
        ],
        query_expansions=["基金经理", "业绩", "排名"],
        market="基金经理",
        confidence=0.90,
    ),
    # Rule: 基金经理信息/履历
    RouterRule(
        intent="fund_manager_info",
        priority=270,
        pattern=r"基金经理.{0,5}(信息|履历|简介|任职|管理|资历|学历|从业)",
        allowed_yaml_paths=[
            "基金经理/fund_manager_basic_info.yaml",
            "基金经理/fund_manager_comprehensive_diagnosis.yaml",
        ],
        query_expansions=["基金经理", "任职信息"],
        market="基金经理",
        confidence=0.88,
    ),
    # Rule: 基金经理持仓/重仓
    RouterRule(
        intent="fund_manager_holdings",
        priority=265,
        pattern=r"基金经理.{0,5}(持仓|重仓|配置|持股)",
        allowed_yaml_paths=[
            "基金经理/fundmanager_hold_detail.yaml",
            "基金经理/fundmanager_hold_detail_latest.yaml",
            "基金经理/fundmanager_asset_allocation.yaml",
        ],
        query_expansions=["基金经理持仓", "重仓"],
        market="基金经理",
        frequency="季度",
        confidence=0.88,
    ),

    # ===========================================================
    #  基金公司规则 (priority 280 ~ 300)
    # ===========================================================

    # Rule: 基金公司基金经理人数
    RouterRule(
        intent="fund_company_staff_count",
        priority=299,
        pattern=r"[\u4e00-\u9fffA-Za-z]{2,12}基金.{0,12}(基金经理人数|基金经理数量|股票型基金经理人数|经理人数)",
        allowed_yaml_paths=[
            "基金公司/fund_company_basic_info.yaml",
            "基金公司/fund_company_staff.yaml",
            "基金公司/fund_company_latest_index.yaml",
        ],
        query_expansions=["基金公司", "基金经理人数", "管理人"],
        market="基金公司",
        confidence=0.92,
    ),
    # Rule: 基金公司规模增长率
    RouterRule(
        intent="fund_company_size_growth",
        priority=298,
        pattern=r"[\u4e00-\u9fffA-Za-z]{2,12}基金.{0,12}(规模增长率|管理规模增长率|规模增速|规模增长)",
        allowed_yaml_paths=[
            "基金公司/fund_company_shares_size.yaml",
            "基金公司/fund_company_latest_index.yaml",
        ],
        query_expansions=["基金公司规模", "规模增长率", "管理规模"],
        market="基金公司",
        confidence=0.90,
    ),
    # Rule: 基金公司资产/持股市值
    RouterRule(
        intent="fund_company_asset_value",
        priority=297,
        pattern=r"[\u4e00-\u9fffA-Za-z]{2,12}基金.{0,8}(市值|持股市值|股票市值|资产配置)",
        allowed_yaml_paths=[
            "基金公司/fund_company_asset_allocation.yaml",
            "基金公司/fund_company_basic_info.yaml",
        ],
        query_expansions=["基金公司市值", "资产配置", "持股市值"],
        market="基金公司",
        confidence=0.90,
    ),
    # Rule: 基金公司累计申购/赎回统计
    RouterRule(
        intent="fund_company_subscription_stats",
        priority=296,
        pattern=(
            r"("
            r"(基金公司).{0,12}(累计申购次数|累计赎回次数|申购次数|赎回次数)"
            r"|"
            r"(累计申购次数|累计赎回次数|申购次数|赎回次数).{0,12}(基金公司)"
            r")"
        ),
        allowed_yaml_paths=[
            "基金/fund_company_self_subscription_redemption.yaml",
        ],
        query_expansions=["基金公司", "累计申购次数", "累计赎回次数"],
        market="基金",
        confidence=0.92,
    ),
    # Rule: 个股被哪些基金公司买入/持仓
    RouterRule(
        intent="fund_company_stock_holding",
        priority=294,
        pattern=(
            r"("
            r"(哪几家|有多少家).{0,4}基金公司.{0,8}(买入|持仓|持有)"
            r"|"
            r"(基金公司).{0,8}(买入|持仓|持有).{0,12}"
            r"|"
            r"[\u4e00-\u9fffA-Za-z0-9]{2,16}.{0,6}(有多少|哪几家).{0,6}基金公司.{0,6}(买入|持仓|持有)"
            r")"
        ),
        allowed_yaml_paths=[
            "股票/stock_astock_shareholding_insitutions.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["基金公司持仓", "机构持仓", "买入"],
        market="A股",
        frequency="季度",
        confidence=0.90,
    ),
    # Rule: 基金公司信息/规模
    RouterRule(
        intent="fund_company_info",
        priority=295,
        pattern=r"(基金公司|管理人|管理公司).{0,5}(信息|规模|AUM|管理规模|排名|评价|评级|人员)",
        allowed_yaml_paths=[
            "基金公司/fund_company_basic_info.yaml",
            "基金公司/fund_company_latest_index.yaml",
            "基金公司/fund_company_shares_size.yaml",
        ],
        query_expansions=["基金公司", "管理规模"],
        market="基金公司",
        confidence=0.88,
    ),
    # Rule: 基金公司业绩/产品
    RouterRule(
        intent="fund_company_performance",
        priority=290,
        pattern=r"(基金公司|管理人|管理公司).{0,5}(业绩|收益|旗下|产品数|基金数量)",
        allowed_yaml_paths=[
            "基金公司/fund_company_performance_stat.yaml",
            "基金公司/fund_company_evaluation.yaml",
        ],
        query_expansions=["基金公司业绩", "旗下基金"],
        market="基金公司",
        confidence=0.85,
    ),

    # ===========================================================
    #  港股规则 (priority 300 ~ 350)
    # ===========================================================

    # Rule: 港股日行情/价格
    RouterRule(
        intent="hk_daily_quote",
        priority=345,
        pattern=r"(港股|恒生指数|恒指|\.HK|H股).{0,8}(行情|价格|涨跌|成交|收盘|开盘|K线|走势|换手|量价)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_mkt_daily_trans.yaml",
            "港股/stock_hkstock_mkt_trans_latest.yaml",
        ],
        query_expansions=["港股行情", "港币"],
        market="港股",
        frequency="日频",
        confidence=0.90,
    ),
    # Rule: 港股基本信息
    RouterRule(
        intent="hk_basic_info",
        priority=340,
        pattern=r"(港股|恒生指数|恒指|\.HK|H股).{0,8}(基本|信息|简介|上市|公司|主营)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_basic_info.yaml",
        ],
        query_expansions=["港股信息", "基本资料"],
        market="港股",
        confidence=0.88,
    ),
    # Rule: 港股财务/财报
    RouterRule(
        intent="hk_financial",
        priority=335,
        pattern=r"(港股|恒生指数|恒指|\.HK|H股).{0,8}(财报|营收|利润|EPS|ROE|资产负债|现金流|财务)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_company_financial_data.yaml",
            "港股/stock_hkstock_finc_analys.yaml",
            "港股/stock_hkstock_finc_analys_latest.yaml",
        ],
        query_expansions=["港股财报", "财务数据"],
        market="港股",
        frequency="季度",
        confidence=0.88,
    ),
    # Rule: 港股 PEV/内含价值估值
    RouterRule(
        intent="hk_pev_valuation",
        priority=334,
        pattern=r"(PEV|内含价值).{0,8}(估值|估值法|比较|对比)?|(友邦|保诚).{0,10}(PEV|内含价值)",
        negative_pattern=r"(A股|美股|PEVC)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_basic_info.yaml",
            "港股/stock_hkstock_mkt_year_trans.yaml",
        ],
        query_expansions=["PEV估值", "内含价值", "年估值"],
        market="港股",
        frequency="年频",
        confidence=0.90,
    ),
    # Rule: 港股分红/派息
    RouterRule(
        intent="hk_dividend",
        priority=330,
        pattern=r"(港股|恒生指数|恒指|\.HK|H股).{0,8}(分红|派息|股息|红利)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_annual_dividend.yaml",
            "港股/stock_hkstock_annual_dividend_latest.yaml",
            "港股/stock_hkstock_dividend_status.yaml",
        ],
        query_expansions=["港股分红", "股息"],
        market="港股",
        confidence=0.88,
    ),
    # Rule: 港股通/互联互通
    RouterRule(
        intent="hk_connect",
        priority=325,
        pattern=r"(港股通|沪港通|深港通|南向资金|南下资金).{0,5}(持股|成交|额度|流入|流出|净买入|净流入)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_shc.yaml",
            "港股/stock_hkstock_szc.yaml",
        ],
        query_expansions=["港股通", "互联互通"],
        market="港股",
        confidence=0.90,
    ),
    # Rule: 港股卖空/沽空
    RouterRule(
        intent="hk_short_selling",
        priority=320,
        pattern=r"(沽空|卖空|孖展|做空).{0,5}(比例|金额|数量|成交)?",
        negative_pattern=r"(A股|沪市|深市|创业板|科创板)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_parallel_trading.yaml",
            "港股/stock_hkstock_mkt_daily_trans.yaml",
        ],
        query_expansions=["沽空", "卖空"],
        market="港股",
        confidence=0.88,
    ),
    # Rule: 港股投资者持股
    RouterRule(
        intent="hk_investor_hold",
        priority=315,
        pattern=r"(港股|恒生指数|恒指|\.HK|H股).{0,8}(持股|股东|投资者|大股东|机构)",
        allowed_yaml_paths=[
            "港股/stock_hkstcok_investor_hold.yaml",
            "港股/stock_hkstcok_investor_hold_latest.yaml",
            "港股/stock_hkstock_participate_in_holding.yaml",
        ],
        query_expansions=["投资者持股", "大股东"],
        market="港股",
        confidence=0.85,
    ),
    # Rule: 港股研报/评级
    RouterRule(
        intent="hk_research",
        priority=310,
        pattern=r"(港股|恒生指数|恒指|\.HK|H股).{0,8}(研报|评级|目标价|分析师|研究报告)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_research_report_rating.yaml",
            "港股/stock_hkstock_institutional_performance_forcast.yaml",
        ],
        query_expansions=["研报", "评级", "目标价"],
        market="港股",
        confidence=0.85,
    ),
    # Rule: 港股业绩预告
    RouterRule(
        intent="hk_performance_forecast",
        priority=305,
        pattern=r"(港股|恒生指数|恒指|\.HK|H股).{0,8}(业绩预告|盈利预测|预警|业绩快报)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_company_performance_forecast.yaml",
        ],
        query_expansions=["业绩预告", "盈利预测"],
        market="港股",
        frequency="季度",
        confidence=0.85,
    ),

    # ===========================================================
    #  美股规则 (priority 400 ~ 450)
    # ===========================================================

    # Rule: 美股日行情/价格
    RouterRule(
        intent="us_daily_quote",
        priority=445,
        pattern=r"(美股|纳斯达克|纽交所|NYSE|NASDAQ|\.US|标普|道琼斯).{0,8}(行情|价格|涨跌|成交|收盘|开盘|K线|走势)",
        allowed_yaml_paths=[
            "美股/stock_ustock_mkt_daily_trans.yaml",
            "美股/stock_ustock_mkt_daily_trans_latest.yaml",
        ],
        query_expansions=["美股行情", "美元"],
        market="美股",
        frequency="日频",
        confidence=0.90,
    ),
    # Rule: 美股基本信息
    RouterRule(
        intent="us_basic_info",
        priority=440,
        pattern=r"(美股|纳斯达克|纽交所|NYSE|NASDAQ|\.US).{0,8}(基本|信息|简介|上市|公司|主营)",
        allowed_yaml_paths=[
            "美股/stock_ustock_basic_info.yaml",
        ],
        query_expansions=["美股信息", "基本资料"],
        market="美股",
        confidence=0.88,
    ),
    # Rule: 美股财务/财报
    RouterRule(
        intent="us_financial",
        priority=435,
        pattern=r"(美股|纳斯达克|纽交所|NYSE|NASDAQ|\.US).{0,8}(财报|营收|利润|EPS|ROE|资产负债|现金流|财务|revenue|earnings)",
        allowed_yaml_paths=[
            "美股/stock_ustock_fin_data.yaml",
            "美股/stock_ustock_fin_data_new.yaml",
            "美股/stock_ustock_finc_analys.yaml",
        ],
        query_expansions=["美股财报", "财务数据"],
        market="美股",
        frequency="季度",
        confidence=0.88,
    ),
    # Rule: 美股分红/派息
    RouterRule(
        intent="us_dividend",
        priority=430,
        pattern=r"(美股|纳斯达克|纽交所|NYSE|NASDAQ|\.US).{0,8}(分红|派息|股息|红利|dividend)",
        allowed_yaml_paths=[
            "美股/stock_ustock_dividend_fy.yaml",
            "美股/stock_ustock_dividend_record.yaml",
        ],
        query_expansions=["美股分红", "股息"],
        market="美股",
        confidence=0.88,
    ),
    # Rule: 美股持股/股东
    RouterRule(
        intent="us_shareholding",
        priority=425,
        pattern=r"(美股|纳斯达克|纽交所|NYSE|NASDAQ|\.US).{0,8}(持股|股东|投资者|大股东|机构)",
        allowed_yaml_paths=[
            "美股/stock_ustock_shareholding.yaml",
            "美股/stock_ustock_shareholding_new.yaml",
            "美股/stock_ustock_participation_holding.yaml",
        ],
        query_expansions=["持股", "股东"],
        market="美股",
        confidence=0.85,
    ),
    # Rule: 美股预测/展望
    RouterRule(
        intent="us_forecast",
        priority=420,
        pattern=r"(美股|纳斯达克|纽交所|NYSE|NASDAQ|\.US).{0,8}(预测|预期|展望|分析师|研报|目标价|评级)",
        allowed_yaml_paths=[
            "美股/stock_ustock_fin_forecast.yaml",
            "美股/stock_ustock_research_report_rating.yaml",
        ],
        query_expansions=["美股预测", "分析师预期"],
        market="美股",
        confidence=0.85,
    ),
    # Rule: 美股FDA审批
    RouterRule(
        intent="us_fda",
        priority=415,
        pattern=r"(FDA|药品审批|新药上市|生物制药|biotech).{0,5}(审批|通过|获批|进展|申请)?",
        negative_pattern=r"(A股|沪市|深市|创业板|科创板|北交所|港股|H股)",
        allowed_yaml_paths=[
            "美股/stock_ustock_fda.yaml",
        ],
        query_expansions=["FDA", "药品审批"],
        market="美股",
        confidence=0.90,
    ),

    # ===========================================================
    #  期货规则 (priority 500 ~ 550)
    # ===========================================================

    # Rule: 期货合约信息
    RouterRule(
        intent="futures_contract",
        priority=545,
        pattern=r"(期货|合约).{0,5}(信息|代码|合约规格|交割|保证金|手续费|到期|交易单位)",
        allowed_yaml_paths=[
            "期货/futu_contract_info.yaml",
            "期货/futu_contract_trade_info.yaml",
        ],
        query_expansions=["期货合约", "合约信息"],
        market="期货",
        confidence=0.90,
    ),
    # Rule: 期货日行情/价格
    RouterRule(
        intent="futures_daily_quote",
        priority=540,
        pattern=r"(期货|主力合约|合约).{0,5}(行情|价格|涨跌|成交|收盘|开盘|结算|持仓量|成交量)",
        allowed_yaml_paths=[
            "期货/futu_mkt_daily_quo.yaml",
            "期货/futu_mkt_daily_quo_latest.yaml",
            "期货/futu_mkt_quo_latest.yaml",
        ],
        query_expansions=["期货行情", "主力合约"],
        market="期货",
        frequency="日频",
        confidence=0.90,
    ),
    # Rule: 期货持仓/多空/龙虎榜
    RouterRule(
        intent="futures_position",
        priority=535,
        pattern=r"(期货|合约).{0,5}(持仓|多空|净多|净空|多头|空头|持仓量|增仓|减仓)",
        allowed_yaml_paths=[
            "期货/futu_mbr_position_contract_status.yaml",
            "期货/futu_mbr_position_contract_status_latest.yaml",
        ],
        query_expansions=["期货持仓", "多空"],
        market="期货",
        frequency="日频",
        confidence=0.88,
    ),
    # Rule: 期货会员/席位持仓排名
    RouterRule(
        intent="futures_member_position",
        priority=530,
        pattern=r"(期货|合约).{0,5}(会员|席位|排名|龙虎|前20|十大)",
        allowed_yaml_paths=[
            "期货/futu_mbr_position_contract_stat.yaml",
            "期货/futu_mbr_position_contract_stat_latest.yaml",
            "期货/futu_mbr_list.yaml",
        ],
        query_expansions=["会员持仓", "席位排名"],
        market="期货",
        frequency="日频",
        confidence=0.88,
    ),
    # Rule: 期现货/基差/升贴水
    RouterRule(
        intent="futures_spot",
        priority=525,
        pattern=r"(基差|升贴水|期现|现货价格|期货现货|期现价差)",
        allowed_yaml_paths=[
            "期货/futu_contract_spot_status.yaml",
            "期货/futu_contract_spot_status_latest.yaml",
        ],
        query_expansions=["基差", "升贴水", "期现价差"],
        market="期货",
        confidence=0.92,
    ),
    # Rule: 期货仓单
    RouterRule(
        intent="futures_warehouse",
        priority=520,
        pattern=r"(仓单|注册仓单|仓单数量|仓单变化|库存)",
        negative_pattern=r"(A股|港股|美股|基金)",
        allowed_yaml_paths=[
            "期货/futu_contract_warehouse_receipt_stat.yaml",
            "期货/futu_contract_warehouse_receipt_stat_latest.yaml",
        ],
        query_expansions=["仓单", "库存"],
        market="期货",
        confidence=0.88,
    ),
    # Rule: 期货品种/产品信息
    RouterRule(
        intent="futures_variety",
        priority=515,
        pattern=(
            r"((期货品种|品种信息|商品期货|金融期货|农产品期货|有色金属期货|黑色系期货|能源化工期货)"
            r".{0,5}(信息|交易|走势|行情|数据)?|"
            r"(有色金属|黑色系|能源化工).{0,4}(期货|合约|主力))"
        ),
        negative_pattern=r"(A股|港股|美股|基金|股票|个股|上市公司|行业|板块|概念)",
        allowed_yaml_paths=[
            "期货品种/futu_pdt_info.yaml",
            "期货品种/futu_pdt_trade_info.yaml",
            "期货品种/futu_pdt_sales_situation_latest.yaml",
        ],
        query_expansions=["期货品种", "品种"],
        market="期货",
        confidence=0.85,
    ),
    # Rule: 期货品种持仓排名
    RouterRule(
        intent="futures_variety_position",
        priority=510,
        pattern=r"(期货品种|品种).{0,5}(持仓|多空|排名|净多|净空)",
        allowed_yaml_paths=[
            "期货品种/futu_mbr_position_variety_status.yaml",
            "期货品种/futu_mbr_position_variety_status_latest.yaml",
            "期货品种/futu_mbr_position_variety_stat.yaml",
        ],
        query_expansions=["品种持仓", "品种排名"],
        market="期货",
        frequency="日频",
        confidence=0.85,
    ),
    # Rule: 期货通用兜底 (当查询提到期货/主力合约但无明确动作词时)
    RouterRule(
        intent="futures_daily_quote",
        priority=500,
        pattern=r"(期货|主力合约).{0,10}(期货|主力合约|连续|当月|下月|远月)?",
        negative_pattern=r"(A股|港股|美股|基金|指数基金|ETF基金)",
        allowed_yaml_paths=[
            "期货/futu_mkt_daily_quo.yaml",
            "期货/futu_mkt_daily_quo_latest.yaml",
            "期货/futu_contract_info.yaml",
        ],
        query_expansions=["期货", "主力合约", "行情"],
        market="期货",
        confidence=0.75,
    ),
    # Rule: 有期权的期货品种 + 分钟技术面
    RouterRule(
        intent="futures_option_technical",
        priority=872,
        pattern=r"(有期权的期货品种|期货品种).{0,24}(分钟|15分钟|30分钟|60分钟).{0,24}(均线|金叉|死叉|斜率)",
        allowed_yaml_paths=[
            "期货/futu_contract_info.yaml",
            "期货/futu_mkt_minute_quo.yaml",
            "期货/futu_mkt_daily_quo.yaml",
            "期货/futu_mkt_weekly_quo.yaml",
            "期货/futu_mkt_monthly_quo.yaml",
            "期权/options_basics.yaml",
        ],
        query_expansions=["期货品种", "分钟行情", "均线金叉", "商品期权"],
        market="期货",
        frequency="时序",
        confidence=0.90,
    ),

    # ===========================================================
    #  技术指标规则 (priority 600 ~ 650)
    #  技术指标数据来源于行情表（日/周/月/年K线）
    # ===========================================================

    # Rule: 多周期 MACD / 年线月线周线 MACD
    RouterRule(
        intent="technical_multi_period_macd",
        priority=648,
        pattern=r"(MACD|DIF|DEA).{0,12}(年线|月线|周线|多周期)|(年线|月线|周线|多周期).{0,12}(MACD|DIF|DEA)",
        negative_pattern=r"(港股|美股|期货|基金|指数|新三板|可转债|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_month_trans.yaml",
            "股票/stock_astock_mkt_week_trans.yaml",
            "股票/stock_astock_mkt_year_trans.yaml",
            "股票/stock_astock_mkt_daily_trans.yaml",
        ],
        query_expansions=["MACD", "周线", "月线", "年线"],
        market="A股",
        frequency="日频",
        confidence=0.96,
    ),
    # Rule: 多周期均线
    RouterRule(
        intent="technical_multi_period_ma",
        priority=627,
        pattern=r"(多周期均线|(年线|月线|周线).{0,10}(均线|MA)|(均线|MA).{0,10}(年线|月线|周线))",
        negative_pattern=r"(港股|美股|期货|基金|指数|新三板|可转债|H股|\.HK|\.US|NASDAQ|NYSE|(?<![A-Za-z])ETF(?![A-Za-z]))",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_mkt_month_trans.yaml",
            "股票/stock_astock_mkt_week_trans.yaml",
            "股票/stock_astock_mkt_year_trans.yaml",
        ],
        query_expansions=["均线", "周线", "月线", "年线"],
        market="A股",
        frequency="日频",
        confidence=0.94,
    ),
    # Rule: MACD
    RouterRule(
        intent="technical_macd",
        priority=645,
        pattern=r"MACD|异同移动平均|DIF|DEA|MACD柱",
        negative_pattern=r"(港股|美股|期货|基金|指数|新三板|可转债|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["MACD", "DIF", "DEA", "技术指标", "金叉", "死叉"],
        market="A股",
        frequency="日频",
        confidence=0.95,
    ),
    # Rule: KDJ
    RouterRule(
        intent="technical_kdj",
        priority=640,
        pattern=r"KDJ|随机指标|K值|D值|J值",
        negative_pattern=r"(港股|美股|期货|基金|指数|新三板|可转债|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["KDJ", "随机指标", "超买超卖"],
        market="A股",
        frequency="日频",
        confidence=0.95,
    ),
    # Rule: RSI
    RouterRule(
        intent="technical_rsi",
        priority=635,
        pattern=r"RSI|相对强弱指标|相对强弱",
        negative_pattern=r"(港股|美股|期货|基金|指数|新三板|可转债|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["RSI", "相对强弱"],
        market="A股",
        frequency="日频",
        confidence=0.95,
    ),
    # Rule: EMV (简易波动指标)
    RouterRule(
        intent="technical_emv",
        priority=632,
        pattern=r"EMV|简易波动|简易波动指标|MAEMV",
        negative_pattern=r"(港股|美股|期货|基金|指数|新三板|可转债|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["EMV", "emv", "MAEMV", "maemv", "技术指标"],
        market="A股",
        frequency="日频",
        confidence=0.95,
    ),
    # Rule: 布林带
    RouterRule(
        intent="technical_boll",
        priority=630,
        pattern=r"BOLL|布林|布林带|布林线|上轨|下轨|中轨",
        negative_pattern=r"(铁路|高铁|轨道交通|港股|美股|期货|基金|指数|新三板|可转债|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["布林带", "BOLL", "上轨", "下轨"],
        market="A股",
        frequency="日频",
        confidence=0.92,
    ),
    # Rule: 均线/MA 金叉死叉
    RouterRule(
        intent="technical_ma",
        priority=625,
        pattern=r"(均线|移动平均|MA\d+|MA线).{0,5}(金叉|死叉|交叉|突破|多头排列|空头排列|上穿|下穿)",
        negative_pattern=r"(港股|美股|期货|基金|指数|新三板|可转债|H股|\.HK|\.US|NASDAQ|NYSE|(?<![A-Za-z])ETF(?![A-Za-z]))",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["均线", "移动平均", "金叉", "死叉"],
        market="A股",
        frequency="日频",
        confidence=0.90,
    ),
    # Rule: 成交量/换手/量价背离
    RouterRule(
        intent="technical_volume",
        priority=620,
        pattern=r"(放量|缩量|天量|地量|量价背离|量价齐升|量价齐跌|量能)",
        negative_pattern=r"(港股|美股|期货|基金|指数|新三板|可转债|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["成交量", "量价"],
        market="A股",
        frequency="日频",
        confidence=0.85,
    ),
    # Rule: K线形态
    RouterRule(
        intent="technical_kline_pattern",
        priority=615,
        pattern=r"(十字星|锤子线|锤头线|吊颈线|吞没|乌云盖顶|启明星|射击之星|光头|光脚|阳线|阴线|大阳|大阴|长上影|长下影|孕线|红三兵|三只乌鸦|墓碑线|蜻蜓线|螺旋桨|倒锤子|上升三部曲|下降三部曲)",
        negative_pattern=r"(港股|美股|期货|基金|指数|新三板|可转债|H股|\.HK|\.US|NASDAQ|NYSE)",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["K线形态", "技术形态"],
        market="A股",
        frequency="日频",
        confidence=0.85,
    ),
    # Rule: 通用技术分析（兜底）
    RouterRule(
        intent="technical_general",
        priority=610,
        pattern=r"(技术面|技术分析|技术指标|超买|超卖|背离|支撑|压力|阻力|趋势线|金叉|死叉|突破|形态)",
        negative_pattern=r"(基本面|财务|业绩|营收|利润|分红|港股|美股|期货|基金|指数|新三板|可转债|H股|\.HK|\.US|NASDAQ|NYSE|(?<![A-Za-z])ETF(?![A-Za-z]))",
        allowed_yaml_paths=[
            "股票/stock_astock_mkt_daily_trans.yaml",
            "股票/stock_astock_latest_index.yaml",
        ],
        query_expansions=["技术指标", "技术分析"],
        market="A股",
        frequency="日频",
        confidence=0.75,
    ),

    # ===========================================================
    #  新三板规则 (priority 700 ~ 750)
    # ===========================================================

    # Rule: 新三板行情/价格
    RouterRule(
        intent="threeboard_daily_quote",
        priority=745,
        pattern=r"(新三板|三板|北交所|精选层|创新层|基础层).{0,8}(行情|价格|涨跌|成交|收盘|开盘|走势|换手)",
        negative_pattern=rf"(A股|沪市|深市|创业板(?!指)|科创板|{_NEG_BJ_EXCLUSION_PATTERN})",
        allowed_yaml_paths=[
            "新三板/stock_threeboard_mkt_daily_trans.yaml",
            "新三板/stock_threeboard_mkt_trans_latest.yaml",
        ],
        query_expansions=["新三板行情", "三板"],
        market="新三板",
        frequency="日频",
        confidence=0.90,
    ),
    # Rule: 新三板基本信息
    RouterRule(
        intent="threeboard_basic_info",
        priority=740,
        pattern=r"(新三板|三板|北交所|精选层|创新层|基础层).{0,8}(基本|信息|简介|上市|公司|主营|层级|分层)",
        negative_pattern=rf"(转板|转A|转主板|IPO|{_NEG_BJ_EXCLUSION_PATTERN})",
        allowed_yaml_paths=[
            "新三板/stock_threeboard_basic_info.yaml",
        ],
        query_expansions=["新三板信息", "层级"],
        market="新三板",
        confidence=0.88,
    ),
    # Rule: 新三板财务/财报
    RouterRule(
        intent="threeboard_financial",
        priority=735,
        pattern=r"(新三板|三板|北交所).{0,8}(财报|营收|利润|EPS|ROE|资产负债|现金流|财务)",
        negative_pattern=_NEG_BJ_EXCLUSION_PATTERN,
        allowed_yaml_paths=[
            "新三板/stock_threeboard_company_financial_data.yaml",
        ],
        query_expansions=["新三板财报", "财务数据"],
        market="新三板",
        frequency="季度",
        confidence=0.88,
    ),
    # Rule: 新三板分红/派息
    RouterRule(
        intent="threeboard_dividend",
        priority=730,
        pattern=r"(新三板|三板|北交所).{0,8}(分红|派息|股息|红利|送转)",
        negative_pattern=_NEG_BJ_EXCLUSION_PATTERN,
        allowed_yaml_paths=[
            "新三板/stock_threeboard_annual_dividend.yaml",
            "新三板/stock_threeboard_dividend_status.yaml",
        ],
        query_expansions=["新三板分红", "股息"],
        market="新三板",
        confidence=0.88,
    ),
    # Rule: 新三板股东/持股
    RouterRule(
        intent="threeboard_shareholders",
        priority=725,
        pattern=r"(新三板|三板|北交所).{0,8}(股东|持股|十大|前十|股东变动)",
        negative_pattern=_NEG_BJ_EXCLUSION_PATTERN,
        allowed_yaml_paths=[
            "新三板/stock_threeboard_top10_shareholders_detail.yaml",
            "新三板/stock_threeboard_top10_shareholders_stat.yaml",
            "新三板/stock_threeboard_top10_circulate_shareholders_detail.yaml",
            "新三板/stock_threeboard_top10_circulate_shareholders_stat.yaml",
        ],
        query_expansions=["股东", "十大股东"],
        market="新三板",
        frequency="季度",
        confidence=0.85,
    ),
    # Rule: 新三板转板/层级变动
    RouterRule(
        intent="threeboard_tier_transfer",
        priority=720,
        pattern=r"(新三板|三板|北交所).{0,8}(转板|层级变动|升层|降层|转A|IPO|转主板|精选层转)",
        negative_pattern=_NEG_BJ_EXCLUSION_PATTERN,
        allowed_yaml_paths=[
            "新三板/stock_threeboard_tier_changes.yaml",
            "新三板/stock_threeboard_transfer_to_the_board.yaml",
        ],
        query_expansions=["转板", "层级变动"],
        market="新三板",
        confidence=0.88,
    ),
    # Rule: 新三板定增/再融资
    RouterRule(
        intent="threeboard_seo",
        priority=715,
        pattern=r"(新三板|三板|北交所).{0,8}(定增|增发|再融资|融资|募集)",
        negative_pattern=_NEG_BJ_EXCLUSION_PATTERN,
        allowed_yaml_paths=[
            "新三板/stock_threeboard_seo.yaml",
            "新三板/stock_threeboard_share_capital.yaml",
        ],
        query_expansions=["定增", "再融资"],
        market="新三板",
        confidence=0.85,
    ),
    # Rule: 新三板做市商
    RouterRule(
        intent="threeboard_market_maker",
        priority=710,
        pattern=r"(新三板|三板|北交所).{0,8}(做市商|做市|做市转让|协议转让|竞价转让)",
        negative_pattern=_NEG_BJ_EXCLUSION_PATTERN,
        allowed_yaml_paths=[
            "新三板/stock_threeboard_market_maker.yaml",
        ],
        query_expansions=["做市商", "转让方式"],
        market="新三板",
        confidence=0.85,
    ),
    # Rule: 新三板股权质押/激励
    RouterRule(
        intent="threeboard_equity",
        priority=705,
        pattern=r"(新三板|三板|北交所).{0,8}(股权质押|质押|股权激励|激励|期权)",
        negative_pattern=_NEG_BJ_EXCLUSION_PATTERN,
        allowed_yaml_paths=[
            "新三板/stock_threeboard_equity_pledge.yaml",
            "新三板/stock_threeboard_equity_incentives.yaml",
            "新三板/stock_threeboard_equity_transfer.yaml",
        ],
        query_expansions=["股权质押", "股权激励"],
        market="新三板",
        confidence=0.85,
    ),

    # ===========================================================
    #  全量债券规则 (priority 800 ~ 850)
    # ===========================================================

    # Rule: 债券行情
    RouterRule(
        intent="bond_quote",
        priority=845,
        pattern=r"(债券|国债|企业债|公司债|信用债|利率债|城投债).{0,8}(行情|价格|涨跌|成交|收盘|开盘|收益率|到期收益|买卖|报价|净价|全价)",
        negative_pattern=r"(可转债|转债|A股.{0,4}债券|公司发行债券)",
        allowed_yaml_paths=[
            "全量债券/bond_mkt_quo.yaml",
            "全量债券/bond_broker_mkt_quo.yaml",
            "全量债券/bond_interbank_mkt_quo.yaml",
            "全量债券/bond_sse_fixed_income_platform_quo.yaml",
        ],
        query_expansions=["债券行情", "收益率", "净价"],
        market="全量债券",
        frequency="日频",
        confidence=0.88,
    ),
    # Rule: 债券基本信息/发行
    RouterRule(
        intent="bond_basic_info",
        priority=840,
        pattern=r"(债券|国债|企业债|公司债|信用债|利率债|城投债).{0,8}(基本|信息|发行|票面|期限|付息|兑付|规模|面值|简介|代码)",
        negative_pattern=r"(可转债|转债)",
        allowed_yaml_paths=[
            "全量债券/bond_basic_info.yaml",
            "全量债券/bond_issue_info.yaml",
            "全量债券/bond_basic_info_time_params.yaml",
        ],
        query_expansions=["债券信息", "发行信息"],
        market="全量债券",
        confidence=0.88,
    ),
    # Rule: 债券评级
    RouterRule(
        intent="bond_rating",
        priority=835,
        pattern=r"(债券|国债|企业债|公司债|信用债).{0,8}(评级|信用评级|主体评级|债项评级|评级变动|评级调整|违约|信用风险|CDS|信用衍生品)",
        negative_pattern=r"(可转债|转债)",
        allowed_yaml_paths=[
            "全量债券/bond_rate_issuer.yaml",
            "全量债券/bond_rate_specified_date.yaml",
            "全量债券/bond_latest_bond_rate.yaml",
            "全量债券/bond_credit_derivative.yaml",
        ],
        query_expansions=["债券评级", "信用评级"],
        market="全量债券",
        confidence=0.85,
    ),
    # Rule: 债券估值
    RouterRule(
        intent="bond_valuation",
        priority=830,
        pattern=r"(债券|国债|企业债|公司债|信用债).{0,8}(估值|中债估值|中证估值|收益率曲线|久期|凸性|修正久期|利差|信用利差|期限利差)",
        negative_pattern=r"(可转债|转债)",
        allowed_yaml_paths=[
            "全量债券/bond_ccdc_valuation_index.yaml",
            "全量债券/bond_cfets_valuation_index.yaml",
            "全量债券/bond_csi_valuation_index.yaml",
            "全量债券/bond_ihs_valuation.yaml",
            "全量债券/bond_yy_valuation_index.yaml",
        ],
        query_expansions=["债券估值", "中债估值", "久期"],
        market="全量债券",
        confidence=0.88,
    ),
    # Rule: 债券持仓/持有人
    RouterRule(
        intent="bond_holding",
        priority=825,
        pattern=r"(债券|国债|企业债|公司债|信用债).{0,8}(持仓|持有|基金持债|机构持有|托管|限售)",
        negative_pattern=r"(可转债|转债)",
        allowed_yaml_paths=[
            "全量债券/bond_fund_hold.yaml",
            "全量债券/bond_hold_index.yaml",
            "全量债券/bond_institution_restricted.yaml",
        ],
        query_expansions=["债券持仓", "持有人"],
        market="全量债券",
        frequency="季度",
        confidence=0.85,
    ),
    # Rule: 可转债/ABS分析（债券视角）
    RouterRule(
        intent="bond_convertible_abs",
        priority=820,
        pattern=r"(ABS|资产支持证券|资产证券化|CLO|MBS|RMBS|CMBS).{0,8}(信息|发行|基本|行情|评级|规模)?",
        allowed_yaml_paths=[
            "全量债券/bond_basic_abs.yaml",
            "全量债券/bond_basic_abs_spc_data.yaml",
            "全量债券/bond_convertible_bond_analysis_index.yaml",
            "全量债券/bond_convertible_bond_issue_info.yaml",
        ],
        query_expansions=["ABS", "资产证券化"],
        market="全量债券",
        confidence=0.85,
    ),
    # Rule: 债券风险/收益分析
    RouterRule(
        intent="bond_risk_return",
        priority=815,
        pattern=r"(债券|国债|企业债|公司债|信用债).{0,8}(风险|收益|回报|夏普|波动|最大回撤|年化收益)",
        negative_pattern=r"(可转债|转债|基金|理财)",
        allowed_yaml_paths=[
            "全量债券/bond_risk_return.yaml",
        ],
        query_expansions=["债券风险", "债券收益"],
        market="全量债券",
        confidence=0.82,
    ),
    # Rule: 债券通用兜底
    RouterRule(
        intent="bond_general",
        priority=800,
        pattern=r"(债券|国债|企业债|公司债|信用债|利率债|城投债|地方债|政府债|金融债|短融|超短融|中票|中期票据)",
        negative_pattern=r"(可转债|转债|A股.{0,4}债券|公司发行债券)",
        allowed_yaml_paths=[
            "全量债券/bond_mkt_quo.yaml",
            "全量债券/bond_basic_info.yaml",
        ],
        query_expansions=["债券"],
        market="全量债券",
        confidence=0.72,
    ),

    # ===========================================================
    #  期权规则 (priority 850 ~ 870)
    # ===========================================================

    # Rule: 期权行情
    RouterRule(
        intent="options_quote",
        priority=865,
        pattern=r"(期权|认购期权|认沽期权|看涨期权|看跌期权).{0,8}(行情|价格|涨跌|成交|收盘|开盘|报价|结算|隐含波动率|IV|Greeks?|Delta|Gamma|Vega|Theta)",
        allowed_yaml_paths=[
            "期权/options_mkt_daily.yaml",
            "期权/options_mkt_lastest.yaml",
            "期权/options_mkt_minute.yaml",
            "期权/options_mkt_monthly.yaml",
            "期权/options_mkt_weekly.yaml",
        ],
        query_expansions=["期权行情", "隐含波动率"],
        market="期权",
        frequency="日频",
        confidence=0.90,
    ),
    # Rule: 期权基本信息
    RouterRule(
        intent="options_basic_info",
        priority=860,
        pattern=r"(期权|认购期权|认沽期权|看涨|看跌).{0,8}(基本|信息|合约|行权|到期|标的|ETF期权|股指期权|商品期权)",
        allowed_yaml_paths=[
            "期权/options_basics.yaml",
            "期权/options_etf_conversion.yaml",
        ],
        query_expansions=["期权信息", "合约"],
        market="期权",
        confidence=0.88,
    ),
    # Rule: 期权通用兜底
    RouterRule(
        intent="options_general",
        priority=850,
        pattern=r"(期权|认购|认沽|行权价|行权日|期权链|波动率微笑|波动率曲面|期权定价|Black.?Scholes|BS模型)",
        negative_pattern=r"(股权激励|期权激励|新三板.{0,4}期权|基金.{0,2}认购|认购.{0,4}(份额|金额|费率|费用)|申购.{0,4}(份额|金额|费率))",
        allowed_yaml_paths=[
            "期权/options_mkt_daily.yaml",
            "期权/options_basics.yaml",
        ],
        query_expansions=["期权"],
        market="期权",
        confidence=0.75,
    ),

    # ===========================================================
    #  银行理财规则 (priority 870 ~ 890)
    # ===========================================================

    # Rule: 理财产品行情/净值
    RouterRule(
        intent="bwmp_nav",
        priority=885,
        pattern=r"(银行理财|理财产品|净值型理财).{0,8}(净值|行情|价格|收益|涨跌|回报|七日年化|万份收益|业绩比较基准)",
        allowed_yaml_paths=[
            "银行理财/bwmp_daily_market_data.yaml",
            "银行理财/bwmp_daily_market_data_new.yaml",
            "银行理财/bwmp_performance_risk_analysis.yaml",
        ],
        query_expansions=["理财净值", "理财收益"],
        market="银行理财",
        frequency="日频",
        confidence=0.90,
    ),
    # Rule: 理财产品信息
    RouterRule(
        intent="bwmp_basic_info",
        priority=880,
        pattern=r"(银行理财|理财产品|净值型理财).{0,8}(基本|信息|期限|类型|风险等级|发行|规模|门槛|起购|费率)",
        allowed_yaml_paths=[
            "银行理财/bwmp_basic_info.yaml",
            "银行理财/bwmp_fee_rate_info.yaml",
            "银行理财/bwmp_hist_stats.yaml",
        ],
        query_expansions=["理财产品信息", "费率"],
        market="银行理财",
        confidence=0.88,
    ),
    # Rule: 理财持仓/配置
    RouterRule(
        intent="bwmp_holding",
        priority=877,
        pattern=r"(银行理财|理财产品).{0,8}(持仓|配置|投向|资产配置|债券配置|股票配置|份额|规模变动)",
        allowed_yaml_paths=[
            "银行理财/bwmp_position_detail.yaml",
            "银行理财/bwmp_position_detail_new.yaml",
            "银行理财/bwmp_share_and_scale_changes.yaml",
            "银行理财/bwmp_share_and_scale_changes_new.yaml",
        ],
        query_expansions=["理财持仓", "投资配置"],
        market="银行理财",
        frequency="季度",
        confidence=0.85,
    ),
    # Rule: 银行理财通用兜底
    RouterRule(
        intent="bwmp_general",
        priority=870,
        pattern=r"(银行理财|理财产品|净值型理财|固收理财|固定收益理财|理财到期|理财赎回|理财风险等级R[1-5]|R[1-5]理财)",
        negative_pattern=r"(基金|保险|信托|期货|可转债)",
        allowed_yaml_paths=[
            "银行理财/bwmp_daily_market_data.yaml",
            "银行理财/bwmp_basic_info.yaml",
        ],
        query_expansions=["银行理财"],
        market="银行理财",
        confidence=0.72,
    ),

    # ===========================================================
    #  外盘期货规则 (priority 890 ~ 910)
    # ===========================================================

    # Rule: 外盘期货行情
    RouterRule(
        intent="foreign_futures_quote",
        priority=905,
        pattern=r"(外盘期货|伦铜|伦铝|伦锌|伦镍|伦铅|伦锡|WTI|布伦特|Brent|COMEX|LME|NYMEX|ICE|CME).{0,8}(行情|价格|涨跌|成交|收盘|开盘|结算|走势|K线)?",
        allowed_yaml_paths=[
            "外盘期货/futu_mkt_daily_quo_foris.yaml",
            "外盘期货/futu_mkt_monthly_quo_foris.yaml",
            "外盘期货/futu_mkt_weekly_quo_foris.yaml",
            "外盘期货/futu_mkt_yearly_quo_foris.yaml",
        ],
        query_expansions=["外盘期货行情", "外盘"],
        market="外盘期货",
        frequency="日频",
        confidence=0.90,
    ),
    # Rule: 外盘期货通用兜底
    RouterRule(
        intent="foreign_futures_general",
        priority=890,
        pattern=r"(外盘期货|外盘|伦敦金属|纽约原油|芝加哥|外盘合约)",
        negative_pattern=r"(A股|港股|美股|国内期货|内盘)",
        allowed_yaml_paths=[
            "外盘期货/futu_mkt_daily_quo_foris.yaml",
            "外盘期货/futu_contract_info_foris.yaml",
        ],
        query_expansions=["外盘期货"],
        market="外盘期货",
        confidence=0.75,
    ),

    # ===========================================================
    #  市场环境规则 (priority 910 ~ 930)
    # ===========================================================

    # Rule: 交易日历/经济事件
    RouterRule(
        intent="market_calendar_events",
        priority=925,
        pattern=r"(交易日历|休市安排|开市安排|节假日安排|经济事件|经济数据发布|宏观事件|CPI发布|GDP发布|PMI发布|非农|FOMC|美联储|降息|加息|MLF|LPR|公开市场操作)",
        negative_pattern=r"(涨停|跌停|连板|股价|成交量|成交额|换手率|量比|主板|创业板|科创板|北交所|个股|股票|均线|MACD|KDJ|RSI|分时|竞价|封单|内盘|外盘|主力资金|DDE)",
        allowed_yaml_paths=[
            "市场环境/pub_sec_mkt_trade_calendar.yaml",
            "市场环境/pub_sec_mkt_economic_events.yaml",
        ],
        query_expansions=["交易日历", "经济事件"],
        market="市场环境",
        confidence=0.88,
    ),
    # Rule: 市场分析/情绪
    RouterRule(
        intent="market_sentiment",
        priority=920,
        pattern=r"(市场温度|市场情绪|大盘情绪|赚钱效应|涨跌家数|涨停数|跌停数|新财富|旅游资金|市场表现|交易活跃度)",
        allowed_yaml_paths=[
            "市场环境/pub_sec_mkt_trade_performance.yaml",
            "市场环境/pub_sec_mkt_travel_capital.yaml",
            "市场环境/stock_astock_evaluate_new_fortune.yaml",
        ],
        query_expansions=["市场情绪", "市场分析"],
        market="市场环境",
        confidence=0.85,
    ),
    # Rule: 市场环境通用兜底
    RouterRule(
        intent="market_env_general",
        priority=910,
        pattern=r"(市场环境|宏观环境|大盘环境|交易环境|私募产品净值)",
        allowed_yaml_paths=[
            "市场环境/pub_sec_mkt_trade_calendar.yaml",
            "市场环境/pub_sec_mkt_trade_performance.yaml",
            "市场环境/private_product_nav.yaml",
        ],
        query_expansions=["市场环境"],
        market="市场环境",
        confidence=0.72,
    ),

    # ===========================================================
    #  同花顺保险规则 (priority 930 ~ 940)
    # ===========================================================

    # Rule: 保险产品
    RouterRule(
        intent="insurance_product",
        priority=935,
        pattern=r"(保险|保险产品|寿险|财险|车险|健康险|意外险|医疗险|重疾险|年金险|万能险|投连险|保障计划|保险条款|保费|赔付|理赔)",
        negative_pattern=(
            r"(社保|保险持仓|保险持股|保险资金|"
            # A股行业/概念上下文中的"保险"（如"证券或银行或保险"）不应触发保险产品规则
            r"涨跌幅|成交|换手|涨停|跌停|行业|概念|板块|龙头|"
            r"证券.{0,6}保险|银行.{0,6}保险|或.{0,6}保险|保险.{0,6}或|"
            r"金融.{0,4}保险)"
        ),
        allowed_yaml_paths=[
            "同花顺保险/insurance_basic.yaml",
            "同花顺保险/insurance_protection_plan.yaml",
        ],
        query_expansions=["保险产品", "保险"],
        market="同花顺保险",
        confidence=0.85,
    ),

    # ===========================================================
    #  英股规则 (priority 940 ~ 950)
    # ===========================================================

    # Rule: 英股IPO
    RouterRule(
        intent="uk_stock_ipo",
        priority=945,
        pattern=r"(英股|伦敦证券|LSE|伦交所|英国上市|FTSE|富时).{0,8}(IPO|上市|发行|新股|英股)?",
        negative_pattern=r"(富时中国|富时A50|A50|中国A50|沪深|A股)",
        allowed_yaml_paths=[
            "英股/stock_ukstock_ipo.yaml",
        ],
        query_expansions=["英股", "IPO"],
        market="英股",
        confidence=0.85,
    ),

    # ===========================================================
    #  港股扩展规则 (priority 300 ~ 350 范围扩展)
    # ===========================================================

    # Rule: 港股回购
    RouterRule(
        intent="hk_buyback",
        priority=318,
        pattern=r"(港股|恒生指数|恒指|\.HK|H股).{0,8}(回购|股份回购|回购股份|回购金额)",
        allowed_yaml_paths=[
            "港股/stock_hkstcok_buyback.yaml",
        ],
        query_expansions=["港股回购"],
        market="港股",
        confidence=0.85,
    ),
    # Rule: 港股IPO/融资
    RouterRule(
        intent="hk_financing",
        priority=316,
        pattern=r"(港股|恒生指数|恒指|\.HK|H股).{0,8}(IPO|上市|新股|发行|融资|配股|供股)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_financing.yaml",
            "港股/stock_hkstock_share_capital.yaml",
        ],
        query_expansions=["港股IPO", "融资"],
        market="港股",
        confidence=0.85,
    ),
    # Rule: 港股主营构成
    RouterRule(
        intent="hk_revenue_composition",
        priority=314,
        pattern=r"(港股|恒生指数|恒指|\.HK|H股).{0,8}(主营|收入构成|收入结构|业务构成|主营构成|分产品|分地区)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_main_business_composition.yaml",
        ],
        query_expansions=["港股主营", "收入构成"],
        market="港股",
        confidence=0.82,
    ),
    # Rule: 港股ESG/历史统计
    RouterRule(
        intent="hk_esg_history",
        priority=312,
        pattern=r"(港股|恒生指数|恒指|\.HK|H股).{0,8}(ESG|环境|社会责任|公司治理|历史统计|历史数据|统计汇总)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_esg_rating.yaml",
            "港股/stock_hkstock_history_statistics.yaml",
        ],
        query_expansions=["ESG", "港股统计"],
        market="港股",
        confidence=0.82,
    ),
    # Rule: 港股财务分析latest
    RouterRule(
        intent="hk_financial_latest",
        priority=334,
        pattern=r"(港股|恒生指数|恒指|\.HK|H股).{0,8}(最新财务|最新财报|财务分析|财务指标|PE|PB|PS|市盈率|市净率)",
        allowed_yaml_paths=[
            "港股/stock_hkstock_finc_analys_latest.yaml",
            "港股/stock_hkstock_finc_analys.yaml",
        ],
        query_expansions=["港股财务指标", "最新财报"],
        market="港股",
        confidence=0.85,
    ),

    # ===========================================================
    #  美股扩展规则 (priority 400 ~ 450 范围扩展)
    # ===========================================================

    # Rule: 美股资本结构
    RouterRule(
        intent="us_capital_structure",
        priority=418,
        pattern=r"(美股|纳斯达克|纽交所|NYSE|NASDAQ|\.US).{0,8}(资本结构|股本|股份|流通股|总股本|市值)",
        allowed_yaml_paths=[
            "美股/stock_ustock_capital_structure.yaml",
        ],
        query_expansions=["美股资本结构", "股本"],
        market="美股",
        confidence=0.82,
    ),
    # Rule: 美股IPO/发行
    RouterRule(
        intent="us_offering",
        priority=416,
        pattern=r"(美股|纳斯达克|纽交所|NYSE|NASDAQ|\.US).{0,8}(IPO|上市|发行|新股|offering|SPO|二次发行)",
        allowed_yaml_paths=[
            "美股/stock_ustock_offering.yaml",
        ],
        query_expansions=["美股IPO", "发行"],
        market="美股",
        confidence=0.85,
    ),
    # Rule: 美股管理层
    RouterRule(
        intent="us_management",
        priority=414,
        pattern=r"(美股|纳斯达克|纽交所|NYSE|NASDAQ|\.US).{0,8}(管理层|高管|CEO|CFO|董事|管理团队|薪酬)",
        allowed_yaml_paths=[
            "美股/ustock_company_mgmt.yaml",
        ],
        query_expansions=["美股管理层", "高管"],
        market="美股",
        confidence=0.82,
    ),
    # Rule: 美股历史统计
    RouterRule(
        intent="us_historical_stats",
        priority=412,
        pattern=r"(美股|纳斯达克|纽交所|NYSE|NASDAQ|\.US).{0,8}(历史统计|历史数据|统计汇总|历史表现)",
        allowed_yaml_paths=[
            "美股/stock_ustock_historical_statistics.yaml",
        ],
        query_expansions=["美股历史统计"],
        market="美股",
        confidence=0.82,
    ),

    # ===========================================================
    #  基金扩展规则 (priority 200 ~ 250 范围扩展)
    # ===========================================================

    # Rule: FOF持仓
    RouterRule(
        intent="fund_fof_holding",
        priority=208,
        pattern=r"(FOF|基金中基金|母基金).{0,8}(持仓|配置|持有|重仓|投向)",
        allowed_yaml_paths=[
            "基金/fof_fund_hold_detail.yaml",
        ],
        query_expansions=["FOF持仓", "基金中基金"],
        market="基金",
        frequency="季度",
        confidence=0.85,
    ),
    # Rule: 基金大宗交易
    RouterRule(
        intent="fund_block_trading",
        priority=207,
        pattern=r"(基金|ETF).{0,5}(大宗交易|大宗|折价|溢价)",
        negative_pattern=r"(A股|港股|美股|期货)",
        allowed_yaml_paths=[
            "基金/fund_block_trading.yaml",
        ],
        query_expansions=["基金大宗交易"],
        market="基金",
        confidence=0.82,
    ),
    # Rule: 基金财务数据
    RouterRule(
        intent="fund_financial_data",
        priority=206,
        pattern=r"(基金|ETF).{0,5}(财务|财报|利润|资产负债|现金流|收入|成本|费用支出)",
        negative_pattern=r"(基金经理|基金公司|A股|港股|美股)",
        allowed_yaml_paths=[
            "基金/fund_financial_data.yaml",
        ],
        query_expansions=["基金财务", "基金财报"],
        market="基金",
        frequency="季度",
        confidence=0.82,
    ),
    # Rule: 基金大额持有人
    RouterRule(
        intent="fund_major_holder",
        priority=204,
        pattern=r"(基金|ETF).{0,5}(大额持有|机构持有|持有人结构|持有人|大户|机构占比)",
        negative_pattern=r"(基金经理|基金公司)",
        allowed_yaml_paths=[
            "基金/fund_major_holder.yaml",
        ],
        query_expansions=["基金持有人", "大额持有"],
        market="基金",
        frequency="季度",
        confidence=0.82,
    ),

    # ===========================================================
    #  全量指数扩展规则 (priority 180 ~ 200 范围扩展)
    # ===========================================================

    # Rule: 指数分钟行情
    RouterRule(
        intent="index_minute_quote",
        priority=188,
        pattern=r"(指数|沪深300|上证指数|深证成指|创业板指|科创50|中证\d+).{0,5}(分钟|分时|盘口|1分钟|5分钟|15分钟|30分钟|60分钟)",
        negative_pattern=r"(基金|ETF|期货)",
        allowed_yaml_paths=[
            "全量指数/index_mkt_min_trans.yaml",
        ],
        query_expansions=["指数分钟行情", "分时"],
        market="指数",
        frequency="时序",
        confidence=0.88,
    ),
    # Rule: 指数周月行情
    RouterRule(
        intent="index_weekly_monthly_quote",
        priority=186,
        pattern=r"(指数|沪深300|上证指数|深证成指|创业板指|科创50|中证\d+).{0,5}(周线|月线|周K|月K|周行情|月行情|周涨幅|月涨幅)",
        negative_pattern=r"(基金|ETF|期货)",
        allowed_yaml_paths=[
            "全量指数/index_mkt_weekly_trans.yaml",
            "全量指数/index_mkt_monthly_trans.yaml",
        ],
        query_expansions=["指数周线", "指数月线"],
        market="指数",
        confidence=0.85,
    ),
    # Rule: 指数盈利预测
    RouterRule(
        intent="index_profit_forecast",
        priority=183,
        pattern=r"(指数|沪深300|上证指数|深证成指|创业板指|科创50|中证\d+).{0,5}(盈利预测|利润预测|EPS预测|一致预期|预期收益)",
        negative_pattern=r"(基金|ETF|期货)",
        allowed_yaml_paths=[
            "全量指数/index_profit_forecast.yaml",
        ],
        query_expansions=["指数盈利预测", "一致预期"],
        market="指数",
        confidence=0.85,
    ),

    # ===========================================================
    #  期货品种扩展规则 (priority 500 ~ 515 范围扩展)
    # ===========================================================

    # Rule: 品种风险
    RouterRule(
        intent="futures_variety_risk",
        priority=508,
        pattern=r"(期货品种|品种).{0,5}(风险|波动|波动率|VaR|风险指标|风险分析)",
        allowed_yaml_paths=[
            "期货品种/futu_variety_risk.yaml",
        ],
        query_expansions=["品种风险", "波动率"],
        market="期货",
        confidence=0.82,
    ),
    # Rule: 品种现货
    RouterRule(
        intent="futures_variety_spot",
        priority=506,
        pattern=r"(期货品种|品种).{0,5}(现货|现货价|现货状态|产销|供需|库存|产量|消费量)",
        allowed_yaml_paths=[
            "期货品种/futu_variety_spot_status.yaml",
        ],
        query_expansions=["品种现货", "现货价格"],
        market="期货",
        confidence=0.82,
    ),
    # Rule: 品种仓单明细
    RouterRule(
        intent="futures_variety_warehouse",
        priority=504,
        pattern=r"(期货品种|品种).{0,5}(仓单|仓单明细|仓单统计|注册仓单|有效仓单)",
        allowed_yaml_paths=[
            "期货品种/futu_variety_warehouse_receipt_stat.yaml",
            "期货品种/futu_warehosue_receipt_detail.yaml",
        ],
        query_expansions=["品种仓单", "仓单明细"],
        market="期货",
        confidence=0.82,
    ),
]


# ============================================================
# 领域路由器
# ============================================================


class DomainRouter:
    """
    领域路由器 (Enhanced v2)

    支持两种模式：
    1. 单意图模式（默认）：规则按优先级排序，first-match wins
    2. 多意图模式：收集所有匹配规则，合并输出（用于对比类查询）
    """

    # 置信度阈值调整（delta 加到 threshold 上）：
    #   - 正值 → 提高阈值 → 更难触发 scoped retrieval（用于偏通用/易误匹配的规则）
    #   - 负值 → 降低阈值 → 更易触发 scoped retrieval（用于高精度专用规则）
    #   - 不在此字典中 → delta=0，使用默认阈值
    _INTENT_CONFIDENCE_DELTAS: Dict[str, float] = {
        # 通用/兜底规则 → 提高阈值，要求更高置信度才使用 scoped
        "price_change": 0.10,        # 通用涨跌幅，容易误匹配
        "continuous_days": 0.10,     # 模糊匹配
        "technical_general": 0.10,   # 通用技术面兜底
        "fund_basic_info": 0.05,     # 基金信息兜底
        # 各域 catchall 兜底规则 → 提高阈值，避免窄范围 scoped 检索
        "bond_general": 0.10,            # 债券兜底
        "options_general": 0.10,         # 期权兜底
        "bwmp_general": 0.10,            # 银行理财兜底
        "foreign_futures_general": 0.10, # 外盘期货兜底
        "market_env_general": 0.10,      # 市场环境兜底
        # 高精度专用规则 → 降低阈值，更容易启用 scoped
        "lhb_foreign_trade": -0.05,  # 龙虎榜外资精准
        "futures_spot": -0.05,       # 期现基差精准
        "cb_conversion": -0.05,      # 转股/下修精准
    }

    def __init__(
        self,
        rules: Optional[List[RouterRule]] = None,
        default_market: Optional[str] = None,
        confidence_threshold: float = 0.7,
        enable_multi_intent: bool = True,
        max_intents: int = 3,
    ):
        """
        Args:
            rules: 路由规则列表，默认使用 DEFAULT_ROUTER_RULES
            default_market: 默认市场
            confidence_threshold: 置信度阈值，低于此值时不触发路由
            enable_multi_intent: 是否启用多意图模式
            max_intents: 多意图模式下最大意图数
        """
        self.rules = rules if rules is not None else DEFAULT_ROUTER_RULES
        self.default_market = default_market
        self.confidence_threshold = confidence_threshold
        self.enable_multi_intent = enable_multi_intent
        self.max_intents = max_intents

        # 按优先级排序（降序）
        self.rules = sorted(self.rules, key=lambda r: r.priority, reverse=True)

        logger.info(
            f"DomainRouter initialized with {len(self.rules)} rules, "
            f"threshold={confidence_threshold}, multi_intent={enable_multi_intent}"
        )

    @staticmethod
    def _extract_explicit_markets(query: str) -> List[str]:
        """按文本出现顺序提取显式市场标签。"""
        if not query:
            return []

        positions: List[Tuple[int, str]] = []
        for market, pattern in _MARKET_PATTERNS.items():
            match = pattern.search(query)
            if match:
                positions.append((match.start(), market))

        positions.sort(key=lambda item: item[0])
        ordered_markets: List[str] = []
        seen = set()
        for _, market in positions:
            if market in seen:
                continue
            ordered_markets.append(market)
            seen.add(market)
        return ordered_markets

    @classmethod
    def _looks_like_comparison(cls, query: str) -> bool:
        """判断是否是对比类查询（显式关键词或多市场连接词）。"""
        if _RE_COMPARISON.search(query):
            return True

        explicit_markets = cls._extract_explicit_markets(query)
        return len(explicit_markets) >= 2 and bool(
            _RE_MULTI_MARKET_SEPARATOR.search(query)
        )

    @staticmethod
    def _has_cross_domain_signals(query: str) -> bool:
        """Detect if query spans both financial and market domains."""
        return bool(_FINANCIAL_DOMAIN_KW.search(query) and _MARKET_DOMAIN_KW.search(query))

    @staticmethod
    def _enrich_output(output: RouterOutput, query: str) -> RouterOutput:
        """Attach cross-cutting metadata (negation terms) to router output."""
        neg = extract_negation_terms(query)
        if not neg:
            return output
        from dataclasses import replace
        return replace(output, negation_terms=neg)

    def route(self, query: str) -> RouterOutput:
        """
        路由查询，返回搜索范围和扩展词

        对比类查询自动启用多意图模式（如 "A股和港股对比黄金涨跌幅"）。

        Args:
            query: 原始查询

        Returns:
            RouterOutput 包含意图、扩展词、搜索范围等
        """
        q = (query or "").strip()

        if not q:
            return self._default_output()

        # 检测是否为对比类查询或跨域查询 → 自动启用多意图
        use_multi = self.enable_multi_intent and (
            self._looks_like_comparison(q) or self._has_cross_domain_signals(q)
        )

        if use_multi:
            result = self._route_multi_intent(q)
            return self._enrich_output(result, q)

        # 单意图模式：按优先级尝试匹配（first-match wins）
        for rule in self.rules:
            if rule.matches(q):
                logger.debug(
                    f"Query '{q[:30]}...' matched rule '{rule.intent}' "
                    f"(priority={rule.priority})"
                )
                result = RouterOutput(
                    intent=rule.intent,
                    query_expansions=tuple(rule.query_expansions),
                    allowed_yaml_paths=tuple(rule.allowed_yaml_paths),
                    market=rule.market or self.default_market,
                    frequency=rule.frequency,
                    confidence=rule.confidence,
                    fallback_strategy=rule.fallback_strategy,
                    # 单意图也填充多意图字段
                    intents=(rule.intent,),
                    markets=(rule.market,) if rule.market else (),
                    frequencies=(rule.frequency,) if rule.frequency else (),
                )
                return self._enrich_output(result, q)

        # 无规则匹配 → 尝试 A股 Jargon/隐式信号兜底层
        fallback = self._astock_fallback(q)
        if fallback is not None:
            logger.info(
                f"A-stock fallback triggered for '{q[:30]}...' "
                f"(confidence={fallback.confidence:.2f})"
            )
            return self._enrich_output(fallback, q)

        # 显式市场标签兜底：检测港股/美股/基金等显式标签
        market_fb = self._market_tag_fallback(q)
        if market_fb is not None:
            logger.info(
                f"Market-tag fallback triggered for '{q[:30]}...' "
                f"(market={market_fb.market}, confidence={market_fb.confidence:.2f})"
            )
            return self._enrich_output(market_fb, q)

        theme_fb = self._theme_short_query_fallback(q)
        if theme_fb is not None:
            logger.info(
                f"Theme short-query fallback triggered for '{q}' "
                f"(confidence={theme_fb.confidence:.2f})"
            )
            return self._enrich_output(theme_fb, q)

        # Short query with no market tag → broader A-stock fallback
        short_fb = self._short_query_fallback(q)
        if short_fb is not None:
            logger.info(
                f"Short-query fallback triggered for '{q}' "
                f"(len={len(q)}, confidence={short_fb.confidence:.2f})"
            )
            return self._enrich_output(short_fb, q)

        # 真正无法识别，返回全局搜索
        return self._enrich_output(self._default_output(), q)

    def _route_multi_intent(self, query: str) -> RouterOutput:
        """多意图路由：收集规则匹配 + 显式市场补全，合并输出。"""
        matched_rules = [rule for rule in self.rules if rule.matches(query)]

        # For cross-domain queries, ensure both financial and market intents are represented
        if self._has_cross_domain_signals(query) and matched_rules:
            has_financial = any(
                _FINANCIAL_DOMAIN_KW.search(r.pattern) for r in matched_rules
            )
            has_market = any(
                _MARKET_DOMAIN_KW.search(r.pattern) for r in matched_rules
            )
            # If one domain is missing from matched rules, try to find a rule for it.
            # Respect the query's detected market — don't hardcode A股.
            if not has_financial or not has_market:
                matched_markets = {r.market for r in matched_rules if r.market}
                # Acceptable markets: None (generic) + markets already present in matched rules
                acceptable_markets = matched_markets | {None}
                # Fallback: if no market matched, default to A股
                if not matched_markets:
                    acceptable_markets.add("A股")

                for rule in self.rules:
                    if rule in matched_rules:
                        continue
                    rule_is_financial = any(
                        kw in rule.intent for kw in ("financial", "fin_", "财务")
                    ) or any(
                        kw in " ".join(rule.query_expansions)
                        for kw in ("财务", "财报", "营收", "净利润")
                    )
                    rule_is_market = any(
                        kw in rule.intent for kw in ("price", "mkt", "daily", "行情")
                    ) or any(
                        kw in " ".join(rule.query_expansions)
                        for kw in ("行情", "涨跌", "涨幅", "收盘")
                    )
                    if not has_financial and rule_is_financial and rule.market in acceptable_markets:
                        matched_rules.append(rule)
                        has_financial = True
                    elif not has_market and rule_is_market and rule.market in acceptable_markets:
                        matched_rules.append(rule)
                        has_market = True
                    if has_financial and has_market:
                        break

        all_intents: List[str] = []
        all_expansions: List[str] = []
        all_paths: List[str] = []
        all_markets: List[str] = []
        all_frequencies: List[str] = []
        confidence_values: List[float] = []

        seen_intents: Set[str] = set()
        seen_expansions: Set[str] = set()
        seen_paths: Set[str] = set()

        def _merge_item(
            intent: str,
            query_expansions: List[str],
            allowed_yaml_paths: List[str],
            market: Optional[str],
            frequency: Optional[str],
            confidence: float,
        ) -> None:
            if intent not in seen_intents:
                all_intents.append(intent)
                seen_intents.add(intent)
                confidence_values.append(confidence)

            for exp in query_expansions:
                if exp not in seen_expansions:
                    all_expansions.append(exp)
                    seen_expansions.add(exp)

            for path in allowed_yaml_paths:
                if path not in seen_paths:
                    all_paths.append(path)
                    seen_paths.add(path)

            if market and market not in all_markets:
                all_markets.append(market)
            if frequency and frequency not in all_frequencies:
                all_frequencies.append(frequency)

        for rule in matched_rules:
            _merge_item(
                intent=rule.intent,
                query_expansions=list(rule.query_expansions),
                allowed_yaml_paths=list(rule.allowed_yaml_paths),
                market=rule.market,
                frequency=rule.frequency,
                confidence=rule.confidence,
            )
            if len(all_intents) >= self.max_intents:
                break

        # 对比类查询常见写法是“市场A + 市场B + 对比”，未必带具体指标。
        # 当某些显式市场没命中规则时，补齐市场兜底路径，避免退化为 global。
        if len(all_intents) < self.max_intents:
            for market in self._extract_explicit_markets(query):
                if market in all_markets:
                    continue
                fallback = _MARKET_FALLBACKS.get(market)
                if not fallback:
                    continue
                _merge_item(
                    intent=str(fallback["intent"]),
                    query_expansions=list(fallback["query_expansions"]),
                    allowed_yaml_paths=list(fallback["allowed_yaml_paths"]),
                    market=str(fallback["market"]),
                    frequency=(
                        str(fallback["frequency"])
                        if fallback.get("frequency")
                        else None
                    ),
                    confidence=float(fallback["confidence"]),
                )
                if len(all_intents) >= self.max_intents:
                    break

        if not all_intents:
            return self._default_output()

        primary_intent = all_intents[0]
        primary_market = all_markets[0] if all_markets else self.default_market
        primary_frequency = all_frequencies[0] if all_frequencies else None
        max_confidence = max(confidence_values) if confidence_values else 0.0

        logger.info(
            f"Multi-intent route for '{query[:30]}...': "
            f"intents={all_intents}, markets={all_markets}, "
            f"paths_count={len(all_paths)}"
        )

        return RouterOutput(
            intent=primary_intent,
            query_expansions=tuple(all_expansions),
            allowed_yaml_paths=tuple(all_paths),
            market=primary_market,
            frequency=primary_frequency,
            confidence=max_confidence,
            fallback_strategy="merge",
            intents=tuple(all_intents),
            markets=tuple(all_markets),
            frequencies=tuple(all_frequencies),
        )

    def _astock_fallback(self, query: str) -> Optional[RouterOutput]:
        """A股兜底层：当精确规则均不命中时，检测隐式 A股 信号或专属 Jargon。

        检测顺序：
        0. 显式非 A股 市场标签检查（港股/美股/期权等 → 跳过 A股 兜底）
        1. ASTOCK_JARGON_SET 子串匹配（同花顺自创形态/指标名，精度高）
        2. _ASTOCK_IMPLICIT_SIGNALS 正则匹配（泛 A股 语义信号，覆盖面广）

        Returns:
            RouterOutput with intent="astock_general_fallback" if matched, else None.
        """
        # 0. 显式市场标签优先：如果 query 包含明确的非 A股 市场标记，
        #    不应被 A股 jargon/信号拦截（修复港股/美股查询误判为 A股）
        explicit_market = detect_explicit_market_tag(query)
        if explicit_market and explicit_market not in ("A股", ""):
            return None

        # 0b. Guard against non-A股 market keywords before applying A股 jargon fallback
        for guard_market in ("基金", "期货", "可转债", "指数", "新三板", "期权", "外盘期货", "银行理财", "同花顺保险"):
            pat = _MARKET_PATTERNS.get(guard_market)
            if pat and pat.search(query):
                return None

        # 1. Jargon set — 精确子串匹配，O(|JARGON_SET|)
        jargon_hit = any(j in query for j in ASTOCK_JARGON_SET)

        # 2. Implicit signals — 正则广覆盖
        signal_hit = bool(_ASTOCK_IMPLICIT_SIGNALS.search(query))

        if not jargon_hit and not signal_hit:
            return None

        # Jargon 命中时给予略高置信度（确定性更强）
        confidence = 0.65 if jargon_hit else 0.60

        return RouterOutput(
            intent="astock_general_fallback",
            query_expansions=("A股", "行情"),
            allowed_yaml_paths=(
                "股票/stock_astock_mkt_daily_trans.yaml",
                "股票/stock_astock_basic_info.yaml",
                "股票/stock_astock_latest_index.yaml",
            ),
            market="A股",
            frequency="日频",
            confidence=confidence,
            fallback_strategy="merge",
            intents=("astock_general_fallback",),
            markets=("A股",),
            frequencies=("日频",),
        )

    def _market_tag_fallback(self, query: str) -> Optional[RouterOutput]:
        """市场标签兜底层：当精确规则和 A股 jargon 均不命中时，
        使用 detect_explicit_market_tag + _MARKET_PATTERNS 检测显式市场标签。

        解决的问题：query 包含"港股"/"美股"等显式标签但无精确规则命中时，
        之前会 fallback 到 global (market=A股)，导致 BM25 误过滤。

        Returns:
            RouterOutput with detected market, or None if no explicit tag found.
        """
        # 检测显式市场标签
        explicit_market = detect_explicit_market_tag(query)
        if not explicit_market or explicit_market == "A股":
            # 也检查 _MARKET_PATTERNS（覆盖更多模式如 ETF→基金）
            for market, pattern in _MARKET_PATTERNS.items():
                if market == "A股":
                    continue
                if pattern.search(query):
                    explicit_market = market
                    break
            else:
                return None

        # 使用 _MARKET_FALLBACKS 中的预定义路径（如果有）
        fallback_info = _MARKET_FALLBACKS.get(explicit_market)
        if fallback_info:
            # 复用 _MARKET_FALLBACKS 的 confidence（与 multi-intent 路径一致）
            fb_confidence = float(fallback_info.get("confidence", 0.50))
            fb_intent = str(fallback_info.get("intent", "market_tag_fallback"))
            return RouterOutput(
                intent=fb_intent,
                query_expansions=tuple(fallback_info.get("query_expansions", ())),
                allowed_yaml_paths=tuple(fallback_info.get("allowed_yaml_paths", ())),
                market=explicit_market,
                frequency=fallback_info.get("frequency"),
                confidence=fb_confidence,
                fallback_strategy="merge",
                intents=(fb_intent,),
                markets=(explicit_market,),
            )

        # 无预定义 fallback 路径，返回无范围限制但带正确市场标签的输出
        return RouterOutput(
            intent="market_tag_fallback",
            query_expansions=(),
            allowed_yaml_paths=(),
            market=explicit_market,
            frequency=None,
            confidence=0.40,
            fallback_strategy="global_only",
            intents=("market_tag_fallback",),
            markets=(explicit_market,),
        )

    def _short_query_fallback(self, query: str) -> Optional[RouterOutput]:
        """Short-query fallback: when query is very short and no rules matched.

        Short queries lack enough context for precise routing, so we provide
        a broader A-stock candidate set with lower confidence.

        Only triggers when:
        - Query length <= 8 characters
        - No explicit non-A-stock market tag detected
        """
        if len(query) > 8:
            return None

        explicit_market = detect_explicit_market_tag(query)
        if explicit_market and explicit_market not in ("A股", ""):
            return None

        return RouterOutput(
            intent="short_query_fallback",
            query_expansions=("A股",),
            allowed_yaml_paths=(
                "股票/stock_astock_mkt_daily_trans.yaml",
                "股票/stock_astock_basic_info.yaml",
                "股票/stock_astock_latest_index.yaml",
                "股票/stock_astock_concept.yaml",
                "股票/stock_astock_company_financial_data.yaml",
            ),
            market="A股",
            frequency=None,
            confidence=0.45,
            fallback_strategy="merge",
            intents=("short_query_fallback",),
            markets=("A股",),
            frequencies=(),
        )

    def _theme_short_query_fallback(self, query: str) -> Optional[RouterOutput]:
        """Theme/entity short-query fallback for sector-like Chinese noun phrases."""
        if len(query) > 8:
            return None
        if not _RE_SHORT_THEME_QUERY.fullmatch(query):
            return None
        if _RE_COMPANY_LIKE_SUFFIX.search(query):
            return None
        if _ASTOCK_IMPLICIT_SIGNALS.search(query):
            return None

        explicit_market = detect_explicit_market_tag(query)
        if explicit_market and explicit_market not in ("A股", ""):
            return None

        return RouterOutput(
            intent="theme_short_query_fallback",
            query_expansions=(query, "概念", "行业", "板块"),
            allowed_yaml_paths=(
                "股票/stock_astock_concept.yaml",
                "股票/stock_astock_basic_info.yaml",
                "股票/stock_astock_mkt_daily_trans.yaml",
                "股票/stock_astock_latest_index.yaml",
            ),
            market="A股",
            frequency=None,
            confidence=0.72,
            fallback_strategy="merge",
            intents=("theme_short_query_fallback",),
            markets=("A股",),
            frequencies=(),
        )

    def _default_output(self) -> RouterOutput:
        """返回默认路由结果（全局搜索）"""
        return RouterOutput(
            intent="global",
            query_expansions=(),
            allowed_yaml_paths=(),
            market=self.default_market,
            frequency=None,
            confidence=0.0,
            fallback_strategy="global_only",
        )

    def should_use_scoped_retrieval(self, router_output: RouterOutput) -> bool:
        """判断是否应该使用范围限定检索 (with per-intent calibration)"""
        if not router_output.allowed_yaml_paths:
            return False
        if router_output.fallback_strategy != "merge":
            return False

        # 多意图场景下，不使用单意图 delta（避免主意图偏通用导致误关 scoped）。
        if router_output.is_multi_intent:
            return router_output.confidence >= self.confidence_threshold

        # Per-intent confidence threshold adjustment
        threshold = self.confidence_threshold
        delta = self._INTENT_CONFIDENCE_DELTAS.get(router_output.intent, 0.0)
        if delta < 0:
            threshold = max(threshold + delta, 0.5)
        elif delta > 0:
            threshold = min(threshold + delta, 0.95)

        return router_output.confidence >= threshold
