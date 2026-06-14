#!/usr/bin/env python3
"""
七角色分析师圆桌会议 — 多维度评分系统
港大交易分析框架

7个角色:
  📈 趋势跟踪者 → 方向 (均线/MACD/缠论)
  💰 价值投资者 → 估值 (PE/PB/基本面评分)
  ⚡ 动量交易者 → 热度 (量比/RSI/涨停基因)
  📉 逆向投资者 → 是否过度反应 (超买超卖/回调幅度)
  🔍 基本面分析师 → 质地 (ROE/毛利率/负债率)
  🛡️ 风险管理师 → 最坏能亏多少 (止损位/最大回撤)
  🎯 事件驱动交易者 → 催化剂 (涨停/试盘/龙模式)
"""
from typing import Dict, List, Tuple
import numpy as np
from chip_distribution import analyze_turnover_rate


def seven_roles_analysis(klines: list, chip_metrics: dict = None,
                          fin_summary: dict = None) -> Dict:
    """
    七角色圆桌会议分析

    Args:
        klines: KLine列表
        chip_metrics: 筹码分布指标（可选）
        fin_summary: 基本面摘要（可选）

    Returns:
        {每角色的评分+判断+建议, 综合评分, 总评}
    """
    from local_screener import calc_ma, calc_macd, calc_rsi, calc_vr
    from local_screener import is_first_buy_point, is_second_buy_point, is_third_buy_point

    if len(klines) < 60:
        return {}

    c = len(klines) - 1
    today = klines[c]

    # 计算公共指标
    ma5 = calc_ma(klines, 5)[-1]
    ma10 = calc_ma(klines, 10)[-1]
    ma20 = calc_ma(klines, 20)[-1]
    ma60 = calc_ma(klines, 60)[-1]
    dif, dea, hist = calc_macd(klines)
    rsi6 = calc_rsi(klines, 6)[-1]
    rsi14 = calc_rsi(klines, 14)[-1]
    vr = calc_vr(klines, 5)[-1]
    prev_5d = sum(k.pct_chg for k in klines[-6:-1])
    prev_20d = sum(k.pct_chg for k in klines[-21:-1])

    roles = {}
    total_score = 0
    max_score = 0

    # ============================================================
    # 📈 趋势跟踪者 → 方向 (30分)
    # ============================================================
    trend = {"scores": [], "desc": []}
    # 均线方向
    if ma5 > ma10 > ma20 and ma20 > ma60:
        trend["scores"].append(25)
        trend["desc"].append("均线多头排列")
    elif ma5 > ma10 and ma20 > ma60:
        trend["scores"].append(18)
        trend["desc"].append("短期向上+中期多头")
    elif ma5 > ma10:
        trend["scores"].append(12)
        trend["desc"].append("短期向上")
    else:
        trend["scores"].append(5)
        trend["desc"].append("短期回调")

    if today.close > ma20:
        trend["scores"].append(5)
        trend["desc"].append("在MA20上")
    else:
        trend["scores"].append(1)
        trend["desc"].append("在MA20下")

    if dif[-1] > dea[-1]:
        trend["scores"].append(5)
        trend["desc"].append("MACD多头")
    else:
        trend["scores"].append(0)
        trend["desc"].append("MACD空头")

    trend_score = sum(trend["scores"])
    trend_max = 35
    total_score += trend_score
    max_score += trend_max

    roles["趋势跟踪者"] = {
        "icon": "📈", "score": trend_score, "max": trend_max,
        "pct": round(trend_score / trend_max * 100),
        "desc": " | ".join(trend["desc"]),
        "verdict": "多头趋势✅" if trend_score >= 25 else ("中性" if trend_score >= 15 else "空头趋势❌"),
    }

    # ============================================================
    # 💰 价值投资者 → 估值 (15分)
    # ============================================================
    value_score = 0
    val_desc = []
    val_max = 15

    if fin_summary:
        pe = fin_summary.get("动态PE", 0)
        pb = fin_summary.get("PB", 0)
        roe = fin_summary.get("roe", 0)
        debt = fin_summary.get("debt_ratio", 100)

        if 0 < pe < 30:
            value_score += 5
            val_desc.append(f"PE合理({pe})")
        elif pe > 50:
            value_score += 1
            val_desc.append(f"PE偏高({pe})")
        elif pe <= 0:
            value_score += 2
            val_desc.append("亏损无PE")

        if roe > 15:
            value_score += 5
            val_desc.append(f"ROE优秀({roe:.1f}%)")
        elif roe > 8:
            value_score += 3
            val_desc.append(f"ROE一般({roe:.1f}%)")
        else:
            val_desc.append(f"ROE偏低({roe:.1f}%)")

        if debt < 50:
            value_score += 5
            val_desc.append("低负债")
        elif debt < 70:
            value_score += 3
            val_desc.append("负债适中")
        else:
            val_desc.append(f"高负债({debt:.0f}%)")
    else:
        # 无基本面数据，用价格相对位置粗略估值
        if len(klines) >= 250:
            year_high = max(k.high for k in klines[-250:])
            year_low = min(k.low for k in klines[-250:])
            if year_high > year_low:
                pos = (today.close - year_low) / (year_high - year_low) * 100
                if pos < 30:
                    value_score += 10
                    val_desc.append("年线低位")
                elif pos > 80:
                    value_score += 2
                    val_desc.append("年线高位")
                else:
                    value_score += 5
                    val_desc.append("年线中位")
        else:
            value_score += 5
            val_desc.append("数据不足")

    total_score += value_score
    max_score += val_max
    roles["价值投资者"] = {
        "icon": "💰", "score": value_score, "max": val_max,
        "pct": round(value_score / val_max * 100),
        "desc": " | ".join(val_desc),
        "verdict": "估值合理✅" if value_score >= 10 else ("中性" if value_score >= 5 else "估值偏高⚠️"),
    }

    # ============================================================
    # ⚡ 动量交易者 → 热度 (15分)
    # ============================================================
    momentum_score = 0
    mom_desc = []
    mom_max = 15

    if vr > 2.0:
        momentum_score += 5
        mom_desc.append(f"放量{vr:.1f}x🔥")
    elif vr > 1.5:
        momentum_score += 4
        mom_desc.append(f"活跃{vr:.1f}x")
    elif vr > 1.0:
        momentum_score += 2
        mom_desc.append(f"正常{vr:.1f}x")
    else:
        mom_desc.append(f"缩量{vr:.1f}x")

    if 60 <= rsi6 <= 80:
        momentum_score += 5
        mom_desc.append("RSI强势")
    elif 40 <= rsi6 < 60:
        momentum_score += 3
        mom_desc.append("RSI中性")
    elif rsi6 > 80:
        momentum_score += 1
        mom_desc.append("RSI超买⚠️")
    else:
        mom_desc.append("RSI偏弱")

    if today.pct_chg > 0:
        momentum_score += 3
    if prev_5d > 5:
        momentum_score += 2
        mom_desc.append("连续上涨")

    # 换手率分析
    try:
        tr = analyze_turnover_rate(klines)
        if tr:
            tr_rank = tr.get("tr_rank", 0)
            if tr_rank >= 5:
                momentum_score += 3
                mom_desc.append(f"高换手{tr.get('current_tr',0):.0f}%")
            elif tr_rank >= 3:
                momentum_score += 1
                mom_desc.append(f"活跃{tr.get('current_tr',0):.0f}%")
            tr_hint = tr.get("action_hint", "")
            if tr_hint:
                mom_desc.append(tr_hint)
    except:
        pass

    total_score += momentum_score
    max_score += mom_max
    roles["动量交易者"] = {
        "icon": "⚡", "score": momentum_score, "max": mom_max,
        "pct": round(momentum_score / mom_max * 100),
        "desc": " | ".join(mom_desc),
        "verdict": "热度高🔥" if momentum_score >= 10 else ("正常" if momentum_score >= 6 else "冷清❄️"),
    }

    # ============================================================
    # 📉 逆向投资者 → 是否过度反应 (10分)
    # ============================================================
    reverse_score = 10
    rev_desc = []
    rev_max = 10

    # 超卖信号加分（逆向买入机会）
    if rsi6 < 30:
        reverse_score += 5
        rev_desc.append("RSI超卖(逆向机会)")
    elif rsi6 < 20:
        reverse_score += 8
        rev_desc.append("RSI深度超卖")

    # 短期跌多了
    if prev_5d < -8:
        reverse_score += 5
        rev_desc.append(f"近5日大跌{prev_5d:.0f}%")
    elif prev_5d < -5:
        reverse_score += 3
        rev_desc.append("短期回调")

    # 超买信号减分（逆向看风险）
    if rsi6 > 85:
        reverse_score -= 8
        rev_desc.append("RSI超买(高风险)")
    elif rsi6 > 75:
        reverse_score -= 4
        rev_desc.append("RSI偏高(谨慎)")

    if prev_5d > 15 and today.pct_chg > 5:
        reverse_score -= 5
        rev_desc.append("加速赶顶⚠️")

    reverse_score = max(0, reverse_score)
    total_score += reverse_score
    max_score += rev_max
    roles["逆向投资者"] = {
        "icon": "📉", "score": reverse_score, "max": rev_max,
        "pct": round(reverse_score / rev_max * 100),
        "desc": " | ".join(rev_desc) if rev_desc else "无极端信号",
        "verdict": "超跌机会✅" if reverse_score >= 3 and rsi6 < 35 else ("过热⚠️" if rsi6 > 80 else "中性"),
    }

    # ============================================================
    # 🔍 基本面分析师 → 质地 (15分)
    # ============================================================
    quality_score = 5
    q_desc = ["基础分"]
    q_max = 15

    if fin_summary:
        roe = fin_summary.get("roe", 0)
        gross = fin_summary.get("gross_margin", 0)
        debt = fin_summary.get("debt_ratio", 100)
        rev_growth = fin_summary.get("revenue_growth", 0)
        profit_growth = fin_summary.get("profit_growth", 0)

        if roe > 15:
            quality_score += 5
            q_desc.append(f"ROE{roe:.0f}%优秀")
        elif roe > 8:
            quality_score += 3
            q_desc.append(f"ROE{roe:.0f}%")
        if gross > 40:
            quality_score += 3
            q_desc.append(f"毛利率{gross:.0f}%高")
        elif gross > 20:
            quality_score += 1
        if debt < 40:
            quality_score += 2
            q_desc.append("低负债")
        elif debt < 60:
            quality_score += 1
        if rev_growth > 10:
            quality_score += 2
            q_desc.append(f"营收+{rev_growth:.0f}%")
        if profit_growth > 20:
            quality_score += 2
            q_desc.append(f"利润+{profit_growth:.0f}%")
        elif profit_growth < -20:
            quality_score -= 3
            q_desc.append(f"利润下滑{profit_growth:.0f}%⚠️")

        score_basic = fin_summary.get("score", 50)
        quality_score += (score_basic - 50) / 10
    else:
        q_desc.append("无基本面数据")

    quality_score = max(0, min(q_max, quality_score))
    total_score += quality_score
    max_score += q_max
    roles["基本面分析师"] = {
        "icon": "🔍", "score": round(quality_score, 1), "max": q_max,
        "pct": round(quality_score / q_max * 100),
        "desc": " | ".join(q_desc),
        "verdict": "质地优良✅" if quality_score >= 10 else ("一般" if quality_score >= 6 else "质地偏弱⚠️"),
    }

    # ============================================================
    # 🛡️ 风险管理师 → 最坏能亏多少 (10分)
    # ============================================================
    risk_score = 10
    risk_desc = []
    risk_max = 10

    # 波动率评估
    recent_high = max(k.high for k in klines[-20:]) if len(klines) >= 20 else today.close
    recent_low = min(k.low for k in klines[-20:]) if len(klines) >= 20 else today.close
    if recent_low > 0:
        volatility = (recent_high - recent_low) / recent_low * 100
    else:
        volatility = 0

    if volatility > 30:
        risk_score -= 3
        risk_desc.append(f"高波动{volatility:.0f}%")
    elif volatility > 20:
        risk_score -= 1
        risk_desc.append(f"波动较大{volatility:.0f}%")
    else:
        risk_score += 1
        risk_desc.append(f"波动适中{volatility:.0f}%")

    if prev_5d < -5:
        risk_score -= 2
        risk_desc.append("短期弱势")
    if rsi6 < 30:
        risk_score += 1
        risk_desc.append("超卖区(安全)")
    if today.close < ma20:
        risk_score -= 2
        risk_desc.append("跌破MA20")

    # 换手率风险评估
    try:
        tr = analyze_turnover_rate(klines)
        if tr:
            tr_rank = tr.get("tr_rank", 0)
            current_tr = tr.get("current_tr", 0)
            if tr_rank >= 5 and today.pct_chg < 0:
                risk_score -= 3
                risk_desc.append(f"高换手下跌({current_tr:.0f}%)⚠️")
            elif tr_rank >= 5 and today.pct_chg > 0:
                risk_score -= 1
                risk_desc.append(f"高换手上涨({current_tr:.0f}%)需警惕")
            elif tr_rank <= 1:
                risk_score += 1
                risk_desc.append(f"低换手({current_tr:.0f}%)安全")
    except:
        pass

    # 最大潜在亏损估算（按MA20止损）
    if ma20 > 0:
        max_loss = (today.close - ma20 * 0.97) / today.close * 100
        risk_desc.append(f"潜在止损约{abs(max_loss):.1f}%")

    # 仓位建议
    if risk_score >= 10:
        pos_advice = "重仓(>40%)"
    elif risk_score >= 7:
        pos_advice = "中等(20-40%)"
    elif risk_score >= 4:
        pos_advice = "轻仓(10-20%)"
    else:
        pos_advice = "观望/空仓"

    risk_score = max(0, min(risk_max, risk_score))
    total_score += risk_score
    max_score += risk_max
    roles["风险管理师"] = {
        "icon": "🛡️", "score": risk_score, "max": risk_max,
        "pct": round(risk_score / risk_max * 100),
        "desc": " | ".join(risk_desc),
        "verdict": f'{pos_advice}',
    }

    # ============================================================
    # 🎯 事件驱动交易者 → 催化剂 (15分)
    # ============================================================
    event_score = 0
    ev_desc = []
    ev_max = 15

    # 涨停基因
    zt_10d = sum(1 for k in klines[-12:-1] if k.pct_chg >= 9.0)
    if zt_10d >= 3:
        event_score += 5
        ev_desc.append(f"近期{zt_10d}次涨停🔥")
    elif zt_10d >= 1:
        event_score += 3
        ev_desc.append(f"近期{zt_10d}次涨停")

    # 试盘线（主力动作）
    try:
        from advanced_signals import detect_test_line
        tl_ok, tl_info = detect_test_line(klines, 30)
        if tl_ok:
            if tl_info.get("has_triple_vol"):
                event_score += 5
                ev_desc.append("三倍量试盘💪")
            else:
                event_score += 3
                ev_desc.append("试盘线")
    except:
        pass

    # 今日表现
    if today.pct_chg > 7:
        event_score += 3
        ev_desc.append("今日大涨")
    elif today.pct_chg > 4:
        event_score += 2
        ev_desc.append("今日偏强")

    # 均线突破
    if today.close > ma20 and today.close > ma5:
        event_score += 2
        ev_desc.append("站上均线")

    total_score += event_score
    max_score += ev_max
    roles["事件驱动交易者"] = {
        "icon": "🎯", "score": event_score, "max": ev_max,
        "pct": round(event_score / ev_max * 100),
        "desc": " | ".join(ev_desc) if ev_desc else "无明显催化剂",
        "verdict": "催化剂明确🔥" if event_score >= 10 else ("有迹象" if event_score >= 5 else "平静期"),
    }

    # ============================================================
    # 综合评分
    # ============================================================
    overall_pct = round(total_score / max_score * 100) if max_score > 0 else 0

    # 评级
    if overall_pct >= 75:
        rating = "⭐⭐⭐⭐⭐ 强烈推荐"
    elif overall_pct >= 60:
        rating = "⭐⭐⭐⭐ 推荐"
    elif overall_pct >= 45:
        rating = "⭐⭐⭐ 观望"
    elif overall_pct >= 30:
        rating = "⭐⭐ 谨慎"
    else:
        rating = "⭐ 回避"

    return {
        "roles": roles,
        "total_score": total_score,
        "max_score": max_score,
        "overall_pct": overall_pct,
        "rating": rating,
    }
