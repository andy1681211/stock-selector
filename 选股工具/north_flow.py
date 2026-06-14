#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北向资金追踪模块 v1.1
====================
基于东方财富API追踪北向资金动向。

数据说明: 每日净流入明细接口自2024年8月起停更，
        当前仅可用: 当日汇总、个股北向持股、行业板块排行。

用法:
  from north_flow import generate_north_report
  report = generate_north_report()
"""

import sys, os
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional

TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"


def get_north_summary() -> Optional[List[Dict]]:
    """
    获取当日北向资金汇总（基于RPT_MUTUAL_QUOTA）。

    Returns:
        [{"板块":"沪股通","净买额":0.0亿,"资金净流入":0.0亿,"上涨":N,"下跌":N,"指数涨跌幅":1.12}, ...]
    """
    import akshare as ak
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is None or df.empty:
            return None

        results = []
        for _, row in df.iterrows():
            results.append({
                "板块": str(row.get("板块", "")),
                "资金方向": str(row.get("资金方向", "")),
                "成交净买额": float(row.get("成交净买额", 0) or 0),
                "资金净流入": float(row.get("资金净流入", 0) or 0),
                "上涨数": int(row.get("上涨数", 0) or 0),
                "下跌数": int(row.get("下跌数", 0) or 0),
                "持平数": int(row.get("持平数", 0) or 0),
                "指数涨跌幅": float(row.get("指数涨跌幅", 0) or 0),
                "交易状态": int(row.get("交易状态", 0)),
                "相关指数": str(row.get("相关指数", "")),
            })
        return results
    except Exception as e:
        return None


def get_north_individual(stock_code: str) -> Optional[Dict]:
    """
    获取单只股票的北向资金持股占比。

    Args:
        stock_code: 6位代码，如 "600519"

    Returns:
        {"持股日期":"2026-03-31", "占A股比例":4.69, "变化1日":null, "变化5日":null, "变化10日":null}
    """
    import akshare as ak
    try:
        df = ak.stock_hsgt_individual_em(stock=stock_code)
        if df is None or df.empty:
            return None
        row = df.iloc[-1]
        return {
            "持股日期": str(row.iloc[0]) if len(row) > 0 else "",
            "收盘价": float(row.iloc[1]) if len(row) > 1 else 0,
            "涨跌幅": float(row.iloc[2]) if len(row) > 2 else 0,
            "持股数量": float(row.iloc[3]) if len(row) > 3 else 0,
            "占A股比例": float(row.iloc[6]) if len(row) > 6 else 0,
            "变化1日": float(row.iloc[7]) if len(row) > 7 and row.iloc[7] else None,
            "变化5日": float(row.iloc[8]) if len(row) > 8 and row.iloc[8] else None,
        }
    except Exception:
        return None


def check_stocks_north_holdings(stock_codes: List[str]) -> List[Dict]:
    """
    批量查自选股的北向持股占比。

    Args:
        stock_codes: 代码列表 ["600519"]

    Returns:
        有北向数据的股票（占比降序）
    """
    if not stock_codes:
        return []
    results = []
    for i, code in enumerate(stock_codes):
        if i > 0 and i % 10 == 0:
            import time
            time.sleep(0.3)
        info = get_north_individual(code)
        if info and info["占A股比例"] > 0:
            results.append(info | {"代码": code})
    results.sort(key=lambda x: -x["占A股比例"])
    return results


def get_north_industry_ranking(top_n: int = 10) -> List[str]:
    """
    获取北向资金增持行业板块排行。
    """
    import akshare as ak
    try:
        for indicator in ["今日", "近3日", "近5日"]:
            try:
                df = ak.stock_hsgt_board_rank_em(
                    symbol="北向资金增持行业板块排行", indicator=indicator
                )
                if df is not None and not df.empty:
                    names = [str(row.iloc[1]) for _, row in df.head(top_n).iterrows()]
                    return names
            except Exception:
                continue
    except Exception:
        pass
    return []


def generate_north_report() -> str:
    """生成北向资金报告"""
    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append("  北向资金动向")
    lines.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 70)
    lines.append("")

    summary = get_north_summary()
    if not summary:
        lines.append("  暂无北向资金数据（非交易日或接口暂不可用）")
        return "\n".join(lines)

    # 提取北向数据
    north_items = [s for s in summary if s["资金方向"] == "北向"]
    if not north_items:
        lines.append("  暂无北向数据")
        return "\n".join(lines)

    lines.append("  ┌─ 北向资金当日概况 ─────────────────────┐")
    for item in north_items:
        board = item["板块"]
        net = item["成交净买额"]
        inflow = item["资金净流入"]
        up = item["上涨数"]
        dn = item["下跌数"]
        idx = item["相关指数"]
        idx_chg = item["指数涨跌幅"]
        direction = "↑ 净流入" if net > 0 else ("↓ 净流出" if net < 0 else "— 持平")
        lines.append(f"  │ {board:<6} {direction} {abs(net):>8.2f}亿  | {idx}")
        lines.append(f"  │ 上涨{up}家 下跌{dn}家 指数{idx_chg:+.2f}%")

    north_net = sum(item["成交净买额"] for item in north_items)
    lines.append(f"  │ ───────────────────────────────")
    lines.append(f"  │ 合计: {'净流入' if north_net > 0 else '净流出' if north_net < 0 else '持平'} {abs(north_net):.2f}亿")
    lines.append("  └────────────────────────────────────┘")
    lines.append("")

    # 行业板块
    industries = get_north_industry_ranking(8)
    if industries:
        lines.append(f"  北向增持行业: {' | '.join(industries)}")
        lines.append("")

    lines.append("  ⚠ 北向资金数据T+1发布，仅供参考")

    return "\n".join(lines)


def add_north_to_report(existing_report: str = "") -> str:
    report = generate_north_report()
    return existing_report + "\n" + report if existing_report else report


if __name__ == "__main__":
    sys.stdout = open(1, 'w', encoding='utf-8', closefd=False)
    report = generate_north_report()
    print(report)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    rp = OUTPUT_DIR / f"北向资金报告_{ts}.txt"
    rp.write_text(report, encoding="utf-8")
    print(f"\n[报告] 已保存: {rp}")
