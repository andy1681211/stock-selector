#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Playwright 盘中监控模块 v1.0
===========================
在交易时段使用 Playwright 监控自选股实时行情。

功能:
  1. 打开东方财富/同花顺自选股页面
  2. 按一定频率刷新页面截图
  3. 价格异动时自动截图并发送通知
  4. 收市后生成日内走势摘要

用法:
  python playwright_monitor.py --codes 600593,601688  # 监控指定股票
  python playwright_monitor.py --tracker              # 监控跟踪池中的股票
  python playwright_monitor.py --codes 600593 --interval 60  # 每60秒刷新
"""

import os
import sys
import time
import json
from datetime import datetime, time as dtime
from pathlib import Path
from typing import List, Optional

TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"
MONITOR_DIR = OUTPUT_DIR / "monitor"
MONITOR_DIR.mkdir(parents=True, exist_ok=True)


def get_tracked_codes() -> List[str]:
    """从跟踪池获取股票代码"""
    try:
        from local_screener import load_tracker
        tracker = load_tracker()
        codes = []
        for s in tracker.values():
            code = s.get("code", "")
            if code and not code.startswith(("300", "301", "688", "689", "4", "8", "9")):
                codes.append(code)
        return codes[:20]  # 最多20只
    except Exception:
        return []


def _make_url(code: str) -> str:
    """生成监控页面URL"""
    if code.startswith(("6", "9", "5")):
        return f"https://quote.eastmoney.com/sh{code}.html"
    elif code.startswith(("0", "3", "2")):
        return f"https://quote.eastmoney.com/sz{code}.html"
    else:
        return f"https://quote.eastmoney.com/sh{code}.html"


def monitor_stocks(codes: List[str], interval: int = 60, max_cycles: int = 0):
    """
    盘中实时监控指定股票。

    Args:
        codes: 股票代码列表
        interval: 刷新间隔（秒）
        max_cycles: 最大监控轮次（0=无限）
    """
    if not codes:
        print("[监控] 无可监控股票")
        return

    # 检查是否在交易时间（9:30-15:00 工作日）
    now = datetime.now()
    morning_start = dtime(9, 25)
    market_close = dtime(15, 5)

    print(f"[监控] 启动盘中监控 - {len(codes)}只股票")
    print(f"       刷新间隔: {interval}秒")
    print(f"       监控股票: {' '.join(codes[:10])}" + (f"...等{len(codes)}只" if len(codes) > 10 else ""))
    print()

    cycle = 0
    screenshot_interval = max(1, 600 // interval)  # 每10分钟截一次图

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[监控] ❌ 需要 playwright 库: pip install playwright")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        try:
            while True:
                if max_cycles > 0 and cycle >= max_cycles:
                    break

                cycle += 1
                now = datetime.now()
                time_str = now.strftime("%H:%M:%S")
                date_str = now.strftime("%Y%m%d_%H%M%S")

                # 检查交易时间
                # if now.weekday() >= 5:
                #     print(f"  [{time_str}] 非交易日，停止监控")
                #     break
                # if now.time() < morning_start or now.time() > market_close:
                #     if max_cycles == 0:
                #         print(f"  [{time_str}] 非交易时间，停止监控")
                #         break

                print(f"\n[{time_str}] 第{cycle}轮监控...", end=" ")

                # 获取实时价格（用 pytdx 更快）
                prices = {}
                try:
                    from tdx_reader import get_realtime_prices
                    prices = get_realtime_prices(codes)
                except Exception:
                    pass

                # 打印价格
                now = datetime.now()
                if prices:
                    alerts = []
                    for code in codes[:10]:
                        p = prices.get(code, {})
                        price = p.get("price", 0)
                        chg = p.get("pct_chg", 0)
                        if price:
                            flag = " ⚡" if abs(chg) > 5 else (" ↑" if chg > 2 else (" ↓" if chg < -2 else ""))
                            print(f"{code}{price:.2f}({chg:+.2f}%){flag}", end="  ")
                            if abs(chg) > 5:
                                alerts.append((code, price, chg))
                    print()

                    # 异动截图
                    if alerts and cycle % screenshot_interval == 0:
                        page = context.new_page()
                        for code, price, chg in alerts:
                            try:
                                url = _make_url(code)
                                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                                page.wait_for_timeout(3000)
                                shot_path = MONITOR_DIR / f"alert_{code}_{date_str}_{chg:+.1f}%.png"
                                page.screenshot(path=str(shot_path), full_page=False)
                                print(f"    ⚡ 异动截图: {shot_path.name}")

                                # 推送到Memos
                                try:
                                    from memos_logger import create_memo
                                    content = f"""⚡ **异动预警** {now.strftime('%H:%M')}

{code} 当前价:{price:.2f} 涨幅:{chg:+.2f}%

截图: {shot_path.name}

#异动预警 #{code}
"""
                                    create_memo(content)
                                except Exception:
                                    pass
                            except Exception:
                                pass
                        page.close()
                else:
                    print("价格获取失败", end="")
                    # 备用：截取自选股页面
                    if cycle % screenshot_interval == 0:
                        try:
                            # 打开东方财富自选股页面
                            page = context.new_page()
                            page.goto("https://quote.eastmoney.com/center/", wait_until="domcontentloaded", timeout=15000)
                            page.wait_for_timeout(5000)
                            shot_path = MONITOR_DIR / f"watchlist_{date_str}.png"
                            page.screenshot(path=str(shot_path))
                            print(f"  截图: {shot_path.name}")
                            page.close()
                        except Exception:
                            pass
                    print()

                # 休息
                if max_cycles == 0 or cycle < max_cycles:
                    time.sleep(interval)

        except KeyboardInterrupt:
            print("\n[监控] 用户中断")
        finally:
            context.close()
            browser.close()

    print(f"[监控] 结束（共{cycle}轮）")


def quick_check(codes: List[str]) -> dict:
    """
    快速检查股票当前价格（单次，不循环）。
    用于收盘后被调用获取当日表现。
    """
    result = {}
    try:
        from tdx_reader import get_realtime_prices
        prices = get_realtime_prices(codes)
        for code in codes:
            p = prices.get(code, {})
            if p.get("price"):
                result[code] = {
                    "price": p["price"],
                    "pct_chg": p.get("pct_chg", 0),
                    "volume": p.get("volume", 0),
                }
    except Exception:
        pass

    return result


def save_monitor_summary(codes: List[str], output_path: str = None):
    """生成监控摘要报告"""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    prices = quick_check(codes)

    if not output_path:
        output_path = str(MONITOR_DIR / f"监测摘要_{now.strftime('%Y%m%d_%H%M%S')}.txt")

    lines = [
        f"盘中监测摘要 - {date_str}",
        f"生成时间: {now.strftime('%H:%M')}",
        "",
        f"  {'代码':<8} {'名称':<10} {'最新价':<8} {'涨幅':<8}",
        f"  {'-'*8} {'-'*10} {'-'*8} {'-'*8}",
    ]

    # 取名称
    name_map = {}
    try:
        from utils import load_stock_names
        all_stocks = load_stock_names()
        name_map = {s.get("code", ""): s.get("name", "") for s in all_stocks if "code" in s}
    except Exception:
        pass

    for code in codes:
        p = prices.get(code, {})
        price = p.get("price", 0)
        chg = p.get("pct_chg", 0)
        name = name_map.get(code, "")
        if price:
            lines.append(f"  {code:<8} {name:<10} {price:<8.2f} {chg:<+7.2f}%")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")

    # 推Memos
    try:
        from memos_logger import create_memo
        memo = f"# 盘中监测 {date_str}\n\n"
        for code in codes[:10]:
            p = prices.get(code, {})
            if p.get("price"):
                memo += f"{code} {name_map.get(code,'')}: {p['price']:.2f} ({p['pct_chg']:+.2f}%)\n"
        memo += f"\n#盘中监测 #{now.strftime('%Y%m%d')}"
        create_memo(memo)
    except Exception:
        pass

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Playwright 盘中监控")
    ap.add_argument("--codes", help="股票代码，逗号分隔")
    ap.add_argument("--tracker", action="store_true", help="监控跟踪池")
    ap.add_argument("--interval", type=int, default=60, help="刷新间隔(秒)")
    ap.add_argument("--cycles", type=int, default=0, help="监控轮次(0=无限)")
    ap.add_argument("--summary", action="store_true", help="生成监测摘要并退出")
    args = ap.parse_args()

    codes = []
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",")]
    elif args.tracker:
        codes = get_tracked_codes()
    else:
        codes = get_tracked_codes()[:10]

    if args.summary:
        save_monitor_summary(codes)
    elif codes:
        monitor_stocks(codes, args.interval, args.cycles)
    else:
        print("无股票可监控")
