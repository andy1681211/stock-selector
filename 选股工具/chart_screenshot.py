#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
走势图截图模块 v1.0
==================
使用 Playwright 对选出的重点股自动截图 K 线图/分时图。

数据源:
  - 东方财富个股页面 (https://quote.eastmoney.com/)
  - 同花顺个股页面 (https://stockpage.10jqka.com.cn/)
  - 备用: akshare + matplotlib 本地生成

用法:
  from chart_screenshot import screenshot_stock_chart
  screenshot_stock_chart("600593", "大连圣亚")
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional

TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"
CHART_DIR = OUTPUT_DIR / "charts"
CHART_DIR.mkdir(parents=True, exist_ok=True)

# ===== 股票代码转换 =====

def _format_code(code: str) -> tuple:
    """
    将股票代码转为东方财富/同花顺格式。
    返回 (eastmoney_code, page_title)
    """
    code = code.strip()
    if code.startswith(("6", "9", "5")):
        return f"sh{code}", f"SH{code}"
    elif code.startswith(("0", "3", "2")):
        return f"sz{code}", f"SZ{code}"
    elif code.startswith(("4", "8")):
        return f"bj{code}", f"BJ{code}"
    return code, code


# ===== Playwright 截图 =====

def screenshot_stock_chart(code: str, name: str = "",
                           source: str = "eastmoney") -> Optional[str]:
    """
    使用 Playwright 截图个股 K 线图。

    Args:
        code: 股票代码 (如 "600593")
        name: 股票名称 (用于文件名)
        source: 数据源 ("eastmoney" 或 "10jqka")

    Returns:
        截图文件路径，失败返回 None
    """
    em_code, _ = _format_code(code)
    name_safe = name or code

    if source == "eastmoney":
        url = f"https://quote.eastmoney.com/{em_code}.html"
        chart_selector = "#mainChart"  # K线图区域
    elif source == "10jqka":
        url = f"https://stockpage.10jqka.com.cn/{code}/"
        chart_selector = ".chart-container"
    else:
        return None

    # 构建输出路径
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = CHART_DIR / f"{code}_{name_safe}_{ts}.png"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _fallback_chart(code, name)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()
            # 使用 domcontentloaded 避免 networkidle 超时
            page.goto(url, wait_until="domcontentloaded", timeout=20000)

            # 等待图表加载
            try:
                page.wait_for_selector(chart_selector, timeout=8000)
            except Exception:
                pass

            # 让图表渲染完毕
            page.wait_for_timeout(4000)

            # 截图
            try:
                chart = page.query_selector(chart_selector)
                if chart:
                    chart.screenshot(path=str(out_path))
                else:
                    page.screenshot(path=str(out_path), full_page=True)
            except Exception:
                page.screenshot(path=str(out_path), full_page=True)

            context.close()
            browser.close()

        if out_path.exists() and out_path.stat().st_size > 1000:
            print(f"  [截图] {code} {name} -> {out_path.name}")
            return str(out_path)
        else:
            return _fallback_chart(code, name)

    except Exception as e:
        print(f"  [截图] {code} {name} Playwright 失败: {e}")
        return _fallback_chart(code, name)


def screenshot_top_stocks(results: List[dict], max_stocks: int = 5) -> List[str]:
    """
    为选股结果中排名靠前的股票截图。

    Args:
        results: 选股结果列表
        max_stocks: 最多截图几只

    Returns:
        截图文件路径列表
    """
    paths = []
    for r in results[:max_stocks]:
        code = r.get("代码", "")
        name = r.get("名称", "")
        if not code:
            continue
        path = screenshot_stock_chart(code, name)
        if path:
            paths.append(path)
    return paths


def screenshot_batch(codes_with_names: List[tuple]) -> List[str]:
    """批量截图"""
    paths = []
    for code, name in codes_with_names:
        path = screenshot_stock_chart(code, name)
        if path:
            paths.append(path)
    return paths


# ===== 本地备用生成 =====

def _fallback_chart(code: str, name: str = "") -> Optional[str]:
    """
    备用方案: 使用 akshare 获取数据 + matplotlib 本地生成 K 线图。
    当 Playwright 截图失败时自动降级。
    """
    name_safe = name or code
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = CHART_DIR / f"{code}_{name_safe}_{ts}_local.png"

    try:
        import akshare as ak
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import matplotlib.ticker as mticker
        from matplotlib.patches import FancyBboxPatch
        import numpy as np
        import pandas as pd
        # 绕过代理
        os.environ["no_proxy"] = "*"
    except ImportError:
        return None

    try:
        # 判断市场
        if code.startswith(("6", "9", "5")):
            symbol = f"sh{code}"
        elif code.startswith(("0", "3", "2")):
            symbol = f"sz{code}"
        elif code.startswith(("4", "8")):
            symbol = f"bj{code}"
        else:
            symbol = code

        df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                start_date="20250101", adjust="qfq")
        if df is None or len(df) < 30:
            return None

        # 按日期排序
        df.sort_values("日期", inplace=True)
        df.reset_index(drop=True, inplace=True)

        # 计算均线
        closes = df["收盘"].values
        df["MA5"] = pd.Series(closes).rolling(5).mean().values
        df["MA10"] = pd.Series(closes).rolling(10).mean().values
        df["MA20"] = pd.Series(closes).rolling(20).mean().values
        df["MA60"] = pd.Series(closes).rolling(60).mean().values

        # 计算成交量缩放
        volumes = df["成交量"].values
        vol_scaled = volumes / volumes.max() * max(closes[-60:]) * 0.3

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7),
                                        gridspec_kw={"height_ratios": [3, 1]},
                                        sharex=True)
        fig.patch.set_facecolor("#1a1a2e")
        fig.suptitle(f"{code} {name_safe} 日K线", color="white", fontsize=14, fontweight="bold")

        for ax in [ax1, ax2]:
            ax.set_facecolor("#16213e")
            ax.tick_params(colors="#cccccc")
            ax.spines["bottom"].set_color("#333355")
            ax.spines["top"].set_color("#333355")
            ax.spines["left"].set_color("#333355")
            ax.spines["right"].set_color("#333355")
            ax.grid(True, alpha=0.15, color="#6666aa")

        dates = df["日期"].values
        x = np.arange(len(df))

        # ---- K线图 ----
        # 阳线/阴线
        opens = df["开盘"].values
        highs = df["最高"].values
        lows = df["最低"].values

        green = "#00c853"
        red = "#ff1744"

        for i in range(len(df)):
            color = green if closes[i] >= opens[i] else red
            ax1.vlines(x[i], lows[i], highs[i], color=color, linewidth=0.8)
            if closes[i] >= opens[i]:
                rect = plt.Rectangle((x[i] - 0.25, opens[i]), 0.5,
                                     closes[i] - opens[i], color=color, alpha=0.9)
            else:
                rect = plt.Rectangle((x[i] - 0.25, closes[i]), 0.5,
                                     opens[i] - closes[i], color=color, alpha=0.9)
            ax1.add_patch(rect)

        # 均线
        for ma, label, color in [
            (df["MA5"].values, "MA5", "#ffd600"),
            (df["MA10"].values, "MA10", "#00e5ff"),
            (df["MA20"].values, "MA20", "#d500f9"),
            (df["MA60"].values, "MA60", "#ff9100"),
        ]:
            valid = ~np.isnan(ma)
            ax1.plot(x[valid], ma[valid], label=label, color=color,
                     linewidth=1.2, alpha=0.8)

        ax1.legend(loc="upper left", facecolor="#1a1a2e", edgecolor="#333355",
                   labelcolor="#cccccc", fontsize=9)
        ax1.set_ylabel("价格", color="#cccccc", fontsize=10)

        # ---- 成交量 ----
        for i in range(len(df)):
            color = green if closes[i] >= opens[i] else red
            ax2.bar(x[i], vol_scaled[i], width=0.6, color=color, alpha=0.6)

        # 成交量均线
        vol_ma5 = pd.Series(vol_scaled).rolling(5).mean().values
        ax2.plot(x, vol_ma5, color="#ffd600", linewidth=1, alpha=0.8,
                 label="VOL5")
        ax2.legend(loc="upper left", facecolor="#1a1a2e", edgecolor="#333355",
                   labelcolor="#cccccc", fontsize=9)
        ax2.set_ylabel("成交量", color="#cccccc", fontsize=10)

        # X轴标签
        step = max(1, len(df) // 8)
        tick_positions = x[::step]
        tick_labels = [str(d)[:10] for d in dates[::step]]
        ax2.set_xticks(tick_positions)
        ax2.set_xticklabels(tick_labels, rotation=30, ha="right",
                            color="#cccccc", fontsize=8)

        plt.tight_layout()
        fig.savefig(str(out_path), dpi=150, bbox_inches="tight",
                    facecolor="#1a1a2e")
        plt.close()

        if out_path.exists() and out_path.stat().st_size > 1000:
            print(f"  [图表] {code} {name} -> {out_path.name}")
            return str(out_path)

    except Exception as e:
        print(f"  [图表] {code} 本地生成失败: {e}")

    return None


# ===== 报告嵌入 =====

def append_chart_report(report: str, chart_paths: List[str]) -> str:
    """
    将截图信息追加到报告中。
    Playwright截图实际是图片文件，报告文本中注明文件路径。
    """
    if not chart_paths:
        return report

    lines = ["\n【走势截图】", ""]
    for p in chart_paths:
        fname = Path(p).name
        # 提取代码和名称
        parts = fname.split("_")
        if len(parts) >= 2:
            code = parts[0]
            name = parts[1] if len(parts) > 1 else ""
            lines.append(f"  {code} {name}: {p}")
        else:
            lines.append(f"  {p}")

    return report + "\n".join(lines)


if __name__ == "__main__":
    # 命令行模式
    import argparse
    ap = argparse.ArgumentParser(description="走势图截图工具")
    ap.add_argument("codes", nargs="+", help="股票代码 (如 600593)")
    ap.add_argument("--names", nargs="*", default=[], help="股票名称")
    args = ap.parse_args()

    names = args.names or [""] * len(args.codes)
    for code, name in zip(args.codes, names):
        path = screenshot_stock_chart(code, name)
        if path:
            print(f"  OK: {path}")
        else:
            print(f"  FAIL: {code}")
