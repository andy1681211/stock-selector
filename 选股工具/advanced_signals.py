"""
高级交易信号模块 v1.0
========================
集成课程笔记中尚未量化实现的策略：

1. 缠论底分型检测   — 底分型 + 有效性评分（缠论第15课）
2. 平步青云评分模型 — 强势股7大特征评分（陈老师第二节）
3. 洗盘结束识别     — 快速砸盘再拉起的洗盘结束信号（操盘笔记）
4. 倍量阳线+横盘突破 — 横盘后倍量阳线启动（三步伏击涨停）

所有函数均接收 KLine 对象列表（duck-typing），不依赖 local_screener，
可直接在 scan_stock 中调用。
"""

import numpy as np
import talib
import math
from typing import List, Dict, Tuple, Any, Optional
from datetime import datetime, date


# ==================== 内部指标计算（避免循环依赖 local_screener）====================

def _closes(klines) -> np.ndarray:
    return np.array([k.close for k in klines], dtype=float)

def _highs(klines) -> np.ndarray:
    return np.array([k.high for k in klines], dtype=float)

def _lows(klines) -> np.ndarray:
    return np.array([k.low for k in klines], dtype=float)

def _volumes(klines) -> List[float]:
    return [k.volume for k in klines]

def _calc_ma(klines, period: int) -> List[float]:
    result = talib.SMA(_closes(klines), period)
    return [float(v) if not np.isnan(v) else 0.0 for v in result]

def _calc_macd(klines, fast=12, slow=26, signal=9):
    dif, dea, hist = talib.MACD(_closes(klines), fast, slow, signal)
    return ([float(v) if not np.isnan(v) else 0.0 for v in dif],
            [float(v) if not np.isnan(v) else 0.0 for v in dea],
            [float(v) if not np.isnan(v) else 0.0 for v in hist])

def _calc_vr(klines, period=5) -> List[float]:
    vols = _volumes(klines)
    return [vols[i]/sum(vols[max(0,i-period):i])*period if i >= period and sum(vols[max(0,i-period):i]) > 0 else 0.0
            for i in range(len(vols))]


# ======================================================================
#  1. 缠论底分型检测
# ======================================================================

def detect_bottom_fractal(klines, lookback: int = 15) -> Tuple[bool, str]:
    """
    缠论底分型检测（第15课）

    底分型定义：
      连续3根K线，中间那根的低点是3根中最低的，
      中间那根的高点也是3根中最低的。

    有效性确认（缠师原文）：
      - 第三根K线收盘站上第一根K线最高价 = 强势底分型
      - MACD绿柱缩短 = 下跌力度衰竭
      - 底分型后不破新低 = 确认有效

    Args:
        klines: KLine对象列表
        lookback: 回溯天数

    Returns:
        (是否出现可信底分型, 描述文字)
    """
    if len(klines) < 5:
        return False, "数据不足"

    c = len(klines)
    search_start = max(0, c - lookback - 2)

    # ---- 在 lookback 范围内寻找底分型 ----
    found = []
    for i in range(search_start, c - 2):
        k1, k2, k3 = klines[i], klines[i+1], klines[i+2]

        # 核心条件：中间K线低点最低、高点最低
        if k2.low < k1.low and k2.low < k3.low and k2.high < k1.high and k2.high < k3.high:
            found.append({
                "idx": i,
                "k1_close": k1.close,
                "k1_high": k1.high,
                "k2_low": k2.low,
                "k3_close": k3.close,
                "k3_high": k3.high,
                "type": "标准底分型",
            })

    if not found:
        return False, "未发现底分型"

    # ---- 分析最新的底分型（离今天最近的）----
    last = found[-1]
    idx = last["idx"]
    k1, k2, k3 = klines[idx], klines[idx+1], klines[idx+2]
    today = klines[-1]
    today_idx = len(klines) - 1

    # 底分型距今多少天
    days_since = today_idx - (idx + 2)

    # ---- 有效性评分 ----
    confirmations = []

    # 条件1: 第三根K线收盘 > 第一根K线最高价 -> 强势底分型
    if k3.close > k1.high:
        confirmations.append("强势")
    elif k3.close > k2.high:
        confirmations.append("确认")
    elif k3.close > k2.low:
        confirmations.append("待确认")
    else:
        confirmations.append("弱势")

    # 条件2: MACD绿柱缩短
    _, _, macd_hist = _calc_macd(klines)
    if len(macd_hist) >= 5:
        # MACD柱最近3天是否在缩短（从更负向0靠近）
        recent_3 = macd_hist[-3:]
        if recent_3[-1] > recent_3[0]:
            confirmations.append("MACD转好")
        elif recent_3[-1] > recent_3[-2]:
            confirmations.append("MACD微好")

    # 条件3: 底分型后不破新低（最关键的确认）
    if days_since >= 0:
        post_low = min(k.low for k in klines[idx+2:])
        if post_low >= k2.low * 0.995:
            confirmations.append("不破新低")
        else:
            confirmations.append("破新低!!️")

    # 条件4: 量能萎缩（缩量见底信号）
    if len(klines) >= 15:
        vols = _volumes(klines)
        vol_5 = sum(vols[-5:]) / 5
        vol_pre_5 = sum(vols[-10:-5]) / 5 if len(vols) >= 10 else vol_5
        if vol_pre_5 > 0 and vol_5 / vol_pre_5 < 0.8:
            confirmations.append("缩量")

    # 条件5: 底分型后近3天有企稳小阳线
    if days_since <= 3:
        post_klines = klines[idx+2:]
        if any(k.pct_chg > 0 for k in post_klines[-min(3, len(post_klines)):]):
            confirmations.append("企稳")

    strength = "+".join(confirmations)

    # 判定是否可信
    is_valid = (
        "强势" in confirmations or "确认" in confirmations
    ) and "破新低" not in confirmations

    if days_since > 5:
        return (True, f"底分型({days_since}天前)({strength})")

    return (is_valid, f"底分型({days_since}天前)({strength})")


def is_bottom_fractal_valid(klines) -> bool:
    """简化的底分型是否成立（只检查最近3根K线）"""
    if len(klines) < 3:
        return False
    k1, k2, k3 = klines[-3], klines[-2], klines[-1]
    return (k2.low < k1.low and k2.low < k3.low
            and k2.high < k1.high and k2.high < k3.high
            and k3.close > k2.high)  # 第三根确认


# ======================================================================
#  2. 平步青云评分模型
# ======================================================================

def pingbu_qingyun_score(klines, vr: float = 0) -> Dict[str, Any]:
    """
    平步青云强势股评分（陈老师第二节课程笔记）

    7大特征 -> 每项0~20分 -> 总分0~100（>60视为强信号）

    特征1: 短期快速拉升（N日涨幅 > 阈值）
    特征2: 放量突破启动（启动日量 > 均量x1.5）
    特征3: 前期长期横盘震荡洗盘（振幅<30%, 时间>20天）
    特征4: 上涨前有倍量阳线（某日量/前日量 > 2.0）
    特征5: 目标在左侧压力位附近（前高/筹码密集区）
    特征6: 模式可复制（评分框架本身即元数据）
    特征7: 5日线不下弯（MA5方向向上）

    Args:
        klines: KLine对象列表
        vr: 当前量比（可选择传入，0则自动计算）

    Returns:
        { "score": int, "details": {特征名: 得分}, "summary": "描述" }
    """
    if len(klines) < 70:
        return {"score": 0, "details": {"数据不足": 0}, "summary": "数据不足"}

    result = {"score": 0, "details": {}, "summary": ""}
    details = {}
    total = 0.0

    c = len(klines) - 1
    today = klines[c]

    # ---- 特征1: 短期快速拉升（权重20分）----
    # 近5日涨幅 > 10% 且 近5日有至少1天涨幅>5%
    chg_5d = sum(k.pct_chg for k in klines[-5:])
    max_chg_5d = max(k.pct_chg for k in klines[-5:])

    s1 = 0
    if chg_5d >= 15 and max_chg_5d >= 7:
        s1 = 20
    elif chg_5d >= 10 and max_chg_5d >= 5:
        s1 = 15
    elif chg_5d >= 7:
        s1 = 10
    elif chg_5d >= 3:
        s1 = 5
    else:
        s1 = 0
    details["短期拉升"] = s1
    total += s1

    # ---- 特征2: 放量突破启动（权重20分）----
    # 寻找最近20天内的放量突破日：某天涨幅>3% 且 量>20日均量x1.5
    vol_20_avg = sum(k.volume for k in klines[-20:]) / 20
    current_vr = vr if vr > 0 else _calc_vr(klines, 5)[-1]

    has_breakout = False
    for i in range(-20, 0):
        k = klines[i]
        if k.pct_chg >= 3 and k.volume > vol_20_avg * 1.5:
            has_breakout = True
            break

    s2 = 0
    if has_breakout and current_vr >= 2.0:
        s2 = 20
    elif has_breakout:
        s2 = 15
    elif current_vr >= 2.0:
        s2 = 10
    elif current_vr >= 1.5:
        s2 = 5
    details["放量突破"] = s2
    total += s2

    # ---- 特征3: 前期长期横盘震荡洗盘（权重20分）----
    # 检查20~50天前的横盘区间：振幅<30%，时间>20天
    if len(klines) >= 50:
        pre_range = klines[-50:-20]  # 20~50天前
        if pre_range:
            pre_high = max(k.high for k in pre_range)
            pre_low = min(k.low for k in pre_range)
            pre_amplitude = (pre_high - pre_low) / pre_low * 100 if pre_low > 0 else 999

            # 横盘判断
            if pre_amplitude < 25:
                # 再检查缩量横盘：量能萎缩
                vol_pre = sum(k.volume for k in pre_range) / len(pre_range)
                vol_recent = sum(k.volume for k in klines[-5:]) / 5
                vol_idx = vol_pre / vol_recent if vol_recent > 0 else 1

                if pre_amplitude < 15 and vol_idx < 1.5:
                    s3 = 20  # 窄幅横盘缩量 = 强洗盘
                elif pre_amplitude < 20:
                    s3 = 15
                else:
                    s3 = 10
            elif pre_amplitude < 30:
                s3 = 5
            else:
                s3 = 0
        else:
            s3 = 0
    else:
        s3 = 0
    details["横盘洗盘"] = s3
    total += s3

    # ---- 特征4: 倍量阳线（权重15分）----
    # 最近30天内是否有一根倍量阳线（量/前日量 > 2 且 收阳）
    has_volume_surge = False
    for i in range(-30, 0):
        k = klines[i]
        if k.close > k.open and i > -30:  # 阳线
            prev_vol = klines[i-1].volume
            if prev_vol > 0 and k.volume / prev_vol >= 2.0:
                has_volume_surge = True
                break

    s4 = 0
    if has_volume_surge:
        # 检查倍量是否在近期（加分）
        if any(k.pct_chg >= 5 for k in klines[-5:]):
            s4 = 15
        else:
            s4 = 10
    else:
        # 检查今日是否倍量
        if len(klines) >= 2 and klines[-2].volume > 0:
            if today.volume / klines[-2].volume >= 2.0 and today.close > today.open:
                s4 = 12
        if s4 == 0:
            s4 = 0
    details["倍量阳线"] = s4
    total += s4

    # ---- 特征5: 左侧压力位空间（权重10分）----
    # 检查距前高/筹码密集区的距离
    if len(klines) >= 60:
        lookback_range = klines[-250:] if len(klines) >= 250 else klines
        year_high = max(k.high for k in lookback_range)
        recent_high_60 = max(k.high for k in klines[-60:])
        current = today.close

        dist_to_high = (year_high - current) / current * 100 if current > 0 else 0

        if 5 <= dist_to_high <= 30:
            s5 = 10  # 距离前高5%-30% = 最佳上涨空间
        elif dist_to_high > 30:
            s5 = 5   # 空间大但短期压力小
        elif dist_to_high > 0:
            s5 = 8   # 接近前高
        else:
            s5 = 2   # 已经创新高，上方无压力
    else:
        s5 = 5
    details["压力空间"] = s5
    total += s5

    # ---- 特征6: 模式可复制（权重5分）----
    # 检查是否同时出现多种强势特征（特征6是元特征）
    feature_count = sum(1 for s in [s1 >= 10, s2 >= 10, s3 >= 10, s4 >= 10, s7_check()] if s)
    s6 = min(5, feature_count * 2)
    details["模式可复制"] = s6
    total += s6

    # ---- 特征7: 5日线不下弯（权重10分）----
    ma5 = _calc_ma(klines, 5)
    ma5_now = ma5[-1]
    ma5_3ago = ma5[-4] if len(ma5) >= 4 else 0

    s7 = 0
    if ma5_now > ma5_3ago and ma5_now > 0:
        # 5日线向上且股价在5日线上方
        if today.close > ma5_now:
            ma5_angle = math.atan((ma5_now - ma5_3ago) / ma5_3ago * 100) * 180 / 3.14159 if ma5_3ago > 0 else 0
            if ma5_angle >= 30:
                s7 = 10  # 强势上攻
            else:
                s7 = 8   # 温和向上
        else:
            s7 = 5       # 线上但股价破线
    elif ma5_now > ma5_3ago:
        s7 = 3           # 刚拐头
    else:
        s7 = 0           # 5日线下弯
    details["5日线向上"] = s7
    total += s7

    # ---- 综合评分 ----
    score = min(100, int(total))

    # 生成描述
    details_str = " | ".join(f"{k}:{v}" for k, v in sorted(details.items(), key=lambda x: -x[1]) if v > 0)

    if score >= 80:
        summary = f"***** 极强 {score}分 | {details_str}"
    elif score >= 65:
        summary = f"**** 强势 {score}分 | {details_str}"
    elif score >= 50:
        summary = f"*** 可关注 {score}分 | {details_str}"
    elif score >= 30:
        summary = f"** 一般 {score}分 | {details_str}"
    else:
        summary = f"* 偏弱 {score}分 | {details_str}"

    result["score"] = score
    result["details"] = details
    result["summary"] = summary

    # 是否满足"平步青云"主升浪条件（>65分且5日线向上+放量突破）
    result["is_strong"] = score >= 65 and s7 >= 8 and s2 >= 10

    return result


def s7_check():
    """用于特征6的内部检查"""
    return True


# ======================================================================
#  3. 洗盘结束识别
# ======================================================================

def is_washout_complete(klines) -> Tuple[bool, str]:
    """
    洗盘结束识别（操盘笔记p7）

    笔记原文:
      「判断洗盘结束：前日曾有一次洗盘 -> 今日再出现分时剧烈震荡
       （快速砸盘再拉起）-> 确认洗盘结束」
      「买点：低开高走后的快速回踩是极佳买点」
      「止损点：当日最低点」

    日K线级别近似判断：
    1. 前日（或近2天）有洗盘特征：收阴线 / 长上影 / 大波动
    2. 今日低开高走（open < prev_close, close > open）
    3. 今日有下影线（下影线长度 > 实体的1倍）
    4. 收盘不破前日最低点
    5. 量能配合：洗盘日缩量，今日温和放量

    Args:
        klines: KLine对象列表

    Returns:
        (是否洗盘结束, 描述)
    """
    if len(klines) < 5:
        return False, "数据不足"

    c = len(klines) - 1
    today = klines[c]
    yesterday = klines[c-1]

    # ---- 检查前日是否有洗盘特征 ----
    washout_signals = []

    # 特征A: 前日收阴线
    if yesterday.close < yesterday.open:
        washout_signals.append("前日阴线")

    # 特征B: 前日长上影线（上影线 > 实体2倍）
    yesterday_upper_shadow = yesterday.high - max(yesterday.close, yesterday.open)
    yesterday_body = abs(yesterday.close - yesterday.open)
    if yesterday_body > 0 and yesterday_upper_shadow > yesterday_body * 2:
        washout_signals.append("前日长上影")

    # 特征C: 前日大波动（振幅 > 5%）
    yesterday_amplitude = (yesterday.high - yesterday.low) / yesterday.low * 100 if yesterday.low > 0 else 0
    if yesterday_amplitude > 5:
        washout_signals.append("前日大波动")

    # 特征D: 再前一日也是洗盘（两天连洗 = 更可信的洗盘末端）
    if c >= 2:
        day_before = klines[c-2]
        if day_before.close < day_before.open or day_before.pct_chg < -1:
            washout_signals.append("持续洗盘")

    if not washout_signals:
        return False, "无前日洗盘特征"

    # ---- 检查今日的"快速砸盘再拉起" ----

    # 条件1: 低开（open < prev_close）
    if today.open >= yesterday.close:
        return False, f"非低开({today.open}≥{yesterday.close})"

    # 条件2: 收涨（close > open）
    if today.close <= today.open:
        return False, "低开未收红"

    # 条件3: 下影线明显（下影线 > 实体0.5倍，表示砸盘后拉起）
    lower_shadow = min(today.open, today.close) - today.low
    body = abs(today.close - today.open)
    if body > 0 and lower_shadow < body * 0.5:
        return False, f"下影线不足({lower_shadow}<{body*0.5})"

    # 条件4: 收盘不破前日最低
    if today.close <= yesterday.low:
        return False, f"收{yesterday.low}破前日低{yesterday.low}"

    # 条件5: 量能合理（洗盘后放量或温和放量）
    if c >= 3:
        vol_3 = sum(k.volume for k in klines[-3:-1]) / 2
        if vol_3 > 0 and today.volume > vol_3 * 1.2:
            washout_signals.append("放量确认")
        elif vol_3 > 0 and today.volume > vol_3 * 0.8:
            washout_signals.append("温和放量")
    washout_signals.append("洗盘结束 OK")

    desc = " + ".join(washout_signals)
    return True, desc


def is_day_trade_entry(klines) -> Tuple[bool, str]:
    """
    分时级买点的日线近似判断（操盘笔记p56-58）

    笔记原文：
      「低开高走后的快速回踩是极佳买点」

    日线近似：
    1. 今日低开 < 昨日收盘
    2. 收红（close > open）
    3. 今日最低点 < 开盘价（说明盘中砸过）
    4. 收盘 > 开盘价（砸后收回）
    5. 前一日最好是收阴回调（洗盘日）
    """
    if len(klines) < 3:
        return False, ""

    c = len(klines) - 1
    today = klines[c]
    yesterday = klines[c-1]

    # 今日低开
    if today.open >= yesterday.close:
        return False, "非低开"

    # 今日收红
    if today.close <= today.open:
        return False, "未收红"

    # 盘中砸破开盘价（最低 < 开盘）
    if today.low >= today.open:
        return False, "未砸盘"

    # 收盘收回
    if today.close <= today.open:
        return False, "未收回"

    # 前日最好是阴线回调
    desc_parts = []
    if yesterday.close < yesterday.open:
        desc_parts.append("前日洗盘阴")

    # 量能：今日温和放量
    if len(klines) >= 4:
        avg_vol = sum(k.volume for k in klines[-4:-1]) / 3
        if avg_vol > 0:
            if today.volume > avg_vol * 1.3:
                desc_parts.append("放量")
            elif today.volume > avg_vol * 0.8:
                desc_parts.append("温和")

    desc_parts.append("回踩买点")
    return True, " + ".join(desc_parts)


# ======================================================================
#  4. 倍量阳线 + 横盘突破
# ======================================================================

def is_volume_surge_breakout(klines, lookback: int = 30) -> Tuple[bool, str]:
    """
    倍量阳线横盘突破（三步伏击涨停 + 平步青云融合）

    条件：
    1. 前期横盘整理（过去20天振幅<30%）
    2. 今日放量突破横盘高点
    3. 今日是倍量阳线（量/前日量 > 1.8）
    4. 均线开始多头排列或即将多头

    Args:
        klines: KLine对象列表
        lookback: 横盘回溯天数

    Returns:
        (是否突破, 描述)
    """
    if len(klines) < lookback + 5:
        return False, "数据不足"

    c = len(klines) - 1
    today = klines[c]

    # ---- 横盘区间检测 ----
    platform = klines[-(lookback+1):-1]  # 不含今日的前N天
    if not platform:
        return False, ""

    platform_high = max(k.high for k in platform)
    platform_low = min(k.low for k in platform)
    platform_amplitude = (platform_high - platform_low) / platform_low * 100 if platform_low > 0 else 999

    # 横盘振幅<30%
    if platform_amplitude > 30:
        return False, f"横盘振幅{platform_amplitude:.0f}%>30%"

    # ---- 今日突破 ----
    # 收盘站上横盘最高点
    if today.close <= platform_high:
        return False, f"未突破平台高{platform_high:.2f}"

    # 涨幅 > 2%
    if today.pct_chg < 2:
        return False, f"涨幅{today.pct_chg:.1f}%不足"

    # ---- 倍量条件 ----
    prev_volumes = [k.volume for k in klines[-6:-1]]
    avg_vol = sum(prev_volumes) / len(prev_volumes) if prev_volumes else 0
    if avg_vol <= 0:
        return False, "量数据异常"

    vol_ratio = today.volume / klines[-2].volume if klines[-2].volume > 0 else 0
    vol_ratio_avg = today.volume / avg_vol if avg_vol > 0 else 0

    conditions = []

    if vol_ratio >= 1.8:
        conditions.append("倍量")
    elif vol_ratio_avg >= 1.5:
        conditions.append(f"放量({vol_ratio_avg:.1f}x均量)")
    else:
        return False, f"量不足({vol_ratio:.1f}x{vol_ratio_avg:.1f}x)"

    # 收阳线
    if today.close > today.open:
        conditions.append("阳线")
    else:
        conditions.append("假阳")

    # ---- 均线状态 ----
    if len(klines) >= 20:
        ma5 = _calc_ma(klines, 5)[-1]
        ma10 = _calc_ma(klines, 10)[-1]
        ma20 = _calc_ma(klines, 20)[-1]
        if ma5 > ma10 > ma20:
            conditions.append("多头排列")
        elif ma5 > ma10:
            conditions.append("趋势向好")
        elif ma5 > ma20:
            conditions.append("5线在20线上")

    # ---- 横盘特征描述 ----
    if platform_amplitude < 15:
        conditions.append("窄横盘")
    else:
        conditions.append("宽横盘")

    desc = "突破! " + " + ".join(conditions)
    return True, desc


# ======================================================================
#  5. 股海炼金术第三课 — 建仓型/洗盘型涨停板 + 二进三战法
# ======================================================================

def is_position_building_limit_up(klines) -> Tuple[bool, str]:
    """
    建仓型涨停板识别 — 抢筹式建仓（陈老师第三节 星火燎原）

    定义:
      建仓型涨停板又称 **抢筹式建仓型涨停板**，
      是主力以快速拉涨停板或连续拉涨停板的方式进行暴力抢筹的动作。
      这是主力介入一只股票的 **第一个实质性动作**，
      是用时间换空间、急于收集筹码的表现。

    四大核心特征（A-D）:
      A. 突然抢筹 — 无征兆暴力拉涨停抢筹码（前期无明显拉升）
      B. 趋势转折 — 改变了股票走势（下跌→止跌起稳）
      C. 封停迅速 — 脉冲式封死（阻中小投资者跟风 + 引跟风抬轿）
      D. 中低位置 — 重复出现在股价的中低位置

    附加信号:
      - 反常抢筹: 主力一反常态急于用涨停建仓 → 必有短期利好刺激
      - 连续建仓: 可以连续拉涨停建仓（持续数日）

    Args:
        klines: KLine对象列表

    Returns:
        (是否建仓型涨停板, 描述)
    """
    if len(klines) < 60:
        return False, "数据不足"

    c = len(klines) - 1
    today = klines[c]

    # 今日必须涨停或接近涨停（≥7%允许小幅缺口）
    if today.pct_chg < 7:
        return False, f"非涨停({today.pct_chg:.1f}%)"

    # 涨停幅度检查：如果是真涨停（≥9.5%）加分，但7%以上也认可
    is_full_limit = today.pct_chg >= 9.5

    # ═══════════════════════════════════════════
    # A. 突然抢筹 — 前期无明显主力运作痕迹
    # ═══════════════════════════════════════════
    # 暴力抢筹的特征：前期无明显拉升，今日突然拉涨停
    # 但不是完全不看前期，而是主力刻意在之前隐藏痕迹

    # 检查前10天是否有过涨停
    pre_10d_has_zt = any(klines[i].pct_chg >= 9.5 for i in range(-15, -4)) if len(klines) >= 15 else False

    # 检查前20天涨幅（剔除建仓期本身，如果连续涨停建仓）
    pre_20d_chg = sum(k.pct_chg for k in klines[-25:-5]) if len(klines) >= 25 else 0

    # 连续涨停建仓：如果今天涨停 + 昨天也涨停，算连续建仓
    yesterday_limit = False
    if c >= 1:
        yesterday_limit = klines[c-1].pct_chg >= 9.0

    # 如果是连续建仓（今天涨停、昨天也涨停），放宽前期检查
    is_consecutive_building = yesterday_limit

    if is_consecutive_building:
        # 连续建仓：检查更早之前（5天前）有没有大涨
        earlier = sum(k.pct_chg for k in klines[-10:-5]) if len(klines) >= 10 else 0
        if earlier > 20:
            return False, "连续涨停前已大涨"
        cond_a = True
        a_desc = "连续拉涨停建仓"
    else:
        # 单日建仓：必须是"突然"的（前期无明显大涨）
        if pre_10d_has_zt:
            return False, "前期已涨停(非突然抢筹)"
        if pre_20d_chg > 15:
            return False, f"前期涨幅{pre_20d_chg:.0f}%过大"
        cond_a = True
        a_desc = "突然拉涨停抢筹"

    # ═══════════════════════════════════════════
    # B. 趋势转折 — 下跌转止跌/起稳
    # ═══════════════════════════════════════════
    ma20_vals = _calc_ma(klines, 20)
    ma20_now = ma20_vals[-1] if ma20_vals else 0
    ma20_5ago = ma20_vals[-6] if len(ma20_vals) >= 6 else 0
    ma60_vals = _calc_ma(klines, 60)
    ma60_now = ma60_vals[-1] if ma60_vals else 0

    # MA20走平或向上 = 趋势转折信号
    was_downtrend = ma20_5ago > 0 and ma20_now > ma20_5ago * 0.95
    # MA60没有明显下行
    ma60_not_bad = ma60_now > 0  # 不要求向上，但不崩盘

    if is_consecutive_building:
        cond_b = True  # 连续涨停建仓自然形成趋势转折
        b_desc = "连续建仓转势"
    elif was_downtrend:
        cond_b = True
        b_desc = "趋势转折"
    else:
        cond_b = False
        b_desc = "趋势未变"

    # ═══════════════════════════════════════════
    # C. 封停迅速 — 脉冲式封死
    # ═══════════════════════════════════════════
    # 特征：涨停干脆不拖泥带水，目的是阻止跟风盘入场
    # 同时也吸引跟风盘抬轿
    if today.high > today.low:
        amplitude = (today.high - today.low) / today.low * 100
        cond_c = amplitude < 8  # 振幅小 = 封停迅速
    else:
        cond_c = False

    # ═══════════════════════════════════════════
    # D. 中低位置 — 不在高位出货区
    # ═══════════════════════════════════════════
    year_range = klines[-250:] if len(klines) >= 250 else klines
    year_high = max(k.high for k in year_range)
    year_low = min(k.low for k in year_range)

    # 中低位置定义：股价在年高中低位
    if year_high > 0 and year_low > 0:
        position_ratio = (today.close - year_low) / (year_high - year_low) * 100
        cond_d = position_ratio < 70  # 在年线区间的70%以下 = 中低位置
    else:
        cond_d = False

    # ═══════════════════════════════════════════
    # 综合判定
    # ═══════════════════════════════════════════
    details = [a_desc]
    if cond_b:
        details.append(b_desc)
    if cond_c:
        if is_full_limit:
            details.append("一字脉冲")
        else:
            details.append("脉冲封死")
    if cond_d:
        details.append("中低位置")
    if is_consecutive_building:
        details.append("暴力抢筹")

    # 至少满足A + D（突然抢筹 + 中低位置）
    if cond_a and cond_d:
        return True, "建仓型涨停 " + " + ".join(details)
    # 或者满足 A + B + C（趋势转折 + 封停迅速）
    if cond_a and cond_b and cond_c:
        return True, "建仓型涨停 " + " + ".join(details)

    return False, f"条件不足(A:{cond_a} B:{cond_b} C:{cond_c} D:{cond_d})"


def is_washout_limit_up(klines) -> Tuple[bool, str]:
    """
    洗盘型涨停板识别（陈老师第三节 星火燎原）

    定义:
      洗盘型涨停板主要指 **V字形涨停板**，
      即股价涨停后打开缺口、再次封板。
      是主力在涨停板上进行洗盘，甩出不坚定散户。

    两大核心特征:
      1. 全天股价长时间处于涨停状态（收盘封死在高位）
      2. 中间有缺口走势打开涨停板，同时伴随着成交量的放大

    N字洗盘过程:
      涨停 → 炸板（打开缺口放量） → 回封 → 全天大部分时间封死

    Args:
        klines: KLine对象列表

    Returns:
        (是否洗盘型涨停板, 描述)
    """
    if len(klines) < 5:
        return False, "数据不足"

    c = len(klines) - 1
    today = klines[c]

    # 今日必须涨停或接近涨停
    if today.pct_chg < 7:
        return False, f"非涨停({today.pct_chg:.1f}%)"

    # ═══════════════════════════════════════════
    # 特征1: 全天长时间处于涨停状态
    # ═══════════════════════════════════════════
    # 收盘在高位（接近最高价）= 最终封死
    if today.close < today.high * 0.98:
        return False, "未封死涨停"

    # ═══════════════════════════════════════════
    # 特征2: 中间有缺口打开（V字型走势）
    # ═══════════════════════════════════════════
    # 日线上表现为: 有下影线（回踩缺口）或上影线（炸板后回封）
    lower_shadow = min(today.open, today.close) - today.low
    upper_shadow = today.high - max(today.open, today.close)
    body = abs(today.close - today.open)

    # V字形特征检测
    has_gap = False
    v_type = ""
    if lower_shadow > body * 0.5:
        has_gap = True
        v_type = "V型回踩缺口"  # 股价打开→下探→拉回封板
    elif upper_shadow > body * 0.5:
        has_gap = True
        v_type = "炸板回封"     # 涨停→炸板→再回封
    elif lower_shadow > body * 0.3 or upper_shadow > body * 0.3:
        has_gap = True
        v_type = "盘中打开"

    if not has_gap:
        return False, "无V型缺口(一字板)"

    # ═══════════════════════════════════════════
    # 特征3: 缺口打开伴随成交量放大
    # ═══════════════════════════════════════════
    if c >= 2:
        prev_vol = sum(k.volume for k in klines[-4:-1]) / 3 if len(klines) >= 4 else klines[c-1].volume
        if prev_vol > 0:
            vol_ratio = today.volume / prev_vol
            if vol_ratio < 1.2:
                return False, f"量未放大({vol_ratio:.1f}x)"
        else:
            vol_ratio = 1.0
    else:
        vol_ratio = 1.0

    desc_parts = [f"洗盘型({v_type})"]
    if vol_ratio >= 3.0:
        desc_parts.append(f"天量{vol_ratio:.1f}x")
    elif vol_ratio >= 2.0:
        desc_parts.append(f"巨量{vol_ratio:.1f}x")
    else:
        desc_parts.append(f"放量{vol_ratio:.1f}x")

    # 检查是否有前一天的建仓型涨停作为首板（二进三的辅助判断）
    if c >= 1:
        prev = klines[c-1]
        if prev.pct_chg >= 7:
            desc_parts.append("二板中")

    return True, " + ".join(desc_parts)


def is_erjin_san_pattern(klines) -> Tuple[bool, str]:
    """
    二进三战法 — 龙凤呈祥（第三课核心战法）

    条件:
    1. 底部起涨不超过30%
    2. 出现两次以上试盘线,且其中一次是三倍量试盘线
    3. 后期出现拉升型涨停板
    4. 股价位于60MA上方运行
    5. 次日股价超过前一天涨停板收盘价 = 介入点

    首板 = 建仓型涨停板
    二板 = 洗盘型涨停板
    二板炸板回封时 = 介入

    Returns:
        (是否二进三模式, 描述)
    """
    if len(klines) < 60:
        return False, "数据不足"

    c = len(klines) - 1
    today = klines[c]

    # ---- 条件4: 股价位于60MA上方 ----
    ma60_vals = _calc_ma(klines, 60)
    ma60 = ma60_vals[-1] if ma60_vals else 0
    if today.close < ma60:
        return False, f"低于60MA({today.close:.2f}<{ma60:.2f})"

    # ---- 条件1: 底部起涨不超过30% ----
    # 从近期低点算起
    recent_30d_low = min(k.low for k in klines[-30:]) if len(klines) >= 30 else 0
    if recent_30d_low > 0:
        rise_pct = (today.close - recent_30d_low) / recent_30d_low * 100
        if rise_pct > 30:
            return False, f"底部起涨{rise_pct:.0f}%>30%"

    # ---- 条件2: 两次以上试盘线 ----
    # 试盘线特征: 放量上影线/长上影小实体
    test_line_count = 0
    has_triple_vol = False
    for i in range(-20, -1):
        k = klines[i]
        body = abs(k.close - k.open)
        upper = k.high - max(k.close, k.open)
        # 试盘线: 上影线 > 实体2倍 且 有一定涨幅
        if body > 0 and upper > body * 2 and k.pct_chg > 0:
            test_line_count += 1
            # 检查三倍量
            if i > -20:
                avg_vol_5 = sum(klines[j].volume for j in range(i-5, i)) / 5 if i >= 5 else 0
                if avg_vol_5 > 0 and k.volume > avg_vol_5 * 3:
                    has_triple_vol = True

    if test_line_count < 2:
        return False, f"试盘线不足({test_line_count}次)"

    # ---- 找最近的首板和二板 ----
    # 找最近5天内涨停的日期
    zt_indices = []
    for i in range(-10, 0):
        k = klines[i]
        if k.pct_chg >= 7:
            zt_indices.append(i)

    if len(zt_indices) < 2:
        return False, f"连板不足({len(zt_indices)}板)"

    # 最后两个涨停
    last_zt = zt_indices[-1]  # 可能是今天
    prev_zt = zt_indices[-2]  # 前一个涨停

    # 检查首板和二板的间隔（应该在3天内）
    gap = abs(last_zt - prev_zt)
    if gap > 5:
        return False, f"连板间隔{gap}天过大"

    # ---- 条件5: 次日股价超过前一天涨停收盘 ----
    # 今天的收盘价 > 前一个涨停的收盘价
    prev_zt_close = klines[prev_zt if prev_zt >= 0 else len(klines) + prev_zt].close
    if today.close <= prev_zt_close:
        return False, f"未超前板收({today.close:.2f}<={prev_zt_close:.2f})"

    # ---- 二板是否洗盘型 ----
    second_zt_k = klines[prev_zt if prev_zt >= 0 else len(klines) + prev_zt]
    second_zt_body = abs(second_zt_k.close - second_zt_k.open)
    second_zt_lower = min(second_zt_k.open, second_zt_k.close) - second_zt_k.low
    second_is_washout = second_zt_lower > second_zt_body * 0.3

    desc_parts = [f"二进三({len(zt_indices)}板)"]
    if has_triple_vol:
        desc_parts.append("三倍试盘")
    if second_is_washout:
        desc_parts.append("二板洗盘")

    return True, " + ".join(desc_parts)


def limit_up_type_analysis(klines) -> Dict:
    """
    涨停板类型综合分析（股海炼金术第三课）

    判断最近的涨停板是建仓型还是洗盘型,
    以及是否符合二进三战法条件。

    Returns:
        {
            "position_building": bool,  # 是否有建仓型涨停
            "washout": bool,            # 是否有洗盘型涨停
            "erjin_san": bool,          # 是否符合二进三
            "type_desc": str,           # 类型描述
            "zt_count": int,            # 近期涨停数
        }
    """
    result = {
        "position_building": False,
        "washout": False,
        "erjin_san": False,
        "type_desc": "",
        "zt_count": 0,
    }

    if len(klines) < 60:
        result["type_desc"] = "数据不足"
        return result

    # 检查建仓型涨停
    pb, pd = is_position_building_limit_up(klines)
    result["position_building"] = pb

    # 检查洗盘型涨停
    wo, wd = is_washout_limit_up(klines)
    result["washout"] = wo

    # 检查二进三
    ej, ed = is_erjin_san_pattern(klines)
    result["erjin_san"] = ej

    # 统计近期涨停数
    c = len(klines) - 1
    zt_count = sum(1 for i in range(-10, 0) if klines[i].pct_chg >= 7)
    result["zt_count"] = zt_count

    # 综合描述
    desc_parts = []
    if pb:
        desc_parts.append("建仓型")
    if wo:
        desc_parts.append("洗盘型")
    if ej:
        desc_parts.append("二进三★")
    if not desc_parts and zt_count > 0:
        desc_parts.append(f"{zt_count}板")
    elif not desc_parts:
        desc_parts.append("普通")

    result["type_desc"] = " + ".join(desc_parts)
    return result


# ======================================================================
#  6. 独立试盘线检测 — 主升浪起爆前置信号
# ======================================================================

def detect_test_line(klines, lookback: int = 30) -> Tuple[bool, Dict]:
    """
    试盘线独立检测（股海炼金术主升浪起爆理论）

    震荡建仓 → 试盘线(测试抛压) → 缩量整理 → 起爆

    试盘线特征（完整版）:
      1. 上影线 > 实体2倍（长上影试探抛压）
      2. 有一定涨幅但未封板或长上影假阳（故意留上影）
      3. 放量 > 5日均量1.5倍以上
      4. 出现位置在震荡平台中上沿（非大幅拉高后）
      5. 三倍量试盘线 = 更强信号（量 > 5日均量3倍）

    Args:
        klines: KLine对象列表
        lookback: 回溯天数（在此范围内找试盘线）

    Returns:
        (是否有试盘线, {
            "count": 试盘线出现次数,
            "latest_idx": 最近试盘线在klines中的位置偏移,
            "latest_desc": 最近试盘线描述,
            "has_triple_vol": 是否有三倍量试盘线,
            "avg_shadow_ratio": 平均上影/实体比,
            "details": [每条试盘线的描述列表],
        })
    """
    c = len(klines)
    if c < 30:
        return False, {"count": 0, "latest_idx": -1, "latest_desc": "数据不足",
                        "has_triple_vol": False, "avg_shadow_ratio": 0.0, "details": []}

    # 震荡区间参考：过去lookback天的振幅
    start = max(0, c - lookback - 5)
    search_range = range(c - lookback, c - 1)

    test_lines = []
    total_ratio = 0.0
    has_triple = False

    for i in search_range:
        k = klines[i]
        body = abs(k.close - k.open)
        upper = k.high - max(k.close, k.open)

        if body <= 0:
            continue

        shadow_ratio = upper / body

        # 核心条件: 上影线 > 实体2倍 且 有一定涨幅（不能是跌的试盘）
        if shadow_ratio >= 2.0 and k.pct_chg > -1.0:
            # 涨幅不能太大（涨停的不算试盘线，那是拉升）
            if k.pct_chg >= 9.5:
                continue

            # 量能检查: 放量
            avg_vol_5 = sum(klines[j].volume for j in range(max(0, i-5), i)) / 5 if i >= 5 else 0
            vol_ratio = k.volume / avg_vol_5 if avg_vol_5 > 0 else 0

            if vol_ratio < 1.3:
                continue  # 量不够不算试盘

            is_triple = vol_ratio >= 3.0
            if is_triple:
                has_triple = True

            total_ratio += shadow_ratio

            # 描述
            desc_parts = []
            if is_triple:
                desc_parts.append(f"三倍量({vol_ratio:.1f}x)")
            else:
                desc_parts.append(f"放量{vol_ratio:.1f}x")

            if shadow_ratio >= 4.0:
                desc_parts.append("长上影")
            elif shadow_ratio >= 3.0:
                desc_parts.append("中上影")
            else:
                desc_parts.append("短上影")

            if k.pct_chg >= 5:
                desc_parts.append(f"涨{k.pct_chg:.1f}%")
            elif k.pct_chg >= 2:
                desc_parts.append(f"冲高{k.pct_chg:.1f}%")
            else:
                desc_parts.append(f"微涨{k.pct_chg:.1f}%")

            desc = " + ".join(desc_parts)

            test_lines.append({
                "idx": i,
                "date": klines[i].date,
                "shadow_ratio": shadow_ratio,
                "vol_ratio": vol_ratio,
                "pct_chg": k.pct_chg,
                "is_triple": is_triple,
                "desc": desc,
            })

    if not test_lines:
        return False, {"count": 0, "latest_idx": -1, "latest_desc": "未发现试盘线",
                        "has_triple_vol": False, "avg_shadow_ratio": 0.0, "details": []}

    # 找最近的一次试盘线
    latest = test_lines[-1]
    avg_shadow = total_ratio / len(test_lines)

    details = [t["desc"] for t in test_lines]

    result = {
        "count": len(test_lines),
        "latest_idx": latest["idx"],
        "latest_date": latest["date"],
        "latest_desc": latest["desc"],
        "latest_shadow_ratio": latest["shadow_ratio"],
        "latest_vol_ratio": latest["vol_ratio"],
        "latest_pct_chg": latest["pct_chg"],
        "has_triple_vol": has_triple,
        "avg_shadow_ratio": round(avg_shadow, 1),
        "details": details,
    }

    return True, result


def is_main_wave_ignition(klines) -> Tuple[bool, str]:
    """
    主升浪起爆确认（股海炼金术完整主升浪起爆信号）

    四阶段模型:
    ┌─────────────────────────────────────────────────────────┐
    │ 阶段1: 震荡建仓 —— 主力震荡吸筹，振幅<35%，量能温和     │
    │ 阶段2: 试盘线 —— 放量上影线测试抛压（独立检测）         │
    │ 阶段3: 缩量整理 —— 试盘后缩量回调不破试盘线起点         │
    │ 阶段4: 放量突破 —— 今日放量突破试盘线高点 = 起爆确认    │
    └─────────────────────────────────────────────────────────┘

    三重确认（提高胜率）:
      ✅ 结构确认: 有震荡建仓基底
      ✅ 试盘确认: 出现有效试盘线
      ✅ 突破确认: 今日放量突破试盘线高点

    Returns:
        (是否起爆信号, 描述文字)
    """
    if len(klines) < 60:
        return False, "数据不足"

    c = len(klines) - 1
    today = klines[c]

    if today.pct_chg <= 0:
        return False, "今日未涨"

    # ════════════════════════════════════════
    # 阶段1: 震荡建仓检测（过去30-60天）
    # ════════════════════════════════════════
    lookback_range = min(60, len(klines) - 5)
    base = klines[-lookback_range:]

    base_high = max(k.high for k in base)
    base_low = min(k.low for k in base)
    base_avg_vol = sum(k.volume for k in base) / len(base)

    # 振幅条件: < 35%（震荡建仓期振幅不会太大）
    if base_low <= 0:
        return False, "数据异常"
    amplitude = (base_high - base_low) / base_low * 100
    if amplitude > 38:
        return False, f"振幅{amplitude:.0f}%过大(非震荡建仓)"

    # 排除已经走出一大段行情的（不是起爆，已经在半路了）
    current_from_base_low = (today.close - base_low) / base_low * 100
    if current_from_base_low > 45:
        return False, f"已从低位涨{current_from_base_low:.0f}%(非起爆点)"

    # 均线收敛: MA20和MA60接近（震荡期均线黏合）
    ma20_vals = _calc_ma(klines, 20)
    ma60_vals = _calc_ma(klines, 60)
    ma5_vals = _calc_ma(klines, 5)
    ma10_vals = _calc_ma(klines, 10)
    ma5 = ma5_vals[-1] if ma5_vals else 0
    ma10 = ma10_vals[-1] if ma10_vals else 0
    ma20 = ma20_vals[-1] if ma20_vals else 0
    ma60 = ma60_vals[-1] if ma60_vals else 0

    ma_gap = abs(ma20 - ma60) / ma60 * 100 if ma60 > 0 else 99
    # 均线不能离太远（震荡期均线应靠近）
    if ma_gap > 20 and current_from_base_low < 30:
        return False, f"均线发散(MA20/60差{ma_gap:.0f}%)"

    # ════════════════════════════════════════
    #  均线多头检查（主升浪起爆的必要条件）
    # ════════════════════════════════════════
    # 条件A: 短期均线向上 MA5 > MA10（不能是死叉状态）
    if ma5 <= ma10:
        return False, f"短期均线死叉(MA5{ma5:.2f}<MA10{ma10:.2f})"

    # 条件B: 股价在MA20之上（不能跌到均线下方）
    if today.close < ma20 * 0.98:
        return False, f"股价在MA20下方({today.close:.2f}<{ma20:.2f})"

    # 条件C: MA20不能明显下行（至少走平或向上）
    ma20_5ago = ma20_vals[-6] if len(ma20_vals) >= 6 else 0
    if ma20_5ago > 0 and ma20 < ma20_5ago * 0.98:
        return False, f"MA20下行({ma20:.2f}<{ma20_5ago:.2f})"

    # 条件D: 中期趋势 MA20 > MA60 加分但不是必须
    ma_mid_bullish = ma20 > ma60
    mid_tag = "中期多头" if ma_mid_bullish else "中期震荡"

    # ════════════════════════════════════════
    # 阶段2: 试盘线检测（过去30天内）
    # ════════════════════════════════════════
    has_test_line, tl_info = detect_test_line(klines, lookback=30)
    if not has_test_line:
        return False, "无试盘线"

    latest_test_idx = tl_info["latest_idx"]

    # ════════════════════════════════════════
    # 阶段3: 试盘后缩量整理检测
    # ════════════════════════════════════════
    test_line_k = klines[latest_test_idx]
    test_high = test_line_k.high  # 试盘线最高点
    test_low = test_line_k.low    # 试盘线最低点
    test_vol = test_line_k.volume

    # 试盘后到今天的区间
    post_range = klines[latest_test_idx + 1:c + 1]
    if len(post_range) < 2:
        # 试盘线就是今天？不构成起爆（需要确认）
        if latest_test_idx == c:
            return False, "试盘线即今日(尚未确认起爆)"
        # 试盘线是昨天？有可能
        # 至少需要1天的确认

    # 从试盘后到今天，最低价不能跌破试盘线最低价
    # 但允许小幅跌破2%（主力可能故意砸一下）
    post_min = min(k.low for k in post_range)
    if post_min < test_low * 0.97:
        return False, f"试盘后已跌破低点({post_min:.2f}<{test_low:.2f})"

    # 缩量确认: 试盘后均量 < 试盘前均量
    if latest_test_idx >= 10:
        pre_avg_vol = sum(klines[j].volume for j in range(latest_test_idx-10, latest_test_idx)) / 10
        post_avg_vol = sum(k.volume for k in post_range) / len(post_range) if post_range else 0
        if pre_avg_vol > 0 and post_avg_vol < pre_avg_vol * 1.1:
            pass  # 缩量整理确认
        elif post_avg_vol > pre_avg_vol * 1.5 and today.volume > pre_avg_vol * 1.5:
            # 如果放量可能是直接突破，也可以
            pass

    # ════════════════════════════════════════
    # 阶段4: 今日放量突破试盘线高点
    # ════════════════════════════════════════
    # 今日收盘 > 试盘线最高价
    if today.close <= test_high * 1.01:
        return False, f"未突破试盘线高点({today.close:.2f}<={test_high:.2f})"

    # 今日放量确认
    avg_vol_10 = sum(k.volume for k in klines[-15:-5]) / 10 if len(klines) >= 15 else 0
    if avg_vol_10 > 0 and today.volume < avg_vol_10 * 1.2:
        return False, f"突破量不足({today.volume/avg_vol_10:.1f}x<1.2x)"

    # ════════════════════════════════════════
    # 起爆信号确认 ✅
    # ════════════════════════════════════════

    # 计算各种辅助描述
    days_since_test = c - latest_test_idx

    # 判断试盘线类型
    tl_type = "普通"
    if tl_info["has_triple_vol"]:
        tl_type = "三倍量"
    elif tl_info["count"] >= 2:
        tl_type = "双试盘"

    # 突破力度
    breakout_strength = (today.close - test_high) / test_high * 100
    vol_ratio = today.volume / avg_vol_10 if avg_vol_10 > 0 else 0

    details = [
        f"震荡建仓(振幅{amplitude:.0f}%)",
        f"{tl_type}试盘{days_since_test}天前",
        f"突破{breakout_strength:.1f}%",
        f"放量{vol_ratio:.1f}x",
    ]

    # 均线状态
    if mid_tag == "中期多头":
        details.append("中期多头")
    else:
        details.append("中期震荡")

    # MACD状态
    _, _, macd_hist = _calc_macd(klines)
    if len(macd_hist) >= 2 and macd_hist[-1] > macd_hist[-2] > 0:
        details.append("MACD多头增强")

    return True, " + ".join(details)


def detect_base_consolidation(klines, lookback: int = 45) -> Tuple[bool, str]:
    """
    底部震荡建仓结构识别（辅助函数）

    判断过去N天是否处于震荡建仓形态:
    1. 振幅<35%
    2. MA20与MA60靠拢（均线收敛）
    3. 量能没有异常放大（无出货迹象）
    4. 不是单边下跌趋势

    Returns:
        (是否震荡建仓形态, 描述)
    """
    if len(klines) < lookback + 5:
        return False, "数据不足"

    segment = klines[-lookback:]

    seg_high = max(k.high for k in segment)
    seg_low = min(k.low for k in segment)
    seg_start = klines[-lookback].close
    seg_end = klines[-1].close

    if seg_low <= 0:
        return False, "数据异常"

    amplitude = (seg_high - seg_low) / seg_low * 100

    # 振幅太大 = 不是震荡建仓
    if amplitude > 35:
        return False, f"振幅{amplitude:.0f}%过大"

    # 排除单边下跌
    net_chg = (seg_end - seg_start) / seg_start * 100
    if net_chg < -20:
        return False, f"处于下跌趋势({net_chg:.0f}%)"

    # 均线收敛检测
    ma20 = _calc_ma(klines, 20)[-1]
    ma60 = _calc_ma(klines, 60)[-1]
    if ma60 > 0:
        ma_gap = abs(ma20 - ma60) / ma60 * 100
        ma_converging = ma_gap < 15
    else:
        ma_converging = False

    # 量能无异常
    avg_vol = sum(k.volume for k in segment) / len(segment)
    recent_vol = sum(k.volume for k in segment[-5:]) / 5
    no_abnormal_vol = recent_vol < avg_vol * 1.8  # 没有突然暴量

    parts = [f"震荡建仓(振幅{amplitude:.0f}%)"]
    if ma_converging:
        parts.append("均线收敛")
    if no_abnormal_vol:
        parts.append("量能正常")
    if net_chg > 5:
        parts.append(f"底部抬高{net_chg:.1f}%")

    return True, " + ".join(parts)


# ======================================================================
#  7. 飞龙在天 — 抓取龙头主升浪机会
# ======================================================================

def is_feilongzaitian(klines) -> Tuple[bool, Dict]:
    """
    飞龙在天策略 — 抓取龙头主升浪机会

    7大核心条件:
      条件1: 三连板以上（3+连续涨停 = 龙头辨识度）
      条件2: 断板洗盘（连续涨停后某天未涨停 = 风险释放）
      条件3: 反包/再板（断板次日涨停反包 = 主力继续拉升确认）
      条件4: 筹码集中 + 资金流入加快（辅助验证）
      条件5: 叠加当下持续性主线题材热点（空间支撑）
      条件6: 介入点 = 突破断板当日实体最高价
      条件7: 止损位 = 跌破断板当日最低价（5-8个点）

    空间龙/人气龙门槛总结:
      "3连板"是核心门槛 → 筛选有资金记忆的强势股
      "断板洗盘"是风险释放 → 规避短期获利盘、降低介入风险
      "反包/再板"是确认信号 → 验证主力继续拉升的意图
      与主线题材绑定 → 反包后有持续上涨空间

    Returns:
        (是否飞龙在天模式, { ... })
    """
    if len(klines) < 20:
        return False, {}

    c = len(klines) - 1

    # ═══════════════════════════════════════
    # 在最近20天内搜索 连板→断板→反包 模式
    # ═══════════════════════════════════════
    # 不限定搜索起始点：任何位置出现3连板+断板+反包都算
    for start in range(max(0, c - 20), c - 4):
        # 检查从start开始的连续涨停
        zt_indices = []
        for j in range(start, min(c + 1, start + 10)):
            prev_close = klines[j-1].close if j > 0 else 0
            if prev_close > 0 and klines[j].close >= prev_close * 1.09:
                zt_indices.append(j)
            else:
                break

        if len(zt_indices) < 3:
            continue

        # 找到了3+连板
        zt_count = len(zt_indices)
        last_zt_idx = zt_indices[-1]

        # 断板日
        break_idx = last_zt_idx + 1
        if break_idx > c:
            continue  # 断板日还没发生

        break_k = klines[break_idx]
        prev_close_break = klines[break_idx - 1].close
        if prev_close_break > 0 and break_k.close >= prev_close_break * 1.09:
            continue  # 未断板（继续涨停）

        if break_k.pct_chg < -7:
            continue  # 暴跌不是洗盘

        # 反包日
        confirm_idx = break_idx + 1
        if confirm_idx > c:
            continue  # 反包日还没发生

        confirm_k = klines[confirm_idx]
        prev_close_confirm = klines[break_idx].close
        is_confirm_up = confirm_k.close >= prev_close_confirm * 1.09
        is_confirm_today = (confirm_idx == c)

        if not is_confirm_up and not is_confirm_today:
            continue  # 无反包

        # ═══════════════════════════════════════
        # 条件4: 筹码集中判断（辅助）
        # ═══════════════════════════════════════
        chip_concentrated = False
        try:
            from chip_distribution import calc_chip_metrics
            cm = calc_chip_metrics(klines[:confirm_idx+1], lookback=250)
            if cm:
                if cm.get('float_chip', 100) < 25 and cm.get('profit_chip', 0) > 30:
                    chip_concentrated = True
        except:
            pass

        # 介入点/止损点
        break_entity_high = max(break_k.open, break_k.close)
        break_low = break_k.low
        is_entry = klines[c].close > break_entity_high * 1.01

        desc_parts = [f"飞龙在天({zt_count}连板)"]
        if chip_concentrated:
            desc_parts.append("筹码集中")
        if is_confirm_up:
            desc_parts.append(f"涨停反包{confirm_k.pct_chg:.1f}%")
        elif is_confirm_today:
            desc_parts.append("反包确认中")
        if is_entry:
            desc_parts.append("突破介入点")

        return True, {
            "连板数": zt_count,
            "断板日期": str(break_k.date),
            "断板涨幅": round(break_k.pct_chg, 2),
            "反包日期": str(confirm_k.date) if not is_confirm_today else "今日(待确认)",
            "反包涨幅": round(confirm_k.pct_chg, 2) if is_confirm_up else 0,
            "断板实体最高": round(break_entity_high, 2),
            "断板最低": round(break_low, 2),
            "介入价": round(break_entity_high * 1.01, 2),
            "止损价": round(break_low, 2),
            "描述": " + ".join(desc_parts),
        }

    return False, {"reason": "未找到飞龙在天模式"}

    # ═══════════════════════════════════════
    # 条件4: 筹码集中判断（辅助）
    # ═══════════════════════════════════════
    chip_concentrated = False
    try:
        from chip_distribution import calc_chip_metrics
        cm = calc_chip_metrics(klines[:break_idx+2], lookback=250)
        if cm:
            # 浮动筹码<20% 且 获利盘>40%
            if cm.get('float_chip', 100) < 25 and cm.get('profit_chip', 0) > 30:
                chip_concentrated = True
    except:
        pass

    # ═══════════════════════════════════════
    # 条件6: 介入点 = 突破断板日实体最高价
    # ═══════════════════════════════════════
    # 断板日的实体最高价 = max(开盘, 收盘)
    break_entity_high = max(break_k.open, break_k.close)
    break_low = break_k.low  # 条件7: 止损位

    # 如果今天就是反包日，看是否已突破断板实体最高价
    is_entry = today.close > break_entity_high * 1.01

    # ═══════════════════════════════════════
    # 生成结果
    # ═══════════════════════════════════════
    desc_parts = [f"飞龙在天({zt_count}连板)"]
    if chip_concentrated:
        desc_parts.append("筹码集中")
    if is_confirm_up:
        desc_parts.append(f"涨停反包{confirm_k.pct_chg:.1f}%")
    elif is_confirm_today:
        desc_parts.append("反包确认中")
    if is_entry:
        desc_parts.append("突破介入点")

    return True, {
        "连板数": zt_count,
        "断板日期": str(break_k.date),
        "断板涨幅": round(break_k.pct_chg, 2),
        "反包日期": str(klines[break_idx+1].date) if not is_confirm_today else "今日(待确认)",
        "反包涨幅": round(confirm_k.pct_chg, 2) if is_confirm_up else 0,
        "断板实体最高": round(break_entity_high, 2),
        "断板最低": round(break_low, 2),
        "介入价": round(break_entity_high * 1.01, 2),
        "止损价": round(break_low, 2),
        "描述": " + ".join(desc_parts),
    }


# ======================================================================
#  8. 潜龙回首战法 — 龙回头核心机会
# ======================================================================

def is_qianlonghuishou(klines) -> Tuple[bool, str]:
    """
    潜龙回首战法 — 股价连续大涨后的龙回头机会

    核心要点:
      条件1: 二板以上，涨幅20%以上（前期有龙头基因）
      条件2: 回调天数2-8天（洗盘时间适中）
      条件3: 回调幅度不超过50%（不能破位）
      条件4: 回调后企稳/放量信号（辅助确认）

    逻辑:
      不是所有回调都做 → 只做有辨识度的龙头股回调
      回调是风险释放 → 规避追高风险
      企稳确认 → 验证主力未走

    Args:
        klines: KLine对象列表

    Returns:
        (是否潜龙回首模式, 描述文字)
    """
    if len(klines) < 30:
        return False, "数据不足"

    c = len(klines) - 1
    today = klines[c]

    # ═══════════════════════════════════════
    # 找最近一波拉升的顶点
    # ═══════════════════════════════════════
    lookback = min(25, c)
    segment = klines[c - lookback:c + 1]

    # 找最近的高点（峰值）
    peak_idx = -1
    peak_price = 0
    for i in range(len(segment) - 1, -1, -1):
        k = segment[i]
        if k.close > peak_price:
            peak_price = k.close
            peak_idx = c - lookback + i

    if peak_idx < 0:
        return False, "未找到近期高点"

    # ═══════════════════════════════════════
    # 条件1: 前期涨幅>20%（二板以上）
    # ═══════════════════════════════════════
    pre_low_idx = max(0, peak_idx - 15)
    pre_low = min(k.low for k in klines[pre_low_idx:peak_idx + 1])

    if pre_low <= 0:
        return False, "数据异常"

    up_from_low = (peak_price - pre_low) / pre_low * 100
    if up_from_low < 18:
        return False, f"前期涨幅不足({up_from_low:.0f}%<20%)"

    # 涨停基因验证
    zt_count = sum(1 for k in klines[max(0, peak_idx-15):peak_idx+1] if k.pct_chg >= 9.0)
    if zt_count < 2 and up_from_low < 25:
        return False, "涨停基因不足"

    # ═══════════════════════════════════════
    # 条件2: 回调天数2-8天
    # ═══════════════════════════════════════
    pullback_days = c - peak_idx
    if pullback_days < 1:
        return False, "未开始回调"
    if pullback_days > 8:
        return False, f"回调天数过多({pullback_days}天>8天)"

    # ═══════════════════════════════════════
    # 条件3: 回调幅度不超过50%
    # ═══════════════════════════════════════
    pullback_low = min(k.low for k in klines[peak_idx:c + 1])
    pullback_pct = (peak_price - pullback_low) / peak_price * 100

    if pullback_pct > 50:
        return False, f"回调幅度过大({pullback_pct:.0f}%>50%)"

    # 从最高点回撤了多少
    current_from_peak = (today.close - peak_price) / peak_price * 100

    # ═══════════════════════════════════════
    # 生成描述
    # ═══════════════════════════════════════
    parts = [f"潜龙回首(回调{pullback_days}天)"]
    parts.append(f"前期涨{up_from_low:.0f}%")
    parts.append(f"最大回撤{pullback_pct:.0f}%")
    if zt_count >= 3:
        parts.append(f"{zt_count}板基因")
    if today.pct_chg > 0:
        parts.append("今日收涨(企稳中)")

    return True, " + ".join(parts)


def is_dragon_pattern(klines) -> Tuple[bool, str, str]:
    """
    综合龙头模式识别（飞龙在天 + 潜龙回首）
    返回: (是否为龙头模式, 模式类型, 描述)
    """
    # 先检测飞龙在天（主升浪中的龙头接力）
    fl_ok, fl_info = is_feilongzaitian(klines)
    if fl_ok:
        return True, "飞龙在天", fl_info.get("描述", "")

    # 再检测潜龙回首（回调后的龙回头机会）
    ql_ok, ql_desc = is_qianlonghuishou(klines)
    if ql_ok:
        return True, "潜龙回首", ql_desc

    return False, "", ""
