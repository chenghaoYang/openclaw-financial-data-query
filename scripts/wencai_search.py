#!/usr/bin/env python3
"""
问财综合搜索接口封装
提供金融领域的多渠道搜索能力，增强SQL查询的上下文信息

支持的搜索渠道:
- news: 财经新闻
- announcement: 上市公司公告
- report: 研究报告
- web: 通用网页搜索
- baidu/bing: 指定搜索引擎
- yike: 易客知识社区
- teleconference: 电话会议
"""

import sys
import json
import asyncio
import argparse
from typing import Dict, List, Optional, Any
from datetime import datetime
from itertools import zip_longest
from pathlib import Path
import uuid

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# 导入公共HTTP客户端
from common_clients import SimpleBaseClient


# ============================================================================
# 搜索客户端
# ============================================================================
class WencaiSearchClient:
    """问财综合搜索客户端"""

    # 默认搜索服务器地址
    DEFAULT_HOST = "http://iwc-index-mobilesearch.wencai"
    SEARCH_ENDPOINT = "/comprehensive/search"

    # 支持的搜索渠道
    CHANNELS = {
        'news': '财经新闻',
        'announcement': '上市公司公告',
        'report': '研究报告',
        'web': '通用网页搜索',
        'baidu': '百度搜索(仅国内)',
        'bing': 'Bing搜索(仅国内)',
        'web_en': '国际网页搜索',
        'knowledge': '百科接口(站外百科和yike) → 实际返回baike',
        'yike': '百科接口(yike) → 实际返回baike',
        'news_en': '海外资讯',
        'interact': '董秘问答 ⭐有stock_infos',
        'community': '社区观点 → 实际返回news',
        'app_function': '功能页',
        'teleconference': '电话会议 → 实际返回us_teleconference(主要美股)',
        'en_paper': '英文论文'
    }

    # 预设搜索方案（基于实际测试优化）
    PRESETS = {
        'event': ['news', 'announcement', 'report'],  # 事件驱动查询
        'company': ['announcement', 'report', 'interact'],  # 公司分析（含董秘问答）
        'market': ['news', 'report', 'web'],  # 市场分析
        'policy': ['news', 'announcement', 'web'],  # 政策影响
        'research': ['report', 'knowledge', 'interact'],  # 深度研究（去除美股teleconference）
        'quick': ['news', 'report'],  # 快速查询
        'comprehensive': ['news', 'announcement', 'report', 'interact', 'web']  # 全面搜索
    }

    def __init__(self, base_url: Optional[str] = None, timeout: float = 60.0):
        """初始化搜索客户端

        Args:
            base_url: 搜索服务器地址，默认使用内网地址
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url or self.DEFAULT_HOST
        self.client = SimpleBaseClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"X-Arsenal-Auth": "claudable"}
        )

    async def search(
        self,
        query: str,
        channels: Optional[List[str]] = None,
        preset: Optional[str] = None,
        app_id: str = "cbas-financial_analysis",
        size: int = 10,
        offset: int = 0,
        need_content: bool = False,
        need_feature: bool = False,
        output: str = "block",
        time_start: Optional[int] = None,
        time_end: Optional[int] = None,
        stock_code: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """执行综合搜索

        Args:
            query: 搜索关键词
            channels: 搜索渠道列表，如 ['news', 'report']
            preset: 预设方案名称，如 'event', 'company'等（与channels二选一）
            app_id: 应用标识
            size: 返回结果数量（默认10，最大20）
            offset: 结果偏移量，用于分页
            need_content: 是否返回完整内容（默认False，仅返回摘要）
            need_feature: 是否返回特征信息
            output: 输出格式（block/doc）
            time_start: 时间范围-开始时间戳（毫秒）
            time_end: 时间范围-结束时间戳（毫秒）
            stock_code: 股票代码过滤
            **kwargs: 其他高级参数

        Returns:
            搜索结果字典
        """
        # 确定使用的channels
        if preset:
            if preset not in self.PRESETS:
                raise ValueError(f"未知的预设方案: {preset}，支持的方案: {list(self.PRESETS.keys())}")
            channels = self.PRESETS[preset]
        elif not channels:
            channels = ['news', 'report']  # 默认搜索新闻和研报

        # 验证channels
        invalid_channels = [ch for ch in channels if ch not in self.CHANNELS]
        if invalid_channels:
            raise ValueError(f"不支持的搜索渠道: {invalid_channels}，支持的渠道: {list(self.CHANNELS.keys())}")

        # 构建请求参数
        request_data = {
            "query": query,
            "channels": channels,
            "app_id": app_id,
            "qid": str(uuid.uuid4()),  # 生成唯一请求ID
            "output": output,
            "size": min(size, 20),  # 限制最大20条
            "offset": offset,
            "need_content": str(need_content).lower(),
            "need_feature": str(need_feature).lower()
        }

        # 添加可选参数
        slots = []
        if time_start is not None or time_end is not None:
            time_slot = {"type": "time"}
            if time_start is not None:
                time_slot["time_start"] = time_start
            if time_end is not None:
                time_slot["time_end"] = time_end
            slots.append(time_slot)
        if stock_code:
            slots.append({"type": "stock", "code": stock_code})
        if slots:
            request_data["slots"] = slots

        # 合并额外参数
        request_data.update(kwargs)

        try:
            # 发送请求
            result = await self.client.post(
                self.SEARCH_ENDPOINT,
                json=request_data,
                headers={"Content-Type": "application/json"}
            )

            # 检查HTTP响应状态
            if result['status'] != 200:
                return {
                    "success": False,
                    "error": f"HTTP {result['status']}",
                    "message": result.get('body', '请求失败')
                }

            # 解析响应
            response_data = result.get('json', {})

            # 检查业务状态码
            status_code = response_data.get('status_code', -1)
            if status_code != 0:
                return {
                    "success": False,
                    "error": f"API错误 {status_code}",
                    "message": response_data.get('status_msg', '请求失败')
                }

            # 标准化返回格式
            return {
                "success": True,
                "query": query,
                "channels": channels,
                "total_count": response_data.get('total', 0),
                "results": self._parse_results(response_data),
                "took": response_data.get('took', 0),
                "raw_response": response_data
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"搜索请求失败: {str(e)}"
            }

    def _parse_results(self, response_data: Dict) -> List[Dict]:
        """解析搜索结果"""
        # data字段是一个数组，包含所有channel的结果
        data = response_data.get('data', [])
        if not isinstance(data, list):
            return []
        return [self._parse_item(item) for item in data]

    def _parse_item(self, item: Dict) -> Dict:
        """解析单个搜索结果项"""
        # 提取extra中的信息
        extra = item.get('extra', {})

        parsed = {
            "channel": item.get('channel', ''),
            "title": item.get('title', ''),
            "summary": item.get('summary', ''),
            "url": item.get('url', ''),
            "source": extra.get('publish_source', '') or extra.get('real_publish_source', ''),
            "publish_time": item.get('publish_time', 0),
            "publish_date": item.get('publish_date', ''),
            "score": item.get('score', 0),
        }

        # 提取股票相关信息（核心字段）
        stock_infos = item.get('stock_infos', [])
        if stock_infos:
            parsed['stock_codes'] = [s.get('code', '') for s in stock_infos if s.get('code')]
            parsed['stock_names'] = [s.get('name', '') for s in stock_infos if s.get('name')]

        # Report渠道：机构和作者（辅助判断研报质量）
        if item.get('channel') == 'report':
            if extra.get('organization'):
                parsed['organization'] = extra['organization']
            if extra.get('author'):
                parsed['author'] = extra['author']

        # 保留原始数据
        parsed['raw'] = item

        return parsed

    async def close(self):
        """关闭客户端连接"""
        await self.client.close()


# ============================================================================
# 命令行接口
# ============================================================================
async def main_async():
    """异步主函数"""
    parser = argparse.ArgumentParser(
        description='问财综合搜索工具 - 金融数据查询增强',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
搜索渠道说明:
{chr(10).join(f"  {k:15s} - {v}" for k, v in WencaiSearchClient.CHANNELS.items())}

预设方案:
{chr(10).join(f"  {k:15s} - {', '.join(v)}" for k, v in WencaiSearchClient.PRESETS.items())}

示例:
  # 使用预设方案搜索
  python wencai_search.py --query "浙金中心暴雷" --preset event

  # 指定搜索渠道
  python wencai_search.py --query "贵州茅台" --channels news report

  # 时间范围搜索
  python wencai_search.py --query "新能源政策" --preset policy --days 7

  # 公司相关搜索
  python wencai_search.py --query "财报分析" --stock-code "600519.SH" --preset company
        """
    )

    # 基础参数
    parser.add_argument('--query', '-q', required=True, help='搜索关键词')

    # 渠道选择（二选一）
    channel_group = parser.add_mutually_exclusive_group()
    channel_group.add_argument('--channels', '-c', nargs='+',
                              help='搜索渠道列表（如: news report announcement）')
    channel_group.add_argument('--preset', '-p',
                              choices=list(WencaiSearchClient.PRESETS.keys()),
                              help='预设搜索方案')

    # 结果参数
    parser.add_argument('--size', '-s', type=int, default=10,
                       help='返回结果数量（默认10，最大20）')
    parser.add_argument('--offset', '-o', type=int, default=0,
                       help='结果偏移量（用于分页）')
    parser.add_argument('--content', action='store_true',
                       help='返回完整内容（默认仅返回摘要）')

    # 过滤参数
    parser.add_argument('--days', '-d', type=int,
                       help='搜索最近N天的内容')
    parser.add_argument('--stock-code',
                       help='按股票代码过滤（如：600519.SH）')

    # 输出参数
    parser.add_argument('--format', choices=['json', 'pretty', 'simple'],
                       default='pretty',
                       help='输出格式')
    parser.add_argument('--output-file', '-f',
                       help='保存结果到文件')

    # 服务配置
    parser.add_argument('--host', help='搜索服务器地址（默认使用内网地址）')
    parser.add_argument('--timeout', type=float, default=60.0,
                       help='请求超时时间（秒）')

    args = parser.parse_args()

    # 计算时间范围
    time_start = None
    time_end = None
    if args.days:
        now_ts = datetime.now().timestamp()
        time_end = int(now_ts * 1000)
        time_start = int((now_ts - args.days * 86400) * 1000)

    # 创建客户端
    client = WencaiSearchClient(base_url=args.host, timeout=args.timeout)

    try:
        # 执行搜索
        print(f"正在搜索: {args.query}")
        if args.preset:
            print(f"使用预设方案: {args.preset} ({', '.join(WencaiSearchClient.PRESETS[args.preset])})")
        elif args.channels:
            print(f"搜索渠道: {', '.join(args.channels)}")

        result = await client.search(
            query=args.query,
            channels=args.channels,
            preset=args.preset,
            size=args.size,
            offset=args.offset,
            need_content=args.content,
            time_start=time_start,
            time_end=time_end,
            stock_code=args.stock_code
        )

        # 格式化输出
        if args.format == 'json':
            output_text = json.dumps(result, ensure_ascii=False, indent=2)
        elif args.format == 'simple':
            output_text = format_simple(result)
        else:  # pretty
            output_text = format_pretty(result)

        # 输出结果
        if args.output_file:
            with open(args.output_file, 'w', encoding='utf-8') as f:
                f.write(output_text)
            print(f"\n结果已保存到: {args.output_file}")
        else:
            print(output_text)

        # 返回状态码
        return 0 if result['success'] else 1

    except Exception as e:
        print(f"错误: {str(e)}", file=sys.stderr)
        return 1
    finally:
        await client.close()


def format_pretty(result: Dict) -> str:
    """格式化为易读输出"""
    if not result['success']:
        return f"\n❌ 搜索失败: {result.get('message', result.get('error'))}\n"

    lines = [
        "\n" + "="*80,
        f"搜索关键词: {result['query']}",
        f"搜索渠道: {', '.join(result['channels'])}",
        f"结果数量: {result['total_count']} | 耗时: {result.get('took', 0)}ms",
        "="*80 + "\n"
    ]

    for i, item in enumerate(result['results'], 1):
        lines.append(f"{i}. [{item['channel'].upper()}] {item['title']}")

        # 来源和时间
        source_line = f"   来源: {item['source']} | 时间: {item['publish_date']} | 得分: {item['score']}"

        # Report渠道显示机构和作者
        if item['channel'] == 'report':
            if item.get('organization'):
                source_line += f" | 机构: {item['organization']}"
            if item.get('author'):
                source_line += f" | 作者: {item['author']}"

        lines.append(source_line)

        # 摘要
        if item['summary']:
            summary = item['summary']
            summary_display = summary[:200] + ("..." if len(summary) > 200 else "")
            lines.append(f"   摘要: {summary_display}")

        # 相关股票
        if item.get('stock_codes'):
            stocks_display = ', '.join(f"{name}({code})"
                                      for name, code in zip_longest(item.get('stock_names', []), item['stock_codes'], fillvalue='--'))
            lines.append(f"   相关股票: {stocks_display}")

        # URL
        if item['url']:
            lines.append(f"   链接: {item['url']}")

        lines.append("")

    return "\n".join(lines)


def format_simple(result: Dict) -> str:
    """格式化为简洁输出（用于Claude处理）"""
    if not result['success']:
        return f"搜索失败: {result.get('message', result.get('error'))}"

    lines = [f"查询: {result['query']} | 结果数: {result['total_count']} | 耗时: {result.get('took', 0)}ms"]
    lines.append("")

    for item in result['results']:
        # 标题行
        title_line = f"• [{item['channel']}] {item['title']}"
        lines.append(title_line)

        # 来源和时间
        meta_line = f"  来源: {item['source']} | {item['publish_date']}"
        if item['channel'] == 'report' and item.get('organization'):
            meta_line += f" | {item['organization']}"
        lines.append(meta_line)

        # 摘要
        if item['summary']:
            summary = item['summary'][:150].replace('\n', ' ')
            lines.append(f"  {summary}" + ("..." if len(item['summary']) > 150 else ""))

        # 股票信息
        if item.get('stock_codes'):
            stocks_display = ', '.join(f"{name}({code})"
                                      for name, code in zip_longest(item.get('stock_names', []), item['stock_codes'], fillvalue='--'))
            lines.append(f"  股票: {stocks_display}")

        lines.append("")

    return "\n".join(lines)


def main():
    """同步入口"""
    return asyncio.run(main_async())


if __name__ == '__main__':
    sys.exit(main())
