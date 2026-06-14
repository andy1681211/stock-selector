#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网页数据降级模块 v1.0
====================
当通达信本地数据读不到时，自动从网页抓取数据作为降级方案。

数据源选项（按优先级）:
  1. akshare（Python库，最快）
  2. Playwright 东方财富网页抓取（备用）

返回格式与 tdx_reader.KLine 兼容:
  List[KLine(date, open, high, low, close, amount, volume, pct_chg)]
"""

import os
import sys
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass


# 复刻 KLine 结构，避免循环依赖
@dataclass
class KLine:
    date: date
    open: float
    high: float
    low: float
    close: float
    amount: float
    volume: float
    pct_chg: float = 0.0


# ===== 核心函数 =====

def get_stock_klines(code: str, days: int = 250) -> Optional[List[KLine]]:
    """
    获取个股日K线数据（多源自动降级）。

    Args:
        code: 股票代码 (如 "600593")
        days: 需要多少天的数据

    Returns:
        KLine 列表（最新在最后），失败返回 None
    """
    # 源1: Sina 财经 API（最快最稳定）
    result = _from_akshare(code, days)
    if result and len(result) >= 30:
        return result

    # 源2: akshare 作为补充
    result = _from_akshare_v2(code, days)
    if result and len(result) >= 30:
        return result

    # 源3: Playwright 网页抓取（最终备用）
    result = _from_playwright(code, days)
    if result and len(result) >= 30:
        return result

    return None


def get_market_index(days: int = 250) -> Optional[List[KLine]]:
    """获取上证指数日K线"""
    return get_stock_klines("000001", days)


def _format_akshare_code(code: str) -> str:
    """转为 akshare 格式"""
    code = code.strip()
    if code.startswith(("6", "9", "5")):
        return f"sh{code}"
    elif code.startswith(("0", "3", "2")):
        return f"sz{code}"
    elif code.startswith(("4", "8")):
        return f"bj{code}"
    return code


def _from_akshare(code: str, days: int = 250) -> Optional[List[KLine]]:
    """使用 Sina 财经 API 获取数据（最稳定）"""
    try:
        import urllib.request
        import json

        symbol = _format_akshare_code(code)
        # Sina 日K线API
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
            f"/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=5&datalen={days}"
        )

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("gbk")

        records = json.loads(raw)
        if not records:
            return None

        klines = []
        for r in records:
            d = r.get("day", "")
            if not d:
                continue
            try:
                dt = datetime.strptime(d[:10], "%Y-%m-%d").date()
                open_p = float(r.get("open", 0))
                high = float(r.get("high", 0))
                low = float(r.get("low", 0))
                close = float(r.get("close", 0))
                volume = float(r.get("volume", 0))
                # 估算成交额和涨跌幅
                amount = volume * (open_p + close) / 2
                pct = (close - open_p) / open_p * 100 if open_p else 0.0

                klines.append(KLine(
                    date=dt, open=open_p, high=high, low=low,
                    close=close, amount=amount, volume=volume,
                    pct_chg=pct,
                ))
            except (ValueError, KeyError):
                continue

        return klines if len(klines) >= 20 else None

    except Exception as e:
        print(f"  [降级:sina] {code}: {e}")
        return None


def _from_akshare_v2(code: str, days: int = 250) -> Optional[List[KLine]]:
    """使用 akshare 的实时行情接口（补充数据）"""
    try:
        import urllib.request
        import json

        symbol = _format_akshare_code(code)
        url = (
            f"https://web.sqt.gtimg.cn/q={symbol}"
        )
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("gbk")

        # Tencent format: v_sh600593="1~name~code~...~open~...~high~...~low~...~close~..."
        if "~" not in raw:
            return None

        # For daily klines, use the Sina API for best results
        # Tencent real-time only gives current day
        return None

    except Exception as e:
        print(f"  [降级:akshare_v2] {code}: {e}")
        return None


def _from_playwright(code: str, days: int = 250) -> Optional[List[KLine]]:
    """使用 Playwright 打开东方财富页面抓取数据"""
    try:
        os.environ["no_proxy"] = "*"
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    em_code = _format_akshare_code(code)
    # 东方财富K线API接口（JSON数据，不需要渲染）
    api_url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&ut=7eea3edcaed734bea9cbfc24409ed989"
        f"&klt=101&fqt=1"
        f"&secid=1.{em_code}"
        f"&beg=20250101&end=20500101"
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox"]
            )
            context = browser.new_context()
            page = context.new_page()

            page.goto(api_url, wait_until="domcontentloaded", timeout=15000)
            content = page.evaluate("() => document.body.innerText")
            context.close()
            browser.close()

        if not content:
            return None

        import json
        data = json.loads(content)
        raw = data.get("data", {})
        klines_raw = raw.get("klines", [])

        if not klines_raw:
            return None

        klines = []
        for line in klines_raw[-days:]:
            parts = line.split(",")
            if len(parts) < 8:
                continue
            try:
                d = datetime.strptime(parts[0][:10], "%Y-%m-%d").date()
                klines.append(KLine(
                    date=d,
                    open=float(parts[1]),
                    close=float(parts[2]),
                    high=float(parts[3]),
                    low=float(parts[4]),
                    volume=float(parts[5]),
                    amount=float(parts[6]),
                    pct_chg=float(parts[7]),
                ))
            except (ValueError, IndexError):
                continue

        return klines if len(klines) >= 20 else None

    except Exception as e:
        print(f"  [降级:playwright] {code}: {e}")
        return None


# ===== 板块内股票列表降级 =====

def get_sector_stocks_from_web(sector_name: str) -> List[str]:
    """
    从网页获取某板块的所有股票代码（当通达信板块文件读不到时）。
    使用东方财富板块成分股API。
    """
    os.environ["no_proxy"] = "*"
    try:
        import akshare as ak
        # 东方财富行业板块
        df = ak.stock_board_industry_cons_em(sector_name)
        if df is not None and len(df) > 0:
            codes = []
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                # 统一格式：去掉前缀字母
                code = code.replace("SH", "").replace("SZ", "").replace("BJ", "")
                codes.append(code)
            return codes
    except Exception as e:
        print(f"  [降级:板块] {sector_name}: {e}")

    return []


def get_all_stock_codes() -> List[str]:
    """获取全市场股票代码列表"""
    os.environ["no_proxy"] = "*"
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is not None and "代码" in df.columns:
            codes = []
            for _, row in df.iterrows():
                code = str(row["代码"]).strip()
                # 过滤创业板、科创板、北交所
                if code.startswith(("300", "301", "688", "689", "4", "8", "9")):
                    continue
                codes.append(code)
            return codes
    except Exception as e:
        print(f"  [降级:全市场] {e}")

    return []


# ===== 集成到 local_screener 的补丁 =====

def patch_tdx_reader():
    """
    猴子补丁：替换 tdx_reader.parse_day_file 为带降级版本的函数。
    在 local_screener 导入前调用。
    """
    import tdx_reader as tdx

    original_parse = tdx.parse_day_file

    def patched_parse(filepath: str, max_records: int = 0) -> List:
        """带降级的 parse_day_file"""
        # 先尝试原始方法
        result = original_parse(filepath, max_records)
        if result and len(result) >= 20:
            return result

        # 降级：从文件名提取股票代码
        fname = os.path.basename(filepath)
        code = fname.replace(".day", "")
        # 去掉市场前缀 (sh/sz/bj)
        if code.startswith(("sh", "sz", "bj")):
            code = code[2:]

        print(f"  [降级] 通达信数据不足，尝试网页获取 {code}...")
        web_klines = get_stock_klines(code)
        if web_klines and len(web_klines) >= 20:
            if max_records > 0:
                web_klines = web_klines[-max_records:]
            return web_klines

        return result  # 返回原始结果（可能为空）

    tdx.parse_day_file = patched_parse
    return True


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="网页数据降级工具")
    ap.add_argument("code", help="股票代码")
    args = ap.parse_args()

    klines = get_stock_klines(args.code)
    if klines:
        print(f"✅ 获取到 {len(klines)} 条K线")
        print(f"   最新: {klines[-1].date} 收盘:{klines[-1].close} 涨幅:{klines[-1].pct_chg:+.2f}%")
        print(f"   开盘:{klines[-1].open} 最高:{klines[-1].high} 最低:{klines[-1].low}")
        print(f"   量:{klines[-1].volume} 额:{klines[-1].amount}")
    else:
        print(f"❌ 获取失败")
