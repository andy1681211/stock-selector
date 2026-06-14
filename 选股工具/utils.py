"""
短线选股策略系统 - 工具函数模块
"""

import csv
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


def safe_filename(s: str, max_len: int = 80) -> str:
    """将字符串转为安全文件名（去除非法字符）"""
    s = re.sub(r'[<>:"/\\|?*]', "_", s)
    s = s.strip().replace(" ", "_")[:max_len]
    return s or "output"


def write_csv(filepath: Path, rows: List[Dict[str, str]]) -> None:
    """写入CSV文件（UTF-8 BOM，兼容Excel）"""
    if not rows:
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_csv(filepath: Path) -> List[Dict[str, str]]:
    """读取CSV文件"""
    if not filepath.exists():
        return []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def get_timestamp() -> str:
    """获取时间戳"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def get_date_str() -> str:
    """获取日期字符串"""
    return datetime.now().strftime("%Y-%m-%d")


def dedup_by_code(rows: List[Dict[str, str]],
                  key: str = "代码") -> List[Dict[str, str]]:
    """按股票代码去重，保留首次出现"""
    seen = set()
    result = []
    for row in rows:
        code = row.get(key, "")
        if code and code not in seen:
            seen.add(code)
            result.append(row)
    return result


def find_field(row: Dict[str, str], *patterns: str) -> str:
    """
    模糊查找字段名（兼容API返回的动态含日期字段名）
    示例: find_field(row, '涨跌幅', 'CHG') 会匹配 '涨跌幅(%) 2026.05.29'
    """
    for pattern in patterns:
        for key in row:
            if pattern in key:
                val = row.get(key, "")
                return val if val is not None else ""
    return ""


def normalize_row(row: Dict[str, str]) -> Dict[str, str]:
    """
    将API返回的动态字段名统一为标准字段名
    """
    return {
        "代码": row.get("代码", find_field(row, "代码")),
        "名称": row.get("名称", find_field(row, "名称", "简称")),
        "最新价": find_field(row, "最新价"),
        "涨跌幅": find_field(row, "涨跌幅", "CHG"),
        "换手率": find_field(row, "换手率"),
        "量比": find_field(row, "量比"),
        "总市值": find_field(row, "总市值"),
        "流通市值": find_field(row, "流通市值"),
        "市盈率": find_field(row, "市盈率"),
        "市净率": find_field(row, "市净率"),
        "成交额": find_field(row, "成交额"),
        "涨停": find_field(row, "涨停"),
    }


def filter_st_stocks(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """过滤掉ST/*ST股票"""
    result = []
    for row in rows:
        name = row.get("名称", find_field(row, "名称", "简称"))
        if name.startswith("*ST") or name.startswith("ST"):
            continue
        result.append(row)
    return result
