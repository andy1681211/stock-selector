#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘口数字暗语检测模块 v1.0
========================
基于《神奇数字盘口语言汇总》PDF 的完整规则实现。

检测维度:
  1. 股价数字暗语 — 收盘价/最高价/最低价中的特殊数字组合
  2. 盘口逃顶密码 — AA.BB / AB.AB / A.AA 等结构
  3. 手数暗语 — 成交量/委托单中的 1111/2222/8888 等

数据源:
  - 当前实时行情（通过 pytdx）
  - 日K线数据（最近N天的高低价）
"""

from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime

# ===== 股价数字暗语表 =====

PRICE_CODES = [
    # (pattern, meaning, type)
    # ABAB 组合
    ("16.16", "主力建仓/启动信号", "ABAB"),
    ("15.15", "要捂要捂(持股)", "ABAB"),
    ("17.17", "要起要起(拉升)", "ABAB"),
    ("18.18", "要发要发(一路发)", "ABAB"),
    # ABA 结构 (首尾同中间不同, 如 7.87)
    ("7.87", "ABA首尾相同结构-特殊盘口信号", "ABA"),
    ("8.78", "ABA首尾相同结构-方向信号", "ABA"),
    ("6.86", "ABA首尾相同结构-方向信号", "ABA"),
    # 间隔变化形态 (方向选择信号)
    ("22.33", "间隔变化-方向选择(突破/破位)", "间隔"),
    ("23.24", "间隔变化-节点博弈信号", "间隔"),
    ("23.32", "间隔变化-方向选择", "间隔"),
    ("22.66", "间隔变化-量价节点", "间隔"),
    # 顺子/连号 (趋势延续信号)
    ("7.65", "顺子-趋势性做多信号(持续上涨/下跌)", "顺子"),
    ("7.89", "顺子-连惯性做多信号", "顺子"),
    # 整数关口信号
    ("20.00", "整数关口-重要支撑/阻力", "整数"),
    ("20.01", "整数关口-突破/跌破确认", "整数"),
    ("20.02", "整数关口-方向确认", "整数"),
    # 谐音价格
    ("5.68", "五牛发(上涨动力)", "谐音"),
    ("7.77", "起起起(连续上涨)", "谐音"),
    ("8.88", "发发发", "谐音"),
    ("1.11", "要要要(启动)", "谐音"),
    ("2.22", "让让让", "谐音"),
    ("3.33", "赚赚赚/闪闪闪", "谐音"),
    ("4.44", "死死死", "谐音"),
    ("5.55", "捂捂捂(即将上涨)", "谐音"),
    ("6.66", "溜溜溜/留留留", "谐音"),
    ("7.78", "吃吃发", "谐音"),
    # 经典顺码
    ("58", "我发", "顺码"),
    ("68", "留发/路发", "顺码"),
    ("108", "要零发", "顺码"),
    ("168", "一路发", "顺码"),
    ("158", "要我发", "顺码"),
    ("588", "我发发", "顺码"),
    ("518", "我要发", "顺码"),
    ("188", "要发发", "顺码"),
]

# 手数暗语
VOLUME_CODES = {
    1111: "要要要(启动/合作)",
    2222: "让让让(单方行动)",
    3333: "赚赚赚/闪闪闪(高位风险)",
    4444: "死死死(实力雄厚)",
    5555: "捂捂捂(即将上涨)",
    6666: "溜溜溜(留)/留留留(卖)",
    7777: "吃吃吃(联手买入)",
    8888: "发发发(拉升/出货)",
    9999: "救救救(筹码用尽)",
    111: "要要要",
    222: "让让让",
    333: "赚赚赚",
    444: "死死死",
    555: "捂捂捂",
    666: "溜溜溜",
    777: "吃吃吃",
    888: "发发发",
    999: "救救救",
}


# ===== 检测函数 =====

def detect_price_code(price: float) -> List[Dict]:
    """
    检测单个价格是否包含数字暗语。

    Args:
        price: 股价（如 16.16, 7.77）

    Returns:
        [{"code": "16.16", "meaning": "主力建仓/启动信号", "type": "ABAB"}, ...]
    """
    results = []
    price_str = f"{price:.2f}"

    for pattern, meaning, code_type in PRICE_CODES:
        if pattern in price_str:
            results.append({
                "code": pattern,
                "meaning": meaning,
                "type": code_type,
            })

    # 检测 ABAB 结构 (如 16.16, 22.66)
    if len(price_str) >= 5:
        int_part = price_str.split(".")[0]
        dec_part = price_str.split(".")[1]
        if len(int_part) >= 2 and len(dec_part) >= 2:
            if int_part[-2:] == dec_part[:2]:
                if not any(r["type"] == "ABAB" for r in results):
                    results.append({
                        "code": price_str,
                        "meaning": f"ABAB结构: {int_part[-2:]}.{dec_part[:2]}",
                        "type": "ABAB",
                    })

    # 检测 AABB/ABB 结构
    if len(price_str) >= 5:
        int_part = price_str.split(".")[0]
        dec_part = price_str.split(".")[1]
        if len(int_part) >= 2 and dec_part and int_part[-1] == dec_part[0]:
            if not any(r["type"] == "ABB" for r in results):
                results.append({
                    "code": price_str,
                    "meaning": f"ABB结构: {int_part[-1]}{dec_part}",
                    "type": "ABB",
                })

    # 检测双零逃顶密码
    if len(price_str) >= 5:
        int_part = price_str.split(".")[0]
        dec_part = price_str.split(".")[1]
        if len(int_part) >= 2 and len(dec_part) >= 2:
            if int_part[-1:] == dec_part[-1:]:
                if not any(r["type"] == "逃顶" for r in results):
                    results.append({
                        "code": price_str,
                        "meaning": f"尾数对子(逃顶密码): 首尾{int_part[-1:]}",
                        "type": "逃顶",
                    })

    return results


def detect_volume_code(volume: int) -> List[Dict]:
    """
    检测成交量/委托单中的手数暗语。

    Args:
        volume: 手数（股）

    Returns:
        [{"hand": "8888", "meaning": "发发发(拉升/出货)"}, ...]
    """
    results = []
    vol_str = str(int(volume))

    # 从长到短匹配
    for code, meaning in sorted(VOLUME_CODES.items(), reverse=True):
        code_str = str(code)
        if code_str in vol_str:
            results.append({
                "hand": code_str,
                "meaning": meaning,
            })
            break  # 只匹配最长的一个

    return results


def detect_top_escape_pattern(high_price: float, low_price: float,
                               close_price: float, days_drop_pct: float = 0) -> List[Dict]:
    """
    检测盘口逃顶密码。
    条件: 大幅上涨(>25%)或下跌后，出现特殊数字结构。

    Args:
        high_price: 当日最高价
        low_price: 当日最低价
        close_price: 当日收盘价
        days_drop_pct: 近期涨跌幅（正=涨，负=跌）

    Returns:
        [{"price": xx, "pattern": "AA.BB", "signal": "见顶/见底"}, ...]
    """
    results = []

    # 涨幅>25%后出现逃顶密码 → 见顶信号更强
    need_top_signal = days_drop_pct > 25

    # 跌幅>25%后出现 → 见底信号
    need_bottom_signal = days_drop_pct < -25

    prices_to_check = [
        ("最高价", high_price),
        ("最低价", low_price),
        ("收盘价", close_price),
    ]

    for label, price in prices_to_check:
        codes = detect_price_code(price)
        for c in codes:
            if c["type"] in ("ABAB", "逃顶", "ABB"):
                signal = "⚠️ 见顶" if need_top_signal else ("🔻 见底" if need_bottom_signal else "关注")
                results.append({
                    "price_type": label,
                    "price": price,
                    "pattern": c["code"],
                    "type": c["type"],
                    "signal": signal,
                })

    return results


# ===== 股票级检测 =====

def scan_stock_price_code(name: str, code: str, klines: list,
                          current_price: float = None) -> Dict:
    """
    对一只股票完整扫描所有数字暗语信号。

    Args:
        name: 股票名称
        code: 股票代码
        klines: KLine列表（用于检测近期涨跌幅和高低价）
        current_price: 当前价格（可选）

    Returns:
        {
            "price_signals": [...],
            "volume_signals": [...],
            "top_escape": [...],
            "summary": "信号汇总描述",
        }
    """
    result = {
        "price_signals": [],
        "volume_signals": [],
        "top_escape": [],
        "summary": "",
    }

    # 股价检测
    if current_price:
        result["price_signals"] = detect_price_code(current_price)
    elif klines:
        result["price_signals"] = detect_price_code(klines[-1].close)

    # 近期涨跌幅
    days_change = 0
    if klines and len(klines) >= 30:
        start = klines[-30].close
        end = klines[-1].close
        if start > 0:
            days_change = (end - start) / start * 100

    # 逃顶密码
    if klines:
        result["top_escape"] = detect_top_escape_pattern(
            high_price=klines[-1].high,
            low_price=klines[-1].low,
            close_price=klines[-1].close,
            days_drop_pct=days_change,
        )

    # 汇总
    signals = []
    for s in result["price_signals"]:
        signals.append(f"价{s['code']}={s['meaning']}")
    for s in result["top_escape"]:
        signals.append(f"逃顶{s['price']}({s['signal']})")
    if result["volume_signals"]:
        signals.append(f"量{result['volume_signals'][0]['hand']}={result['volume_signals'][0]['meaning']}")

    result["summary"] = " | ".join(signals[:5]) if signals else ""
    return result


def format_signal_report(stock_signals: Dict) -> str:
    """格式化输出盘口暗语信号"""
    lines = []
    if stock_signals.get("price_signals"):
        for s in stock_signals["price_signals"]:
            lines.append(f"  📊 股价暗语: {s['code']} → {s['meaning']} ({s['type']})")

    if stock_signals.get("top_escape"):
        for s in stock_signals["top_escape"]:
            lines.append(f"  🚨 逃顶密码: {s['price_type']}{s['price']} {s['pattern']} {s['signal']}")

    if not lines:
        lines.append("  无盘口暗语信号")

    return "\n".join(lines)


# ===== 命令行测试 =====
if __name__ == "__main__":
    print("=" * 50)
    print("盘口数字暗语检测 - 测试")
    print("=" * 50)

    test_prices = [16.16, 7.77, 8.88, 33.33, 22.66, 5.68, 168.00, 15.15, 11.88, 4.44]
    for p in test_prices:
        codes = detect_price_code(p)
        if codes:
            for c in codes:
                print(f"  {p:>8.2f} → {c['code']} {c['meaning']} ({c['type']})")
        else:
            print(f"  {p:>8.2f} → 无信号")

    print()
    test_volumes = [8888, 11111, 555555, 777000, 6666]
    for v in test_volumes:
        codes = detect_volume_code(v)
        if codes:
            for c in codes:
                print(f"  成交量 {v} → {c['hand']} {c['meaning']}")
