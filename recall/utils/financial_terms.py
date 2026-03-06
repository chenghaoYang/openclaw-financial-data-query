from typing import Dict, List

TERM_LHB = "龙虎榜"
TERM_FOREIGN_TRADER = "境外游资"


FINANCIAL_SYNONYMS: Dict[str, List[str]] = {
    "外资": [
        "北向资金",
        "北上资金",
        "陆股通",
        "沪股通",
        "深股通",
        "港资",
        "QFII",
        TERM_FOREIGN_TRADER,
        "北向",
    ],
    "北向资金": ["外资", "北上资金", "陆股通", "沪股通", "深股通", "港资"],
    "机构": ["主力", "大单", "特大单", "席位", "机构专用"],
    "主力": ["大单", "特大单", "机构资金", "DDE"],
    "散户": ["小单", "个人投资者", "游资"],
    "两融": ["融资融券", "融资", "融券", "余额", "两融余额"],
    "分红": ["派息", "股息", "分利", "送转"],
    "增长率": ["涨幅", "收益率", "变动率", "增长"],
    "股价": ["价格", "现价", "行情", "收盘价"],
    "资金流向": ["流入", "流出", "净流入", "净买入", "资金"],
    "估值": ["市盈率", "PE", "市净率", "PB", "市销率", "PS"],
    "营收": ["营业收入", "收入", "总收入", "主营收入", "销售收入"],
    "利润": ["净利润", "归母净利润", "扣非净利润", "毛利", "毛利率"],
    "涨停": ["涨停板", "一字涨停", "连续涨停", "涨停封板"],
    "跌停": ["跌停板", "一字跌停", "连续跌停"],
    # ---- 技术指标同义词 ----
    "MACD": ["异同移动平均", "DIF", "DEA", "MACD柱", "MACD金叉", "MACD死叉"],
    "KDJ": ["随机指标", "K值", "D值", "J值", "KDJ超买", "KDJ超卖"],
    "RSI": ["相对强弱", "相对强弱指标", "RSI超买", "RSI超卖"],
    "EMV": ["简易波动指标", "简易波动", "emv", "MAEMV", "maemv", "EMV指标"],
    "布林带": ["BOLL", "布林线", "上轨", "下轨", "中轨", "布林通道"],
    "均线": ["移动平均", "MA", "金叉", "死叉", "MA5", "MA10", "MA20", "MA60", "MA120", "MA250", "年线"],
    "成交量": ["VOL", "量能", "放量", "缩量", "天量", "地量", "量比"],
    "K线": ["K线形态", "十字星", "锤头线", "吞没", "早晨之星", "黄昏之星", "三连阳", "三连阴"],
    # ---- 行业/概念同义词 ----
    "成份股": ["成分股", "个股", "行业个股"],
    "成分股": ["成份股", "个股", "行业个股"],
    "行业": ["行业分类", "所属行业", "行业板块"],
    # ---- 期货同义词 ----
    "期货": ["主力合约", "连续合约", "期货合约"],
    "基差": ["升贴水", "期现价差", "期现差"],
    "持仓量": ["未平仓", "持仓", "空头持仓", "多头持仓"],
    # ---- 可转债同义词 ----
    "转股": ["转股价", "转股溢价率", "转股价值", "下修转股价"],
    "可转债": ["转债", "可转换债券", "CB"],
    # ---- 债券同义词 ----
    "债券": ["国债", "企业债", "公司债", "信用债", "利率债", "城投债", "金融债"],
    "到期收益率": ["YTM", "收益率", "债券收益率", "票面利率"],
    "久期": ["修正久期", "麦考利久期", "Duration"],
    "债券评级": ["信用评级", "主体评级", "债项评级", "AAA", "AA+", "AA"],
    # ---- 期权同义词 ----
    "期权": ["认购期权", "认沽期权", "看涨期权", "看跌期权", "Call", "Put"],
    "隐含波动率": ["IV", "波动率", "implied volatility", "Vega"],
    "Greek值": ["Delta", "Gamma", "Theta", "Vega", "Rho"],
    # ---- 银行理财同义词 ----
    "银行理财": ["理财产品", "固收理财", "净值型理财", "银行理财产品"],
}


def _build_reverse_synonym_map() -> Dict[str, List[str]]:
    """Pre-compute value→[key, siblings] map for query-side expansion.

    Forward map:   "外资" → ["北向资金", "陆股通", ...]
    Reverse map:   "陆股通" → ["外资", "北向资金", ...]

    This allows query-side expansion to work when the user's query token
    appears as a *value* (not a key) in FINANCIAL_SYNONYMS.
    """
    reverse: Dict[str, List[str]] = {}
    for key, values in FINANCIAL_SYNONYMS.items():
        group = [key] + list(values)
        for member in group:
            if member not in reverse:
                reverse[member] = []
            for other in group:
                if other != member and other not in reverse[member]:
                    reverse[member].append(other)
    return reverse


REVERSE_SYNONYM_MAP: Dict[str, List[str]] = _build_reverse_synonym_map()
