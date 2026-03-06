"""
时间表达式解析器 - Time Expression Parser

解析中文金融查询中的时间表达式，输出结构化时间范围。
支持相对日期（近3日）、命名周期（今年以来）、绝对日期（2024年Q3）、
日期区间（2024-01-01到2024-06-30）以及多频率组合（年线月线周线）。

使用场景：
- 查询预处理阶段，提取时间范围用于过滤数据
- 与 domain_router / market_rules 配合使用

示例：
    >>> from recall.utils.time_parser import TimeParser
    >>> result = TimeParser.parse("近3日外资买入额")
    >>> result.relative_type
    'days'
    >>> result.relative_value
    3
"""

import calendar
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional, Union

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构定义
# ============================================================

@dataclass
class TimeRange:
    """时间范围结构化表示

    Attributes:
        raw_text: 原始匹配到的时间文本片段
        start_date: 起始日期（ISO 8601 格式，如 "2024-01-01"）
        end_date: 结束日期（ISO 8601 格式）
        relative_type: 相对时间类型
            "days" | "weeks" | "months" | "years" | "ytd" | "qtd" | "mtd"
        relative_value: 相对时间数值（如"近3日"中的 3）
        is_absolute: 是否为绝对日期（有明确的起止日期）
        frequency_hint: 数据频率提示
            "日频" | "周频" | "月频" | "季度" | "年频"
    """
    raw_text: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    relative_type: Optional[str] = None
    relative_value: Optional[int] = None
    is_absolute: bool = False
    frequency_hint: Optional[str] = None


# ============================================================
# 预编译正则表达式
# ============================================================

# --- 相对时间模式 ---
# 近N日/天、最近N日/天、过去N日/天
_RE_NEAR_DAYS = re.compile(
    r"(近|最近|过去)\s*(\d+)\s*(个)?\s*(交易日|交易天|日|天)"
)
# 近N周
_RE_NEAR_WEEKS = re.compile(
    r"(近|最近|过去)\s*(\d+)\s*(个)?\s*周"
)
# 近N个月
_RE_NEAR_MONTHS = re.compile(
    r"(近|最近|过去)\s*(\d+)\s*(个)?\s*月"
)
# 近N年
_RE_NEAR_YEARS = re.compile(
    r"(近|最近|过去)\s*(\d+)\s*(个)?\s*年"
)

# --- 命名周期模式 ---
# 今年以来 / 年初至今
_RE_YTD = re.compile(r"(今年以来|年初至今|年初到现在|今年到目前)")
# 本季度（当季度至今）
_RE_QTD = re.compile(r"(本季度|当季|本季)")
# 本月
_RE_MTD = re.compile(r"(本月|当月)")
# 本周
_RE_THIS_WEEK = re.compile(r"本周|这周|当周")
# 上周
_RE_LAST_WEEK = re.compile(r"上周|上一周")
# 上月
_RE_LAST_MONTH = re.compile(r"上月|上个月|上一个月")

# --- 当天 / 昨天 ---
_RE_TODAY = re.compile(r"今日|今天")
_RE_YESTERDAY = re.compile(r"昨日|昨天")

# --- 绝对年份 ---
# "2024年" 或 "2025年"（不跟季度/月份，避免与季度模式重复匹配）
_RE_ABSOLUTE_YEAR = re.compile(
    r"(?<!\d)(20\d{2})\s*年(?!\s*\d+\s*月)(?!\s*[Q一二三四])"
)

# --- 季度模式 ---
# "Q1" / "Q2" / "一季度" / "二季度" 等（不含年份前缀）
_QUARTER_CN_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}
_RE_QUARTER_WITH_YEAR = re.compile(
    r"(?<!\d)(20\d{2})\s*年?\s*(?:Q([1-4])|第?\s*([一二三四1-4])\s*季度)",
    re.IGNORECASE,
)
_RE_QUARTER_NO_YEAR = re.compile(
    r"(?:Q([1-4])|第?\s*([一二三四])\s*季度)",
    re.IGNORECASE,
)

# --- 日期区间模式 ---
# "2024年1月1日至2024年6月30日" 或 "2024-01-01到2024-06-30"
_RE_DATE_RANGE_CN = re.compile(
    r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?"
    r"\s*(?:至|到|—|~|-|–)\s*"
    r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?"
)
_RE_DATE_RANGE_ISO = re.compile(
    r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})"
    r"\s*(?:至|到|—|~|-|–)\s*"
    r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})"
)

# --- 多频率组合 ---
# "年线月线周线"、"年线 月线"、"年线、月线、周线" 等
_RE_MULTI_FREQ = re.compile(
    r"(年线|月线|周线|日线)"
)
_FREQ_LINE_MAP = {
    "年线": "年频",
    "月线": "月频",
    "周线": "周频",
    "日线": "日频",
}


# ============================================================
# 辅助函数
# ============================================================

def _quarter_start_end(year: int, quarter: int) -> tuple:
    """返回指定季度的起止日期字符串

    Args:
        year: 年份
        quarter: 季度 (1-4)

    Returns:
        (start_date, end_date) ISO 格式字符串
    """
    quarter_months = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}
    start_month, end_month = quarter_months[quarter]
    start_date = f"{year:04d}-{start_month:02d}-01"

    # 计算季度末日期
    if end_month == 12:
        end_date = f"{year:04d}-12-31"
    else:
        # 下一个月第一天的前一天
        next_month_first = datetime(year, end_month + 1, 1)
        last_day = next_month_first - timedelta(days=1)
        end_date = last_day.strftime("%Y-%m-%d")

    return start_date, end_date


def _resolve_reference_date(reference_date: Optional[Union[str, date, datetime]] = None) -> datetime:
    """解析参考日期，默认为当天

    Args:
        reference_date: ISO 格式日期字符串或 None

    Returns:
        datetime 对象
    """
    if reference_date:
        # 支持 datetime, date, 或 ISO 格式字符串
        if isinstance(reference_date, datetime):
            return reference_date
        if hasattr(reference_date, 'year') and hasattr(reference_date, 'month'):
            # date 对象 → 转为 datetime
            return datetime(reference_date.year, reference_date.month, reference_date.day)
        try:
            return datetime.strptime(str(reference_date), "%Y-%m-%d")
        except ValueError:
            logger.warning(
                f"无法解析参考日期 '{reference_date}'，使用当天日期"
            )
    return datetime.now()


def _current_quarter(dt: datetime) -> int:
    """返回日期所在的季度 (1-4)"""
    return (dt.month - 1) // 3 + 1


_CN_DIGIT_MAP = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                 "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_digit(text: str) -> str:
    """Convert Chinese numerals in text to Arabic digits.

    Handles: 一~九, 十, 十五, 二十, 二十一, 三十, etc (up to 99).
    """
    def _convert_cn_num(match: re.Match) -> str:
        s = match.group(0)
        result = 0
        i = 0
        while i < len(s):
            ch = s[i]
            if ch == "十":
                if result == 0:
                    result = 10  # "十五" = 15
                else:
                    result *= 10  # "二十" = 20
                i += 1
            elif ch in _CN_DIGIT_MAP:
                val = _CN_DIGIT_MAP[ch]
                # Check if next char is "十"
                if i + 1 < len(s) and s[i + 1] == "十":
                    result += val * 10
                    i += 2
                else:
                    result += val
                    i += 1
            else:
                break
        return str(result) if result > 0 else s

    # Match sequences of Chinese numeral characters
    pattern = re.compile(r"[一二两三四五六七八九十]+")
    return pattern.sub(_convert_cn_num, text)


# ============================================================
# 主解析器
# ============================================================

class TimeParser:
    """
    中文金融查询时间表达式解析器

    所有方法均为静态方法，无需实例化。
    解析顺序：日期区间 > 绝对年份/季度 > 相对时间 > 命名周期 > 当天/昨天 > 多频率

    用法：
        result = TimeParser.parse("近3日外资卖出金额")
        results = TimeParser.parse("年线月线周线走势")  # 返回 list
    """

    @staticmethod
    def parse(
        text: str,
        reference_date: Optional[Union[str, date, datetime]] = None,
    ) -> Optional[Union[TimeRange, List[TimeRange]]]:
        """解析文本中的时间表达式

        Args:
            text: 待解析的查询文本
            reference_date: 参考日期（ISO 格式字符串、date 或 datetime），默认为当天。
                用于计算相对时间的绝对日期。

        Returns:
            TimeRange: 单个时间范围
            List[TimeRange]: 多频率组合时返回列表（如"年线月线周线"）
            None: 未识别到任何时间表达式
        """
        if not text or not text.strip():
            return None

        text = text.strip()
        # Convert Chinese numerals to digits for regex matching
        text_for_match = _cn_to_digit(text)
        ref = _resolve_reference_date(reference_date)

        # 按优先级依次尝试匹配

        # 1. 日期区间（最高优先级，最明确）
        result = TimeParser._parse_date_range(text_for_match)
        if result:
            return result

        # 2. 带年份的季度（如 "2024年Q3"）
        result = TimeParser._parse_quarter_with_year(text_for_match)
        if result:
            return result

        # 3. 不带年份的季度（如 "Q1"、"一季度"）
        result = TimeParser._parse_quarter_no_year(text_for_match, ref)
        if result:
            return result

        # 4. 绝对年份（如 "2024年"）
        result = TimeParser._parse_absolute_year(text_for_match)
        if result:
            return result

        # 5. 相对时间（近N日/周/月/年）
        result = TimeParser._parse_relative(text_for_match, ref)
        if result:
            return result

        # 6. 命名周期（今年以来、本季度、本月、本周、上周、上月）
        result = TimeParser._parse_named_period(text_for_match, ref)
        if result:
            return result

        # 7. 今天/昨天
        result = TimeParser._parse_today_yesterday(text_for_match, ref)
        if result:
            return result

        # 8. 多频率组合（年线月线周线）→ 返回 list
        result = TimeParser._parse_multi_frequency(text_for_match)
        if result:
            return result

        # 未匹配
        return None

    # ----------------------------------------------------------
    # 日期区间
    # ----------------------------------------------------------
    @staticmethod
    def _parse_date_range(text: str) -> Optional[TimeRange]:
        """解析日期区间: "2024年1月1日至2024年6月30日" 或 "2024-01-01到2024-06-30" """
        # 中文格式
        m = _RE_DATE_RANGE_CN.search(text)
        if m:
            y1, m1, d1, y2, m2, d2 = (int(g) for g in m.groups())
            start = f"{y1:04d}-{m1:02d}-{d1:02d}"
            end = f"{y2:04d}-{m2:02d}-{d2:02d}"
            return TimeRange(
                raw_text=m.group(0),
                start_date=start,
                end_date=end,
                is_absolute=True,
            )

        # ISO 格式
        m = _RE_DATE_RANGE_ISO.search(text)
        if m:
            y1, m1, d1, y2, m2, d2 = (int(g) for g in m.groups())
            start = f"{y1:04d}-{m1:02d}-{d1:02d}"
            end = f"{y2:04d}-{m2:02d}-{d2:02d}"
            return TimeRange(
                raw_text=m.group(0),
                start_date=start,
                end_date=end,
                is_absolute=True,
            )

        return None

    # ----------------------------------------------------------
    # 带年份的季度
    # ----------------------------------------------------------
    @staticmethod
    def _parse_quarter_with_year(text: str) -> Optional[TimeRange]:
        """解析带年份的季度: "2024年Q3"、"2024年三季度" """
        m = _RE_QUARTER_WITH_YEAR.search(text)
        if not m:
            return None

        year = int(m.group(1))

        # 确定季度编号：group(2) 是 Q 后面的数字，group(3) 是中文数字
        q_num = m.group(2)
        q_cn = m.group(3)

        if q_num:
            quarter = int(q_num)
        elif q_cn and q_cn in _QUARTER_CN_MAP:
            quarter = _QUARTER_CN_MAP[q_cn]
        else:
            return None

        start, end = _quarter_start_end(year, quarter)
        return TimeRange(
            raw_text=m.group(0),
            start_date=start,
            end_date=end,
            relative_type=None,
            is_absolute=True,
            frequency_hint="季度",
        )

    # ----------------------------------------------------------
    # 不带年份的季度
    # ----------------------------------------------------------
    @staticmethod
    def _parse_quarter_no_year(text: str, ref: datetime) -> Optional[TimeRange]:
        """解析不带年份的季度: "Q1"、"一季度" """
        m = _RE_QUARTER_NO_YEAR.search(text)
        if not m:
            return None

        # group(1) 是 Q 后面的数字，group(2) 是中文数字
        q_num = m.group(1)
        q_cn = m.group(2)

        if q_num:
            quarter = int(q_num)
        elif q_cn and q_cn in _QUARTER_CN_MAP:
            quarter = _QUARTER_CN_MAP[q_cn]
        else:
            return None

        year = ref.year
        start, end = _quarter_start_end(year, quarter)
        return TimeRange(
            raw_text=m.group(0),
            start_date=start,
            end_date=end,
            relative_type=None,
            is_absolute=True,
            frequency_hint="季度",
        )

    # ----------------------------------------------------------
    # 绝对年份
    # ----------------------------------------------------------
    @staticmethod
    def _parse_absolute_year(text: str) -> Optional[TimeRange]:
        """解析绝对年份: "2024年" """
        m = _RE_ABSOLUTE_YEAR.search(text)
        if not m:
            return None

        year = int(m.group(1))
        return TimeRange(
            raw_text=m.group(0),
            start_date=f"{year:04d}-01-01",
            end_date=f"{year:04d}-12-31",
            is_absolute=True,
            frequency_hint="年频",
        )

    # ----------------------------------------------------------
    # 相对时间
    # ----------------------------------------------------------
    @staticmethod
    def _parse_relative(text: str, ref: datetime) -> Optional[TimeRange]:
        """解析相对时间: "近3日"、"近6个月"、"近1年"、"近3个交易日" 等"""
        # 近N日/天/交易日
        m = _RE_NEAR_DAYS.search(text)
        if m:
            value = int(m.group(2))
            unit_text = m.group(4)
            # 交易日 vs 自然日：交易日需乘以约 1.5 倍（考虑周末）
            is_trading_day = "交易" in unit_text
            if is_trading_day:
                # 粗略估算：交易日 → 自然日（按 7/5 比例，向上取整）
                natural_days = int(value * 7 / 5) + 1
            else:
                natural_days = value
            start = ref - timedelta(days=natural_days)
            return TimeRange(
                raw_text=m.group(0),
                start_date=start.strftime("%Y-%m-%d"),
                end_date=ref.strftime("%Y-%m-%d"),
                relative_type="days",
                relative_value=value,
                is_absolute=False,
                frequency_hint="日频",
            )

        # 近N周
        m = _RE_NEAR_WEEKS.search(text)
        if m:
            value = int(m.group(2))
            start = ref - timedelta(weeks=value)
            return TimeRange(
                raw_text=m.group(0),
                start_date=start.strftime("%Y-%m-%d"),
                end_date=ref.strftime("%Y-%m-%d"),
                relative_type="weeks",
                relative_value=value,
                is_absolute=False,
                frequency_hint="周频",
            )

        # 近N个月
        m = _RE_NEAR_MONTHS.search(text)
        if m:
            value = int(m.group(2))
            # 月份回溯：按日历月精确计算
            target_month = ref.month - value
            target_year = ref.year
            while target_month <= 0:
                target_month += 12
                target_year -= 1
            # 处理目标月份天数不足的情况（如1月31日往前3个月→10月31日OK，但往前1个月→12月31日OK）
            max_day = calendar.monthrange(target_year, target_month)[1]
            target_day = min(ref.day, max_day)
            start = ref.replace(year=target_year, month=target_month, day=target_day)
            return TimeRange(
                raw_text=m.group(0),
                start_date=start.strftime("%Y-%m-%d"),
                end_date=ref.strftime("%Y-%m-%d"),
                relative_type="months",
                relative_value=value,
                is_absolute=False,
                frequency_hint="月频",
            )

        # 近N年
        m = _RE_NEAR_YEARS.search(text)
        if m:
            value = int(m.group(2))
            # 年份回溯：按日历年精确计算
            target_year = ref.year - value
            max_day = calendar.monthrange(target_year, ref.month)[1]
            target_day = min(ref.day, max_day)
            start = ref.replace(year=target_year, day=target_day)
            return TimeRange(
                raw_text=m.group(0),
                start_date=start.strftime("%Y-%m-%d"),
                end_date=ref.strftime("%Y-%m-%d"),
                relative_type="years",
                relative_value=value,
                is_absolute=False,
                frequency_hint="年频",
            )

        return None

    # ----------------------------------------------------------
    # 命名周期
    # ----------------------------------------------------------
    @staticmethod
    def _parse_named_period(text: str, ref: datetime) -> Optional[TimeRange]:
        """解析命名周期: "今年以来"、"本季度"、"本月"、"本周"、"上周"、"上月" """
        # 今年以来 / 年初至今
        m = _RE_YTD.search(text)
        if m:
            start = datetime(ref.year, 1, 1)
            return TimeRange(
                raw_text=m.group(0),
                start_date=start.strftime("%Y-%m-%d"),
                end_date=ref.strftime("%Y-%m-%d"),
                relative_type="ytd",
                is_absolute=False,
            )

        # 本季度
        m = _RE_QTD.search(text)
        if m:
            q = _current_quarter(ref)
            quarter_start_month = (q - 1) * 3 + 1
            start = datetime(ref.year, quarter_start_month, 1)
            return TimeRange(
                raw_text=m.group(0),
                start_date=start.strftime("%Y-%m-%d"),
                end_date=ref.strftime("%Y-%m-%d"),
                relative_type="qtd",
                is_absolute=False,
                frequency_hint="季度",
            )

        # 本月
        m = _RE_MTD.search(text)
        if m:
            start = datetime(ref.year, ref.month, 1)
            return TimeRange(
                raw_text=m.group(0),
                start_date=start.strftime("%Y-%m-%d"),
                end_date=ref.strftime("%Y-%m-%d"),
                relative_type="mtd",
                is_absolute=False,
                frequency_hint="月频",
            )

        # 本周（周一为起始）
        m = _RE_THIS_WEEK.search(text)
        if m:
            # weekday(): Monday=0
            start = ref - timedelta(days=ref.weekday())
            return TimeRange(
                raw_text=m.group(0),
                start_date=start.strftime("%Y-%m-%d"),
                end_date=ref.strftime("%Y-%m-%d"),
                relative_type="weeks",
                relative_value=0,
                is_absolute=False,
                frequency_hint="周频",
            )

        # 上周
        m = _RE_LAST_WEEK.search(text)
        if m:
            # 上周一
            this_monday = ref - timedelta(days=ref.weekday())
            last_monday = this_monday - timedelta(weeks=1)
            last_sunday = this_monday - timedelta(days=1)
            return TimeRange(
                raw_text=m.group(0),
                start_date=last_monday.strftime("%Y-%m-%d"),
                end_date=last_sunday.strftime("%Y-%m-%d"),
                relative_type="weeks",
                relative_value=1,
                is_absolute=False,
                frequency_hint="周频",
            )

        # 上月
        m = _RE_LAST_MONTH.search(text)
        if m:
            # 上月第一天
            first_of_this_month = datetime(ref.year, ref.month, 1)
            last_day_prev = first_of_this_month - timedelta(days=1)
            first_of_prev = datetime(last_day_prev.year, last_day_prev.month, 1)
            return TimeRange(
                raw_text=m.group(0),
                start_date=first_of_prev.strftime("%Y-%m-%d"),
                end_date=last_day_prev.strftime("%Y-%m-%d"),
                relative_type="months",
                relative_value=1,
                is_absolute=False,
                frequency_hint="月频",
            )

        return None

    # ----------------------------------------------------------
    # 今天 / 昨天
    # ----------------------------------------------------------
    @staticmethod
    def _parse_today_yesterday(text: str, ref: datetime) -> Optional[TimeRange]:
        """解析今天/昨天"""
        m = _RE_TODAY.search(text)
        if m:
            date_str = ref.strftime("%Y-%m-%d")
            return TimeRange(
                raw_text=m.group(0),
                start_date=date_str,
                end_date=date_str,
                relative_type="days",
                relative_value=0,
                is_absolute=False,
                frequency_hint="日频",
            )

        m = _RE_YESTERDAY.search(text)
        if m:
            yesterday = ref - timedelta(days=1)
            date_str = yesterday.strftime("%Y-%m-%d")
            return TimeRange(
                raw_text=m.group(0),
                start_date=date_str,
                end_date=date_str,
                relative_type="days",
                relative_value=1,
                is_absolute=False,
                frequency_hint="日频",
            )

        return None

    # ----------------------------------------------------------
    # 多频率组合
    # ----------------------------------------------------------
    @staticmethod
    def _parse_multi_frequency(text: str) -> Optional[List[TimeRange]]:
        """解析多频率组合: "年线月线周线" → 返回频率提示列表

        当查询中包含多个频率关键词（如"年线月线周线走势"）时，
        返回 TimeRange 列表，每个元素仅包含 frequency_hint。
        """
        matches = _RE_MULTI_FREQ.findall(text)
        if len(matches) < 2:
            # 单个频率关键词不算多频率组合，交给其他解析器处理
            return None

        # 去重并保持顺序
        seen = set()
        results = []
        for freq_keyword in matches:
            freq_hint = _FREQ_LINE_MAP.get(freq_keyword)
            if freq_hint and freq_hint not in seen:
                seen.add(freq_hint)
                results.append(
                    TimeRange(
                        raw_text=freq_keyword,
                        frequency_hint=freq_hint,
                        is_absolute=False,
                    )
                )

        return results if results else None


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    test_cases = [
        # 相对时间
        "近3日外资买入额",
        "近10天主力资金流向",
        "最近30日涨跌幅",
        "过去5天融资余额",
        "近3周北向资金",
        "近6个月营收增长",
        "近1年股价表现",
        "近10年分红记录",
        "近3个交易日成交额",
        # 命名周期
        "今年以来涨跌幅",
        "年初至今收益率",
        "本季度业绩",
        "本月资金流向",
        "本周龙虎榜",
        "上周融资净买入",
        "上月机构持仓变动",
        # 当天
        "今日涨停板",
        "今天大盘行情",
        "昨日成交额",
        "昨天外资买入",
        # 绝对年份
        "2024年业绩表现",
        "2025年分红预案",
        # 季度
        "Q1财报",
        "Q2业绩",
        "一季度营收",
        "二季度利润",
        "2024年Q3机构持仓",
        # 日期区间
        "2024年1月1日至2024年6月30日的行情",
        "2024-01-01到2024-06-30的数据",
        # 多频率
        "年线月线周线走势分析",
        # 无时间表达
        "贵州茅台PE是多少",
    ]

    print("\n" + "=" * 70)
    print("TimeParser Test")
    print("=" * 70)

    for query in test_cases:
        result = TimeParser.parse(query, reference_date="2025-01-15")
        if result is None:
            print(f"\n  Query: {query}")
            print("  Result: None（未识别到时间表达式）")
        elif isinstance(result, list):
            print(f"\n  Query: {query}")
            print(f"  Result: 多频率组合 ({len(result)} 个)")
            for r in result:
                print(f"    - raw='{r.raw_text}', freq={r.frequency_hint}")
        else:
            print(f"\n  Query: {query}")
            print(
                f"  Result: raw='{result.raw_text}', "
                f"start={result.start_date}, end={result.end_date}, "
                f"type={result.relative_type}, value={result.relative_value}, "
                f"abs={result.is_absolute}, freq={result.frequency_hint}"
            )
