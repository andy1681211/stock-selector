#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
筹码分布模型 v1.1
==================
基于通达信日K线数据，用"历史成交量-价格分布法"近似计算筹码分布。
可替代通达信的 WINNER 函数。

筹码图中:
  筹码柱 — 每一根横向柱子代表一个价格，柱子长短=该价格对应的成交量
  颜色   — 黄色=获利盘(在现价下方)  白色=套牢盘(在现价上方)
  平均成本线 — 中间黄色横线=全市场平均持仓成本
  获利比例 — 现价位置的获利盘比例，比例越高说明越多人在赚钱

换手率参考:
  1%-3%   萎靡不振，机构不理
  3%-5%   试探性建仓，不连板
  5%-10%  多空分歧，缓慢吸筹
  10%-20% 主力积极买卖，下跌则可能是温和洗盘
  20%-30% 多空激烈博弈，低位=暴力吸筹，高位=可能出货
  30%以上 热门股才有，可能主力出货置换筹码

用法:
  from chip_distribution import calc_winner, calc_chip_metrics, interpret_chip, analyze_turnover_rate
  winner_105 = calc_winner(klines, price*1.05)   # ≈ WINNER(C*1.05)
  winner_095 = calc_winner(klines, price*0.95)   # ≈ WINNER(C*0.95)
  metrics = calc_chip_metrics(klines)            # 完整的筹码指标
  interpretation = interpret_chip(metrics)        # 筹码解读
  turn = analyze_turnover_rate(klines)           # 换手率分析
"""
import numpy as np
from typing import List, Dict, Tuple


def _get_klines_data(klines):
    """提取K线数据为numpy数组"""
    n = len(klines)
    high = np.array([k.high for k in klines], dtype=float)
    low = np.array([k.low for k in klines], dtype=float)
    close = np.array([k.close for k in klines], dtype=float)
    volume = np.array([k.volume for k in klines], dtype=float)
    return high, low, close, volume


def build_chip_distribution(klines, lookback: int = 250, bins: int = 200) -> Tuple[np.ndarray, np.ndarray, float, float]:
    """
    构建筹码分布直方图

    Args:
        klines: KLine对象列表
        lookback: 回溯周期（天）
        bins: 价格区间数量（精度）

    Returns:
        (price_bins, distribution, min_price, max_price)
        price_bins: 价格区间中心点
        distribution: 每个价格区间的筹码量
        min_price: 最低价
        max_price: 最高价
    """
    segment = klines[-lookback:] if len(klines) > lookback else klines
    if len(segment) < 20:
        return np.array([]), np.array([]), 0, 0

    high, low, close, volume = _get_klines_data(segment)

    min_price = min(low)
    max_price = max(high)

    if max_price <= min_price:
        max_price = min_price + 0.01

    price_bins = np.linspace(min_price, max_price, bins)
    bin_width = price_bins[1] - price_bins[0]
    distribution = np.zeros(bins)

    for i in range(len(segment)):
        k_high = high[i]
        k_low = low[i]
        k_vol = volume[i]

        if k_high <= k_low or k_vol <= 0:
            continue

        # 每日成交量均匀分布在最高-最低之间
        vol_per_unit = k_vol / (k_high - k_low)

        # 找到该日K线覆盖的价格区间索引
        start_idx = max(0, int((k_low - min_price) / bin_width))
        end_idx = min(bins - 1, int((k_high - min_price) / bin_width))

        if start_idx > end_idx:
            continue

        # 该日成交量加到对应价格区间
        for j in range(start_idx, end_idx + 1):
            p_low = min_price + j * bin_width
            p_high = p_low + bin_width
            overlap = min(k_high, p_high) - max(k_low, p_low)
            if overlap > 0:
                distribution[j] += overlap * vol_per_unit

    return price_bins, distribution, min_price, max_price


def calc_winner(klines, price: float, lookback: int = 250, bins: int = 200) -> float:
    """
    近似通达信 WINNER 函数

    WINNER(X) = 筹码成本 ≤ X 的比例

    Args:
        klines: KLine对象列表
        price: 目标价格
        lookback: 回溯周期

    Returns:
        0-100 的百分比值
    """
    price_bins, distribution, min_p, max_p = build_chip_distribution(klines, lookback, bins)

    if len(price_bins) == 0 or np.sum(distribution) == 0:
        return 0.0

    if price <= min_p:
        return 0.0
    if price >= max_p:
        return 100.0

    total_chips = np.sum(distribution)
    # 找到价格对应的索引
    idx = int((price - min_p) / (price_bins[1] - price_bins[0]))
    idx = max(0, min(idx, len(price_bins) - 1))

    # 累加低于该价格的所有筹码
    chips_below = np.sum(distribution[:idx + 1])
    ratio = chips_below / total_chips * 100.0
    return min(100.0, max(0.0, ratio))


def calc_chip_metrics(klines, lookback: int = 250, bins: int = 200) -> Dict:
    """
    计算完整的筹码指标（对应通达信公式的三个核心值）

    通达信公式对应关系:
        A02 = WINNER(C*1.05)*100  →  price_up5_winner
        A03 = WINNER(C*0.95)*100  →  price_down5_winner
        获利盘(10) = A03          →  profit_chip
        浮动筹码(10) = A02 - A03  →  float_chip
        套牢盘(10) = 100 - A02    →  locked_chip

    Returns:
        {
            "price_up5_winner": 现价*1.05位置的获利比例(%),  # ≈ A02
            "price_down5_winner": 现价*0.95位置的获利比例(%), # ≈ A03
            "profit_chip": 深度获利盘(%),                     # 成本低于现价95%
            "float_chip": 浮动筹码(%),                       # 成本在现价±5%之间
            "locked_chip": 套牢盘(%),                        # 成本高于现价105%
            "cost_distribution": 筹码分布详情,
            "chip_concentration": 筹码集中度评分(0-100),
        }
    """
    c = klines[-1]
    current_price = c.close

    price_bins, distribution, min_p, max_p = build_chip_distribution(klines, lookback, bins)

    if len(price_bins) == 0 or np.sum(distribution) == 0:
        return {"profit_chip": 0, "float_chip": 0, "locked_chip": 0, "chip_concentration": 0}

    # 计算三个关键值
    winner_up5 = calc_winner(klines, current_price * 1.05, lookback, bins)
    winner_down5 = calc_winner(klines, current_price * 0.95, lookback, bins)

    # 通达信公式对应
    profit_chip = winner_down5          # 获利盘: 成本低于95%现价
    float_chip = winner_up5 - winner_down5  # 浮动筹码: 成本在95%-105%之间
    locked_chip = 100 - winner_up5      # 套牢盘: 成本高于105%现价

    # 筹码集中度: 看浮动筹码大小 + 获利盘和套牢盘的分布
    # 浮动筹码越小 + 一方占优 = 越集中
    if float_chip < 15:
        if profit_chip > 60:
            concentration = 85 + (60 - profit_chip) / 60 * 15  # 获利集中
            conc_desc = "高度集中(获利)"
        elif locked_chip > 60:
            concentration = 85 + (60 - locked_chip) / 60 * 15  # 套牢集中
            conc_desc = "高度集中(套牢)"
        else:
            concentration = 60
            conc_desc = "相对集中"
    elif float_chip < 30:
        concentration = 50 - (float_chip - 15) / 15 * 20
        conc_desc = "一般"
    else:
        concentration = max(10, 30 - (float_chip - 30) / 70 * 20)
        conc_desc = "分散"

    # 筹码峰（分布中的最高峰位置）
    peak_idx = np.argmax(distribution)
    peak_price = min_p + peak_idx * (price_bins[1] - price_bins[0]) if len(price_bins) > 0 else 0
    peak_ratio = (peak_price - current_price) / current_price * 100 if current_price > 0 else 0

    # 当前价格在分布中的分位数
    winner_current = calc_winner(klines, current_price, lookback, bins)

    return {
        "price_up5_winner": round(winner_up5, 1),
        "price_down5_winner": round(winner_down5, 1),
        "profit_chip": round(profit_chip, 1),
        "float_chip": round(float_chip, 1),
        "locked_chip": round(locked_chip, 1),
        "winner_current": round(winner_current, 1),
        "chip_concentration": round(concentration, 0),
        "concentration_desc": conc_desc,
        "peak_ratio": round(peak_ratio, 1),  # 筹码峰相对现价位置(%)
        "peak_price": round(peak_price, 2),
        "current_price": round(current_price, 2),
    }


# ============================================================
#  基于筹码分布的选股条件
# ============================================================

def chip_screen_conditions(klines) -> Dict:
    """
    基于筹码分布的选股条件（对应通达信指标的核心思路）

    条件1: 底部获利盘 > 50%  + 浮动筹码 < 20%  = 主力底部建仓完毕
    条件2: 获利盘 > 60%  + 套牢盘 < 20%  = 上方无压力，容易拉升
    条件3: 浮动筹码 > 40%  = 分歧大，需要洗盘
    条件4: 筹码集中度 > 70  + 获利盘 > 40%  = 主力控盘高
    条件5: 筹码峰在现价下方 + 获利盘 > 50% = 支撑强
    """
    metrics = calc_chip_metrics(klines)
    if not metrics:
        return {"score": 0, "signals": [], "metrics": metrics}

    signals = []
    score = 0

    cp = metrics["profit_chip"]
    fc = metrics["float_chip"]
    lc = metrics["locked_chip"]
    cc = metrics["chip_concentration"]
    pr = metrics["peak_ratio"]

    # 条件1: 底部建仓完毕（获利盘>50% + 浮动筹码<20%）
    if cp > 50 and fc < 20:
        signals.append("底部建仓完毕")
        score += 25
    elif cp > 30 and fc < 25:
        signals.append("建仓中")
        score += 15

    # 条件2: 上方无压力（获利盘>60% + 套牢盘<20%）
    if cp > 60 and lc < 20:
        signals.append("上方无压力")
        score += 25

    # 条件3: 筹码集中
    if cc >= 75 and cp > 40:
        signals.append("高度控盘")
        score += 25
    elif cc >= 60:
        signals.append("筹码集中")
        score += 15

    # 条件4: 筹码峰在现价下方（支撑强）
    if pr < -5 and cp > 50:
        signals.append("筹码峰在下方(强支撑)")
        score += 15
    elif pr < -3:
        signals.append("筹码峰偏下(有支撑)")
        score += 8

    # 条件5: 套牢盘极低
    if lc < 10:
        signals.append("几乎无套牢盘")
        score += 15
    elif lc < 20:
        signals.append("套牢盘少")
        score += 8

    # 条件6: 浮动筹码低（筹码锁定好）
    if fc < 10:
        signals.append("筹码锁定好")
        score += 10
    elif fc < 20:
        signals.append("浮动盘少")
        score += 5

    # 条件7: 获利盘>套牢盘（多头主导）
    if cp > lc:
        signals.append("多头主导")
        score += 10
        if cp > lc * 2:
            signals.append("绝对优势")
            score += 10

    if not signals:
        signals.append("无显著信号")

    return {
        "score": min(100, score),
        "signals": signals,
        "metrics": metrics,
    }


# ============================================================
#  筹码解读 + 换手率分析
# ============================================================

def interpret_chip(metrics: Dict) -> Dict:
    """
    筹码分布解读（通达信筹码图对应关系）

    筹码柱 — 每一根横向柱子代表一个价格，柱子长短=成交量
    颜色   — 黄色=获利盘(现价下方筹码)  白色=套牢盘(现价上方筹码)
    平均成本线 — 中间黄色横线=全市场平均持仓成本
    获利比例 — 现价位置获利盘百分比

    Args:
        metrics: calc_chip_metrics 返回的筹码指标

    Returns:
        {
            "avg_cost": 平均成本价,
            "chip_color_desc": 筹码颜色解读,
            "chip_pillar_desc": 筹码柱形态解读,
            "avg_cost_line_desc": 平均成本线解读,
            "profit_ratio_desc": 获利比例解读,
        }
    """
    if not metrics:
        return {"avg_cost": 0, "chip_color_desc": "数据不足", "chip_pillar_desc": "", "avg_cost_line_desc": "", "profit_ratio_desc": ""}

    cp = metrics.get("profit_chip", 0)
    fc = metrics.get("float_chip", 0)
    lc = metrics.get("locked_chip", 0)
    cur = metrics.get("current_price", 0)
    conc = metrics.get("concentration_desc", "")
    peak = metrics.get("peak_ratio", 0)

    # 估算平均成本（筹码峰最佳位置如果有的话）
    if peak != 0 and cur > 0:
        avg_cost = cur * (1 + peak / 100)
    else:
        avg_cost = cur

    # 筹码颜色解读
    if cp > 70:
        color_desc = f"黄色获利盘占{cp:.0f}%（绝大部分人在赚钱）"
    elif cp > 50:
        color_desc = f"黄色获利盘占{cp:.0f}%，白色套牢盘{lc:.0f}%（多数人赚钱）"
    elif cp > 30:
        color_desc = f"白色套牢盘占{lc:.0f}%，黄色获利盘{cp:.0f}%（多数人被套）"
    else:
        color_desc = f"白色套牢盘占{lc:.0f}%（绝大部分人被套，上方压力大）"

    # 筹码柱形态解读
    if "高度集中" in conc or fc < 10:
        pillar_desc = "筹码柱高度集中，柱子集中在窄价格区间=主力高度控盘"
    elif fc < 20:
        pillar_desc = "筹码柱相对集中，浮动筹码少=筹码锁定较好"
    elif fc > 40:
        pillar_desc = "筹码柱分散在各价格区间，浮动筹码多=市场分歧大"
    else:
        pillar_desc = "筹码柱分布均匀，市场处于正常博弈状态"

    # 平均成本线解读
    if avg_cost > 0 and cur > 0:
        if cur > avg_cost:
            cost_desc = f"现价{cur:.2f}在平均成本{avg_cost:.2f}上方{(cur-avg_cost)/avg_cost*100:+.1f}%=市场整体盈利"
        else:
            cost_desc = f"现价{cur:.2f}在平均成本{avg_cost:.2f}下方{(cur-avg_cost)/avg_cost*100:+.1f}%=市场整体亏损"
    else:
        cost_desc = "数据不足"

    # 获利比例解读
    if cp > 80:
        profit_desc = f"获利比例{cp:.0f}%（极高，注意获利盘兑现风险）"
    elif cp > 60:
        profit_desc = f"获利比例{cp:.0f}%（偏高，上方压力小，拉升阻力小）"
    elif cp > 40:
        profit_desc = f"获利比例{cp:.0f}%（适中，上有压力下有支撑）"
    elif cp > 20:
        profit_desc = f"获利比例{cp:.0f}%（偏低，套牢盘较重）"
    else:
        profit_desc = f"获利比例{cp:.0f}%（极低，深度套牢区）"

    return {
        "avg_cost": round(avg_cost, 2),
        "chip_color_desc": color_desc,
        "chip_pillar_desc": pillar_desc,
        "avg_cost_line_desc": cost_desc,
        "profit_ratio_desc": profit_desc,
    }


def analyze_turnover_rate(klines, lookback: int = 250) -> Dict:
    """
    换手率分析

    换手率参考:
      1%-3%   萎靡不振，机构不理
      3%-5%   试探性建仓，不连板
      5%-10%  多空分歧，缓慢吸筹
      10%-20% 主力积极买卖
      20%-30% 多空激烈博弈
      30%以上 热门股出货可能

    注意事项:
      - 股票的流通市值不同，换手率的基数不同
      - 小盘股换手率天生高于大盘股
      - 需结合股价位置判断(高位>低位)

    Args:
        klines: KLine列表
        lookback: 回溯天数

    Returns:
        {
            "current_tr": 当前换手率(%),
            "avg_tr": 日均换手率(%),
            "tr_rank": 换手率档位(1-6),
            "tr_desc": 换手率解读,
            "volume_status": 量能状态,
            "action_hint": 操作提示,
        }
    """
    if len(klines) < 5:
        return {}

    c = len(klines) - 1
    today = klines[c]

    # 估算流通股本：从日成交量和换手率反推
    # 用最大日成交量估算（假设某天换手率达100%为极端）
    max_vol = max(k.volume for k in klines[-lookback:]) if len(klines) > lookback else max(k.volume for k in klines)
    # 从通达信数据估算，.day文件不含换手率，需从成交量估算流通股本
    # 假设近250天最大日换手30%=极端值，推估流通股本
    if max_vol > 0:
        estimated_shares = max_vol / 0.3  # 假设最大日换手30%
    else:
        estimated_shares = 1

    # 当前换手率估算
    if estimated_shares > 0:
        current_tr = today.volume / estimated_shares * 100
    else:
        current_tr = 0

    # 历史平均换手率
    avg_vol = sum(k.volume for k in klines[-min(60, len(klines)):]) / min(60, len(klines))
    avg_tr = avg_vol / estimated_shares * 100 if estimated_shares > 0 else 0

    # 量比
    if len(klines) >= 6:
        avg_vol_5 = sum(klines[j].volume for j in range(c-5, c)) / 5
        vol_ratio = today.volume / avg_vol_5 if avg_vol_5 > 0 else 0
    else:
        vol_ratio = 1

    # 换手率档位判断
    if current_tr > 30:
        tr_rank = 6
        tr_desc = "极高换手(>30%): 题材热门股，多空激战，警惕主力出货"
        volume_status = "极端放量"
    elif current_tr > 20:
        tr_rank = 5
        tr_desc = "高换手(20-30%): 多空激烈博弈，低位=暴力吸筹，高位=可能出货"
        volume_status = "巨量"
    elif current_tr > 10:
        tr_rank = 4
        tr_desc = "较高换手(10-20%): 主力资金积极买卖，下跌则可能是温和洗盘"
        volume_status = "放量"
    elif current_tr > 5:
        tr_rank = 3
        tr_desc = "中等换手(5-10%): 多空分歧，主力缓慢吸筹中"
        volume_status = "活跃"
    elif current_tr > 3:
        tr_rank = 2
        tr_desc = "温和换手(3-5%): 试探性建仓，尚未到爆发阶段"
        volume_status = "温和"
    else:
        tr_rank = 1
        tr_desc = "低换手(1-3%): 萎靡不振，机构不理，题材过于传统"
        volume_status = "低迷"

    # 结合量比的细化判断
    if vol_ratio > 2 and current_tr > 10:
        action_hint = "放量异动，关注突破方向"
    elif vol_ratio < 0.5 and current_tr < 3:
        action_hint = "缩量低迷，观望为主"
    elif current_tr > 20 and today.pct_chg > 0:
        action_hint = "高换手上涨，若低位=暴力吸筹，若高位=警惕出货"
    elif current_tr > 20 and today.pct_chg < 0:
        action_hint = "高换手下跌，主力可能出货，谨慎"
    elif current_tr < 3 and today.pct_chg > 0:
        action_hint = "缩量上涨，筹码锁定好，趋势延续"
    else:
        action_hint = "量能正常，按趋势操作"

    return {
        "current_tr": round(current_tr, 2),
        "avg_tr": round(avg_tr, 2),
        "tr_rank": tr_rank,
        "tr_desc": tr_desc,
        "volume_status": volume_status,
        "vol_ratio": round(vol_ratio, 2),
        "action_hint": action_hint,
    }
