#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
止盈止损规则引擎 v1.0
=====================
基于交易策略类型 + ATR动态波动率，为每只跟踪中的股票
自动计算买入价、止损价、止盈价、跟踪止损位。

规则矩阵:
  策略类型        止损规则              止盈规则              跟踪规则
  ─────────      ──────────            ──────────            ──────────
  连板接力        昨收-5%              首板+15%              利润>10%后保本
  低位放量首板    MA5跌破              20日目标(平台高+10%)  利润>12%后MA5跟踪
  趋势加速        MA10跌破或-8%        前高+5%               利润>15%后MA10跟踪
  N字反包        涨停日最低价          前高+3%               利润>8%后保本
  缠论一买        底分型最低价          MA20偏离+8%          —
  缠论二买        回踩最低价           前高+5%               MA5跟踪
  缠论三买        中枢上沿下方-2%       —                    MA10跟踪
  主升浪起爆      试盘线低点-2%         —                    利润>12%后MA5跟踪
  洗盘结束        洗盘日最低价          +15%                 利润>8%后保本
  飞龙在天        断板最低价            +20%                 利润>15%后MA10跟踪
  潜龙回首        回调低点-3%           前高                 利润>10%后保本
  平步青云强       MA5跌破              压力位-2%             MA5跟踪

用法:
  from stop_engine import (
      calc_stop_levels,     # 对单只股票计算止盈止损
      add_stops_to_tracker, # 为跟踪池所有活跃股票补充规则
      generate_stop_report, # 生成止盈止损报告
  )
"""

import sys, os, math
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Tuple
import json

TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"
TDX_ROOT = "D:/new_tdx/vipdoc"


# ==================== ATR 计算（动态波动率）====================

def calc_atr(klines, period: int = 14) -> float:
    """
    计算最近 N 日的平均真实波幅 ATR。

    ATR = 过去N日 TR 的指数移动平均
    TR = max(当日最高-当日最低, |当日最高-前日收盘|, |当日最低-前日收盘|)

    Returns:
        ATR值（价格单位, 如 0.85 元）
    """
    if len(klines) < period + 1:
        return 0.0

    tr_values = []
    for i in range(-period, 0):
        k = klines[i]
        prev_close = klines[i-1].close
        tr = max(k.high - k.low, abs(k.high - prev_close), abs(k.low - prev_close))
        tr_values.append(tr)

    if not tr_values:
        return 0.0

    # 简单平均（简化版）
    return sum(tr_values) / len(tr_values)


def calc_ma(klines, period: int = 5) -> Optional[float]:
    """计算最近N日均线值"""
    if len(klines) < period:
        return None
    return sum(k.close for k in klines[-period:]) / period


# ==================== 策略类型识别 ====================

def _detect_strategy_type(result: Dict) -> str:
    """
    从选股结果的信号字段识别策略类型。

    Returns: 策略类型代码
    """
    if result.get("飞龙在天", ""):
        return "飞龙在天"
    if result.get("潜龙回首", ""):
        return "潜龙回首"
    if result.get("二进三信号", ""):
        return "连板接力"
    if result.get("建仓型涨停", ""):
        return "低位放量首板"
    if result.get("主升浪起爆", ""):
        return "主升浪起爆"
    if result.get("洗盘结束", ""):
        return "洗盘结束"
    if result.get("倍量突破", ""):
        return "低位放量首板"
    if result.get("平步青云强") == "是":
        return "平步青云强"

    chan = result.get("缠论买点", "")
    if "二买" in chan:
        return "缠论二买"
    if "三买" in chan:
        return "缠论三买"
    if "一买" in chan:
        return "缠论一买"

    sl = result.get("策略列表", [])
    if isinstance(sl, list):
        if "连板接力弱转强" in sl:
            return "连板接力"
        if "趋势加速" in sl:
            return "趋势加速"
        if "N字反包" in sl:
            return "N字反包"
        if "低位放量首板" in sl:
            return "低位放量首板"

    return "综合精选"


# ==================== 规则矩阵 ====================

STOP_RULES = {
    "连板接力": {
        "stop_loss_pct": 0.05,      # 止损5%
        "stop_loss_desc": "止损-5%",
        "take_profit_pct": 0.15,    # 止盈15%
        "trail_trigger_pct": 0.10,  # 利润>10%启动跟踪
        "trail_type": "保本",       # 跟踪到成本价
    },
    "低位放量首板": {
        "stop_loss_pct": 0.08,
        "stop_loss_desc": "MA5跌破或-8%",
        "take_profit_pct": 0.20,
        "trail_trigger_pct": 0.12,
        "trail_type": "MA5跟踪",
    },
    "趋势加速": {
        "stop_loss_pct": 0.08,
        "stop_loss_desc": "MA10跌破或-8%",
        "take_profit_pct": 0.25,
        "trail_trigger_pct": 0.15,
        "trail_type": "MA10跟踪",
    },
    "N字反包": {
        "stop_loss_pct": 0.07,
        "stop_loss_desc": "入场日最低价",
        "take_profit_pct": 0.12,
        "trail_trigger_pct": 0.08,
        "trail_type": "保本",
    },
    "缠论一买": {
        "stop_loss_pct": 0.10,
        "stop_loss_desc": "底分型最低价",
        "take_profit_pct": 0.20,
        "trail_trigger_pct": 0.15,
        "trail_type": "MA5跟踪",
    },
    "缠论二买": {
        "stop_loss_pct": 0.07,
        "stop_loss_desc": "回踩最低价",
        "take_profit_pct": 0.18,
        "trail_trigger_pct": 0.10,
        "trail_type": "MA5跟踪",
    },
    "缠论三买": {
        "stop_loss_pct": 0.05,
        "stop_loss_desc": "中枢上沿-2%",
        "take_profit_pct": 0.15,
        "trail_trigger_pct": 0.10,
        "trail_type": "MA10跟踪",
    },
    "主升浪起爆": {
        "stop_loss_pct": 0.06,
        "stop_loss_desc": "试盘线低点-2%",
        "take_profit_pct": 0.30,
        "trail_trigger_pct": 0.12,
        "trail_type": "MA5跟踪",
    },
    "洗盘结束": {
        "stop_loss_pct": 0.06,
        "stop_loss_desc": "洗盘日最低价",
        "take_profit_pct": 0.15,
        "trail_trigger_pct": 0.08,
        "trail_type": "保本",
    },
    "飞龙在天": {
        "stop_loss_pct": 0.05,
        "stop_loss_desc": "断板最低价",
        "take_profit_pct": 0.20,
        "trail_trigger_pct": 0.15,
        "trail_type": "MA10跟踪",
    },
    "潜龙回首": {
        "stop_loss_pct": 0.08,
        "stop_loss_desc": "回调低点-3%",
        "take_profit_pct": 0.10,
        "trail_trigger_pct": 0.10,
        "trail_type": "保本",
    },
    "平步青云强": {
        "stop_loss_pct": 0.06,
        "stop_loss_desc": "MA5跌破",
        "take_profit_pct": 0.20,
        "trail_trigger_pct": 0.12,
        "trail_type": "MA5跟踪",
    },
    "综合精选": {
        "stop_loss_pct": 0.08,
        "stop_loss_desc": "止损-8%",
        "take_profit_pct": 0.15,
        "trail_trigger_pct": 0.10,
        "trail_type": "保本",
    },
}

STYLES = {
    "连板接力": "🔥进攻",
    "低位放量首板": "📗稳健",
    "趋势加速": "🔥进攻",
    "N字反包": "📗稳健",
    "缠论一买": "🛡️抄底",
    "缠论二买": "📗稳健",
    "缠论三买": "🔥进攻",
    "主升浪起爆": "🔥进攻",
    "洗盘结束": "📗稳健",
    "飞龙在天": "🔥进攻",
    "潜龙回首": "📗稳健",
    "平步青云强": "🔥进攻",
    "综合精选": "📗稳健",
}


# ==================== 核心计算 ====================

def load_stock_klines(code: str, days: int = 250) -> Optional[List]:
    """加载单只股票的日K线（复用 local_screener）"""
    try:
        sys.path.insert(0, str(TOOL_DIR))
        from local_screener import parse_day_file
    except ImportError:
        return None

    if code.startswith(("6", "9", "5")):
        market = "sh"
    elif code.startswith(("0", "3", "2")):
        market = "sz"
    elif code.startswith(("4", "8")):
        market = "bj"
    else:
        return None

    fp = os.path.join(TDX_ROOT, market, "lday", f"{market}{code}.day")
    if not os.path.exists(fp):
        return None
    return parse_day_file(fp, days)


def calc_stop_levels(code: str, entry_price: float, strategy_type: str = "综合精选",
                      klines: list = None) -> Dict:
    """
    计算单只股票的止盈止损位。

    Args:
        code: 股票代码
        entry_price: 入场价格（首次入选时的价格）
        strategy_type: 策略类型（自动识别）
        klines: KLine列表（可选，自动加载）

    Returns:
        {
            "止损价": 68.00,
            "止损幅度": -5.0%,
            "止盈价": 80.00,
            "止盈幅度": +15.0%,
            "跟踪止损价": None,  # 仅利润达标后生效
            "当前利润": +3.2%,
            "建议": "持有 / 止损 / 止盈",
            "信号": "MA5跌破止损",
        }
    """
    rules = STOP_RULES.get(strategy_type, STOP_RULES["综合精选"])
    style = STYLES.get(strategy_type, "📗稳健")

    # 获取最新价格
    if klines is None:
        klines = load_stock_klines(code)

    current_price = entry_price
    if klines and len(klines) >= 2:
        current_price = klines[-1].close

    if entry_price <= 0:
        return {
            "止损价": 0, "止损幅度": 0, "止盈价": 0, "止盈幅度": 0,
            "跟踪止损价": None, "当前利润": 0, "建议": "等待入场",
            "策略": strategy_type, "风格": style,
        }

    # 当前利润
    profit_pct = (current_price - entry_price) / entry_price * 100

    # ---- 定损价 ----
    atr = calc_atr(klines, 14) if klines and len(klines) > 14 else 0
    ma5 = calc_ma(klines, 5) if klines and len(klines) >= 5 else 0
    ma10 = calc_ma(klines, 10) if klines and len(klines) >= 10 else 0

    # 基础止损价：固定百分比
    base_stop_pct = 1 - rules["stop_loss_pct"]
    stop_price = round(entry_price * base_stop_pct, 2)

    # 如果ATR可用且止损幅度 < ATR*2，用ATR修正（保证不被正常波动扫出去）
    if atr > 0 and entry_price > 0:
        atr_stop_pct = atr * 2 / entry_price
        if atr_stop_pct > rules["stop_loss_pct"]:
            # 波动率大时放宽止损
            stop_price = round(entry_price * (1 - atr_stop_pct), 2)

    # MA5/MA10 增强判断（如果可用）
    stop_reason = rules["stop_loss_desc"]
    if ma5 > 0 and strategy_type in ("趋势加速", "平步青云强", "主升浪起爆"):
        ma5_stop = round(ma5, 2)
        if ma5_stop < stop_price:
            stop_price = ma5_stop
            stop_reason = "MA5跌破"

    if ma10 > 0 and strategy_type in ("趋势加速",):
        ma10_stop = round(ma10, 2)
        if ma10_stop > stop_price:
            stop_price = ma10_stop
            stop_reason = "MA10跌破"

    # ---- 止盈价 ----
    take_profit_price = round(entry_price * (1 + rules["take_profit_pct"]), 2)

    # ---- 跟踪止损 ----
    trail_stop_price = None
    trail_active = False

    if profit_pct >= rules["trail_trigger_pct"] * 100:
        trail_active = True
        if rules["trail_type"] == "保本":
            trail_stop_price = round(entry_price * 1.01, 2)  # 成本+1%
        elif rules["trail_type"] == "MA5跟踪" and ma5 > 0:
            trail_stop_price = round(ma5, 2)
        elif rules["trail_type"] == "MA10跟踪" and ma10 > 0:
            trail_stop_price = round(ma10, 2)
        else:
            # 回撤锁定: 最高价回撤8%
            max_prices = [d["price"] for d in (klines or [])] or [current_price]
            peak_price = max(max_prices[-10:])
            trail_stop_price = round(peak_price * 0.92, 2)

        # 跟踪止损不低于基础止损
        if trail_stop_price and trail_stop_price < stop_price:
            trail_stop_price = stop_price

    # ---- 建议 ----
    if current_price <= stop_price and trail_stop_price is None:
        advice = "🛑 止损"
        reason = f"跌破止损价{stop_price}"
    elif trail_stop_price and current_price <= trail_stop_price:
        advice = "🛑 止盈出场"
        reason = f"触发跟踪止损{trail_stop_price}"
    elif current_price >= take_profit_price:
        advice = "💰 部分止盈"
        reason = f"达到止盈目标{take_profit_price}"
    elif trail_active:
        advice = "📈 持有(跟踪中)"
        reason = f"跟踪止损{trail_stop_price}"
    elif profit_pct > 0:
        advice = "📈 持有"
        reason = ""
    else:
        advice = "⏳ 观察"
        reason = "待上涨确认"

    # 止损幅度/止盈幅度（基于现价）
    loss_pct = (stop_price - current_price) / current_price * 100 if current_price > 0 else 0
    profit_target_pct = (take_profit_price - current_price) / current_price * 100 if current_price > 0 else 0

    return {
        "入场价": round(entry_price, 2),
        "现价": round(current_price, 2),
        "当前利润": round(profit_pct, 2),
        "止损价": round(stop_price, 2),
        "止损幅度": round(loss_pct, 2),
        "止盈价": round(take_profit_price, 2),
        "止盈幅度": round(profit_target_pct, 2),
        "跟踪止损价": round(trail_stop_price, 2) if trail_stop_price else None,
        "跟踪激活": trail_active,
        "建议": advice,
        "信号理由": reason,
        "策略": strategy_type,
        "风格": style,
        "ATR": round(atr, 3) if atr > 0 else 0,
        "换手信号": _turnover_signal(profit_pct, strategy_type),
    }


def _turnover_signal(profit: float, strategy: str) -> str:
    """根据利润水平给出操作提示"""
    if profit > 25:
        return "⚠️ 利润>25%，建议分批减仓"
    if profit > 15:
        return "📌 利润>15%，启动跟踪止损"
    if profit > 8:
        return "📌 利润>8%，注意锁利"
    if profit < -5:
        return "⚠️ 亏损>5%，严格止损"
    if profit < -3:
        return "👀 小幅亏损，注意止损线"
    return "✅ 正常持仓"


# ==================== 批量处理跟踪池 ====================

def add_stops_to_tracker(tracker: Dict[str, dict], today_results: List[Dict] = None) -> Dict:
    """
    为跟踪池所有活跃股票补充止盈止损数据。

    Args:
        tracker: load_tracker() 的返回值
        today_results: 今日选股结果（用于识别策略类型）

    Returns:
        更新后的 tracker（每条记录加上 stop_engine 字段）
    """
    # 建立代码→策略映射
    code_strategy = {}
    if today_results:
        for r in today_results:
            code_strategy[r.get("代码", "")] = _detect_strategy_type(r)

    updated = 0
    for code, entry in tracker.items():
        if entry.get("status") == "考虑删除":
            continue

        # 取入场价：首次入选日的价格
        daily = entry.get("daily_chgs", [])
        if not daily:
            continue

        entry_price = daily[0]["price"] if daily else 0
        if entry_price <= 0:
            continue

        # 入场价异常保护：用K线数据校准
        klines = load_stock_klines(code)
        if klines and len(klines) > 5:
            today_close = klines[-1].close
            # 如果入场价远离现价超过3倍，用最近K线修正
            if today_close > 1:
                ratio = entry_price / today_close
                if ratio > 3 or ratio < 0.3:
                    # 尝试从daily_chgs的最近价格反推
                    for d in reversed(daily):
                        if d["price"] > today_close * 0.5 and d["price"] < today_close * 3:
                            entry_price = d["price"]
                            break
                    else:
                        # 仍然异常则跳过
                        continue

        # 策略类型
        strategy = code_strategy.get(code, "综合精选")
        # 如果有历史策略记录则用历史的
        old_strategy = entry.get("stop_engine", {}).get("策略", "")
        if old_strategy and old_strategy != "综合精选":
            strategy = old_strategy

        # 计算止盈止损（klines已在上方加载）
        stops = calc_stop_levels(code, entry_price, strategy, klines)

        entry["stop_engine"] = stops
        updated += 1

    return tracker


def get_stop_report(tracker: Dict[str, dict]) -> str:
    """
    生成每只股票的止盈止损报告段。

    Args:
        tracker: 经过 add_stops_to_tracker 处理的跟踪池

    Returns:
        报告文本
    """
    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append("  止盈止损规则引擎 — 持仓监控")
    lines.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 70)
    lines.append("")

    # 筛选有 stop_engine 数据的活跃股票（过滤数据异常）
    active = []
    for code, entry in tracker.items():
        stops = entry.get("stop_engine", {})
        entry_price = stops.get("入场价", 0)
        current_price = stops.get("现价", 0)
        if entry_price <= 0:
            continue
        if entry.get("status") == "考虑删除":
            continue
        # 价格异常保护：入场价不能远离现价超过5倍（防旧数据错误）
        if current_price > 1 and (entry_price / current_price > 5 or current_price / entry_price > 5):
            continue
        # 过滤太久远且亏损的旧数据
        days = entry.get("days_tracked", 0)
        profit = stops.get("当前利润", 0)
        if days > 90 and profit < -40:
            continue
        stops["代码"] = code
        stops["名称"] = entry.get("name", "")
        stops["跟踪天数"] = days
        active.append(stops)

    # 限制输出数量
    max_show = 30

    if not active:
        lines.append("  暂无活跃持仓（选股后运行 add_stops_to_tracker）")
        return "\n".join(lines)

    # 按建议排序：止损 > 止盈 > 持有
    def _sort_key(s):
        if "止损" in s["建议"]:
            return 0
        if "止盈" in s["建议"]:
            return 1
        if "持有" in s["建议"]:
            return 2
        return 3

    active.sort(key=_sort_key)

    lines.append(f"  {'代码':<8} {'名称':<10} {'策略':<10} {'入场':<8} {'现价':<8} {'利润':<7} {'止损':<8} {'止盈':<8} {'跟踪':<8} {'建议'}")
    lines.append(f"  {'-'*8} {'-'*10} {'-'*10} {'-'*8} {'-'*8} {'-'*7} {'-'*8} {'-'*8} {'-'*8} {'-'*20}")

    stop_alarms = []
    profit_alarms = []

    for s in active[:max_show]:
        code = s.get("代码", "")
        name = s.get("名称", "")[:6]
        strategy = s.get("策略", "")[:6]
        entry_p = s.get("入场价", 0)
        curr_p = s.get("现价", 0)
        profit = s.get("当前利润", 0)
        stop_p = s.get("止损价", 0)
        tp_p = s.get("止盈价", 0)
        trail_p = s.get("跟踪止损价", 0)
        advice = s.get("建议", "")

        profit_str = f"{profit:+.1f}%"
        if abs(profit) >= 10:
            profit_str = f"{profit:+.1f}%!"

        trail_str = str(trail_p) if trail_p else "—"
        style = s.get("风格", "")

        lines.append(f"  {code:<8} {name:<10} {style:<10} {entry_p:<8} {curr_p:<8} {profit_str:<7} {stop_p:<8} {tp_p:<8} {trail_str:<8} {advice[:12]}")

        # 收集预警
        if "止损" in advice:
            stop_alarms.append(f"{name}({code}) {profit:+.1f}% 止损{stop_p}")
        if "止盈" in advice and "部分" in advice:
            profit_alarms.append(f"{name}({code}) +{profit:.1f}% 达止盈位")

    lines.append("")

    # 预警汇总
    if stop_alarms:
        lines.append("  ⚠️ 止损预警:")
        for a in stop_alarms[:5]:
            lines.append(f"    🛑 {a}")
    if profit_alarms:
        lines.append("  ✅ 止盈提示:")
        for a in profit_alarms[:3]:
            lines.append(f"    💰 {a}")

    # 统计
    holding = sum(1 for s in active if "持有" in s["建议"])
    stopping = sum(1 for s in active if "止损" in s["建议"])
    taking = sum(1 for s in active if "止盈" in s["建议"])

    lines.append("")
    total_not_shown = len(active) - max_show if len(active) > max_show else 0
    extra = f" (还有{total_not_shown}只未显示)" if total_not_shown > 0 else ""
    lines.append(f"  持仓{holding}只 | 止损信号{stopping}只 | 止盈信号{taking}只{extra}")
    lines.append("")

    return "\n".join(lines)


# ==================== 集成到 run_selector ====================

def enhance_tracker_with_stops(tracker: Dict[str, dict],
                                today_results: List[Dict] = None) -> Dict:
    """
    给跟踪池加止盈止损数据 + 保存。

    Args:
        tracker: 原始跟踪池
        today_results: 今日选股结果

    Returns:
        更新并保存后的跟踪池
    """
    tracker = add_stops_to_tracker(tracker, today_results)

    # 保存回 tracking.json
    try:
        from local_screener import save_tracker
        save_tracker(tracker)
    except ImportError:
        pass

    return tracker


# ==================== 独立运行 ====================

if __name__ == "__main__":
    import sys, os
    sys.stdout = open(1, 'w', encoding='utf-8', closefd=False)

    print("=" * 50)
    print("  止盈止损规则引擎")
    print("=" * 50)
    print()

    # 加载跟踪池
    try:
        sys.path.insert(0, str(TOOL_DIR))
        from local_screener import load_tracker
        tracker = load_tracker()
    except ImportError:
        tracker = {}

    if not tracker:
        print("  跟踪池为空，请先运行 run_selector.py 选股")
        exit(0)

    print(f"  跟踪池: {len(tracker)} 只")

    # 计算止盈止损
    tracker = add_stops_to_tracker(tracker)
    report = get_stop_report(tracker)
    print(report)

    # 保存
    from local_screener import save_tracker
    save_tracker(tracker)
    print(f"\n  [OK] 止盈止损数据已保存到 tracking.json")
