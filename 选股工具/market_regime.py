# -*- coding: utf-8 -*-
"""
市场状态识别 + 策略推荐引擎
模仿 Hermes Skill Router 的架构思想：
  先判断"当前市场是什么情况" → 再推荐"当前最合适的策略"

市场状态分类:
  - 趋势市(牛): 均线多头排列, 指数上涨, 量能放大
  - 震荡市(盘整): 均线粘合, 指数横盘, 量能萎缩
  - 弱势市(熊): 均线空头排列, 指数下跌
  - 急跌市(恐慌): 指数连续大跌, 恐慌情绪

策略推荐:
  趋势市 → 趋势加速 + 连板接力
  震荡市 → N字反包 + 低位放量首板
  弱势市 → 缠论一买/底背驰 (抄底)
  急跌市 → 防狼术 (空仓)
"""
import os
import numpy as np
import talib
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

# ==================== 市场状态识别 ====================

def calc_ma(closes: List[float], period: int) -> List[float]:
    """移动平均线"""
    arr = np.array(closes[-period*3:], dtype=float)
    result = talib.SMA(arr, period)
    return [float(v) if not np.isnan(v) else 0.0 for v in result]


def detect_market_regime(index_klines: List) -> Dict:
    """
    识别当前市场状态（基于大盘指数）

    参数: index_klines = [(日期, 收盘), ...] 或 KLine对象列表

    返回:
      regime: 趋势市|震荡市|弱势市|急跌市
      trend: 上升|下降|横盘
      strength: 强|中|弱
      suggestion: 策略建议
    """
    if len(index_klines) < 60:
        return {"regime": "未知", "trend": "未知", "strength": "中",
                "suggestion": "数据不足，按默认策略运行", "score": 0}

    # 提取收盘价
    if hasattr(index_klines[0], 'close'):
        closes = [k.close for k in index_klines]
        volumes = [k.volume for k in index_klines]
    else:
        closes = [k[1] for k in index_klines]
        volumes = [k[2] if len(k) > 2 else 100 for k in index_klines]

    closes_arr = np.array(closes, dtype=float)

    # ---- 计算均线 ----
    ma5_list = calc_ma(closes, 5)
    ma20_list = calc_ma(closes, 20)
    ma60_list = calc_ma(closes, 60)

    ma5 = ma5_list[-1]
    ma10 = calc_ma(closes, 10)[-1]
    ma20 = ma20_list[-1]
    ma60 = ma60_list[-1]

    # ---- 均线排列 ----
    bullish = ma5 > ma10 > ma20 > ma60  # 多头排列
    bearish = ma5 < ma10 < ma20 < ma60  # 空头排列
    sticky = abs(ma5 - ma20) / ma20 < 0.03 if ma20 > 0 else False  # 均线粘合

    # ---- 近期涨跌幅 ----
    recent_5d = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
    recent_10d = (closes[-1] - closes[-11]) / closes[-11] * 100 if len(closes) >= 11 else 0
    recent_20d = (closes[-1] - closes[-21]) / closes[-21] * 100 if len(closes) >= 21 else 0

    # ---- MACD ----
    dif, dea, hist = talib.MACD(closes_arr, 12, 26, 9)
    macd_bull = dif[-1] > dea[-1] if not np.isnan(dif[-1]) else False
    macd_hist_rising = hist[-1] > hist[-2] if not np.isnan(hist[-1]) and not np.isnan(hist[-2]) else False

    # ---- 量能 ----
    vol_ma5 = np.mean(volumes[-5:]) if len(volumes) >= 5 else 0
    vol_ma20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else 0
    vol_ratio = vol_ma5 / vol_ma20 if vol_ma20 > 0 else 1.0

    # ---- 评分系统 ----
    score = 0
    if bullish: score += 30
    if macd_bull: score += 20
    if macd_hist_rising: score += 10
    if recent_5d > 0: score += 10
    if recent_20d > 5: score += 10
    if vol_ratio > 1.2: score += 10  # 放量
    if vol_ratio > 1.5: score += 5

    if bearish: score -= 30
    if recent_5d < -3: score -= 10
    if recent_10d < -5: score -= 10
    if vol_ratio < 0.7: score -= 5  # 缩量下跌不好

    # ---- 状态判断 ----
    if recent_5d < -5 and recent_10d < -8:
        regime = "急跌市"
        trend = "下降"
        strength = "弱"
        suggestion = "防狼术：建议空仓或极轻仓，等底背驰确认"
    elif bullish and score >= 40:
        regime = "趋势市"
        trend = "上升"
        strength = "强" if score >= 60 else "中"
        suggestion = "趋势加速 + 连板接力（顺势而为）"
    elif sticky or (-20 <= score <= 20):
        regime = "震荡市"
        trend = "横盘"
        strength = "中"
        suggestion = "N字反包 + 低位放量首板（高抛低吸）"
    elif bearish or score <= -10:
        regime = "弱势市"
        trend = "下降"
        strength = "弱"
        suggestion = "缠论精选：寻找一买/底背驰机会（左侧交易）"
    else:
        regime = "震荡市"
        trend = "横盘"
        strength = "中"
        suggestion = "多维精选 + 缠论二买（稳健为主）"

    return {
        "regime": regime,
        "trend": trend,
        "strength": strength,
        "score": score,
        "suggestion": suggestion,
        "ma5": round(ma5, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "macd_bull": "多头" if macd_bull else "空头",
        "recent_5d": round(recent_5d, 2),
        "recent_20d": round(recent_20d, 2),
        "vol_ratio": round(vol_ratio, 2),
    }


def get_strategy_weights(regime_info: Dict) -> Dict[str, float]:
    """
    根据市场状态，返回各策略的推荐权重

    权重范围: 0.0 (不推荐) ~ 2.0 (强烈推荐)

    返回示例:
    {
        "缠论精选": 1.5,
        "低位放量首板": 1.0,
        "连板接力弱转强": 0.5,
        "趋势加速": 0.0,
        "N字反包": 1.5,
        "多维精选": 1.0,
    }
    """
    regime = regime_info.get("regime", "震荡市")

    weights = {
        "趋势市": {
            "低位放量首板": 1.0,    # 趋势好，首板溢价高
            "连板接力弱转强": 1.5,  # 趋势好，连板概率大
            "趋势加速": 2.0,        # 主升浪，最该做
            "N字反包": 0.8,        # 回调就是机会
            "多维精选": 1.2,
            "缠论精选": 1.2,        # 三买为主
        },
        "震荡市": {
            "低位放量首板": 1.5,    # 震荡市找突破
            "连板接力弱转强": 0.5,  # 连板难持续
            "趋势加速": 0.3,        # 趋势难持续
            "N字反包": 1.8,        # 高抛低吸首选
            "多维精选": 1.2,
            "缠论精选": 1.0,        # 二买为主
        },
        "弱势市": {
            "低位放量首板": 0.3,    # 弱势首板容易炸
            "连板接力弱转强": 0.1,  # 高位接力风险大
            "趋势加速": 0.0,        # 没有趋势
            "N字反包": 0.5,        # 难反包
            "多维精选": 0.5,
            "缠论精选": 2.0,        # 寻找一买/背驰！重点
        },
        "急跌市": {
            "低位放量首板": 0.0,
            "连板接力弱转强": 0.0,
            "趋势加速": 0.0,
            "N字反包": 0.0,
            "多维精选": 0.0,
            "缠论精选": 1.0,        # 观望，等底背驰确认
        },
    }

    return weights.get(regime, weights["震荡市"])


def format_market_report(regime: Dict, weights: Dict) -> str:
    """生成市场状态报告文本"""
    lines = []
    lines.append("=" * 60)
    lines.append(f"  市场状态识别报告")
    lines.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 60)
    lines.append(f"")
    lines.append(f"  【当前状态】{regime['regime']}")
    lines.append(f"  【趋势方向】{regime['trend']}  |  【强度】{regime['strength']}  |  【综合评分】{regime['score']}")
    lines.append(f"  【短期涨幅】5日:{regime['recent_5d']}%  20日:{regime['recent_20d']}%")
    lines.append(f"  【均线位置】MA5:{regime['ma5']}  MA20:{regime['ma20']}  MA60:{regime['ma60']}")
    lines.append(f"  【MACD状态】{regime['macd_bull']}  |  【量能比】{regime['vol_ratio']}")
    lines.append(f"  【策略建议】{regime['suggestion']}")
    lines.append(f"")
    lines.append(f"  ┌─ 策略推荐权重 ─────────────────────┐")

    # 按权重排序
    sorted_w = sorted(weights.items(), key=lambda x: -x[1])
    for name, w in sorted_w:
        bar = "█" * int(w * 5)
        label = f"{name}:"
        lines.append(f"  │ {label:<16} {bar:<10} {w:.1f} │")

    lines.append(f"  └────────────────────────────────────┘")
    lines.append(f"")
    lines.append(f"  权重说明: 2.0=强烈推荐  1.0=正常  0.5=谨慎  0.0=不推荐")
    lines.append(f"")

    return "\n".join(lines)
