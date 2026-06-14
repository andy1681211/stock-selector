#!/usr/bin/env python3
"""
本地选股引擎 - 基于通达信日K线数据
直接读取本地 .day 文件，计算技术指标，执行5大短线策略
无需API，数据更快，能算MACD/均线/RSI等
"""

import os
import sys
import struct
import re
import math
import numpy as np
import talib
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# 导入市场状态识别模块（Hermes Skill Router 架构思想）
from market_regime import detect_market_regime, get_strategy_weights, format_market_report
# 导入基本面筛选模块
from fundamental_screen import fundamental_filter
# 导入高级信号模块（缠论底分型 / 平步青云 / 洗盘识别 / 倍量突破 / 股海炼金术）
from advanced_signals import (
    detect_bottom_fractal, is_bottom_fractal_valid,
    pingbu_qingyun_score,
    is_washout_complete, is_day_trade_entry,
    is_volume_surge_breakout,
    is_position_building_limit_up, is_washout_limit_up,
    is_erjin_san_pattern, limit_up_type_analysis,
    # 主升浪起爆信号
    detect_test_line, is_main_wave_ignition, detect_base_consolidation,
    # 龙头模式信号
    is_feilongzaitian, is_qianlonghuishou, is_dragon_pattern,
)
# 导入筹码分布模块
from chip_distribution import calc_chip_metrics, chip_screen_conditions, interpret_chip, analyze_turnover_rate
# 导入七角色圆桌会议模块
from seven_roles import seven_roles_analysis

TDX_ROOT = "D:/new_tdx/vipdoc"
HQ_CACHE = "D:/new_tdx/T0002/hq_cache"
OUTPUT_DIR = Path(__file__).parent / "output"
TRACKING_FILE = OUTPUT_DIR / "tracking.json"


# ==================== 持续跟踪池 ====================

def load_tracker() -> Dict[str, dict]:
    """加载历史跟踪数据"""
    if not TRACKING_FILE.exists():
        return {}
    try:
        import json
        data = json.loads(TRACKING_FILE.read_text("utf-8"))
        if isinstance(data, list):
            d = {}
            for item in data:
                code = item.get("code", "")
                if code:
                    d[code] = item
            return d
        return data
    except:
        return {}


def save_tracker(tracker: Dict[str, dict]):
    """保存跟踪数据"""
    TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)
    import json
    sorted_data = dict(sorted(tracker.items(), key=lambda x: x[1].get("first_selected", "")))
    TRACKING_FILE.write_text(json.dumps(sorted_data, ensure_ascii=False, indent=2), "utf-8")


def merge_into_tracker(tracker: Dict[str, dict], today_results: List[Dict]):
    """
    当日选股结果合并入跟踪池
    - 新股票: 记录首次入选日期
    - 已有股票: 追加当日涨跌数据, 更新 last_seen
    - 标记过期的删除候选
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_date = datetime.now().date()

    for r in today_results:
        code = r.get("代码", "")
        if not code:
            continue
        name = r.get("名称", "")
        chg = r.get("涨跌幅", 0) or 0
        price = r.get("最新价", 0) or 0
        score = r.get("综合评分", 0) or r.get("评分", 0) or r.get("策略命中", 0) * 10
        tag_str = _make_tracker_tag(r)

        if code not in tracker:
            tracker[code] = {
                "code": code,
                "name": name,
                "first_selected": today_str,
                "last_seen": today_str,
                "days_tracked": 1,
                "daily_chgs": [],
                "max_daily_chg": 0.0,
                "recent_3d_sum": 0.0,
                "status": "跟踪中",
                "signals": [tag_str],
            }

        entry = tracker[code]
        entry["name"] = name
        entry["last_seen"] = today_str
        entry["days_tracked"] = (today_date - datetime.strptime(entry["first_selected"], "%Y-%m-%d").date()).days + 1

        entry["daily_chgs"].append({
            "date": today_str, "chg": round(chg, 2),
            "price": round(price, 2), "signal": tag_str
        })

        if len(entry["daily_chgs"]) > 30:
            entry["daily_chgs"] = entry["daily_chgs"][-30:]

        daily_chgs = [d["chg"] for d in entry["daily_chgs"]]
        entry["max_daily_chg"] = round(max(daily_chgs), 2)
        recent_3 = daily_chgs[-3:] if len(daily_chgs) >= 3 else daily_chgs
        entry["recent_3d_sum"] = round(sum(recent_3), 2)

        if entry["daily_chgs"]:
            entry["total_chg"] = round(
                (entry["daily_chgs"][-1]["price"] - entry["daily_chgs"][0]["price"])
                / entry["daily_chgs"][0]["price"] * 100, 2
            )
        else:
            entry["total_chg"] = 0.0

        if tag_str not in entry["signals"]:
            entry["signals"].append(tag_str)
        if len(entry["signals"]) > 5:
            entry["signals"] = entry["signals"][-5:]

        # 判定淘汰: 跟踪 >= 7天 且 期间最大单日涨幅 < 2% 且 最近3日涨幅 < 2%
        if entry["days_tracked"] >= 7 and entry["max_daily_chg"] < 2.0 and entry["recent_3d_sum"] < 2.0:
            entry["status"] = "考虑删除"
        elif entry["days_tracked"] >= 10 and entry["max_daily_chg"] < 3.0:
            entry["status"] = "考虑删除"
        elif entry["days_tracked"] >= 7 and entry["max_daily_chg"] >= 2.0:
            entry["status"] = "跟踪中"
        else:
            entry["status"] = "跟踪中"

    save_tracker(tracker)
    return tracker


def _make_tracker_tag(r: Dict) -> str:
    """生成简短标记用于跟踪"""
    tags = []
    lc = r.get("低吸买点", "")
    if lc:
        tags.append("低吸")
    chan = r.get("缠论买点", "")
    if chan:
        short = chan.replace(" + ", "+").replace("二买", "2买").replace("三买", "3买").replace("一买", "1买")
        tags.append(f"缠{short}")
    sbo = r.get("九爆发", "")
    if sbo == "三破":
        tags.append("三破")
    elif sbo == "七入":
        tags.append("七入")
    elif sbo:
        tags.append("九爆发")
    e7 = r.get("三破七入", "")
    if e7 and not sbo:
        tags.append("3破7入")
    sl = r.get("策略列表", [])
    if "低位放量首板" in sl and "低吸买点" not in sl:
        tags.append("首板")
    if "连板接力弱转强" in sl:
        tags.append("连板")
    if "趋势加速" in sl and "低吸买点" not in sl:
        tags.append("加速")
    if "N字反包" in sl and "低吸买点" not in sl:
        tags.append("N字")
    # 主升浪起爆信号
    if r.get("主升浪起爆", ""):
        tags.append("起爆")
    if r.get("三倍量试盘", ""):
        tags.append("三倍试盘")
    elif r.get("试盘线", ""):
        tags.append("试盘")
    if r.get("震荡建仓", ""):
        tags.append("震仓")
    return "+".join(tags[:4]) if tags else "其他"


def get_tracking_report(tracker: Dict[str, dict], max_stocks: int = 20) -> str:
    """生成持续跟踪池报告段"""
    if not tracker:
        return ""

    today_date = datetime.now().date()
    lines = []
    lines.append("")
    lines.append("─" * 70)
    lines.append("【持续跟踪池】历史入选股票每日表现")
    lines.append("  规则: 新股票追加不覆盖 | 跟踪>=7天无上涨(单日<2%)自动标记删除")
    lines.append("─" * 70)

    active = [e for e in tracker.values() if e.get("status") != "考虑删除"]
    to_del = [e for e in tracker.values() if e.get("status") == "考虑删除"]

    active.sort(key=lambda e: -(e.get("recent_3d_sum", 0) * 2 + e.get("max_daily_chg", 0)))
    to_del.sort(key=lambda e: -e.get("days_tracked", 0))

    lines.append(f"  {'标记':<14} {'代码':<8} {'名称':<10} {'入选日':<10} {'天数':<4} {'最大日涨':<8} {'近3日':<8} {'累计':<8} {'状态'}")
    lines.append(f"  {'-'*14} {'-'*8} {'-'*10} {'-'*10} {'-'*4} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")

    for e in (active + to_del)[:max_stocks]:
        sig = (e.get("signals") or ["?"])[0]
        fs = e.get("first_selected", "?")
        days = e.get("days_tracked", 0)
        mdc = e.get("max_daily_chg", 0)
        r3 = e.get("recent_3d_sum", 0)
        tc = e.get("total_chg", 0)
        st = e.get("status", "跟踪中")
        st_mark = "*" if st == "跟踪中" else "-"

        try:
            fs_date = datetime.strptime(fs, "%Y-%m-%d").date()
            days_ago = (today_date - fs_date).days
            fs_display = fs if days_ago <= 1 else f"{fs}({days_ago}d)"
        except:
            fs_display = fs

        lines.append(f"  {sig:<14} {e['code']:<8} {e['name']:<10} {fs_display:<10} {days:<4} {mdc:<+7.2f}% {r3:<+7.2f}% {tc:<+7.2f}% {st_mark}")

    if to_del:
        lines.append("")
        lines.append("  ⚠️ 以下股票连续7天无表现，建议删除自选:")
        for e in to_del[:5]:
            sig = (e.get("signals") or ["?"])[0]
            mdc = e.get("max_daily_chg", 0)
            lines.append(f"    {sig:<12} {e['code']:<8} {e['name']:<10} 跟踪:{e['days_tracked']}天  最大涨幅:{mdc:+.1f}%")

    lines.append("")
    return "\n".join(lines)


# ==================== 股票名称映射 ====================

_code_name_map = None

def load_code_name_map() -> Dict[str, str]:
    """加载股票代码->名称映射"""
    global _code_name_map
    if _code_name_map is not None:
        return _code_name_map

    _code_name_map = {}
    path = os.path.join(HQ_CACHE, "infoharbor_ex.code")
    if os.path.exists(path):
        with open(path, 'r', encoding='gbk', errors='ignore') as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) >= 2:
                    code, name = parts[0].strip(), parts[1].strip()
                    if code and name:
                        _code_name_map[code] = name
    return _code_name_map


def get_stock_name(code: str) -> str:
    """获取股票名称"""
    m = load_code_name_map()
    return m.get(code, "")


# ==================== 日K线解析 ====================

class KLine:
    """日K线"""
    __slots__ = ('date', 'open', 'high', 'low', 'close', 'amount', 'volume', 'pct_chg')

    def __init__(self, date: date, open_: float, high: float, low: float,
                 close: float, amount: float, volume: float):
        self.date = date
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.amount = amount    # 元
        self.volume = volume    # 手
        self.pct_chg = 0.0


def parse_day_file(filepath: str, max_records: int = 500) -> List[KLine]:
    """解析通达信 .day 文件"""
    if not os.path.exists(filepath):
        return []

    size = os.path.getsize(filepath)
    count = size // 32
    if count == 0:
        return []
    if max_records > 0 and count > max_records:
        # 只读最近的数据
        skip = count - max_records
    else:
        skip = 0

    klines = []
    with open(filepath, 'rb') as f:
        if skip > 0:
            f.seek(skip * 32)
        for _ in range(count - skip if max_records > 0 else count):
            rec = f.read(32)
            if len(rec) != 32:
                break
            date_int, open_, high, low, close, amount, volume, _ = \
                struct.unpack('iiiiifii', rec)
            try:
                dt = datetime.strptime(str(date_int), '%Y%m%d').date()
            except:
                continue
            kl = KLine(dt, open_/100, high/100, low/100, close/100, amount, volume/100)
            klines.append(kl)

    # 补涨跌幅
    for i in range(1, len(klines)):
        prev = klines[i-1].close
        if prev > 0:
            klines[i].pct_chg = (klines[i].close - prev) / prev * 100
    return klines


# ==================== 技术指标（基于TA-Lib）====================

def calc_ma(klines: List[KLine], period: int) -> List[float]:
    """移动平均线 (使用TA-Lib)"""
    closes = np.array([k.close for k in klines], dtype=float)
    result = talib.SMA(closes, period)
    return [float(v) if not np.isnan(v) else 0.0 for v in result]


def calc_ema(values: List[float], period: int) -> List[float]:
    """指数移动平均 (使用TA-Lib)"""
    arr = np.array(values, dtype=float)
    result = talib.EMA(arr, period)
    return [float(v) if not np.isnan(v) else 0.0 for v in result]


def calc_macd(klines: List[KLine], fast=12, slow=26, signal=9):
    """MACD: 返回 (DIF, DEA, MACD柱) 三列表 (使用TA-Lib)"""
    closes = np.array([k.close for k in klines], dtype=float)
    dif, dea, hist = talib.MACD(closes, fast, slow, signal)
    return ([float(v) if not np.isnan(v) else 0.0 for v in dif],
            [float(v) if not np.isnan(v) else 0.0 for v in dea],
            [float(v) if not np.isnan(v) else 0.0 for v in hist])


def calc_rsi(klines: List[KLine], period=6) -> List[float]:
    """RSI指标 (使用TA-Lib)"""
    closes = np.array([k.close for k in klines], dtype=float)
    result = talib.RSI(closes, period)
    return [float(v) if not np.isnan(v) else 50.0 for v in result]


def calc_vr(klines: List[KLine], period=5) -> List[float]:
    """量比 = 今日量 / 5日均量"""
    vols = [k.volume for k in klines]
    return [vols[i]/sum(vols[max(0,i-period):i])*period if i >= period and sum(vols[max(0,i-period):i]) > 0 else 0.0
            for i in range(len(vols))]


def is_ma_bullish(klines: List[KLine], periods=(5, 10, 20, 60)) -> bool:
    """均线多头排列检查"""
    if len(klines) < max(periods): return False
    mas = [calc_ma(klines, p)[-1] for p in periods]
    return all(mas[i] > mas[i+1] > 0 for i in range(len(mas)-1))


def is_macd_golden_cross(klines: List[KLine]) -> bool:
    """MACD金叉 (DIF上穿DEA)"""
    if len(klines) < 35: return False
    dif, dea, _ = calc_macd(klines)
    return dif[-1] > dea[-1] and dif[-2] <= dea[-2]


def is_macd_bullish(klines: List[KLine]) -> bool:
    """MACD多头 (DIF > DEA > 0)"""
    if len(klines) < 35: return False
    dif, dea, _ = calc_macd(klines)
    return dif[-1] > dea[-1] > 0


def is_volume_breakout(klines: List[KLine], ratio=2.0) -> bool:
    """放量突破: 今日量 > 5日均量 * ratio"""
    if len(klines) < 6: return False
    vr = calc_vr(klines, 5)
    return vr[-1] >= ratio


def has_recent_limit_up(klines: List[KLine], days=10) -> bool:
    """最近N日内是否涨停/大涨>9%"""
    if len(klines) < days+1: return False
    for k in klines[-days:]:
        if k.pct_chg >= 9.0:
            return True
    return False


def is_n_shape(klines: List[KLine]) -> bool:
    """N字反包: 前10天内有涨停, 随后有过回调(阴线), 今日重新走强"""
    if len(klines) < 15: return False

    k = klines
    c = len(k) - 1

    # 10天内有涨停基因
    has_limit = False
    limit_pos = -1
    for i in range(-11, -1):
        if k[i].pct_chg >= 9.0:
            has_limit = True
            limit_pos = i
            break
    if not has_limit:
        return False

    # 涨停后到昨天之间有至少1天的回调(阴线或负涨幅)
    had_pullback = False
    for i in range(limit_pos + 1, c):
        if k[i].pct_chg <= -0.5 or k[i].close < k[i].open:
            had_pullback = True
            break
    if not had_pullback:
        return False

    # 今日涨幅>3%确认启动
    return k[c].pct_chg >= 3.0


def is_platform_breakout(klines: List[KLine], lookback=20, tolerance=0.3) -> bool:
    """
    突破20日平台判断（三步伏击涨停笔记）
    条件:
    1. 过去20天横盘整理(振幅<30%)
    2. 今日收盘突破20日最高点
    3. 伴随放量
    """
    if len(klines) < lookback + 5:
        return False

    recent = klines[-(lookback+1):-1]  # 前20天（不含今日）
    today = klines[-1]

    # 20日平台最高价和最低价
    platform_high = max(k.high for k in recent)
    platform_low = min(k.low for k in recent)

    # 平台振幅<30%（横盘整理）
    if platform_low > 0:
        amplitude = (platform_high - platform_low) / platform_low * 100
        if amplitude > 30:
            return False

    # 今日收涨>2%且收盘站上平台最高价
    if today.close > platform_high and today.pct_chg > 2:
        return True

    return False


# ==================== 低吸买点检测（新增）====================

def is_pullback_entry(klines: List[KLine]) -> bool:
    """
    低吸买点检测 —— 放过第一波，等缩量回调企稳再介入

    核心逻辑（三步伏击涨停笔记 + 缠论二买思想）:
    1. 前期(5-15天内)有过放量大涨/涨停/突破 = 主力进场痕迹
    2. 近期(最近3天)缩量回调/横盘 = 洗盘/蓄力
    3. 今日企稳信号 = 小阳/十字星/下影线，不破关键支撑
    4. MACD仍在多头区域或即将金叉 = 趋势未走坏

    返回: True = 当前是低吸买点区域
    """
    if len(klines) < 25:
        return False

    k = klines
    c = len(k) - 1  # 今日
    today = k[c]

    # ----- 1. 检查前期是否出现过拉升信号（5-15天前）-----
    has_initial_signal = False
    initial_high = 0.0
    initial_vol_avg = 0.0
    for i in range(-16, -4):  # T-5 ~ T-15
        chg = k[i].pct_chg
        if chg >= 5.0:  # 大涨/涨停
            has_initial_signal = True
            # 记录拉升期的高点和量能
            for j in range(max(-20, i-2), min(-3, i+3)):
                if k[j].high > initial_high:
                    initial_high = k[j].high
                initial_vol_avg += k[j].volume
            break

    if not has_initial_signal:
        return False

    # ----- 2. 检查近期是否缩量回调（最近3天）-----
    recent_3 = k[-4:-1]  # T-3 ~ T-1（不含今日）
    pullback_vol_avg = sum(x.volume for x in recent_3) / 3
    ref_vol = sum(x.volume for x in k[-10:-4]) / 6  # 拉升前/中的均量

    if ref_vol <= 0:
        return False

    vol_shrink_ratio = pullback_vol_avg / ref_vol
    # 量能萎缩到前期均量的70%以下 = 缩量回调
    is_vol_shrinking = vol_shrink_ratio < 0.7

    # 回调幅度：从拉升高点回撤了至少一部分
    pullback_low = min(x.low for x in recent_3)
    pullback_from_high = (initial_high - pullback_low) / initial_high * 100

    # 不能完全没回调（还在继续涨 -> 不是低吸点）
    if pullback_from_high < 1.0:
        return False

    # ----- 3. 今日企稳信号 -----
    today_vol_ratio = today.volume / ref_vol if ref_vol > 0 else 99

    # 企稳条件：
    # 条件A: 今日收小阳线/十字星（涨幅-1% ~ +3%）, 量能不大
    cond_small_stabilize = (
        -1.0 <= today.pct_chg <= 3.0
        and today_vol_ratio < 1.2  # 不放量
        and today.close >= pullback_low * 0.99  # 不破近期低点
    )

    # 条件B: 今日小跌但下影线长（探底回升）
    lower_shadow = today.high - today.low
    body = abs(today.close - today.open)
    cond_long_lower_shadow = (
        today.pct_chg < 0
        and lower_shadow > body * 2  # 下影线是实体的2倍以上
        and today_vol_ratio < 1.3
        and today.close > pullback_low  # 收盘没破近期低点
    )

    if not (cond_small_stabilize or cond_long_lower_shadow):
        return False

    # ----- 4. 关键支撑检查 -----
    ma20_list = calc_ma(klines, 20)
    ma20 = ma20_list[-1] if ma20_list else 0
    ma60_list = calc_ma(klines, 60)
    ma60 = ma60_list[-1] if ma60_list else 0

    # 不跌破重要均线（允许小幅跌破MA20但必须收回）
    if today.close < ma20 * 0.97:
        return False

    # ---- 5. MACD状态检查 ----
    dif, dea, macd_hist = calc_macd(klines)
    macd_still_good = (
        dif[-1] > dea[-1]  # DIF > DEA（多头）
        or macd_hist[-1] > macd_hist[-2]  # 绿柱缩短/红柱变长
    )

    if not macd_still_good and today.pct_chg <= 0:
        # 如果MACD走坏且今天没涨，说明可能真跌了
        return False

    return True


def describe_pullback(klines: List[KLine]) -> str:
    """低吸买点描述，说明处于哪个阶段"""
    if not is_pullback_entry(klines):
        return ""
    k = klines
    c = len(k) - 1
    parts = []

    # 判断回调程度
    recent_3_low = min(x.low for x in k[-4:-1])
    ma20_list = calc_ma(klines, 20)
    ma20 = ma20_list[-1] if ma20_list else 0

    if k[c].close >= ma20 * 1.02:
        parts.append("强势回踩")
    elif k[c].close >= ma20 * 0.99:
        parts.append("精准回踩MA20")
    else:
        parts.append("回踩企稳")

    # 判断量能
    ref_vol = sum(x.volume for x in k[-10:-4]) / 6
    today_ratio = k[c].volume / ref_vol if ref_vol > 0 else 1
    if today_ratio < 0.5:
        parts.append("地量")

    return " + ".join(parts)


# ==================== 三破七入九爆发（首板→破位→启动）====================

def is_second_breakout(klines: List[KLine], full_code: str = "") -> Tuple[bool, str]:
    """
    三破七入九爆发策略（PDF原文完整移植，含全部细节要素）

    通达信公式:
    ───────────────────────────────────────
    ZT:=C>=REF(C,1)*1.095 AND C=H;
    ZTO:=REF(O,BARSLAST(ZT));
    ZTL:=REF(L,BARSLAST(ZT));
    X:BARSLAST(ZT)>1 AND BARSLAST(ZT)<11
    AND C>ZTO
    AND (
     (REF(L,BARSLAST(ZT)-1)<ZTL AND BARSLAST(ZT)>1 AND BARSLAST(ZT)<9 AND C=HHV(C,BARSLAST(ZT)-1))
     OR
     (REF(L,BARSLAST(ZT)-2)<ZTL AND REF(L,BARSLAST(ZT)-1)>ZTL AND
      BARSLAST(ZT)>2 AND BARSLAST(ZT)<10 AND C=HHV(C,BARSLAST(ZT)-2))
     OR
     (REF(L,BARSLAST(ZT)-3)<ZTL AND REF(L,BARSLAST(ZT)-2)>ZTL AND
      REF(L,BARSLAST(ZT)-1)>ZTL AND BARSLAST(ZT)>3 AND BARSLAST(ZT)<11
      AND C=HHV(C,BARSLAST(ZT)-3))
    );

    PDF细节要素（全部纳入前置过滤）:
    ─────────────────────────────────────────────────────────────
    结构要点:  有涨停 → 不疯狂(不≥三连板) → 3天内破涨停最低
    上车量价时空: 量>均量 | 收>ZTO且<涨停收 | 7天内 | 距历史高点>20%
    细节要素:  60均上/走平+涨停开在60均上 | 破板绿量递减 | 不跌停 | 不次新
    ─────────────────────────────────────────────────────────────

    三种模式:
      三破  — 第1天跌破涨停最低 → 今日创涨停后新高
      七入  — 第1天守住 → 第2天跌破 → 今日创涨停后新高
      九爆发 — 第1~2天守住 → 第3天跌破 → 今日创涨停后新高
    """
    if len(klines) < 60:  # 需60天数据用于MA60
        return (False, "")

    c = len(klines) - 1
    today = klines[c]

    # ═══════════════════════════════════════════
    #  步骤1: 寻找最近的涨停板
    # ═══════════════════════════════════════════
    zt_idx = -1
    for i in range(c - 1, 0, -1):
        prev_close = klines[i-1].close
        if prev_close > 0 and klines[i].close >= prev_close * 1.095 and klines[i].close == klines[i].high:
            # 检查: 涨停不能是一字板(O==C==H) 或 T字板(有下影线但C=H)
            if klines[i].open == klines[i].close == klines[i].high:
                continue  # 一字板跳过
            zt_idx = i
            break

    if zt_idx == -1:
        return (False, "")

    bars_last = c - zt_idx
    zt = klines[zt_idx]
    zto = zt.open        # ZTO: 涨停开盘价
    ztl = zt.low          # ZTL: 涨停最低价
    ztc = zt.close        # 涨停收盘价

    # ═══════════════════════════════════════════
    #  前置过滤: 所有PDF细节要素
    # ═══════════════════════════════════════════

    # ── 1. 不能≥三连板（涨停前不能有连续2个涨停）──
    consecutive = 1
    for j in range(zt_idx - 1, max(0, zt_idx - 5), -1):
        prev_c = klines[j-1].close if j > 0 else 0
        if prev_c > 0 and klines[j].close >= prev_c * 1.095:
            consecutive += 1
        else:
            break
    if consecutive >= 3:
        return (False, f"≥{consecutive}连板")

    # ── 2. 一年以内的次新不做 ──
    # 检查最早可用数据是否覆盖至少1年
    data_span = (klines[c].date - klines[0].date).days
    if data_span < 250:
        return (False, "数据不足1年(疑似次新)")

    # ── 3. 60均方向往上或走平; 涨停开盘价在60均上方 ──
    ma60_list = calc_ma(klines, 60)
    ma60 = ma60_list[-1] if ma60_list else 0
    ma60_prev = ma60_list[-5] if len(ma60_list) >= 5 else 0

    if ma60 <= 0 or zto <= 0:
        return (False, "均线数据异常")

    # MA60方向: 当前MA60 > 5天前的MA60 * 0.98 视为走平或向上
    if ma60 < ma60_prev * 0.98:
        return (False, f"60均下行({round(ma60,2)}<{round(ma60_prev,2)})")

    # 涨停开盘价在60均上方
    if zto < ma60:
        return (False, f"涨停开{round(zto,2)}<60均{round(ma60,2)}")

    # ── 4. 下跌趋势不做 ──
    # 检查过去20日涨幅
    chg_20d = (ztc - klines[max(0, zt_idx-20)].close) / klines[max(0, zt_idx-20)].close * 100 if klines[max(0, zt_idx-20)].close > 0 else 0
    if chg_20d < -10:
        return (False, "下跌趋势")

    # ── 5. 破板期间不能有跌停 ──
    for j in range(zt_idx + 1, c):
        prev_c = klines[j-1].close
        if prev_c > 0 and klines[j].close <= prev_c * 0.905:
            return (False, "破板期有跌停")

    # ── 6. 破板期间绿色量逐步缩减 ──
    # 找到破板期间的阴线(close<open)，检查量能是否递减
    green_days = []
    for j in range(zt_idx + 1, c):
        if klines[j].close < klines[j].open:  # 阴线
            green_days.append((j, klines[j].volume))

    if len(green_days) >= 3:
        # 检查阴线量能是否递减(最后阴线量<第一阴线量)
        if green_days[-1][1] > green_days[0][1] * 0.9:
            return (False, f"绿色量未递减({green_days[0][1]:.0f}→{green_days[-1][1]:.0f})")

    # ── 7. 破板期间，只能有一个开或收盘≥涨停收盘 ──
    exceed_count = 0
    for j in range(zt_idx + 1, c):
        if klines[j].open >= ztc or klines[j].close >= ztc:
            exceed_count += 1
    if exceed_count > 1:
        return (False, f"破板期{exceed_count}次触碰涨停收")

    # ── 8. 距历史高点至少20%空间（检查年线高点）──
    year_high = max(k.high for k in klines[max(0, c-250):c+1])
    if today.close >= year_high * 0.80:
        return (False, f"距历史高{round(year_high,2)}不足20%空间")

    # ═══════════════════════════════════════════
    #  步骤2: 公式核心条件
    # ═══════════════════════════════════════════

    # ── BARSLAST>1 AND <11 AND C>ZTO ──
    if not (bars_last > 1 and bars_last < 11):
        return (False, f"周期{bars_last}∉[2,10]")

    if today.close <= zto:
        return (False, f"今日收{round(today.close,2)}≤涨停开{round(zto,2)}")

    # ── 三破模式 ──
    if bars_last > 1 and bars_last < 9:
        day1 = zt_idx + 1
        if day1 <= c and klines[day1].low < ztl:
            post_closes = [k.close for k in klines[zt_idx + 1:]]
            if post_closes and today.close == max(post_closes):
                return (True, "三破")

    # ── 七入模式 ──
    if bars_last > 2 and bars_last < 10:
        day1 = zt_idx + 1
        day2 = zt_idx + 2
        if (day2 <= c
                and klines[day1].low > ztl
                and klines[day2].low < ztl):
            post_closes = [k.close for k in klines[zt_idx + 2:]]
            if post_closes and today.close == max(post_closes):
                return (True, "七入")

    # ── 九爆发模式 ──
    if bars_last > 3 and bars_last < 11:
        day1 = zt_idx + 1
        day2 = zt_idx + 2
        day3 = zt_idx + 3
        if (day3 <= c
                and klines[day1].low > ztl
                and klines[day2].low > ztl
                and klines[day3].low < ztl):
            post_closes = [k.close for k in klines[zt_idx + 3:]]
            if post_closes and today.close == max(post_closes):
                return (True, "九爆发")

    return (False, "")


def is_entry_3po7ru(klines: List[KLine], full_code: str = "") -> Tuple[bool, str]:
    """
    三破七入上车策略（PDF上车标准完整实现）

    上车量价时空:
    ───────────────────────────────────
    量: 目标K线量 > 涨停后到判断日前的均量
    价: 收盘 > 涨停开盘(ZTO) 且 < 涨停收盘(ZTC)
    时: 只做破板后7天内（涨停日不算，破板日算第1天）
    空: 距历史高点至少20%空间

    买点规则:
    - 买点K线只做红K(close>open)且放量
    - 破板期间缩量调整为宜(放量防止出货)
    - 止损: 买点K线最低价
    """
    if len(klines) < 60:
        return (False, "")

    c = len(klines) - 1
    today = klines[c]

    # ── 找最近涨停 ──
    zt_idx = -1
    for i in range(c - 1, 0, -1):
        prev_close = klines[i-1].close
        if prev_close > 0 and klines[i].close >= prev_close * 1.095 and klines[i].close == klines[i].high:
            if klines[i].open == klines[i].close == klines[i].high:
                continue  # 一字板跳过
            zt_idx = i
            break
    if zt_idx == -1:
        return (False, "")

    bars_last = c - zt_idx
    zt = klines[zt_idx]
    zto = zt.open
    ztl = zt.low
    ztc = zt.close

    # ── 前置过滤(同is_second_breakout) ──

    # 不≥三连板
    consecutive = 1
    for j in range(zt_idx - 1, max(0, zt_idx - 5), -1):
        prev_c = klines[j-1].close if j > 0 else 0
        if prev_c > 0 and klines[j].close >= prev_c * 1.095:
            consecutive += 1
        else:
            break
    if consecutive >= 3:
        return (False, "")

    # 不次新
    data_span = (klines[c].date - klines[0].date).days
    if data_span < 250:
        return (False, "")

    # 60均方向
    ma60_list = calc_ma(klines, 60)
    ma60 = ma60_list[-1] if ma60_list else 0
    ma60_prev = ma60_list[-5] if len(ma60_list) >= 5 else 0
    if ma60 <= 0 or ma60 < ma60_prev * 0.98:
        return (False, "")
    if zto < ma60:
        return (False, "")

    # ── 3破条件: 涨停后3天内出现过跌破涨停最低 ──
    has_break = False
    break_day = -1
    for j in range(1, min(4, c - zt_idx + 1)):
        idx = zt_idx + j
        if idx <= c and klines[idx].low < ztl:
            has_break = True
            break_day = j
            break
    if not has_break:
        return (False, "")

    # ── 7入条件: 破板后7天内找上车点 ──
    # 涨停当天不算，今天是破板后的第N天
    days_since_zt = c - zt_idx
    if days_since_zt > 7:
        return (False, "超7天")

    # ── 量: 今日量 > 涨停后到判断日前的均量 ──
    post_volumes = [klines[i].volume for i in range(zt_idx + 1, c)]
    avg_vol = sum(post_volumes) / len(post_volumes) if post_volumes else 0
    if avg_vol > 0 and today.volume <= avg_vol:
        return (False, f"量{round(today.volume,0)}≤均{round(avg_vol,0)}")

    # ── 价: 收盘 > ZTO 且 < 涨停收盘 ──
    if not (zto < today.close < ztc):
        return (False, f"收{round(today.close,2)}不在({round(zto,2)},{round(ztc,2)})区间")

    # ── 买点K线只做红K ──
    if today.close <= today.open:
        return (False, "非红K")

    # ── 空: 距历史高点至少20%空间 ──
    year_high = max(k.high for k in klines[max(0, c-250):c+1])
    if today.close >= year_high * 0.80:
        return (False, f"距历史高{round(year_high,2)}空间不足20%")

    # ── 破板期间缩量调整为宜 ──
    # 检查破板期间阴线量能是否总体递减(如果放量可能是出货)
    green_days = []
    for j in range(zt_idx + 1, c):
        if klines[j].close < klines[j].open:
            green_days.append((j, klines[j].volume))
    if len(green_days) >= 3:
        if green_days[-1][1] > green_days[0][1] * 1.1:
            return (False, "破板期绿色量放大(疑似出货)")

    return (True, f"3破{break_day}入{days_since_zt}")


# ==================== 缠论技术分析（基于108课原文）====================

def is_bottom_divergence(klines: List[KLine], macd_hist: List[float], lookback=30) -> bool:
    """
    缠论底背驰检测（第24/25课  MACD对背驰的辅助判断）

    核心逻辑：
    1. 价格创近期新低（下跌趋势延续）
    2. MACD绿柱子面积/高度不创新低（力度衰竭）
    3. 缠师：没有趋势没有背驰，至少两段下跌比较

    返回: True = 底背驰成立
    """
    if len(klines) < lookback + 5:
        return False

    half = lookback // 2
    recent = klines[-half:]
    prev = klines[-lookback:-half]

    recent_low = min(k.low for k in recent)
    prev_low = min(k.low for k in prev)

    # 价格创新低 = 下跌趋势延续
    if recent_low >= prev_low * 0.995:
        return False

    recent_macd = min(macd_hist[-half:])
    prev_macd = min(macd_hist[-lookback:-half])

    # MACD绿柱子缩短 = 下跌力度衰竭
    return recent_macd > prev_macd


def is_top_divergence(klines: List[KLine], macd_hist: List[float], lookback=30) -> bool:
    """
    缠论顶背驰检测（第24课）
    价格创新高 + MACD红柱子不创新高 = 顶背驰（卖出信号）
    """
    if len(klines) < lookback + 5:
        return False

    half = lookback // 2
    recent = klines[-half:]
    prev = klines[-lookback:-half]

    recent_high = max(k.high for k in recent)
    prev_high = max(k.high for k in prev)

    if recent_high <= prev_high * 1.005:
        return False

    recent_macd = max(macd_hist[-half:])
    prev_macd = max(macd_hist[-lookback:-half])

    return recent_macd < prev_macd


def is_first_buy_point(klines: List[KLine], dif: List[float], dea: List[float],
                        macd_hist: List[float]) -> bool:
    """
    缠论第一类买点（第21课 买卖点分析的完备性）

    特征：
    1. 处于下跌趋势末端（MA5 < MA20 < MA60）
    2. 出现底背驰（价格新低 + MACD柱缩短）
    3. DIF在0轴下方（MACD定律：一买都在0轴下背驰形成）

    缠师原文：「第一类买点都是在0轴之下背驰形成的」
    """
    if len(klines) < 40 or len(macd_hist) < 40:
        return False

    ma5 = calc_ma(klines, 5)[-1]
    ma20 = calc_ma(klines, 20)[-1]

    # 已经在上涨趋势了，不是一买
    if ma5 > ma20:
        return False

    # 必须出现底背驰
    if not is_bottom_divergence(klines, macd_hist):
        return False

    # MACD定律：一买在0轴之下
    if dif[-1] > 0:
        return False

    return True


def is_second_buy_point(klines: List[KLine], dif: List[float], dea: List[float],
                         macd_hist: List[float]) -> bool:
    """
    缠论第二类买点（第14课 喝茅台的高潮程序 + 第21课）

    缠中说禅买点定律：
    「大级别的第二类买点由次一级别相应走势的第一类买点构成」

    MACD定律（第15课课后回复）：
    「第二类买点都是第一次上0轴后回抽确认形成的」

    特征：
    1. 之前有过底背驰（一买已出现）
    2. 回调不创新低
    3. DIF回抽0轴附近后再次金叉
    """
    if len(klines) < 45:
        return False

    # ---- 检查过去30天是否有一买特征（底部背驰） ----
    past = klines[-40:-10]
    past_hist = macd_hist[-40:-10]
    earlier = klines[-55:-40]
    earlier_hist = macd_hist[-55:-40]

    past_low = min(k.low for k in past)
    earlier_low = min(k.low for k in earlier)

    had_one_buy = False
    if past_low < earlier_low * 0.995:
        if min(past_hist) > min(earlier_hist):
            had_one_buy = True

    # ---- 当前状态确认 ----
    ma5 = calc_ma(klines, 5)[-1]
    ma10 = calc_ma(klines, 10)[-1]
    ma5_3ago = calc_ma(klines, 5)[-4] if len(klines) >= 9 else ma5

    # MA5走平或向上（不再下跌）
    if ma5 <= ma5_3ago:
        return False

    # DIF在0轴附近（刚上0轴或即将上0轴）
    if dif[-1] < -1.5:  # DIF还在深水区，太弱
        return False

    # DIF > DEA（处于金叉状态）
    if dif[-1] <= dea[-1]:
        return False

    # 二买不一定非要有一买（简化版：底部抬高+回抽金叉也算）
    recent_low = min(k.low for k in klines[-10:])
    prev_low = min(k.low for k in klines[-20:-10])

    if recent_low < prev_low * 0.98:  # 还在创新低
        return False

    return True


def identify_中枢(klines: List[KLine], lookback=40) -> Tuple[float, float]:
    """
    缠论走势中枢识别（第18课 不被面首的雏男是不完美的）

    定义：「某级别走势类型中，被至少三个连续次级别走势类型所重叠的部分」

    简化实现：
    1. 把最近走势分成三个区间
    2. 取三个区间的重叠部分

    返回: (中枢下沿, 中枢上沿)  —— 如果没中枢返回 (0,0)
    """
    if len(klines) < lookback:
        return (0.0, 0.0)

    seg_size = lookback // 3
    seg1 = klines[-lookback:-lookback+seg_size]
    seg2 = klines[-lookback+seg_size:-lookback+seg_size*2]
    seg3 = klines[-lookback+seg_size*2:]

    if not (seg1 and seg2 and seg3):
        return (0.0, 0.0)

    # 三个区间各自的高低点
    s1_low = min(k.low for k in seg1)
    s1_high = max(k.high for k in seg1)
    s2_low = min(k.low for k in seg2)
    s2_high = max(k.high for k in seg2)
    s3_low = min(k.low for k in seg3)
    s3_high = max(k.high for k in seg3)

    # 三区间重叠部分 = 中枢
    center_bottom = max(s1_low, s2_low, s3_low)
    center_top = min(s1_high, s2_high, s3_high)

    if center_top <= center_bottom:
        return (0.0, 0.0)

    return (center_bottom, center_top)


def get_中枢_position(klines: List[KLine], lookback=40) -> str:
    """
    判断股价在中枢的什么位置

    返回: "上方" / "内部" / "下方" / "未知"

    缠论第20课：第三类买点 = 离开中枢后回抽不返回
    - "上方" = 强势（可能是三买区域）
    - "内部" = 盘整（高抛低吸）
    - "下方" = 弱势（等一买/二买）
    """
    bottom, top = identify_中枢(klines, lookback)
    if bottom == 0:
        return "未知"

    current = klines[-1].close

    if current > top:
        return "上方"
    elif current < bottom:
        return "下方"
    else:
        return "内部"


def is_third_buy_point(klines: List[KLine], macd_hist: List[float],
                        dif: List[float], dea: List[float]) -> bool:
    """
    缠论第三类买点（第20课 走势中枢级别扩张及第三类买卖点）

    定义：「某级别中枢的破坏，当且仅当一个次级别走势离开该中枢后，
           其后的次级别回抽走势不重新回到该中枢内」

    特征：
    1. 有明确的中枢
    2. 股价离开中枢向上突破
    3. 回调不跌回中枢
    4. MACD多头（DIF > DEA）
    """
    bottom, top = identify_中枢(klines)
    if bottom == 0:
        return False

    # 最近5天最低价不能跌破中枢上沿
    recent_min5 = min(k.low for k in klines[-5:])
    if recent_min5 <= top:
        return False

    # 当前MACD多头
    if dif[-1] <= dea[-1]:
        return False

    # 回调后的反弹阶段（近3天有上涨）
    recent_3d_chg = sum(k.pct_chg for k in klines[-3:])
    if recent_3d_chg <= 0:
        return False

    return True


def is_macd_divergence_buy(klines: List[KLine], dif: List[float], dea: List[float],
                            macd_hist: List[float]) -> bool:
    """
    缠论综合买点判断（融合一买/二买/三买）

    返回: True = 当前处于缠论买点区域
    """
    if is_first_buy_point(klines, dif, dea, macd_hist):
        return True
    if is_second_buy_point(klines, dif, dea, macd_hist):
        return True
    if is_third_buy_point(klines, macd_hist, dif, dea):
        return True
    return False


# ==================== 区间套（缠论第61课）====================

def parse_minline_file(filepath: str, max_records: int = 800) -> List[KLine]:
    """
    解析通达信分钟K线文件（5/15/30/60分钟）
    格式与日K线相同：32字节/条
    """
    if not os.path.exists(filepath):
        return []
    size = os.path.getsize(filepath)
    count = size // 32
    if count == 0:
        return []
    skip = max(0, count - max_records)
    klines = []
    with open(filepath, 'rb') as f:
        if skip > 0:
            f.seek(skip * 32)
        for _ in range(count - skip):
            rec = f.read(32)
            if len(rec) != 32:
                break
            date_int, open_, high, low, close, amount, volume, _ = \
                struct.unpack('iiiiifii', rec)
            date_str = str(date_int)
            # 分钟线的date可能是YYYYMMDDHHMM格式，取前8位做日期
            if len(date_str) >= 8:
                date_str = date_str[:8]
            try:
                dt = datetime.strptime(date_str, '%Y%m%d').date()
            except:
                continue
            kl = KLine(dt, open_/100, high/100, low/100, close/100, amount, volume/100)
            klines.append(kl)
    # 补涨跌幅
    for i in range(1, len(klines)):
        prev = klines[i-1].close
        if prev > 0:
            klines[i].pct_chg = (klines[i].close - prev) / prev * 100
    return klines


def multi_timeframe_confirm(code: str, market: str,
                             daily_dif: List[float], daily_dea: List[float],
                             daily_hist: List[float]) -> Tuple[bool, str]:
    """
    缠论区间套多周期确认（第61课 区间套定位标准图解分析示范六）

    原理：「大级别定方向，小级别找精确买点」
    - 日线出现买点信号
    - 30分钟线出现一买或背驰 → 精准确认

    返回: (是否确认, 确认描述)
    """
    # 尝试读取30分钟K线
    minline_path = os.path.join(
        TDX_ROOT, market, "minline", f"{market}30#{code}.day"
    )
    m30 = parse_minline_file(minline_path, 400)
    if len(m30) < 60:
        return (False, "无30分钟数据")

    # 在30分钟上找一买/背驰
    m30_dif, m30_dea, m30_hist = calc_macd(m30)
    m30_div = is_bottom_divergence(m30, m30_hist, lookback=40)
    m30_buy1 = is_first_buy_point(m30, m30_dif, m30_dea, m30_hist)
    m30_buy2 = is_second_buy_point(m30, m30_dif, m30_dea, m30_hist)

    if m30_buy1 or (m30_div and m30_dif[-1] > m30_dea[-1]):
        return (True, "30分一买确认")
    elif m30_buy2:
        return (True, "30分二买确认")
    elif m30_dif[-1] > m30_dea[-1] and m30_hist[-1] > m30_hist[-2]:
        return (True, "30分MACD多头")
    else:
        return (False, "30分无共振")


# ==================== 仓位管理（OpenClaw风控模型）====================

def calculate_position(total_capital: float, entry_price: float,
                       stop_loss_price: float, risk_profile: str = "moderate",
                       confidence: float = 1.0) -> Dict[str, str]:
    """
    OpenClaw仓位计算器（InnoNestX/trading-assistant 策略移植）

    风险偏好:
      conservative: 单笔亏损<总资金1%（新手/震荡市）
      moderate:     单笔亏损<总资金2%（默认）
      aggressive:   单笔亏损<总资金5%（高手/牛市）

    信心度调整（缠论信号越强权重越高）:
      confidence=1.0 → 标准仓位
      confidence=0.5 → 半仓（信号一般）
      confidence=1.5 → 加仓（多周期共振）
    """
    risk_ratios = {"conservative": 0.01, "moderate": 0.02, "aggressive": 0.05}
    risk_per_trade = total_capital * risk_ratios.get(risk_profile, 0.02)
    risk_per_share = abs(entry_price - stop_loss_price)

    if risk_per_share <= 0 or entry_price <= 0:
        return {"建议": "参数无效", "说明": "请检查价格参数"}

    position_value = risk_per_trade / risk_per_share * entry_price
    # 缠论风控：单票上限30%
    position_value = min(position_value, total_capital * 0.30)
    # 信心度调整
    position_value *= min(confidence, 2.0)

    shares = max(int(position_value / entry_price / 100) * 100, 100)
    actual_value = shares * entry_price
    risk_amount = abs(shares * (entry_price - stop_loss_price))
    risk_ratio = risk_amount / total_capital * 100
    target_price = entry_price + risk_per_share * 2

    return {
        "建议仓位": f"{shares}股",
        "仓位金额": f"¥{actual_value:,.0f}",
        "仓位比例": f"{actual_value/total_capital*100:.1f}%",
        "最大亏损": f"¥{risk_amount:,.0f} ({risk_ratio:.1f}%)",
        "止损价": f"¥{stop_loss_price:.2f}",
        "目标价": f"¥{target_price:.2f}",
        "盈亏比": "1:2",
    }


# ==================== 本地扫盘引擎 ====================

def scan_stock(code: str, full_code: str, klines: List[KLine]) -> Optional[Dict]:
    """扫描单只股票，返回匹配策略的信号（收紧条件版）"""
    if len(klines) < 60:
        return None

    c = klines[-1]
    n = get_stock_name(code)
    if not n:
        return None

    # ----- 基础过滤（硬性门槛）-----
    chg = c.pct_chg

    # 排除ST
    if n.startswith(("*ST", "ST")):
        return None

    # 排除创业板(300/301开头)、科创板(688/689开头)和北交所(9开头)
    if code.startswith(("300", "301")):
        return None
    if code.startswith(("688", "689")):
        return None
    if code.startswith("9"):
        return None

    # 股价>=5元（排除垃圾低价股）
    if c.close < 5.0:
        return None

    # 今日必须上涨
    if chg <= 0:
        return None

    # 排除今日涨停/一字板（买不进去的不推荐）
    if chg >= 9.95:
        return None

    # ----- 计算指标 -----
    ma5 = calc_ma(klines, 5)[-1]
    ma10 = calc_ma(klines, 10)[-1]
    ma20 = calc_ma(klines, 20)[-1]
    ma60 = calc_ma(klines, 60)[-1]
    vr = calc_vr(klines, 5)[-1]
    dif, dea, macd_hist = calc_macd(klines)
    rsi6 = calc_rsi(klines, 6)[-1]

    # ---- 课程笔记: 突破20日平台判断 ----
    platform_breakout = is_platform_breakout(klines)

    # 前5日累计涨幅（不含今日，判断短期是否过热）
    prev_5d_chg = sum(k.pct_chg for k in klines[-6:-1])

    # 复盘结论: 前5日涨幅>15%的短期获利盘太重,次交易日容易回调
    if prev_5d_chg > 15:
        return None

    # 选股日单日涨幅>6%且前5日>10%, 这是高潮见顶信号
    if chg > 6 and prev_5d_chg > 10:
        return None

    # 新增: 前5日>8% + RSI>75 = 短期已热, 追高容易接盘
    if prev_5d_chg > 8 and rsi6 > 75:
        return None

    # 新增: 前5日>5% + 今日>5% + RSI>80 = 加速赶顶
    if prev_5d_chg > 5 and chg > 5 and rsi6 > 80:
        return None

    # 均线排列（不同粒度）
    ma_bullish_strict = is_ma_bullish(klines, (5, 10, 20, 60))  # 严格多头
    ma_bullish_light = ma5 > ma10 > ma20  # 短期多头
    macd_bull = is_macd_bullish(klines)  # DIF>DEA>0
    macd_positive = dif[-1] > dea[-1]  # DIF>DEA(不要求>0)
    macd_cross = is_macd_golden_cross(klines)
    has_limit = has_recent_limit_up(klines, 10)

    # ---- 改进1: 均线角度 ≥30° ----
    # 双线系统的核心: MA5角度>=30°表示趋势强度足够
    closes = [k.close for k in klines]
    ma5_3ago = calc_ma(klines, 5)[-4] if len(klines) >= 9 else 0  # 3天前的MA5
    if ma5_3ago > 0 and ma5 > ma5_3ago:
        ma5_angle = math.atan((ma5 - ma5_3ago) / ma5_3ago * 100) * 180 / 3.14159
    else:
        ma5_angle = 0
    angle_enough = ma5_angle >= 30

    # ---- 改进2: MACD柱升高确认 ----
    # 不只是DIF>DEA, 还要柱子变长(动量增强)
    macd_rising = len(macd_hist) >= 2 and macd_hist[-1] > macd_hist[-2]

    # ========== 新增：缠论技术信号 ==========
    # 背驰检测（第24课MACD辅助判断法）
    bottom_div = is_bottom_divergence(klines, macd_hist)
    top_div = is_top_divergence(klines, macd_hist)

    # 缠论三类买卖点（第14/20/21课）
    buy1 = is_first_buy_point(klines, dif, dea, macd_hist)
    buy2 = is_second_buy_point(klines, dif, dea, macd_hist)
    buy3 = is_third_buy_point(klines, macd_hist, dif, dea)

    # 中枢位置判断（第18课）
    中枢_pos = get_中枢_position(klines)

    # 新增: 中枢下方的不追涨（弱势反弹容易回落）
    if 中枢_pos == "下方" and chg > 3:
        if not (buy1 or buy2):  # 除非是一买/二买抄底
            return None

    # 综合买点判断
    chan_buy = buy1 or buy2 or buy3

    # 区间套多周期确认（第61课）
    # 尝试读取30分钟数据做精确定位
    mkt = "sh" if code.startswith(("6", "9", "5")) else "sz" if code.startswith(("0", "3", "2")) else "bj"
    interval_confirmed, interval_desc = multi_timeframe_confirm(code, mkt, dif, dea, macd_hist)
    # ========== 缠论信号结束 ==========

    # ---- 策略优先级(1=最高) ----
    # 记录每个策略是否触发
    hit = {"放量首板": False, "连板接力": False, "趋势加速": False, "N字反包": False, "多维精选": False, "缠论精选": False, "低吸买点": False, "九爆发": False, "三破七入": False}

    # === 策略0: 低吸买点（新增——最高优先级）===
    # 放过第一波拉升，等缩量回调企稳再介入
    # 配合缠论二买/三买 = 最安全的低吸位置
    pullback_entry = is_pullback_entry(klines)
    pullback_desc = describe_pullback(klines) if pullback_entry else ""

    if pullback_entry and chg <= 3.0:
        # 今日涨幅不能大（3%以内才算低吸）
        hit["低吸买点"] = True

    # === 策略0b: 三破七入九爆发（二次爆发选股）===
    second_bo, second_bo_desc = is_second_breakout(klines)
    if second_bo:
        hit["九爆发"] = True

    # === 策略0c: 三破七入上车（调整期低吸买入）===
    entry_3p7r, entry_3p7r_desc = is_entry_3po7ru(klines)
    if entry_3p7r and chg <= 3.0:
        hit["三破七入"] = True

    # === 策略1: 低位放量首板(优先级4) ===
    # 课程笔记: 首板突破20日平台 = 涨停突破确认
    if (3.0 <= chg <= 8.0
            and vr >= 1.8
            and ma_bullish_light
            and rsi6 < 80
            and macd_positive
            and macd_rising
            and angle_enough
            and platform_breakout):  # 课程: 突破20日平台确认
        hit["放量首板"] = True

    # === 策略2: 连板接力弱转强(优先级1) ===
    # 10日内涨停 + 今日温和放量 + 均线多头 + MACD多头 + MACD柱升高
    if (has_limit
            and 1.0 <= chg <= 6.0
            and vr >= 1.5
            and ma_bullish_strict
            and macd_bull
            and macd_rising):
        hit["连板接力"] = True

    # === 策略3: 趋势加速(优先级2) ===
    if (ma_bullish_light
            and vr >= 2.0
            and chg >= 2.0
            and macd_positive
            and macd_rising
            and rsi6 < 80
            and c.close > ma20
            and angle_enough):
        hit["趋势加速"] = True

    # === 策略4: N字反包(优先级5) ===
    if (is_n_shape(klines)
            and vr >= 1.5
            and macd_positive
            and c.close > ma10):
        hit["N字反包"] = True

    # === 策略5: 多维精选(优先级4) ===
    if (macd_bull
            and ma_bullish_light
            and vr >= 1.5
            and chg >= 1.0
            and 30 <= rsi6 <= 80
            and c.close > ma20
            and angle_enough):
        hit["多维精选"] = True

    # === 策略6: 缠论精选(优先级1) ===
    # 基于缠中说禅108课核心理论：背驰+买卖点+中枢
    # 二买>三买>一买的优先级（二买确定性最高）
    chan_signals = []
    if buy2:
        chan_signals.append("二买")
    if buy3:
        chan_signals.append("三买")
    if buy1:
        chan_signals.append("一买")
    if bottom_div and not (buy1 or buy2):
        chan_signals.append("底背驰")

    if chan_signals:
        hit["缠论精选"] = True

    # ---- 改进3: 买点优先级排序 ----
    # 按优先级从高到低排列
    priority_list = [
        (1, "低吸买点"),     # 缩量回调企稳低吸（确定性最高，不追高）
        (2, "三破七入"),     # 三破七入上车（调整期低吸买入）
        (3, "九爆发"),       # 三破七入九爆发（首板→破位→再次爆发）
        (4, "缠论精选"),     # 缠论买卖点（二买/三买确定性高）
        (5, "连板接力"),     # 连板弱转强
        (6, "趋势加速"),     # 主升浪加速
        (7, "多维精选"),     # 基本面+技术面共振
        (8, "放量首板"),     # 首板突破
        (9, "N字反包"),     # N字型回调
    ]

    signals = []
    match_strategies = []
    for pri, name in priority_list:
        if hit[name]:
            signals.append(name)
            match_strategies.append({
                "低吸买点": "低吸买点",
                "三破七入": "三破七入",
                "九爆发": "九爆发",
                "缠论精选": "缠论精选",
                "放量首板": "低位放量首板",
                "连板接力": "连板接力弱转强",
                "趋势加速": "趋势加速",
                "N字反包": "N字反包",
                "多维精选": "多维精选",
            }[name])

    if not signals:
        return None

    # ---- 信号去重: 统计独立信号组 ----
    # 取代"策略命中数"(策略间条件高度重叠), 改用互斥的信号类别
    signal_groups = {
        "低吸形态": int(pullback_entry),
        "均线多头排列": int(ma_bullish_light),
        "放量": int(vr >= 1.5),
        "MACD多头": int(macd_positive),
        "MACD柱升高": int(macd_rising),
        "MA角度够": int(angle_enough),
        "缠论买点": int(chan_buy),
        "涨停基因": int(has_limit),
        "量价形态": int(platform_breakout or is_n_shape(klines)),
        "九爆发形态": int(second_bo),
        "三破七入形态": int(entry_3p7r),
    }
    unique_signal_count = sum(signal_groups.values())

    # 缠论买点描述
    chan_buy_desc = " + ".join(chan_signals) if chan_signals else ""
    # 背驰描述
    div_desc = "底背驰" if bottom_div else ("顶背驰" if top_div else "")
    # ========== 新增高级信号（2026/06/11）==========
    # 缠论底分型
    bf_valid, bf_desc = detect_bottom_fractal(klines, lookback=15)

    # 平步青云评分
    pbq = pingbu_qingyun_score(klines, vr)
    pbq_score = pbq["score"]
    pbq_summary = pbq["summary"]
    pbq_is_strong = pbq["is_strong"]

    # 洗盘结束识别
    washout_ok, washout_desc = is_washout_complete(klines)
    daytrade_ok, daytrade_desc = is_day_trade_entry(klines)

    # 倍量阳线横盘突破
    surge_ok, surge_desc = is_volume_surge_breakout(klines)

    # ========== 新增：股海炼金术第三课信号 ==========
    # 建仓型涨停板
    pos_building, pos_desc = is_position_building_limit_up(klines)
    # 洗盘型涨停板
    wo_limit_up, wo_limit_desc = is_washout_limit_up(klines)
    # 二进三战法
    erjin_san, erjin_desc = is_erjin_san_pattern(klines)
    # 涨停板类型综合分析
    ltu = limit_up_type_analysis(klines)

    # ========== 新增：主升浪起爆信号（试盘线+突破确认）==========
    # 独立试盘线检测
    tl_ok, tl_info = detect_test_line(klines, lookback=30)
    # 主升浪起爆确认（震荡建仓→试盘→缩量整理→放量突破）
    mw_ignition, mw_desc = is_main_wave_ignition(klines)
    # 底部震荡建仓结构检测
    base_ok, base_desc = detect_base_consolidation(klines, lookback=45)

    # ========== 筹码分布信号 ==========
    chip_metrics = calc_chip_metrics(klines, lookback=250)
    chip_screen = chip_screen_conditions(klines)
    chip_interpret = interpret_chip(chip_metrics)
    turnover_data = analyze_turnover_rate(klines)

    # ========== 龙头模式信号（飞龙在天+潜龙回首）==========
    fl_ok, fl_info = is_feilongzaitian(klines)
    ql_ok, ql_desc = is_qianlonghuishou(klines)
    dragon_ok, dragon_type, dragon_desc = is_dragon_pattern(klines)

    # ========== 七角色圆桌会议（多维度综合评分）==========
    try:
        seven = seven_roles_analysis(klines, chip_metrics, {})
    except:
        seven = {"roles": {}, "total_score": 0, "max_score": 0, "overall_pct": 0, "rating": ""}

    # 仓位建议（用10万本金示范）
    pos_advice = ""
    if chan_buy_desc or pbq_is_strong or mw_ignition:
        stop_loss = round(c.close * 0.95, 2)  # 5%止损
        pos_info = calculate_position(100000, c.close, stop_loss, "moderate", 1.2)
        pos_advice = pos_info.get("建议仓位", "")

    return {
        "代码": code,
        "名称": n,
        "最新价": round(c.close, 2),
        "涨跌幅": round(chg, 2),
        "量比": round(vr, 2),
        "MA5": round(ma5, 2),
        "MA20": round(ma20, 2),
        "MACD": f"{dif[-1]:.2f}/{dea[-1]:.2f}",
        "RSI6": round(rsi6, 1),
        "MA角度": f"{ma5_angle:.0f}°",
        "信号": " + ".join(signals),
        "策略命中": len(match_strategies),
        "策略列表": match_strategies,
        "独立信号组": unique_signal_count,
        "低吸买点": pullback_desc,
        "九爆发": second_bo_desc if second_bo else "",
        "三破七入": entry_3p7r_desc if entry_3p7r else "",
        # 缠论信号
        "缠论买点": chan_buy_desc,
        "背驰": div_desc,
        "中枢位置": 中枢_pos,
        "区间套": interval_desc if interval_confirmed else "",
        "区间套确认": "是" if interval_confirmed else "否",
        # 新增高级信号
        "底分型": bf_desc if bf_valid else "",
        "平步青云": f"{pbq_score}分" if pbq_score >= 30 else "",
        "平步青云详情": pbq_summary,
        "平步青云强": "是" if pbq_is_strong else "否",
        "洗盘结束": washout_desc if washout_ok else "",
        "回踩买点": daytrade_desc if daytrade_ok else "",
        "倍量突破": surge_desc if surge_ok else "",
        # 股海炼金术第三课信号
        "建仓型涨停": pos_desc if pos_building else "",
        "洗盘型涨停": wo_limit_desc if wo_limit_up else "",
        "二进三信号": erjin_desc if erjin_san else "",
        "涨停类型": ltu.get("type_desc", ""),
        "涨停板数": ltu.get("zt_count", 0),
        "仓位建议": pos_advice,
        # 主升浪起爆信号
        "试盘线": tl_info.get("latest_desc", "") if tl_ok else "",
        "试盘线次数": tl_info.get("count", 0) if tl_ok else 0,
        "三倍量试盘": "是" if (tl_ok and tl_info.get("has_triple_vol", False)) else "",
        "主升浪起爆": mw_desc if mw_ignition else "",
        "震荡建仓": base_desc if base_ok else "",
        # 筹码分布信号
        "获利盘": f"{chip_metrics['profit_chip']:.0f}%" if chip_metrics.get('profit_chip', 0) > 0 else "",
        "浮动筹码": f"{chip_metrics['float_chip']:.0f}%" if chip_metrics.get('float_chip', 0) > 0 else "",
        "套牢盘": f"{chip_metrics['locked_chip']:.0f}%" if chip_metrics.get('locked_chip', 0) > 0 else "",
        "筹码集中": chip_metrics.get("concentration_desc", ""),
        "筹码评分": chip_screen.get("score", 0),
        "筹码信号": "|".join(chip_screen.get("signals", [])[:3]) if chip_screen.get("signals") else "",
        # 龙头模式信号
        "飞龙在天": fl_info.get("描述", "") if fl_ok else "",
        "飞龙连板数": fl_info.get("连板数", 0) if fl_ok else 0,
        "飞龙介入价": fl_info.get("介入价", 0) if fl_ok else 0,
        "飞龙止损价": fl_info.get("止损价", 0) if fl_ok else 0,
        "潜龙回首": ql_desc if ql_ok else "",
        "龙头模式": f"{dragon_type}:{dragon_desc}" if dragon_ok else "",
        # 七角色圆桌会议评分
        "圆桌评分": seven.get("overall_pct", 0),
        "圆桌评级": seven.get("rating", ""),
        "圆桌趋势": f"{seven.get('roles',{}).get('趋势跟踪者',{}).get('score',0)}/{seven.get('roles',{}).get('趋势跟踪者',{}).get('max',0)}",
        "圆桌动量": f"{seven.get('roles',{}).get('动量交易者',{}).get('score',0)}/{seven.get('roles',{}).get('动量交易者',{}).get('max',0)}",
        "圆桌价值": f"{seven.get('roles',{}).get('价值投资者',{}).get('score',0)}/{seven.get('roles',{}).get('价值投资者',{}).get('max',0)}",
        "圆桌逆向": f"{seven.get('roles',{}).get('逆向投资者',{}).get('score',0)}/{seven.get('roles',{}).get('逆向投资者',{}).get('max',0)}",
        "圆桌质量": f"{seven.get('roles',{}).get('基本面分析师',{}).get('score',0)}/{seven.get('roles',{}).get('基本面分析师',{}).get('max',0)}",
        "圆桌风险": f"{seven.get('roles',{}).get('风险管理师',{}).get('score',0)}/{seven.get('roles',{}).get('风险管理师',{}).get('max',0)}",
        "圆桌事件": f"{seven.get('roles',{}).get('事件驱动交易者',{}).get('score',0)}/{seven.get('roles',{}).get('事件驱动交易者',{}).get('max',0)}",
        # 筹码解读 + 换手率
        "获利比例解读": chip_interpret.get("profit_ratio_desc", "") if chip_metrics.get("profit_chip", 0) > 0 else "",
        "筹码颜色": chip_interpret.get("chip_color_desc", "") if chip_metrics.get("profit_chip", 0) > 0 else "",
        "筹码柱形态": chip_interpret.get("chip_pillar_desc", "") if chip_metrics.get("profit_chip", 0) > 0 else "",
        "平均成本线": chip_interpret.get("avg_cost_line_desc", "") if chip_metrics.get("profit_chip", 0) > 0 else "",
        "换手率状态": turnover_data.get("volume_status", "") if turnover_data else "",
        "换手率解读": turnover_data.get("tr_desc", "") if turnover_data else "",
        "换手提示": turnover_data.get("action_hint", "") if turnover_data else "",
    }


def run_local_screen() -> List[Dict]:
    """全市场扫描"""
    results = []
    name_map = load_code_name_map()
    total = 0
    scanned = 0

    for market in ['sh', 'sz', 'bj']:
        lday = os.path.join(TDX_ROOT, market, "lday")
        if not os.path.exists(lday):
            continue
        for fname in sorted(os.listdir(lday)):
            if not fname.endswith('.day'):
                continue
            full_code = fname.replace('.day', '')
            code = full_code[2:]  # 去掉 sh/sz/bj

            total += 1
            if code not in name_map:
                continue  # 跳过无名称的（如ETF、债券）

            scanned += 1
            if scanned % 500 == 0:
                print(f"  扫描中: {scanned} 只...", end='\r', flush=True)

            # 读最近250天数据
            fp = os.path.join(lday, fname)
            klines = parse_day_file(fp, 250)
            if len(klines) < 60:
                continue

            r = scan_stock(code, full_code, klines)
            if r:
                results.append(r)

    print(f"  \n扫描完成: {total} 个文件, {scanned} 只有名称的股票")
    return results


def get_daily_report(results: List[Dict], index_info: Dict = None) -> str:
    """生成文本报告（含缠论信号与仓位建议 + 市场状态识别）"""
    lines = []
    lines.append("=" * 70)
    lines.append("  通达信本地数据 - 短线选股报告")
    lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"  数据来源: 本地日K线(Tdx)")
    lines.append("=" * 70)
    lines.append("")

    # ===== 市场状态识别（Hermes Skill Router 架构）=====
    if index_info:
        regime = index_info.get("regime", "")
        suggestion = index_info.get("suggestion", "")
        score = index_info.get("score", 0)
        trend = index_info.get("trend", "")
        strength = index_info.get("strength", "")
        recent_5d = index_info.get("recent_5d", 0)
        vol_ratio = index_info.get("vol_ratio", 0)

        if regime == "趋势市":
            regime_tag = "[上升趋势]"
        elif regime == "震荡市":
            regime_tag = "[横盘震荡]"
        elif regime == "弱势市":
            regime_tag = "[下跌趋势]"
        elif regime == "急跌市":
            regime_tag = "[恐慌急跌]"
        else:
            regime_tag = f"[{regime}]"

        lines.append(f"  {regime_tag} 评分:{score}  趋势:{trend}/{strength}  5日:{recent_5d:+.2f}%  量比:{vol_ratio}")
        lines.append(f"  建议:{suggestion}")
        lines.append("")
        lines.append("-" * 70)
        lines.append("")

    # 按综合评分/独立信号组排序
    sorted_results = sorted(results, key=lambda x: -(x.get("综合评分", 0) or x.get("策略命中", 0) * 10))

    # ---- 生成每只股票的简短策略标记 ----
    def tag(r: Dict) -> str:
        """返回策略标记, 如 [低吸+缠二买] [首板] [连板] [加速] [N字+缠三买]"""
        tags = []
        lc = r.get("低吸买点", "")
        if lc:
            tags.append("低吸")
        chan = r.get("缠论买点", "")
        if chan:
            # 缩写成 缠二买 / 缠三买 / 缠一买
            short = chan.replace(" + ", "+").replace("二买", "2买").replace("三买", "3买").replace("一买", "1买")
            tags.append(f"缠{short}")
        # 九爆发标记
        sbo = r.get("九爆发", "")
        if sbo == "三破":
            tags.append("三破")
        elif sbo == "七入":
            tags.append("七入")
        elif sbo == "九爆发":
            tags.append("九爆发")
        # 三破七入上车标记
        e7 = r.get("三破七入", "")
        if e7 and not sbo:
            tags.append("3破7入")
        sl = r.get("策略列表", [])
        if "低位放量首板" in sl and "低吸买点" not in sl:
            tags.append("首板")
        if "连板接力弱转强" in sl:
            tags.append("连板")
        if "趋势加速" in sl and "低吸买点" not in sl:
            tags.append("加速")
        if "N字反包" in sl and "低吸买点" not in sl:
            tags.append("N字")
        if "多维精选" in sl and "低吸买点" not in sl and "缠论精选" not in sl:
            tags.append("多维")
        # 新增高级信号标记
        if r.get("平步青云强") == "是":
            tags.append("青云")
        elif r.get("平步青云", "") and int(r.get("平步青云", "0").replace("分","")) >= 50:
            tags.append("青云")
        if r.get("底分型", ""):
            tags.append("底分")
        if r.get("洗盘结束", ""):
            tags.append("洗毕")
        if r.get("倍量突破", ""):
            tags.append("倍量")
        if r.get("回踩买点", ""):
            tags.append("回踩")
        # 股海炼金术第三课信号
        if r.get("建仓型涨停", ""):
            tags.append("建仓")
        if r.get("洗盘型涨停", ""):
            tags.append("洗盘板")
        if r.get("二进三信号", ""):
            tags.append("二进三")
        if r.get("涨停板数", 0) >= 2:
            tags.append(f"{r.get('涨停板数')}板")
        # 主升浪起爆信号
        if r.get("主升浪起爆", ""):
            tags.append("起爆")
        if r.get("三倍量试盘", ""):
            tags.append("三倍试盘")
        elif r.get("试盘线", ""):
            tags.append("试盘")
        if r.get("震荡建仓", ""):
            tags.append("震仓")
        # 龙头模式
        if r.get("飞龙在天", ""):
            tags.append("飞龙")
        if r.get("潜龙回首", ""):
            tags.append("潜龙")
        # 筹码信号
        chip_score = r.get("筹码评分", 0)
        if chip_score >= 70:
            tags.append("筹码优")
        elif chip_score >= 50:
            tags.append("筹码好")
        # 圆桌评分
        yz = r.get("圆桌评分", 0)
        if yz >= 75:
            tags.append("圆桌S")
        elif yz >= 60:
            tags.append("圆桌A")
        elif yz >= 45:
            tags.append("圆桌B")
        if r.get("筹码集中", "") == "高度集中(获利)":
            tags.append("获利集中")
        # 置信度等级标记
        conf_level = r.get("置信等级", "")
        if conf_level == "高置信":
            tags.insert(0, "★")
        elif conf_level == "关注":
            tags.insert(0, "☆")
        if not tags:
            tags.append("其他")
        return "[" + "+".join(tags[:5]) + "]"  # 最多5个标记

    # ===== 高置信推荐榜单 =====
    hc_stocks = [r for r in sorted_results if r.get("置信等级") == "高置信"]
    if hc_stocks:
        lines.append("【高置信推荐】置信度评分>=60 目标胜率>80% (信号跟踪系统自动筛选)")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'量比':<6} {'置信':<6} {'高置信信号':<20}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*6} {'-'*20}")
        for r in hc_stocks[:10]:
            conf = r.get("置信度", 0)
            hc_sig = r.get("高置信信号", "")
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {r['量比']:<6} {conf:<5}分 {hc_sig:<20}")
        lines.append("")

    # ===== 新：缠论精选专区 =====
    chan_stocks = [r for r in sorted_results if r.get("缠论买点", "")]
    if chan_stocks:
        lines.append("【缠论精选】缠论买卖点信号（优先关注）")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'买点':<14} {'中枢':<8} {'基本面'}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*14} {'-'*8} {'-'*20}")
        for r in chan_stocks[:12]:
            chan = r.get("缠论买点", "")
            zhong = r.get("中枢位置", "")
            fin = r.get("基本面", "")
            if not fin:
                fin = ""
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {chan:<14} {zhong:<8} {fin:<20}")
        lines.append("")

    # ===== 新增：平步青云专区 =====
    pq_stocks = [r for r in sorted_results if r.get("平步青云强") == "是"]
    if pq_stocks:
        lines.append("【平步青云★】7大特征评分>=65分 — 主升浪启动信号（陈老师第二节）")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'量比':<6} {'评分':<8} {'状态'}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*8} {'-'*30}")
        for r in pq_stocks[:8]:
            pbq = r.get("平步青云详情", "")
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {r['量比']:<6} {r.get('平步青云',''):<8} {pbq[:30]:<30}")
        lines.append("")

    # ===== 新增：股海炼金术第三课信号 =====
    gh_stocks = [r for r in sorted_results if r.get("建仓型涨停", "") or r.get("洗盘型涨停", "") or r.get("二进三信号", "")]
    if gh_stocks:
        lines.append("【股海炼金术】建仓型/洗盘型涨停 + 二进三战法（第三课）")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'板数':<4} {'类型':<20}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*4} {'-'*20}")
        for r in gh_stocks[:8]:
            zt_type = r.get("涨停类型", "")
            zt_count = r.get("涨停板数", 0)
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {zt_count:<4} {zt_type:<20}")
        lines.append("")

    # ===== 新增：主升浪起爆信号（试盘线+起爆确认）=====
    mw_stocks = [r for r in sorted_results if r.get("主升浪起爆", "")]
    if mw_stocks:
        lines.append("【主升浪起爆】试盘线确认→缩量整理→放量突破=起爆信号（股海炼金术）")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'量比':<6} {'起爆描述'}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*40}")
        for r in mw_stocks[:8]:
            desc = r.get("主升浪起爆", "")
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {r['量比']:<6} {desc:<40}")
        lines.append("")

    # ===== 新增：试盘线独立信号（起爆未确认但试盘已出现）=====
    tl_stocks = [r for r in sorted_results if r.get("试盘线", "") and not r.get("主升浪起爆", "")]
    if tl_stocks:
        lines.append("【试盘线信号】放量上影线测试抛压 — 潜在主升浪起爆前信号")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'量比':<6} {'试盘描述':<28} {'次数'}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*28} {'-'*4}")
        for r in tl_stocks[:8]:
            tl_desc = r.get("试盘线", "")
            tl_cnt = r.get("试盘线次数", 0)
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {r['量比']:<6} {tl_desc:<28} {tl_cnt}次")
        lines.append("")

    # ===== 龙头模式：飞龙在天 =====
    fl_stocks = [r for r in sorted_results if r.get("飞龙在天", "")]
    if fl_stocks:
        lines.append("【飞龙在天】三连板以上->断板洗盘->反包确认-龙头主升浪接力")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'连板':<4} {'介入价':<8} {'止损价':<8} {'描述'}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*4} {'-'*8} {'-'*8} {'-'*30}")
        for r in fl_stocks[:5]:
            zt = r.get("飞龙连板数", 0)
            entry = r.get("飞龙介入价", 0)
            stop = r.get("飞龙止损价", 0)
            desc = r.get("飞龙在天", "")
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {zt}连 {entry:<8.2f} {stop:<8.2f} {desc:<30}")
        lines.append("")

    # ===== 龙头模式：潜龙回首 =====
    ql_stocks = [r for r in sorted_results if r.get("潜龙回首", "")]
    if ql_stocks:
        lines.append("【潜龙回首】二板以上大涨20%+ -> 回调2-8天-> 企稳-龙回头机会")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'量比':<6} {'描述'}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*40}")
        for r in ql_stocks[:5]:
            desc = r.get("潜龙回首", "")
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {r['量比']:<6} {desc:<40}")
        lines.append("")

    # ===== 新增：洗盘结束+回踩买点 + 倍量突破 =====
    washout_stocks = [r for r in sorted_results if r.get("洗盘结束", "") or r.get("倍量突破", "")]
    if washout_stocks:
        lines.append("【量价异动】洗盘结束/倍量突破/回踩买点（操盘笔记信号）")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'量比':<6} {'信号'}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*30}")
        for r in washout_stocks[:8]:
            sig = r.get("洗盘结束", "") or r.get("倍量突破", "") or r.get("回踩买点", "")
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {r['量比']:<6} {sig[:30]:<30}")
        lines.append("")

    # ===== 筹码分布专区（获利盘/套牢盘/集中度）=====
    chip_stocks = [r for r in sorted_results if r.get("筹码评分", 0) >= 50]
    if chip_stocks:
        lines.append("【筹码分布】获利盘/浮动筹码/套牢盘 — 主力筹码状态评估")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'获利%':<7} {'浮动%':<7} {'套牢%':<7} {'集中度':<12} {'信号'}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*12} {'-'*30}")
        for r in chip_stocks[:10]:
            profit = r.get("获利盘", "")
            flt = r.get("浮动筹码", "")
            lock = r.get("套牢盘", "")
            conc = r.get("筹码集中", "")
            csig = r.get("筹码信号", "")
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {profit:<7} {flt:<7} {lock:<7} {conc:<12} {csig:<30}")
        # 筹码解读明细（仅展示第一名）
        if chip_stocks:
            r0 = chip_stocks[0]
            pc = r0.get("获利比例解读", "")
            cp = r0.get("筹码颜色", "")
            pl = r0.get("筹码柱形态", "")
            ac = r0.get("平均成本线", "")
            if any([pc, cp, pl, ac]):
                lines.append(f"    筹码解读:")
                if pc: lines.append(f"      • {pc}")
                if cp: lines.append(f"      • {cp}")
                if pl: lines.append(f"      • {pl}")
                if ac: lines.append(f"      • {ac}")
                tr_v = r0.get("换手率状态", "")
                tr_d = r0.get("换手率解读", "")
                tr_h = r0.get("换手提示", "")
                if tr_v:
                    lines.append(f"      • 换手率状态: {tr_v}")
                    if tr_d: lines.append(f"      • {tr_d}")
                    if tr_h: lines.append(f"      • {tr_h}")
                lines.append("")
        lines.append("")

    # ===== 七角色圆桌会议（综合评分排名）=====
    yz_stocks = [r for r in sorted_results if r.get("圆桌评分", 0) >= 50]
    if yz_stocks:
        yz_stocks.sort(key=lambda x: -x.get("圆桌评分", 0))
        lines.append("【七角色圆桌会议】7大维度综合评分 — 港大交易分析框架")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'总评':<5} {'📈趋势':<7} {'⚡动量':<7} {'💰价值':<7} {'📉逆向':<7} {'🔍质地':<7} {'🛡️风险':<7} {'🎯事件':<7}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*5} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")
        for r in yz_stocks[:10]:
            yz_score = r.get("圆桌评分", 0)
            yz_rank = r.get("圆桌评级", "")
            trend = r.get("圆桌趋势", "")
            momentum = r.get("圆桌动量", "")
            value = r.get("圆桌价值", "")
            reverse = r.get("圆桌逆向", "")
            quality = r.get("圆桌质量", "")
            risk = r.get("圆桌风险", "")
            event = r.get("圆桌事件", "")
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {yz_score:<5} {trend:<7} {momentum:<7} {value:<7} {reverse:<7} {quality:<7} {risk:<7} {event:<7}")
        lines.append("")

    # ===== 新增：低吸买点专区 =====
    lc_stocks = [r for r in sorted_results if r.get("低吸买点", "")]
    if lc_stocks:
        lines.append("【低吸买点】放过第一波，缩量回调企稳低吸（安全边际高）")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'量比':<6} {'低吸描述':<20} {'缠论':<12} {'基本面'}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*20} {'-'*12} {'-'*20}")
        for r in lc_stocks[:10]:
            lc_desc = r.get("低吸买点", "")
            chan = r.get("缠论买点", "")
            fin = r.get("基本面", "")
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {r['量比']:<6} {lc_desc:<20} {chan:<12} {fin:<20}")
        lines.append("")
        lines.append("  低吸策略: 前期放量拉升 → 缩量回调 → 今日企稳")
        lines.append("  买入: 开盘回踩可吸 | 止损: 跌破近期低点-2% | 目标: 前高附近")
        lines.append("")

    # 综合推荐（多策略共振）
    multi = [r for r in sorted_results if r["策略命中"] >= 2]
    if multi:
        lines.append("【综合推荐】多策略共振(>=2)")
        lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'量比':<6} {'共振':<4} {'独信':<4} {'策略'}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*4} {'-'*4} {'-'*30}")
        for r in multi[:15]:
            sl = r.get("策略列表", [])
            sl_short = "|".join(s[:2] for s in sl) if sl else ""
            usg = r.get("独立信号组", r.get("策略命中", 0))
            lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {r['量比']:<6} {r['策略命中']:<3}个 {usg:<4} {sl_short:<30}")
        lines.append("")

    # 各策略分布
    strategy_names = ["低吸买点", "三破七入", "九爆发", "缠论精选", "低位放量首板", "连板接力弱转强", "趋势加速", "N字反包", "多维精选"]
    for sn in strategy_names:
        matched = [r for r in sorted_results if sn in r["策略列表"]]
        if matched:
            lines.append(f"【{sn}】{len(matched)}只")
            lines.append(f"  {'标记':<16} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'量比':<6} {'策略'}")
            lines.append(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*30}")
            for r in matched[:8]:
                sl = r.get("策略列表", [])
                sl_short = "|".join(s[:2] for s in sl) if sl else ""
                lines.append(f"  {tag(r):<16} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {r['量比']:<6} {sl_short:<30}")
            if len(matched) > 8:
                lines.append(f"  ... 还有{len(matched)-8}只")
            lines.append("")

    lines.append("=" * 70)
    lines.append("  策略说明:")
    lines.append("  低吸买点: 前期放量拉升 → 缩量回调(量<70%) → 今日企稳(小阳/下影线) → 不破MA20（回调低吸，不追高）")
    lines.append("  三破七入九爆发: 首板涨停(非一字/T板,不≥3连板) + 60均上+开在60均上 + 破板绿量递减 + 距高点>20%空间 + 公式选:三破(第1天破→涨停后新高)/七入(第2天破→新高)/九爆发(第3天破→新高) — 二次爆发用")
    lines.append("  三破七入上车: 3天内破涨停最低 + 7天内红K放量站上ZTO且<ZTC + 60均上 + 距高点>20%空间 — 调整期低吸用")
    lines.append("  缠论精选: 一买/二买/三买 + 底背驰（缠师108课核心）")
    lines.append("  低位放量首板: 涨幅>3% + 量比>1.8 + 均线多头 + 突破20日平台")
    lines.append("  连板接力: 近期有涨停 + 今日上涨 + 均线多头 + MACD多头")
    lines.append("  趋势加速: 均线多头 + 放量 + MACD多头 + MA5角度>=30°")
    lines.append("  N字反包: 10日内涨停 → 回调 → 今日再涨")
    lines.append("  多维精选: MACD多头 + 均线多头 + 放量 + RSI适中")
    lines.append("")
    lines.append("  新增缠论指标说明:")
    lines.append("  - 背驰: 第24/25课MACD辅助判断法（价格新低+MACD柱缩短）")
    lines.append("  - 中枢位置: 第18课走势中枢（上方=强势/内部=盘整/下方=弱势）")
    lines.append("  - 区间套: 第61课多周期确认（30分钟共振）")
    lines.append("  - 底分型: 第15课分型定义（中间K线低点最低+最高最低）+有效性确认")
    lines.append("  - 仓位建议: OpenClaw风控模型（以10万本金演示）")
    lines.append("")
    lines.append("  置信度评分: 基于历史胜率数据自动优化阈值，目标>80%上涨概率")
    lines.append("    - 高置信(★) = 置信度>=60分，且有已验证的高胜率信号触发")
    lines.append("    - 关注(☆) = 置信度45-59分，有多个信号共振但未达高置信标准")
    lines.append("    - 置信度模型随每日运行自动更新（信号跟踪学习系统）")
    lines.append("")
    lines.append("  高级信号（2026/06/11 新增）:")
    lines.append("  - 平步青云评分: 7大特征评分(0-100)，>65分=主升浪启动信号（陈老师第二节）")
    lines.append("    特征1短期拉升 2放量突破 3横盘洗盘 4倍量阳线 5压力空间 6模式复制 7五日线向上")
    lines.append("  - 洗盘结束: 前日阴线/长上影 → 今日低开高走下影线+放量确认（操盘笔记p7）")
    lines.append("  - 回踩买点: 低开高走+盘中砸破开盘+收回+前日回调阴（操盘笔记p56分时8大买入技巧）")
    lines.append("  - 倍量突破: 横盘振幅<30% + 今日放量突破平台高点 + 倍量阳线")
    lines.append("")
    lines.append("  股海炼金术第三课（2026/06/11 新增）:")
    lines.append("  二进三战法【星火燎原】: 首板=建仓型涨停(抢筹) + 二板=洗盘型涨停(V字炸板回封) + 炸板回封时介入")
    lines.append("    条件: 底部起涨<30% + 2次试盘线(1次三倍量) + 拉升涨停 + 60MA上 + 次日超前板收")
    lines.append("  建仓型涨停(抢筹式): 主力暴力抢筹第一动作 A突然拉涨停 B趋势转折 C脉冲封死 D中低位置")
    lines.append("  洗盘型涨停(V字形): 涨停→炸板放量打开缺口→回封；全天大部分时间封死+中间缺口放量")
    lines.append("")
    lines.append("  主升浪起爆信号（2026/06/11 新增）:")
    lines.append("  试盘线: 长上影>实体2倍 + 放量>=1.3x + 微涨(不涨停) - 主力测试抛压")
    lines.append("  三倍量试盘线: 量>5日均量3倍 - 更强的主力起爆前信号")
    lines.append("  主升浪起爆: 震荡建仓(振幅<35%) + 试盘线 + 缩量整理不破低 + 今日放量突破试盘高点 = 起爆确认")
    lines.append("  震荡建仓: 振幅<35% + MA20/MA60收敛 + 量能正常无出货 - 底部建仓结构识别")
    lines.append("")
    lines.append("  筹码分布指标（2026/06/12 新增）:")
    lines.append("  A02=WINNER(C*1.05)  A03=WINNER(C*0.95)  基于历史成交量-价格分布估算")
    lines.append("  获利盘: A03值(%) — 成本低于现价95%的筹码比例")
    lines.append("  浮动筹码: A02-A03(%) — 成本在现价±5%的松动筹码")
    lines.append("  套牢盘: 100-A02(%) — 成本高于现价105%的套牢筹码")
    lines.append("  筹码集中: 浮动筹码越小+单方占优=越集中; 高度集中(获利)>获利盘>60%+浮动<15%")
    lines.append("  底部建仓完毕: 获利盘>50%+浮动筹码<20% — 主力吸筹完毕等待拉升")
    lines.append("  上方无压力: 获利盘>60%+套牢盘<20% — 拉升抛压小")
    lines.append("  高度控盘: 集中度>75+获利盘>40% — 主力掌控局面")
    lines.append("")
    lines.append("  龙头模式（2026/06/12 新增）:")
    lines.append("  飞龙在天: 三连板以上→断板洗盘→次日反包/涨停确认→突破断板实体最高价介入→跌破断板最低价止损(5-8%)")
    lines.append("    条件1:3连板以上(龙头辨识度) 条件2:断板洗盘(风险释放) 条件3:反包确认(主力意图) 条件4:筹码集中+资金流入")
    lines.append("    条件5:主线题材(空间支撑) 条件6:突破断板实体高=介入 条件7:跌破断板最低=止损")
    lines.append("  潜龙回首: 前期连续大涨(二板以上/涨幅20%+)→回调2-8天→回调幅度不超50%→企稳=龙回头机会")
    lines.append("    核心: 不是所有回调都做—做有辨识度的龙头股回调+风险释放+企稳确认")
    lines.append("  新增基本面筛选说明:")
    lines.append("  - 数据源: akshare财务数据")
    lines.append("  - 排除: 利润下滑>30%/ROE亏损/负债率>85%/营收下滑>20%")
    lines.append("  - 综合评分: 成长性40分+盈利30分+安全20分+每股价值10分")
    lines.append("=" * 70)
    lines.append("  [风险] 基于历史数据筛选，仅供参考，不构成投资建议")
    lines.append("  [信号跟踪] 系统每日自动记录信号→跟踪表现→优化阈值")
    lines.append("  [信号跟踪] 运行 python run_selector.py --learn 查看置信度模型")
    lines.append("  [信号跟踪] 运行 python run_selector.py --report-learn 查看学习报告")

    return "\n".join(lines)


# ==================== 写入通达信板块 ====================

TDX_BLOCK_FILE = "D:/new_tdx/T0002/blocknew/CLAUDEXG.blk"

# 市场前缀: sh->1, sz->0, bj->4
MARKET_PREFIX = {
    "sh": "1",
    "sz": "0",
    "bj": "4",
}


def write_tdx_block(stocks: list, blk_name: str = "CLAUDEXG"):
    """将选股结果写入通达信自定义板块（覆盖写入，首行空行格式）"""
    if not stocks:
        return
    text_lines = [""]
    for s in stocks:
        code = s.get("代码", "")
        if code.startswith(("6", "9", "5")):
            prefix = "1"
        elif code.startswith(("0", "3", "2")):
            prefix = "0"
        elif code.startswith(("4", "8")):
            prefix = "4"
        else:
            continue
        text_lines.append(f"{prefix}{code}")

    blk_dir = "D:/new_tdx/T0002/blocknew"
    blk_path = os.path.join(blk_dir, f"{blk_name}.blk")
    raw_text = '\r\n'.join(text_lines)
    os.makedirs(blk_dir, exist_ok=True)
    with open(blk_path, "wb") as f:
        f.write(raw_text.encode('gbk'))
    print(f"  [板块] {len(text_lines)-1}只 -> {blk_name}.blk")


def write_stock_blocks(results_fin: list):
    """
    统写通达信板块（含策略标记+选股时间，方便跟踪效果）

    写入文件:
      CLAUDEXG.blk          — 全量（通达信主板块）
      CLAUDE_低吸.blk       — 低吸买点策略
      CLAUDE_缠论.blk       — 缠论精选
      CLAUDE_首板.blk       — 低位放量首板
      CLAUDE_连板.blk       — 连板接力
      CLAUDE_加速.blk       — 趋势加速
      CLAUDE_N字.blk        — N字反包
      CLAUDE_多维.blk       — 多维精选
      CLAUDE_九爆发.blk     — 三破七入九爆发
      CLAUDE_备注.txt       — 每只股票的策略标记+选股时间
    """
    if not results_fin:
        return

    now = datetime.now().strftime("%m-%d %H:%M")
    name_map = {r["代码"]: r.get("名称", "") for r in results_fin if "代码" in r}

    # ---- 1. 策略标记函数 ----
    def _tag(r):
        tags = []
        lc = r.get("低吸买点", "")
        if lc: tags.append("低吸")
        chan = r.get("缠论买点", "")
        if chan:
            short = chan.replace(" + ", "+").replace("二买","2买").replace("三买","3买").replace("一买","1买")
            tags.append(f"缠{short}")
        sbo = r.get("九爆发", "")
        if sbo == "三破": tags.append("三破")
        elif sbo == "七入": tags.append("七入")
        elif sbo: tags.append("九爆发")
        e7 = r.get("三破七入", "")
        if e7 and not sbo: tags.append("3破7入")
        sl = r.get("策略列表", [])
        if "低位放量首板" in sl: tags.append("首板")
        if "连板接力弱转强" in sl: tags.append("连板")
        if "趋势加速" in sl: tags.append("加速")
        if "N字反包" in sl: tags.append("N字")
        if "多维精选" in sl: tags.append("多维")
        # 主升浪起爆信号
        if r.get("主升浪起爆", ""): tags.append("起爆")
        if r.get("三倍量试盘", ""): tags.append("三倍试盘")
        elif r.get("试盘线", ""): tags.append("试盘")
        if r.get("震荡建仓", ""): tags.append("震仓")
        if r.get("飞龙在天", ""): tags.append("飞龙")
        if r.get("潜龙回首", ""): tags.append("潜龙")
        return "+".join(tags[:5]) if tags else "其他"

    # ---- 2. 主板块 ----
    write_tdx_block(results_fin, "CLAUDEXG")

    # ---- 3. 按策略分板块 ----
    strategies = [
        ("低吸买点", "CLAUDE_低吸"),
        ("缠论精选", "CLAUDE_缠论"),
        ("九爆发", "CLAUDE_九爆发"),
        ("低位放量首板", "CLAUDE_首板"),
        ("连板接力弱转强", "CLAUDE_连板"),
        ("趋势加速", "CLAUDE_加速"),
        ("N字反包", "CLAUDE_N字"),
        ("多维精选", "CLAUDE_多维"),
        ("三破七入", "CLAUDE_3破7入"),
    ]
    for sn, blk_name in strategies:
        matched = [r for r in results_fin if sn in r.get("策略列表", [])]
        if matched:
            write_tdx_block(matched, blk_name)

    # ---- 4. 备注文件（关键：记录每只股的策略+时间，方便跟踪效果）----
    notes_lines = [
        f"选股时间: {now}  共{len(results_fin)}只",
        "",
        f"{'代码':>6} {'名称':<10} {'策略标记':<16} {'涨幅%':<7} {'量比':<5} {'策略详情'}",
        "-" * 65,
    ]
    for r in results_fin:
        code = r.get("代码", "")
        name = r.get("名称", "")
        chg = r.get("涨跌幅", 0) or 0
        vr = r.get("量比", 0) or 0
        tag = _tag(r)
        sl = "|".join(r.get("策略列表", []))[:30]
        notes_lines.append(f" {code:<6} {name:<10} {tag:<16} {chg:>+5.2f}% {vr:<5.1f} {sl}")

    notes_path = "D:/new_tdx/T0002/blocknew/CLAUDEXG_备注.txt"
    with open(notes_path, "w", encoding="gbk") as f:
        f.write("\r\n".join(notes_lines))
    print(f"  [备注] -> CLAUDEXG_备注.txt ({len(results_fin)}只，含策略标记+选股时间)")

    print(f"  [用法] 通达信Ctrl+F2->自定义板块 查看CLAUDE*系列板块；打开备注.txt对照策略")


def screen_strict_top(results: list, top_n: int = 10) -> list:
    """
    严格精选管道:
      1. 技术面精选（低吸买点放宽/缠论精选收紧）
      2. 基本面筛选（排除利润下滑>30%/ROE亏损等）
      3. 综合评分排序（基本面加权）
    返回: 精选后的股票列表（最多top_n只）
    """
    strict_candidates = []
    for r in results:
        lc = r.get("低吸买点", "")
        chan = r.get("缠论买点", "")
        chg = float(r.get("涨跌幅", 0) or 0)
        price = float(r.get("最新价", 0) or 0)
        vr = float(r.get("量比", 0) or 0)

        # 通道A: 低吸买点（放宽）
        if lc:
            if vr >= 0.6 and 5 <= price <= 100:
                strict_candidates.append(r)
                continue

        # 通道B: 缠论精选（收紧）
        if not chan:
            continue
        if r.get("中枢位置", "") != "上方":
            continue
        if vr < 1.5:
            continue
        if not (0.5 <= chg <= 5.0):
            continue
        if not (5 <= price <= 50):
            continue
        strict_candidates.append(r)

    strict_candidates.sort(key=lambda x: -(x.get("独立信号组", 0) * 2 + x.get("策略命中", 0)))
    strict_top = strict_candidates[:max(top_n * 2, 12)]

    # 基本面筛选
    results_fin = fundamental_filter(strict_top, verbose=True)

    # 综合评分排序
    for r in results_fin:
        fin_score = r.get("基本面评分", 50)
        if not isinstance(fin_score, int):
            fin_score = 50
        strat_hits = r.get("策略命中", 0)
        unique_sigs = r.get("独立信号组", strat_hits)
        base_score = strat_hits * 8 + unique_sigs * 5
        fin_weight = 0.6 + min(fin_score / 150, 0.4)
        if isinstance(r.get("基本面评分"), str) and r.get("基本面评分") == "无数据":
            fin_weight = 0.85
        r["综合评分"] = base_score * fin_weight
        r["基本面评分原始值"] = fin_score

    results_fin.sort(key=lambda x: -x.get("综合评分", 0))
    return results_fin[:top_n]


if __name__ == "__main__":
    import time
    t0 = time.time()
    print("开始本地扫盘...")
    print(f"  股票名称库: {len(load_code_name_map())} 只")
    print()

    results = run_local_screen()
    print(f"\n[OK] 技术面选出 {len(results)} 只 (耗时 {time.time()-t0:.1f}秒)")

    # ===== 严格精选管道: 技术面 → 基本面 → 综合评分 =====
    results_fin = screen_strict_top(results, top_n=10)

    # 写入通达信板块（仅精选股）
    write_stock_blocks(results_fin)
    print(f"  板块写入完成（精选中{len(results_fin)}只，含按策略分板块+备注文件）")

    # ===== 市场状态识别（Hermes Skill Router 架构）=====
    index_info = None
    index_path = os.path.join(TDX_ROOT, "sh", "lday", "sh000001.day")
    if os.path.exists(index_path):
        try:
            index_klines = parse_day_file(index_path, 250)
            if len(index_klines) >= 60:
                index_info = detect_market_regime(index_klines)
                # 生成市场状态报告
                regime_report = format_market_report(index_info, get_strategy_weights(index_info))
                print("\n" + regime_report + "\n")
        except Exception as e:
            print(f"  [市场状态] 识别失败: {e}")

    # ===== 持续跟踪池 =====
    print("\n  [跟踪] 更新持续跟踪池...")
    tracker = load_tracker()
    merge_into_tracker(tracker, results_fin)
    tracking_report = get_tracking_report(tracker)
    print(f"  [跟踪] 池中共 {len(tracker)} 只（历史累计）")
    to_del_count = sum(1 for e in tracker.values() if e.get("status") == "考虑删除")
    if to_del_count:
        print(f"  [跟踪] ⚠️ {to_del_count} 只连续7天无表现，建议删除")

    # 打印报告（含跟踪池）
    report = get_daily_report(results_fin, index_info)
    report += tracking_report
    print("\n" + report)

    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = OUTPUT_DIR / f"本地选股报告_{ts}.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n[OK] 报告已保存: {report_path}")
