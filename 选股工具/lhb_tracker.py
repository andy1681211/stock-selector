#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
龙虎榜游资追踪系统 v1.0
======================
基于 akshare 东方财富数据源，追踪龙虎榜知名游资席位动向。

功能:
  1. 获取每日龙虎榜上榜股票
  2. 识别知名游资席位买卖行为
  3. 分析游资净买入/净卖出/做T
  4. 监测游资与自选股的交集
  5. 生成游资动向报告

用法:
  from lhb_tracker import (
      get_daily_longhubang,
      identify_rogue_traders,
      generate_lhb_report,
      check_my_stocks,
  )
  df = get_daily_longhubang('20260612')
  report = generate_lhb_report('20260612')

关联: [[you-zi-pan-kou-an-yu]], [[zui-xin-cao-pan-bi-ji]]
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import json

TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"

# ==================== 知名游资席位数据库 ====================

# 格式: (营业部名称关键词, 游资昵称/代号, 风格标签, 关联笔记)
ROGUE_TRADER_SEATS = [
    # ===== 西藏天团（散户大本营）- 拉萨军团 =====
    ("拉萨团结路第二", "拉萨团结路二", "散户天团", "上榜王"),
    ("拉萨团结路第一", "拉萨团结路一", "散户天团", "上榜王"),
    ("拉萨金融城南环路", "拉萨金融城南", "散户天团", "上榜王"),
    ("拉萨东环路第二", "拉萨东环路二", "散户天团", "上榜王"),
    ("拉萨东环路第一", "拉萨东环路一", "散户天团", "上榜王"),
    ("拉萨东城区江苏大道", "拉萨江苏大道", "散户天团", ""),
    ("拉萨达孜区虎峰大道", "拉萨虎峰大道", "散户天团", ""),

    # ===== 顶级游资 =====
    ("上海溧阳路", "溧阳路", "顶级游资", "孙哥"),
    ("中信证券上海分公司", "中信上海分", "顶级游资", ""),
    ("南京太平南路", "南京太平南", "顶级游资", "作手新一"),
    ("上海松江区中山东路", "上海松江中山东", "顶级游资", "新晋游资"),
    ("华鑫证券上海分公司", "华鑫上海分", "顶级游资", "炒股养家"),
    ("华鑫证券上海陆家嘴", "华鑫陆家嘴", "顶级游资", ""),
    ("银河证券绍兴", "绍兴营业部", "顶级游资", "赵老哥"),
    ("北京中关村大街", "中关村大街", "顶级游资", ""),
    ("杭州上塘路", "上塘路", "顶级游资", ""),
    ("深圳欢乐海岸", "欢乐海岸", "顶级游资", "欢乐海岸"),
    ("招商证券深圳深南东路", "深南东路", "顶级游资", ""),
    ("杭州市心北路", "市心北路", "顶级游资", ""),
    ("杭州龙井路", "龙井路", "顶级游资", ""),

    # ===== 量化/外资席位 =====
    ("高盛(中国)证券上海浦东新区世纪大道", "高盛上海世纪", "量化外资", "QFII"),
    ("摩根大通证券(中国)上海银城中路", "摩根上海银城", "量化外资", "QFII"),
    ("瑞银证券上海花园石桥路", "瑞银上海花园", "量化外资", "QFII"),
    ("中国国际金融上海分公司", "中金上海分", "量化外资", ""),

    # ===== 机构常用席位 =====
    ("深股通专用", "深股通", "北向资金", "外资"),
    ("沪股通专用", "沪股通", "北向资金", "外资"),
    ("机构专用", "机构专用", "机构", ""),
]


def get_known_seat_names() -> List[str]:
    """返回所有已知游资席位的营业部名称关键词列表"""
    return [s[0] for s in ROGUE_TRADER_SEATS]


def find_rogue_trader(seat_name: str) -> Optional[Dict]:
    """
    查找营业部是否匹配已知游资席位的名称关键词。

    Args:
        seat_name: 龙虎榜中的完整营业部名称

    Returns:
        匹配到的游资信息，或 None
        {
            "nickname": 简称,
            "style": 风格标签,
            "note": 备注,
        }
    """
    for keyword, nickname, style, note in ROGUE_TRADER_SEATS:
        if keyword in seat_name:
            return {
                "keyword": keyword,
                "nickname": nickname,
                "style": style,
                "note": note,
            }
    return None


# ==================== 龙虎榜数据获取 ====================

def get_daily_longhubang(date_str: str = None) -> Optional[List[Dict]]:
    """
    获取指定日期的龙虎榜数据。

    Args:
        date_str: 日期 YYYYMMDD 或 YYYY-MM-DD，默认最新交易日

    Returns:
        龙虎榜股票列表
        [{
            "代码": "000032",
            "名称": "深桑达A",
            "收盘价": 18.92,
            "涨跌幅": 10.00,
            "龙虎榜净买额": 3.43亿,
            "龙虎榜买入额": 5.88亿,
            "龙虎榜卖出额": 2.45亿,
            "净买额占比": 13.53%,
            "换手率": 9.28%,
            "流通市值": 21.53亿,
            "上榜原因": "...",
            "解读": "2家机构买入...",
        }]
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    # 统一格式为 YYYYMMDD
    date_clean = date_str.replace("-", "")

    try:
        import akshare as ak
        df = ak.stock_lhb_detail_em(start_date=date_clean, end_date=date_clean)
        if df is None or df.empty:
            return None
    except Exception as e:
        print(f"  [龙虎榜] 获取失败: {e}")
        return None

    results = []
    for _, row in df.iterrows():
        item = {
            "代码": str(row.get("代码", "")),
            "名称": str(row.get("名称", "")),
            "收盘价": float(row.get("收盘价", 0) or 0),
            "涨跌幅": float(row.get("涨跌幅", 0) or 0),
            "龙虎榜净买额": float(row.get("龙虎榜净买额", 0) or 0),
            "龙虎榜买入额": float(row.get("龙虎榜买入额", 0) or 0),
            "龙虎榜卖出额": float(row.get("龙虎榜卖出额", 0) or 0),
            "龙虎榜成交额": float(row.get("龙虎榜成交额", 0) or 0),
            "净买额占比": float(row.get("净买额占总成交比", 0) or 0),
            "换手率": float(row.get("换手率", 0) or 0),
            "流通市值": float(row.get("流通市值", 0) or 0),
            "上榜原因": str(row.get("上榜原因", "")),
            "解读": str(row.get("解读", "")),
        }
        results.append(item)

    return results


def get_stock_lhb_detail(stock_code: str, date_str: str = None,
                          flag: str = "买入") -> Optional[List[Dict]]:
    """
    获取单只股票当天的龙虎榜席位明细。

    Args:
        stock_code: 股票代码，如 "002421"
        date_str: 日期 YYYYMMDD
        flag: "买入" 或 "卖出"

    Returns:
        席位买卖明细
        [{
            "营业部名称": "...",
            "买入金额": 48494092.2,
            "买入占比": 1.65%,
            "卖出金额": 39608934.0,
            "卖出占比": 1.34%,
            "净额": 8885158.20,
        }]
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    date_clean = date_str.replace("-", "")

    try:
        import akshare as ak
        df = ak.stock_lhb_stock_detail_em(symbol=stock_code, date=date_clean, flag=flag)
        if df is None or df.empty:
            return None
    except Exception as e:
        return None

    results = []
    for _, row in df.iterrows():
        item = {
            "营业部名称": str(row.get("交易营业部名称", "")),
            "买入金额": float(row.get("买入金额", 0) or 0),
            "买入占比": float(row.get("买入金额-占总成交比例", 0) or 0) * 100,
            "卖出金额": float(row.get("卖出金额", 0) or 0),
            "卖出占比": float(row.get("卖出金额-占总成交比例", 0) or 0) * 100,
            "净额": float(row.get("净额", 0) or 0),
            "类型": str(row.get("类型", "")),
        }
        # 计算是买方还是卖方
        if flag == "买入":
            item["方向"] = "买入" if item["净额"] >= 0 else "卖出"
        else:
            item["方向"] = "卖出" if item["净额"] <= 0 else "买入"
        results.append(item)

    return results


# ==================== 游资识别 ====================

def identify_rogue_traders(stock_code: str, date_str: str = None) -> List[Dict]:
    """
    识别单只龙虎榜股票中有哪些知名游资参与。

    获取个股席位明细，匹配游资数据库，去重合并。

    Args:
        stock_code: 股票代码
        date_str: 日期

    Returns:
        [{
            "营业部名称": "...",
            "nickname": "拉萨天团",
            "style": "散户天团",
            "方向": "买入",
            "净额": 8885158.20,
            "净额显示": "+888.5万",
        }]
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    # 该API实际返回混合数据（买入+卖出），只需取"买入"可得全部
    raw_seats = get_stock_lhb_detail(stock_code, date_str, flag="买入")
    if not raw_seats:
        return []

    # 去重合并：同一营业部出现在多类上榜原因中，合并金额
    merged = {}
    for seat in raw_seats:
        name = seat["营业部名称"]
        if name in merged:
            merged[name]["买入金额"] += seat["买入金额"]
            merged[name]["卖出金额"] += seat["卖出金额"]
            merged[name]["净额"] += seat["净额"]
        else:
            merged[name] = dict(seat)

    # 匹配游资数据库
    identified = []
    for seat in merged.values():
        match = find_rogue_trader(seat["营业部名称"])
        if not match:
            continue

        net = seat["净额"]
        identified.append({
            "营业部名称": seat["营业部名称"],
            "nickname": match["nickname"],
            "style": match["style"],
            "note": match["note"],
            "方向": "买入" if net >= 0 else "卖出",
            "净额": net,
            "净额显示": _fmt_money(net),
            "买入金额": seat["买入金额"],
            "卖出金额": seat["卖出金额"],
        })

    return identified


def _fmt_money(amount: float) -> str:
    """格式化金额显示"""
    if abs(amount) >= 1e8:
        return f"{amount/1e8:+.2f}亿"
    elif abs(amount) >= 1e4:
        return f"{amount/1e4:+.0f}万"
    else:
        return f"{amount:+.0f}元"


# ==================== 游资操盘判断 ====================

def detect_trader_tactics(seats: List[Dict]) -> List[str]:
    """
    从游资席位行为判断操盘意图。

    判断规则:
      - 多席位买入 → 集体建仓信号
      - 同一席位买卖都有 → 做T（对倒）
      - 净买入 > 卖出 → 看多
      - 净卖出 > 买入 → 看空
      - 拉萨天团大量买入 → 散户跟风盘（警惕出货）
      - 顶级游资买入 → 题材确认

    Args:
        seats: identify_rogue_traders 返回的列表

    Returns:
        信号描述列表
    """
    signals = []

    if not seats:
        return signals

    # 统计席位风格分布
    style_counts = {}
    net_by_style = {}
    seat_names = set()

    for s in seats:
        style = s.get("style", "未知")
        style_counts[style] = style_counts.get(style, 0) + 1
        net_by_style[style] = net_by_style.get(style, 0) + s.get("净额", 0)
        seat_names.add(s.get("nickname", ""))

    nicknames = "、".join(sorted(seat_names)[:5])

    # 判断1: 散户天团（拉萨军团）主导
    lhasa_net = net_by_style.get("散户天团", 0)
    if lhasa_net > 0:
        signals.append(f"拉萨天团净买{_fmt_money(lhasa_net)}（散户跟风）")
    elif lhasa_net < 0:
        signals.append(f"拉萨天团净卖{_fmt_money(lhasa_net)}（散户出逃）")

    # 判断2: 顶级游资参与
    top_trader_net = net_by_style.get("顶级游资", 0)
    if top_trader_net > 1e7:
        signals.append(f"顶级游资净买{_fmt_money(top_trader_net)}（龙头确认）")
    elif top_trader_net < -1e7:
        signals.append(f"顶级游资净卖{_fmt_money(top_trader_net)}（游资出逃）")

    # 判断3: 北向资金
    north_net = net_by_style.get("北向资金", 0)
    if abs(north_net) > 1e7:
        signals.append(f"北向资金{'净买' if north_net > 0 else '净卖'}{_fmt_money(north_net)}")

    # 判断4: 机构参与
    inst_net = net_by_style.get("机构", 0)
    if abs(inst_net) > 1e7:
        signals.append(f"机构{'净买' if inst_net > 0 else '净卖'}{_fmt_money(inst_net)}")

    # 判断5: 多路游资齐聚
    active_styles = [k for k, v in style_counts.items() if v > 0]
    if len(active_styles) >= 3 and len(seats) >= 4:
        signals.append(f"多路资金齐聚({nicknames})")

    if not signals:
        signals.append(f"游资参与({nicknames})")

    return signals


# ==================== 龙虎榜综合扫描 ====================

def scan_longhubang(date_str: str = None, max_stocks: int = 20) -> List[Dict]:
    """
    全量龙虎榜扫描，识别每只上榜股票中的游资动向。

    Args:
        date_str: 日期
        max_stocks: 最多分析的股票数

    Returns:
        [{
            "代码": "000032",
            "名称": "深桑达A",
            "涨跌幅": 10.00,
            "净买额": 3.43亿,
            "游资数": 3,
            "游资列表": "拉萨团结路二、中信上海分",
            "游资净额": 1.23亿,
            "信号": ["多路资金齐聚", "顶级游资净买"],
            "上榜原因": "...",
            "解读": "...",
        }]
    """
    print(f"  [龙虎榜] 扫描 {date_str or '今天'} 龙虎榜游资...")

    stocks = get_daily_longhubang(date_str)
    if not stocks:
        print("  [龙虎榜] 无数据")
        return []

    # 按净买额绝对值排序
    stocks.sort(key=lambda x: abs(x["龙虎榜净买额"]), reverse=True)

    # 去重（同一股票可能因多类原因上榜）
    seen_codes = set()
    unique_stocks = []
    for s in stocks:
        if s["代码"] not in seen_codes:
            seen_codes.add(s["代码"])
            unique_stocks.append(s)

    results = []
    analyzed = 0

    for stock in unique_stocks[:max_stocks]:
        code = stock["代码"]
        name = stock["名称"]

        # 获取游资席位详情
        seats = identify_rogue_traders(code, date_str)
        if not seats:
            continue

        analyzed += 1

        # 计算游资净额汇总
        total_net = sum(s["净额"] for s in seats)
        buy_seats = [s for s in seats if s["方向"] == "买入"]
        sell_seats = [s for s in seats if s["方向"] == "卖出"]

        # 游资列表（去重昵称，保留顺序）
        nickname_list = list(dict.fromkeys(s["nickname"] for s in seats))

        # 操盘判断
        tactics = detect_trader_tactics(seats)

        item = {
            "代码": code,
            "名称": name,
            "涨跌幅": stock["涨跌幅"],
            "净买额": stock["龙虎榜净买额"],
            "净买额显示": _fmt_money(stock["龙虎榜净买额"]),
            "游资数": len(nickname_list),
            "游资列表": "、".join(nickname_list[:6]),
            "游资总净额": total_net,
            "游资净额显示": _fmt_money(total_net),
            "买入游资": len(buy_seats),
            "卖出游资": len(sell_seats),
            "信号": tactics,
            "上榜原因": stock.get("上榜原因", ""),
            "解读": stock.get("解读", ""),
            "换手率": stock.get("换手率", 0),
            "流通市值": stock.get("流通市值", 0),
            "_seats": seats,  # 原始席位数据，供报告复用
        }
        results.append(item)

        if analyzed >= max_stocks:
            break

    # 如果没有游资参与的股票，补一个说明
    if not results:
        print(f"  [龙虎榜] {len(stocks)}只上榜，但无知名游资参与")

    return results


# ==================== 自选股校验 ====================

def check_my_stocks(my_codes: List[str], date_str: str = None) -> List[Dict]:
    """
    检查自选股中是否有股票上了龙虎榜。

    Args:
        my_codes: 自选股代码列表（如 ["600519", "002230"]）
        date_str: 日期

    Returns:
        自选股中上龙虎榜的股票详情
    """
    if not my_codes:
        return []

    stocks = get_daily_longhubang(date_str)
    if not stocks:
        return []

    hits = []
    for stock in stocks:
        code = stock["代码"]
        if code in my_codes or code[2:] in my_codes:
            seats = identify_rogue_traders(code, date_str)
            tactics = detect_trader_tactics(seats)
            hits.append({
                "代码": code,
                "名称": stock["名称"],
                "涨跌幅": stock["涨跌幅"],
                "净买额显示": _fmt_money(stock["龙虎榜净买额"]),
                "游资": "、".join(list(dict.fromkeys(s["nickname"] for s in seats))[:4]) if seats else "无",
                "信号": "、".join(tactics) if tactics else "无游资",
                "上榜原因": stock.get("上榜原因", ""),
            })

    return hits


# ==================== 报告生成 ====================

def generate_lhb_report(date_str: str = None) -> str:
    """
    生成完整的龙虎榜游资追踪报告。

    Args:
        date_str: 日期

    Returns:
        报告文本
    """
    if date_str is None:
        now = datetime.now()
        # 默认取最近一个交易日（如果是周末取周五）
        if now.weekday() >= 5:
            days_back = now.weekday() - 4
            date_str = (now - timedelta(days=days_back)).strftime("%Y%m%d")
        else:
            date_str = now.strftime("%Y%m%d")

    date_display = date_str.replace("-", "")
    date_obj = datetime.strptime(date_display, "%Y%m%d")
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_names[date_obj.weekday()]

    stocks = get_daily_longhubang(date_str)
    if not stocks:
        return f"  [龙虎榜] {date_display}({weekday}) 暂无数据（非交易日或接口异常）"

    scanned = scan_longhubang(date_str, max_stocks=30)

    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append(f"  龙虎榜游资追踪 {date_display} {weekday}")
    lines.append(f"  上榜股票: {len(stocks)}只 | 游资参与: {len(scanned)}只")
    lines.append("=" * 70)
    lines.append("")

    if not scanned:
        lines.append("  [说明] 本日上榜股票无知名游资席位参与")
        return "\n".join(lines)

    # ===== 分类展示 =====
    # 1. 顶级游资参与的（最有价值）
    top_stocks = [s for s in scanned if any("顶级游资" in str(sig) or "多路资金" in str(sig) for sig in s["信号"])]
    if top_stocks:
        lines.append("  ★ 顶级游资参与（龙头确认信号）")
        lines.append(f"  {'代码':<8} {'名称':<10} {'涨幅%':<8} {'净买额':<12} {'游资':<24} {'信号'}")
        lines.append(f"  {'-'*8} {'-'*10} {'-'*8} {'-'*12} {'-'*24} {'-'*30}")
        for s in top_stocks[:8]:
            name = s["名称"]
            chg = s["涨跌幅"]
            net = s["净买额显示"]
            youzi = s["游资列表"][:20]
            sig = s["信号"][0] if s["信号"] else ""
            lines.append(f"  {s['代码']:<8} {name:<10} {chg:>+7.2f}% {net:<12} {youzi:<24} {sig}")
        lines.append("")

    # 2. 机构/北向资金参与的
    inst_stocks = [s for s in scanned if any("机构" in str(sig) or "北向" in str(sig) for sig in s["信号"])]
    inst_shown = [s for s in inst_stocks if s not in top_stocks]
    if inst_shown:
        lines.append("  ◆ 机构/北向资金参与（价值信号）")
        lines.append(f"  {'代码':<8} {'名称':<10} {'涨幅%':<8} {'净买额':<12} {'游资':<24}")
        lines.append(f"  {'-'*8} {'-'*10} {'-'*8} {'-'*12} {'-'*24}")
        for s in inst_shown[:5]:
            lines.append(f"  {s['代码']:<8} {s['名称']:<10} {s['涨跌幅']:>+7.2f}% {s['净买额显示']:<12} {s['游资列表'][:20]:<24}")
        lines.append("")

    # 3. 拉萨天团买入前几（散户跟风票，警惕）
    lhasa_stocks = [s for s in scanned if any("拉萨" in str(sig) for sig in s["信号"])]
    lhasa_buy = [s for s in lhasa_stocks if s not in top_stocks and s not in inst_shown]
    if lhasa_buy:
        lines.append("  △ 散户天团参与（拉萨军团）")
        lines.append(f"  {'代码':<8} {'名称':<10} {'涨幅%':<8} {'净买额':<12} {'游资':<24}")
        lines.append(f"  {'-'*8} {'-'*10} {'-'*8} {'-'*12} {'-'*24}")
        for s in lhasa_buy[:5]:
            lines.append(f"  {s['代码']:<8} {s['名称']:<10} {s['涨跌幅']:>+7.2f}% {s['净买额显示']:<12} {s['游资列表'][:20]:<24}")
        lines.append("")

    # ===== 游资行为统计 =====
    lines.append("-" * 70)
    lines.append("  游资行为统计")
    lines.append("-" * 70)

    # 按游资昵称统计现身次数和净额
    trader_stats = {}
    for s in scanned:
        if s["游资数"] == 0:
            continue
        # 用 _seats 统计每个昵称在该股票上的汇总净额
        seats = s.get("_seats", [])
        per_nick_net = {}
        for seat in seats:
            nick = seat["nickname"]
            per_nick_net[nick] = per_nick_net.get(nick, 0) + seat["净额"]
        for nick, net in per_nick_net.items():
            if nick not in trader_stats:
                trader_stats[nick] = {"count": 0, "total_net": 0, "stocks": []}
            trader_stats[nick]["count"] += 1
            trader_stats[nick]["total_net"] += net
            if s["名称"] not in trader_stats[nick]["stocks"]:
                trader_stats[nick]["stocks"].append(s["名称"])

    # 净额已在上方统计完毕，跳过重复计算

    sorted_traders = sorted(trader_stats.items(), key=lambda x: -x[1]["count"])
    if sorted_traders:
        lines.append(f"  {'游资':<16} {'上榜次数':<8} {'净额':<12} {'参与的股票'}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*12} {'-'*30}")
        for nick, stats in sorted_traders[:10]:
            net_str = _fmt_money(stats["total_net"])
            stocks_str = "、".join(stats["stocks"][:4])
            lines.append(f"  {nick:<16} {stats['count']:<8} {net_str:<12} {stocks_str}")
    lines.append("")

    # ===== 操作提示 =====
    lines.append("-" * 70)
    lines.append("  操作提示")
    lines.append("-" * 70)

    # 顶级游资净买 + 多路资金 → 龙头可能
    if top_stocks:
        for s in top_stocks[:3]:
            lines.append(f"  ★ {s['名称']}({s['代码']}): 多路游资齐聚, 关注连板机会")
    # 机构净买 → 趋势可能
    if inst_stocks:
        for s in inst_stocks[:2]:
            lines.append(f"  ◆ {s['名称']}({s['代码']}): 机构介入, 趋势可能延续")
    # 散户天团买最多的
    if lhasa_stocks:
        lines.append(f"  △ 拉萨军团活跃, 警惕高位散户接盘")

    lines.append("")
    lines.append("  ⚠ 龙虎榜数据T+1发布, 仅供参考, 不构成投资建议")
    lines.append("")

    return "\n".join(lines)


# ==================== 集成到 run_selector ====================

def add_lhb_to_report(existing_report: str = "", date_str: str = None) -> str:
    """
    生成龙虎榜报告并追加到现有选股报告后。

    Args:
        existing_report: 现有选股报告文本
        date_str: 日期

    Returns:
        追加龙虎榜内容后的报告
    """
    report = generate_lhb_report(date_str)
    return existing_report + "\n" + report if existing_report else report


# ==================== 独立运行 ====================

if __name__ == "__main__":
    import sys, os
    sys.stdout = open(1, 'w', encoding='utf-8', closefd=False)

    print("=" * 50)
    print("  龙虎榜游资追踪系统")
    print("=" * 50)
    print()

    # 默认取最近交易日
    now = datetime.now()
    if now.weekday() >= 5:
        days_back = now.weekday() - 4
        date = (now - timedelta(days=days_back)).strftime("%Y%m%d")
    else:
        date = now.strftime("%Y%m%d")
    if len(sys.argv) > 1:
        date = sys.argv[1].replace("-", "")

    print(f"  日期: {date}")
    print()

    # 获取龙虎榜
    stocks = get_daily_longhubang(date)
    if not stocks:
        print("  暂无龙虎榜数据（非交易日或接口不可用）")
        exit(0)

    print(f"  上榜股票: {len(stocks)} 只")
    print()

    # 扫描游资
    scanned = scan_longhubang(date, max_stocks=30)

    if scanned:
        print()
        print(f"  游资参与: {len(scanned)} 只")
        print()
        # 打印简报
        print(f"  {'代码':<8} {'名称':<10} {'涨幅%':<8} {'净买额':<12} {'游资':<28} {'信号'}")
        print(f"  {'-'*8} {'-'*10} {'-'*8} {'-'*12} {'-'*28} {'-'*30}")
        for s in scanned[:10]:
            sig = s["信号"][0] if s["信号"] else ""
            print(f"  {s['代码']:<8} {s['名称']:<10} {s['涨跌幅']:>+7.2f}% {s['净买额显示']:<12} {s['游资列表'][:24]:<28} {sig}")
    else:
        print("  无知名游资参与")

    print()
    print("=" * 50)

    # 生成完整报告
    report = generate_lhb_report(date)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = OUTPUT_DIR / f"龙虎榜报告_{date}_{ts}.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n[报告] 已保存: {report_path}")
