#!/usr/bin/env python3
"""
金融数据SQL执行工具 - 独立脚本版本
可直接运行的Python脚本，无需MCP服务器

使用方法:
    python fin_sql_executor.py --action preview --sql "SELECT * FROM table"
    python fin_sql_executor.py --action download --sql "SELECT * FROM table" --project-path /path/to/project
"""
import os
import sys
import io
import csv
import argparse
import asyncio
import json
from typing import Any, Dict
from datetime import datetime
from pathlib import Path

# Windows 兼容：设置控制台输出编码为 UTF-8
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# 导入公共客户端类
from common_clients import SimpleSettings, SimpleBaseClient

# 全局配置实例
settings = SimpleSettings()
INTERNAL_SQL_ENDPOINT = "/bfe/internalSqlRun"


# ============================================================================
# 工具函数
# ============================================================================
def _format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes == 0:
        return "0B"
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.2f}{size_names[i]}"


def _build_sql_files_payload(sql: str) -> Dict[str, Any]:
    """构建 SQL 执行接口所需的 multipart payload。"""
    return {
        "sql": (None, sql),
        "env": (None, "prod"),
    }


async def _execute_fin_sql(
    sql: str,
    *,
    failure_message: str,
    exception_message: str,
) -> Dict[str, Any]:
    """统一执行 SQL 并返回标准化响应，减少 preview/download 重复代码。"""
    client = SimpleBaseClient(base_url=settings.fin_sql_container_host)
    try:
        response = await client.post(
            INTERNAL_SQL_ENDPOINT, files=_build_sql_files_payload(sql)
        )

        status = response.get("status")
        if status != 200:
            return {
                "success": False,
                "message": failure_message,
                "error": f"HTTP {status}: {response.get('body', 'Unknown error')}",
            }

        result = response.get("json")
        if not isinstance(result, dict):
            return {
                "success": False,
                "message": failure_message,
                "error": "服务器返回非JSON格式数据",
            }

        if result.get("status_code") != 0:
            return {
                "success": False,
                "message": failure_message,
                "error": result.get("status_msg", "Unknown error"),
            }

        data_section = result.get("data")
        if not isinstance(data_section, dict):
            data_section = {}

        return {
            "success": True,
            "data": result,
            "data_section": data_section,
        }
    except Exception as e:
        return {
            "success": False,
            "message": exception_message,
            "error": str(e),
        }
    finally:
        await client.close()


# ============================================================================
# SQL执行功能函数
# ============================================================================
async def preview_fin_sql_result(sql: str) -> Dict[str, Any]:
    """
    预览金融数据SQL查询结果

    Args:
        sql: 要执行的SQL语句

    Returns:
        包含预览结果信息的字典
    """
    execution = await _execute_fin_sql(
        sql,
        failure_message="金融数据预览执行失败",
        exception_message="金融数据预览执行异常",
    )
    if not execution.get("success"):
        return execution

    result = execution["data"]
    data_section = execution["data_section"]
    title_list = data_section.get("title", [])
    body_list = data_section.get("body", [])
    total = data_section.get("total", 0)

    return {
        "success": True,
        "message": "金融数据预览执行成功",
        "total_rows": total,
        "columns_count": len(title_list),
        "preview_rows": len(body_list),
        "data": result,
    }


async def download_fin_sql_result(sql: str, project_path: str) -> Dict[str, Any]:
    """
    执行金融数据SQL查询并下载结果为CSV文件到本地

    Args:
        sql: 要执行的SQL语句
        project_path: 项目路径

    Returns:
        包含执行结果信息的字典
    """
    if not project_path:
        return {"success": False, "message": "project_path 不能为空"}

    file_path = os.path.join(project_path, "data_file", "intermediate")

    print("开始执行查询...")
    execution = await _execute_fin_sql(
        sql,
        failure_message="金融数据查询执行失败",
        exception_message="金融数据查询执行异常",
    )
    if not execution.get("success"):
        return execution

    data_section = execution["data_section"]
    title_list = data_section.get("title", [])
    body_list = data_section.get("body", [])
    total = data_section.get("total", 0)

    if not title_list:
        return {
            "success": False,
            "message": "金融数据查询执行失败",
            "error": "响应数据中没有列定义(title)",
        }

    # 生成文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"fin_query_result_{timestamp}.csv"
    full_path = os.path.join(file_path, filename)

    # 确保目录存在
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # 提取列名
    column_names = [col.get("name", f"column_{i}") for i, col in enumerate(title_list)]

    # 写入CSV文件
    with open(full_path, "w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(column_names)
        for row in body_list:
            writer.writerow(row)
    file_size = os.path.getsize(full_path)

    print(f"文件下载完成: {full_path}")
    print(f"文件大小: {_format_size(file_size)}")
    print(f"总行数: {total}")

    return {
        "success": True,
        "message": "金融数据查询执行成功！",
        "file_path": full_path,
        "total_rows": total,
        "file_size": _format_size(file_size),
    }


# ============================================================================
# 命令行接口
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description='金融数据SQL执行工具 - 独立脚本版本')
    parser.add_argument('--action', required=True,
                       choices=['preview', 'download'],
                       help='执行的操作: preview(预览) 或 download(下载)')
    parser.add_argument('--sql', required=True,
                       help='SQL语句')
    parser.add_argument('--project-path',
                       help='项目路径 (download操作必需)')

    args = parser.parse_args()

    # 根据不同的action执行对应的操作
    async def run():
        if args.action == 'preview':
            result = await preview_fin_sql_result(args.sql)

        elif args.action == 'download':
            if not args.project_path:
                print("错误: download操作需要 --project-path 参数")
                sys.exit(1)
            result = await download_fin_sql_result(args.sql, args.project_path)

        else:
            print(f"错误: 未知的操作 '{args.action}'")
            sys.exit(1)

        # 打印结果
        print("\n" + "="*60)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("="*60 + "\n")

        # 根据结果设置退出码
        sys.exit(0 if result.get('success') else 1)

    # 运行异步函数
    asyncio.run(run())


if __name__ == "__main__":
    main()
