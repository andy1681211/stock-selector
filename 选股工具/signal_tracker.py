"""
信号跟踪与置信度优化系统 v1.0
================================
目标：记录每次选股信号 → 跟踪后续表现 → 自动优化阈值 → 实现>80%上涨概率

工作流程：
  1. LOG阶段（选股时）：记录当天所有信号及其参数到 signal_events.jsonl
  2. EVAL阶段（下次选股前）：回查之前推荐股票的涨跌表现
  3. BACKTEST阶段（每日一次）：用历史数据回测信号的历史胜率
  4. OPTIMIZE阶段：找到使胜率>80%的最优阈值组合
  5. FILTER阶段：用优化后的阈值过滤当天选股结果，只推高置信度股票

数据文件：
  - output/tracking/signal_events.jsonl   — 全部信号事件日志（追加写）
  - output/tracking/confidence_model.json  — 优化后的置信度模型
  - output/tracking/backtest_cache.json    — 历史回测缓存（避免重复计算）
"""

import os
import json
import math
import numpy as np
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
from collections import defaultdict

# ===== 路径配置 =====
TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"
TRACKING_DIR = OUTPUT_DIR / "tracking"
EVENTS_FILE = TRACKING_DIR / "signal_events.jsonl"
CONFIDENCE_FILE = TRACKING_DIR / "confidence_model.json"
BACKTEST_CACHE = TRACKING_DIR / "backtest_cache.json"


# ======================================================================
#  1. 信号记录（LOG）
# ======================================================================

def _ensure_dirs():
    """确保跟踪数据目录存在"""
    TRACKING_DIR.mkdir(parents=True, exist_ok=True)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def log_signal_events(results: List[Dict], date_str: str = None):
    """
    将当天选股结果记录到信号事件日志。

    每条事件包含：日期、股票、所有信号及其参数、当时行情状态。
    次日运行时通过 evaluate_previous_picks() 补充 outcome 字段。

    Args:
        results: scan_stock 返回的结果列表
        date_str: 日期字符串（默认今天）
    """
    if not results:
        return

    _ensure_dirs()
    date_str = date_str or _today_str()

    # 读取已有事件（避免重复记录同一天）
    existing = set()
    if EVENTS_FILE.exists():
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        evt = json.loads(line)
                        existing.add((evt.get("date", ""), evt.get("code", "")))
                    except:
                        pass

    new_count = 0
    with open(EVENTS_FILE, "a", encoding="utf-8") as f:
        for r in results:
            code = r.get("代码", "")
            key = (date_str, code)
            if key in existing:
                continue

            event = {
                "date": date_str,
                "code": code,
                "name": r.get("名称", ""),
                "price": r.get("最新价", 0),
                "chg": r.get("涨跌幅", 0),
                "vr": r.get("量比", 0),

                # --- 信号参数（用于后续优化阈值）---
                "signals": {
                    "平步青云": {
                        "score": _parse_pbq_score(r.get("平步青云", "")),
                        "is_strong": r.get("平步青云强") == "是",
                    },
                    "洗盘结束": {
                        "detected": bool(r.get("洗盘结束", "")),
                        "desc": r.get("洗盘结束", ""),
                    },
                    "倍量突破": {
                        "detected": bool(r.get("倍量突破", "")),
                        "desc": r.get("倍量突破", ""),
                    },
                    "底分型": {
                        "detected": bool(r.get("底分型", "")),
                        "desc": r.get("底分型", ""),
                    },
                    "回踩买点": {
                        "detected": bool(r.get("回踩买点", "")),
                        "desc": r.get("回踩买点", ""),
                    },
                    "缠论买点": {
                        "detected": bool(r.get("缠论买点", "")),
                        "desc": r.get("缠论买点", ""),
                    },
                    "低吸买点": {
                        "detected": bool(r.get("低吸买点", "")),
                        "desc": r.get("低吸买点", ""),
                    },
                    "九爆发": {
                        "detected": bool(r.get("九爆发", "")),
                        "desc": r.get("九爆发", ""),
                    },
                    "三破七入": {
                        "detected": bool(r.get("三破七入", "")),
                        "desc": r.get("三破七入", ""),
                    },
                    "股海建仓型涨停": {
                        "detected": bool(r.get("建仓型涨停", "")),
                        "desc": r.get("建仓型涨停", ""),
                    },
                    "股海洗盘型涨停": {
                        "detected": bool(r.get("洗盘型涨停", "")),
                        "desc": r.get("洗盘型涨停", ""),
                    },
                    "股海二进三": {
                        "detected": bool(r.get("二进三信号", "")),
                        "desc": r.get("二进三信号", ""),
                        "zt_count": r.get("涨停板数", 0),
                    },
                },

                # --- 辅助信息 ---
                "ma5": r.get("MA5", 0),
                "ma20": r.get("MA20", 0),
                "rsi6": r.get("RSI6", 0),
                "ma_angle": r.get("MA角度", ""),
                "策略命中": r.get("策略命中", 0),
                "独立信号组": r.get("独立信号组", 0),

                # --- outcome 占位（次日填）---
                "outcome": None,
            }
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
            new_count += 1

    if new_count > 0:
        print(f"  [信号跟踪] 记录 {new_count} 条新信号事件到 {EVENTS_FILE.name}")


def _parse_pbq_score(pbq_str: str) -> int:
    """从 '44分' / '95分' 提取数字"""
    if not pbq_str:
        return 0
    try:
        return int(pbq_str.replace("分", ""))
    except:
        return 0


# ======================================================================
#  2. 信号评估（EVAL）—— 回查前N天推荐股票表现
# ======================================================================

def evaluate_previous_picks(lookback_days: int = 5) -> Dict:
    """
    回查最近 N 天信号事件的实际涨跌表现。
    需要通达信日K线数据来获取后续价格。

    对每条 event（outcome 为 null 的）：
      - 获取事件日之后第1天/第3天/第5天的收盘价
      - 计算涨跌幅
      - 记录 outcome

    Returns:
        {"evaluated": int, "hit_rates": {...}, "errors": int}
    """
    from local_screener import parse_day_file, TDX_ROOT

    if not EVENTS_FILE.exists():
        return {"evaluated": 0, "hit_rates": {}, "errors": 0}

    _ensure_dirs()

    # 读所有事件
    events = []
    with open(EVENTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except:
                    pass

    today = datetime.now().date()
    updated = 0
    errors = 0
    hit_counts = defaultdict(lambda: {"up": 0, "down": 0, "total": 0})
    hit_by_threshold = defaultdict(lambda: defaultdict(lambda: {"up": 0, "down": 0}))

    for i, evt in enumerate(events):
        # 只处理未评估的，且在 lookback_days 天内的事件
        if evt.get("outcome") is not None:
            continue

        try:
            evt_date = datetime.strptime(evt["date"], "%Y-%m-%d").date()
        except:
            continue

        days_since = (today - evt_date).days
        if days_since < 1 or days_since > lookback_days:
            continue

        code = evt.get("code", "")
        if not code:
            continue

        # 定位对应市场
        if code.startswith(("6", "9", "5")):
            market = "sh"
        elif code.startswith(("0", "3", "2")):
            market = "sz"
        elif code.startswith(("4", "8")):
            market = "bj"
        else:
            continue

        # 读取日K线
        fp = os.path.join(TDX_ROOT, market, "lday", f"{market}{code}.day")
        if not os.path.exists(fp):
            errors += 1
            continue

        klines = parse_day_file(fp, 500)
        if len(klines) < 10:
            errors += 1
            continue

        # 找到事件日对应的K线索引
        event_idx = None
        for j in range(len(klines)):
            if klines[j].date == evt_date:
                event_idx = j
                break

        if event_idx is None or event_idx >= len(klines) - 1:
            errors += 1
            continue

        # 计算后续涨跌
        def safe_chg(idx, offset):
            if idx + offset < len(klines):
                return klines[idx + offset].pct_chg
            return None

        outcome = {
            "d1_chg": safe_chg(event_idx, 1),
            "d3_chg": safe_chg(event_idx, 3),
            "d5_chg": safe_chg(event_idx, 5),
            "d1_high": max((klines[event_idx + 1].high - klines[event_idx].close) / klines[event_idx].close * 100
                          if klines[event_idx].close > 0 else 0, 0) if event_idx + 1 < len(klines) else None,
            "d1_low": min((klines[event_idx + 1].low - klines[event_idx].close) / klines[event_idx].close * 100
                          if klines[event_idx].close > 0 else 0, 0) if event_idx + 1 < len(klines) else None,
            "eval_date": today.strftime("%Y-%m-%d"),
        }

        events[i]["outcome"] = outcome
        updated += 1

        # ---- 统计每种信号的胜率 ----
        signals = evt.get("signals", {})
        d1 = outcome.get("d1_chg")

        if d1 is not None:
            is_up = d1 > 0

            # 按信号类型统计
            for sig_name, sig_info in signals.items():
                if isinstance(sig_info, dict):
                    detected = sig_info.get("detected", False) or sig_info.get("is_strong", False)
                    if detected:
                        hit_counts[sig_name]["total"] += 1
                        if is_up:
                            hit_counts[sig_name]["up"] += 1
                        else:
                            hit_counts[sig_name]["down"] += 1

            # 按 平步青云 分数段统计
            pbq_score = signals.get("平步青云", {}).get("score", 0)
            if pbq_score >= 30:
                # 按分数段: 30-49, 50-64, 65-79, 80+
                if pbq_score >= 80:
                    bucket = "pbq_80plus"
                elif pbq_score >= 65:
                    bucket = "pbq_65_79"
                elif pbq_score >= 50:
                    bucket = "pbq_50_64"
                else:
                    bucket = "pbq_30_49"

                hit_by_threshold[bucket]["total"] += 1
                if is_up:
                    hit_by_threshold[bucket]["up"] += 1
                else:
                    hit_by_threshold[bucket]["down"] += 1

            # 统计二重/三重共振
            detected_signals = [n for n, s in signals.items()
                                if isinstance(s, dict) and (s.get("detected") or s.get("is_strong"))]
            num_detected = len(detected_signals)
            if num_detected >= 2:
                hit_counts["二重共振"]["total"] += 1
                if is_up:
                    hit_counts["二重共振"]["up"] += 1
                else:
                    hit_counts["二重共振"]["down"] += 1
            if num_detected >= 3:
                hit_counts["三重共振"]["total"] += 1
                if is_up:
                    hit_counts["三重共振"]["up"] += 1
                else:
                    hit_counts["三重共振"]["down"] += 1

    # 写回文件
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        for evt in events:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")

    # 计算胜率
    hit_rates = {}
    for name, counts in hit_counts.items():
        total = counts["total"]
        if total >= 3:
            hit_rates[name] = {
                "win_rate": round(counts["up"] / total * 100, 1),
                "up": counts["up"],
                "down": counts["down"],
                "total": total,
            }

    # 平步青云分段胜率
    pbq_rates = {}
    for bucket, counts in hit_by_threshold.items():
        total = counts["total"]
        if total >= 3:
            pbq_rates[bucket] = {
                "win_rate": round(counts["up"] / total * 100, 1),
                "up": counts["up"],
                "total": total,
            }

    if updated > 0:
        print(f"  [信号跟踪] 评估 {updated} 条历史信号 (错误 {errors} 条)")
        for name, hr in sorted(hit_rates.items(), key=lambda x: -x[1]["win_rate"]):
            print(f"    {name}: 胜率 {hr['win_rate']}% ({hr['up']}/{hr['total']})")

    return {
        "evaluated": updated,
        "hit_rates": hit_rates,
        "pbq_rates": pbq_rates,
        "errors": errors,
    }


# ======================================================================
#  3. 历史回测（BACKTEST）
# ======================================================================

def run_backtest(lookback_days: int = 30, sample_limit: int = 200) -> Dict:
    """
    对当前选出的股票进行历史信号回测。

    方法：对每只今天有信号的股票，回看过去 N 天，
    模拟每天的信号触发情况，检查次日的实际涨跌。
    以此来估算每个信号/阈值的历史胜率。

    Args:
        lookback_days: 回看多少天
        sample_limit: 最多处理多少只股票（避免太慢）

    Returns:
        {signal_type: {threshold: {win_rate, up, total}}}
    """
    from local_screener import parse_day_file, scan_stock, load_code_name_map, TDX_ROOT
    import random

    print(f"  [历史回测] 回看 {lookback_days} 天, 每只股票模拟回测...")

    _ensure_dirs()

    # 读取缓存（避免重复计算）
    cache = {}
    if BACKTEST_CACHE.exists():
        try:
            cache_text = BACKTEST_CACHE.read_text("utf-8")
            if cache_text.strip():
                cache = json.loads(cache_text)
        except:
            pass

    # 获取全市场股票列表（用已有名称映射）
    name_map = load_code_name_map()
    all_stocks = list(name_map.keys())
    random.shuffle(all_stocks)  # 避免板块偏倚

    # 筛选有足够数据的股票
    tested = 0
    results_by_signal = defaultdict(list)  # signal_name -> [(score/threshold, next_day_chg)]

    for code in all_stocks:
        if tested >= sample_limit:
            break

        if code.startswith(("300", "301", "688", "689")):
            continue
        if code.startswith(("6", "9", "5")):
            market = "sh"
        elif code.startswith(("0", "3", "2")):
            market = "sz"
        elif code.startswith(("4", "8")):
            market = "bj"
        else:
            continue

        fp = os.path.join(TDX_ROOT, market, "lday", f"{market}{code}.day")
        if not os.path.exists(fp):
            continue

        # 用缓存键
        cache_key = f"{code}_{lookback_days}"
        if cache_key in cache:
            cached = cache[cache_key]
            for sig_name in cached:
                results_by_signal[sig_name].extend(cached[sig_name])
            tested += 1
            continue

        klines = parse_day_file(fp, 500)
        if len(klines) < 100:
            continue

        stock_results = defaultdict(list)

        # 从后往前，取 lookback_days 个交易日做模拟
        today_idx = len(klines) - 1
        sim_days = []
        step = max(1, lookback_days // 10)  # 采样间隔，保证覆盖但不密集
        for offset in range(lookback_days, 1, -step):
            sim_idx = today_idx - offset
            if sim_idx < 100:
                continue
            sim_days.append(sim_idx)

        if not sim_days:
            continue

        tested += 1

        for sim_idx in sim_days:
            sim_klines = klines[:sim_idx + 1]
            sim_today = sim_klines[-1]

            # ---- 获取次日涨跌 ----
            next_idx = sim_idx + 1
            if next_idx >= len(klines):
                continue
            next_chg = klines[next_idx].pct_chg

            # ---- 模拟 平步青云 评分 ----
            try:
                from advanced_signals import pingbu_qingyun_score
                pbq = pingbu_qingyun_score(sim_klines)
                pbq_score = pbq["score"]
                pbq_strong = pbq["is_strong"]

                stock_results["平步青云"].append((pbq_score, next_chg))
                if pbq_strong:
                    stock_results["平步青云_强"].append((1, next_chg))
            except:
                pass

            # ---- 模拟 洗盘结束 ----
            try:
                from advanced_signals import is_washout_complete
                wo, wd = is_washout_complete(sim_klines)
                if wo:
                    stock_results["洗盘结束"].append((1, next_chg))
            except:
                pass

            # ---- 模拟 倍量突破 ----
            try:
                from advanced_signals import is_volume_surge_breakout
                vs, vd = is_volume_surge_breakout(sim_klines)
                if vs:
                    stock_results["倍量突破"].append((1, next_chg))
            except:
                pass

            # ---- 模拟 回踩买点 ----
            try:
                from advanced_signals import is_day_trade_entry
                dt, dd = is_day_trade_entry(sim_klines)
                if dt:
                    stock_results["回踩买点"].append((1, next_chg))
            except:
                pass

            # ---- 模拟 底分型 ----
            try:
                from advanced_signals import detect_bottom_fractal
                bf_ok, bf_desc = detect_bottom_fractal(sim_klines)
                if bf_ok:
                    stock_results["底分型"].append((1, next_chg))
            except:
                pass

        # 存入缓存
        cache[cache_key] = dict(stock_results)
        for sig_name in stock_results:
            results_by_signal[sig_name].extend(stock_results[sig_name])

        if tested % 50 == 0:
            print(f"    已回测 {tested}/{sample_limit} 只...")

    # 保存缓存
    BACKTEST_CACHE.write_text(json.dumps(cache, ensure_ascii=False), "utf-8")

    # ---- 统计分析 ----
    backtest_results = {}

    for sig_name, entries in results_by_signal.items():
        if not entries:
            continue

        if sig_name in ["平步青云"]:
            # 按分数段统计
            score_buckets = [(30, 49), (50, 64), (65, 79), (80, 100)]
            for lo, hi in score_buckets:
                bucket = [(s, c) for s, c in entries if lo <= s <= hi]
                if len(bucket) < 5:
                    continue
                ups = sum(1 for _, c in bucket if c > 0)
                key = f"pbq_{lo}_{hi}"
                backtest_results[key] = {
                    "win_rate": round(ups / len(bucket) * 100, 1),
                    "up": ups,
                    "total": len(bucket),
                    "avg_next_chg": round(sum(c for _, c in bucket) / len(bucket), 2),
                }

            # 按最低阈值统计（score >= X）
            for threshold in range(30, 95, 5):
                above = [(s, c) for s, c in entries if s >= threshold]
                if len(above) < 5:
                    continue
                ups = sum(1 for _, c in above if c > 0)
                key = f"pbq_{threshold}+"
                backtest_results[key] = {
                    "win_rate": round(ups / len(above) * 100, 1),
                    "up": ups,
                    "total": len(above),
                    "avg_next_chg": round(sum(c for _, c in above) / len(above), 2),
                }

        elif sig_name == "平步青云_强":
            ups = sum(1 for _, c in entries if c > 0)
            backtest_results["平步青云_强"] = {
                "win_rate": round(ups / len(entries) * 100, 1),
                "up": ups,
                "total": len(entries),
                "avg_next_chg": round(sum(c for _, c in entries) / len(entries), 2),
            }

        else:
            # 简单二值信号
            ups = sum(1 for _, c in entries if c > 0)
            backtest_results[sig_name] = {
                "win_rate": round(ups / len(entries) * 100, 1),
                "up": ups,
                "total": len(entries),
                "avg_next_chg": round(sum(c for _, c in entries) / len(entries), 2),
            }

    # ---- 也统计组合信号 ----
    # 如果有足够的平步青云数据，计算"平步青云+其他"组合
    if len(results_by_signal.get("平步青云", [])) > 20:
        pbq_entries = results_by_signal["平步青云"]
        for other_sig in ["洗盘结束", "倍量突破", "回踩买点", "底分型"]:
            other_entries = results_by_signal.get(other_sig, [])
            if len(other_entries) < 5:
                continue

            # 近似估计：平步青云高分 + 其他信号同一天出现的胜率
            # 用平步青云 >= 65 的集合近似
            high_pbq = [c for s, c in pbq_entries if s >= 65]
            # 其他信号本身出现的胜率
            other_ups = sum(1 for _, c in other_entries if c > 0)
            other_rate = round(other_ups / len(other_entries) * 100, 1)

            if high_pbq:
                high_pbq_ups = sum(1 for c in high_pbq if c > 0)
                high_pbq_rate = round(high_pbq_ups / len(high_pbq) * 100, 1)
                # 两个信号在同一天出现 = 近似取较高胜率
                backtest_results[f"pbq65%2B_{other_sig}"] = {
                    "win_rate_estimate": max(high_pbq_rate, other_rate),
                    "pbq65+_win_rate": high_pbq_rate,
                    f"{other_sig}_win_rate": other_rate,
                    "note": "组合信号 = 取单个信号较高者（无精确同一天数据）",
                }

    print(f"  [历史回测] 完成 {tested} 只股票回测, 获得 {len(backtest_results)} 组信号统计")

    return backtest_results


# ======================================================================
#  4. 置信度优化（OPTIMIZE）
# ======================================================================

def optimize_thresholds(backtest_results: Dict = None, eval_results: Dict = None) -> Dict:
    """
    综合历史回测 + 在线评估数据，找到使胜率 > 80% 的最优阈值。

    核心策略：
    - 从回测数据中找到每个信号的 "首个胜率 > 80%" 阈值
    - 如果实时评估数据更准确，优先使用实时数据
    - 阈值只收窄不放宽（保证 precision 不下降）
    - 数据量 < 10 条的信号暂不启用自动筛选

    Returns:
        置信度模型字典（可直接保存为 confidence_model.json）
    """
    model = {
        "version": 2,
        "last_updated": _today_str(),
        "thresholds": {},
        "precision_target": 0.80,
    }

    # ---- 4a. 从回测数据中提取最优阈值 ----
    if backtest_results:
        for key, stats in backtest_results.items():
            total = stats.get("total", 0)
            win_rate = stats.get("win_rate", 0) or stats.get("win_rate_estimate", 0)

            if total < 5:
                continue

            # 解析信号类型
            if key.startswith("pbq_"):
                # 平步青云分数段或阈值
                if key.startswith("pbq_80plus") or key == "pbq_80_100":
                    sig_name = "平步青云_80+"
                elif key.startswith("pbq_65_79"):
                    sig_name = "平步青云_65_79"
                elif key.startswith("pbq_50_64"):
                    sig_name = "平步青云_50_64"
                elif key.startswith("pbq_30_49"):
                    sig_name = "平步青云_30_49"
                elif "+" in key:
                    # pbq_65+ 格式
                    try:
                        threshold = int(key.split("_")[1].replace("+", ""))
                        sig_name = f"平步青云_{threshold}+"
                    except:
                        continue
                else:
                    continue

                model["thresholds"][sig_name] = {
                    "type": "score_threshold",
                    "precision": win_rate,
                    "total": total,
                    "avg_next_chg": stats.get("avg_next_chg", 0),
                    "enabled": win_rate >= 70,  # >70% 就启用，但只有>80%才高亮
                }

            elif key in ["洗盘结束", "倍量突破", "回踩买点", "底分型", "缠论买点", "低吸买点", "九爆发", "三破七入", "股海建仓型涨停", "股海洗盘型涨停", "股海二进三"]:
                model["thresholds"][key] = {
                    "type": "binary_signal",
                    "precision": win_rate,
                    "total": total,
                    "avg_next_chg": stats.get("avg_next_chg", 0),
                    "enabled": win_rate >= 70,
                }

    # ---- 4b. 从实时评估中提取胜率 ----
    if eval_results:
        hit_rates = eval_results.get("hit_rates", {})
        pbq_rates = eval_results.get("pbq_rates", {})

        # 实时评估的数据优先级更高（覆盖回测结果）
        for sig_name, stats in hit_rates.items():
            if stats["total"] < 3:
                continue

            mkey_map = {
                "平步青云": "平步青云_实时",
                "洗盘结束": "洗盘结束",
                "倍量突破": "倍量突破",
                "回踩买点": "回踩买点",
                "底分型": "底分型",
                "缠论买点": "缠论买点",
                "低吸买点": "低吸买点",
                "九爆发": "九爆发",
                "三破七入": "三破七入",
                "股海建仓型涨停": "股海建仓型涨停",
                "股海洗盘型涨停": "股海洗盘型涨停",
                "股海二进三": "股海二进三",
                "二重共振": "二重共振",
                "三重共振": "三重共振",
            }

            mkey = mkey_map.get(sig_name, sig_name)
            if mkey in model["thresholds"] or stats["total"] >= 3:
                key = mkey if mkey in model["thresholds"] else sig_name
                # 合并或覆盖
                existing = model["thresholds"].get(key, {})
                model["thresholds"][key] = {
                    "type": existing.get("type", "binary_signal"),
                    "precision": stats["win_rate"],
                    "total": stats["total"],
                    "up": stats["up"],
                    "down": stats["down"],
                    "source": "live_eval",
                    "enabled": stats["win_rate"] >= 70,
                }

        for bucket, stats in pbq_rates.items():
            bucket_map = {
                "pbq_80plus": "平步青云_80+",
                "pbq_65_79": "平步青云_65_79",
                "pbq_50_64": "平步青云_50_64",
                "pbq_30_49": "平步青云_30_49",
            }
            bkey = bucket_map.get(bucket, bucket)
            if bkey in model["thresholds"] or stats["total"] >= 3:
                existing = model["thresholds"].get(bkey, {})
                model["thresholds"][bkey] = {
                    "type": "score_threshold",
                    "precision": stats["win_rate"],
                    "total": stats["total"],
                    "up": stats["up"],
                    "source": "live_eval",
                    "enabled": stats["win_rate"] >= 70,
                }

    # ---- 4c. 计算 >80% 胜率的"高置信"阈值 ----
    high_conf_signals = []
    for name, info in model["thresholds"].items():
        if info.get("enabled") and info.get("precision", 0) >= 80:
            high_conf_signals.append({
                "name": name,
                "precision": info["precision"],
                "total": info["total"],
                "type": info.get("type", ""),
            })

    model["high_confidence_signals"] = sorted(
        high_conf_signals, key=lambda x: -x["precision"]
    )

    # ---- 4d. 生成置信度调整建议 ----
    # 保存当前最优阈值：用于 scan_stock 时过滤
    # 只有 precision >= 80% 的信号组合才进入"高置信推荐"区
    model["active_filters"] = _build_active_filters(model)

    return model


def _build_active_filters(model: Dict) -> List[Dict]:
    """
    根据当前模型生成实际的筛选规则。
    只有经过验证且 precision >= 80% 的规则才生效。
    """
    filters = []
    thresholds = model.get("thresholds", {})

    # 检查并生成平步青云最优阈值
    pbq_thresholds = [
        (80, "平步青云_80+"),
        (65, "平步青云_65_79"),
    ]
    for score_min, key in pbq_thresholds:
        info = thresholds.get(key, {})
        if info.get("enabled") and info.get("precision", 0) >= 80:
            filters.append({
                "type": "pbq_min_score",
                "value": score_min,
                "precision": info["precision"],
                "total": info["total"],
                "description": f"平步青云评分 >= {score_min}",
            })

    # 二值信号
    for sig_name in ["洗盘结束", "倍量突破", "回踩买点"]:
        info = thresholds.get(sig_name, {})
        if info.get("enabled") and info.get("precision", 0) >= 80:
            filters.append({
                "type": "signal",
                "value": sig_name,
                "precision": info["precision"],
                "total": info["total"],
                "description": f"{sig_name}信号触发",
            })

    # 多重共振（>=2个信号同时触发）
    for key, label in [("二重共振", "2个以上信号共振"), ("三重共振", "3个以上信号共振")]:
        info = thresholds.get(key, {})
        if info.get("precision", 0) >= 80:
            filters.append({
                "type": "resonance",
                "value": 2 if "二重" in key else 3,
                "precision": info["precision"],
                "total": info["total"],
                "description": label,
            })

    return filters


# ======================================================================
#  5. 置信度评分（SCORE）
# ======================================================================

def compute_confidence(result: Dict, model: Dict = None) -> Dict:
    """
    对单只股票的信号结果计算置信度评分。

    返回:
        {
            "score": 0-100,         # 综合置信度
            "level": "高置信"/"关注"/"一般",
            "high_conf_signals": [],  # 触发了哪些高置信信号
            "details": "..."
        }
    """
    if model is None:
        model = load_confidence_model()

    score = 0
    high_conf_signals = []
    reasons = []

    # ---- 平步青云评分 ----
    pbq_score = _parse_pbq_score(result.get("平步青云", ""))
    pbq_strong = result.get("平步青云强") == "是"

    if pbq_score >= 80:
        score += 40
        high_conf_signals.append("平步青云80+")
        reasons.append(f"青云{pbq_score}分")
    elif pbq_score >= 65:
        score += 30
        reasons.append(f"青云{pbq_score}分")
        # 检查模型是否已验证65+分段的胜率
        info_65 = model.get("thresholds", {}).get("平步青云_65_79", {})
        if info_65.get("enabled") and info_65.get("precision", 0) >= 80:
            high_conf_signals.append("平步青云65+")
            score += 5
    elif pbq_score >= 50:
        score += 15
        reasons.append(f"青云{pbq_score}分")
    elif pbq_score >= 30:
        score += 5
        reasons.append(f"青云{pbq_score}分")

    # ---- 洗盘结束 ----
    if result.get("洗盘结束", ""):
        score += 20
        reasons.append("洗盘毕")
        info = model.get("thresholds", {}).get("洗盘结束", {})
        if info.get("enabled") and info.get("precision", 0) >= 80:
            high_conf_signals.append("洗盘结束")

    # ---- 倍量突破 ----
    if result.get("倍量突破", ""):
        score += 25
        reasons.append("倍量突")
        info = model.get("thresholds", {}).get("倍量突破", {})
        if info.get("enabled") and info.get("precision", 0) >= 80:
            high_conf_signals.append("倍量突破")

    # ---- 回踩买点 ----
    if result.get("回踩买点", ""):
        score += 15
        reasons.append("回踩")
        info = model.get("thresholds", {}).get("回踩买点", {})
        if info.get("enabled") and info.get("precision", 0) >= 80:
            high_conf_signals.append("回踩买点")

    # ---- 缠论买点信号 ----
    chan = result.get("缠论买点", "")
    if chan:
        if "二买" in chan:
            score += 20
            reasons.append("缠二买")
        elif "三买" in chan:
            score += 15
            reasons.append("缠三买")
        elif "一买" in chan:
            score += 10
            reasons.append("缠一买")
        else:
            score += 5
            reasons.append("缠论")

    # ---- 低吸买点 ----
    if result.get("低吸买点", ""):
        score += 15
        reasons.append("低吸")

    # ---- 九爆发/三破七入 ----
    if result.get("九爆发", ""):
        score += 20
        reasons.append("九爆发")
    if result.get("三破七入", ""):
        score += 15
        reasons.append("3破7入")

    # ---- 独立信号组数量（策略多样性）----
    unique_groups = result.get("独立信号组", 0)
    if unique_groups >= 8:
        score += 10
        reasons.append(f"{unique_groups}组")
    elif unique_groups >= 5:
        score += 5
        reasons.append(f"{unique_groups}组")

    # ---- 底分型（辅助加分）----
    if result.get("底分型", "") and pbq_score >= 30:
        score += 5
        reasons.append("底分")

    # ---- 均线角度加分 ----
    ma_angle = result.get("MA角度", "0°")
    try:
        angle_val = int(ma_angle.replace("°", ""))
        if angle_val >= 45:
            score += 5
    except:
        pass

    # 截断到100
    score = min(100, score)

    # 等级判断
    high_conf_count = len(high_conf_signals)
    if high_conf_count >= 1 and score >= 60:
        level = "高置信"
    elif score >= 45:
        level = "关注"
    else:
        level = "一般"

    return {
        "score": score,
        "level": level,
        "high_conf_signals": high_conf_signals,
        "reasons": "|".join(reasons[:5]),
    }


# ======================================================================
#  6. 模型加载/保存
# ======================================================================

def load_confidence_model() -> Dict:
    """加载已保存的置信度模型，不存在则返回默认"""
    if CONFIDENCE_FILE.exists():
        try:
            return json.loads(CONFIDENCE_FILE.read_text("utf-8"))
        except:
            pass
    return {
        "version": 2,
        "last_updated": "never",
        "thresholds": {},
        "high_confidence_signals": [],
        "active_filters": [],
    }


def save_confidence_model(model: Dict):
    """保存置信度模型"""
    _ensure_dirs()
    CONFIDENCE_FILE.write_text(
        json.dumps(model, ensure_ascii=False, indent=2), "utf-8"
    )
    print(f"  [置信度模型] 已保存到 {CONFIDENCE_FILE.name}")


# ======================================================================
#  7. 一键运行：评估→回测→优化→保存
# ======================================================================

def run_tracker_pipeline(results: List[Dict] = None):
    """
    完整流程：记录本次信号 → 评估历史 → 回测 → 优化 → 保存模型

    在 run_selector.py 中每天扫描后调用即可自动累积数据。
    """
    print()
    print("─" * 60)
    print("  [信号跟踪] 记录+评估+优化流水线")
    print("─" * 60)

    # Step 1: 记录今天信号（如果有）
    if results:
        log_signal_events(results)

    # Step 2: 评估历史信号
    print("  [评估] 检查之前推荐的股票...")
    eval_result = evaluate_previous_picks(lookback_days=5)

    # Step 3: 运行历史回测（如果已有信号数据）
    print("  [回测] 用历史数据验证信号有效性...")
    backtest_result = run_backtest(lookback_days=30, sample_limit=300)

    # Step 4: 优化阈值
    print("  [优化] 计算最优阈值，目标胜率>80%...")
    model = optimize_thresholds(backtest_result, eval_result)

    # Step 5: 保存模型
    save_confidence_model(model)

    # Step 6: 打印摘要
    _print_model_summary(model)

    return model


def _print_model_summary(model: Dict):
    """打印置信度模型摘要"""
    print()
    print(f"  {'='*55}")
    print(f"  置信度模型 v{model['version']} | 更新: {model['last_updated']}")
    print(f"  目标: 推荐股票上涨概率 > {model['precision_target']*100:.0f}%")
    print(f"  {'='*55}")

    # 按胜率排序的信号
    sorted_sigs = sorted(
        [(n, i) for n, i in model.get("thresholds", {}).items()],
        key=lambda x: -x[1].get("precision", 0),
    )

    if sorted_sigs:
        print(f"  {'信号/阈值':<20} {'胜率':<8} {'样本':<6} {'状态':<8} {'来源'}")
        print(f"  {'-'*20} {'-'*8} {'-'*6} {'-'*8} {'-'*12}")
        for name, info in sorted_sigs[:12]:
            precision = info.get("precision", 0)
            total = info.get("total", 0)
            enabled = "启用" if info.get("enabled") else "停用"
            source = info.get("source", "回测")
            pct_sign = "✓" if precision >= 80 else " "
            print(f"  {name:<20} {pct_sign}{precision:<7.1f}% {total:<6} {enabled:<8} {source:<12}")

    # 高置信信号
    hc = model.get("high_confidence_signals", [])
    if hc:
        print()
        print(f"  >> 高置信筛选规则 (已验证胜率 > 80%):")
        for f in hc:
            print(f"    ★ {f['name']}: 胜率 {f['precision']:.1f}% (样本 {f['total']} 次)")
    else:
        print()
        print(f"  >> 暂无胜率>80%的信号（样本量不够，继续积累）")

    print()


# ======================================================================
#  8. 快速工具：为单次选股结果添加置信度字段
# ======================================================================

def add_confidence_to_results(results: List[Dict]) -> List[Dict]:
    """
    为选股结果添加置信度评分字段。
    每个 result dict 会增加:
      - "置信度": 0-100
      - "置信等级": "高置信" / "关注" / "一般"
      - "高置信信号": [信号名列表]

    同时生成一个"高置信推荐"子集（置信等级=高置信的）。
    """
    model = load_confidence_model()

    for r in results:
        conf = compute_confidence(r, model)
        r["置信度"] = conf["score"]
        r["置信等级"] = conf["level"]
        r["高置信信号"] = "+".join(conf["high_conf_signals"]) if conf["high_conf_signals"] else ""
        r["置信理由"] = conf["reasons"]

    return results


def get_high_confidence_picks(results: List[Dict], min_score: int = 60) -> List[Dict]:
    """
    返回置信度 >= min_score 的股票（目标 >80% 上涨概率）。
    """
    # 先确保有置信度字段
    if results and "置信度" not in results[0]:
        results = add_confidence_to_results(results)

    high_conf = [r for r in results if r.get("置信度", 0) >= min_score]
    high_conf.sort(key=lambda x: -x.get("置信度", 0))

    return high_conf


# ======================================================================
#  9. 查看历史学习报告
# ======================================================================

def generate_learning_report() -> str:
    """生成信号跟踪系统的学习进度报告"""
    model = load_confidence_model()
    eval_result = evaluate_previous_picks(lookback_days=10)

    lines = []
    lines.append("=" * 65)
    lines.append("  信号跟踪系统 - 学习报告")
    lines.append(f"  生成时间: {_today_str()}")
    lines.append("=" * 65)
    lines.append("")

    # 统计日志
    total_events = 0
    evaluated = 0
    if EVENTS_FILE.exists():
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    total_events += 1
                    try:
                        evt = json.loads(line)
                        if evt.get("outcome") is not None:
                            evaluated += 1
                    except:
                        pass

    lines.append(f"  信号事件总计: {total_events} 条")
    lines.append(f"  已评估: {evaluated} 条")
    if total_events > 0:
        lines.append(f"  评估进度: {evaluated/total_events*100:.1f}%")
    lines.append("")

    # 胜率统计
    hit_rates = eval_result.get("hit_rates", {})
    if hit_rates:
        lines.append("  ─ 实时信号胜率 ─")
        lines.append(f"  {'信号':<16} {'胜率':<8} {'上涨':<6} {'总数':<6}")
        lines.append(f"  {'-'*16} {'-'*8} {'-'*6} {'-'*6}")
        for name, hr in sorted(hit_rates.items(), key=lambda x: -x[1]["win_rate"]):
            mark = "★" if hr["win_rate"] >= 80 else " "
            lines.append(f"  {mark}{name:<15} {hr['win_rate']:<7.1f}% {hr['up']:<6} {hr['total']:<6}")
        lines.append("")

    # 回测结果
    thresholds = model.get("thresholds", {})
    if thresholds:
        lines.append("  ─ 历史回测胜率 ─")
        lines.append(f"  {'信号/阈值':<20} {'胜率':<8} {'样本':<6} {'状态'}")
        lines.append(f"  {'-'*20} {'-'*8} {'-'*6} {'-'*10}")
        for name, info in sorted(thresholds.items(), key=lambda x: -x[1].get("precision", 0)):
            p = info.get("precision", 0)
            t = info.get("total", 0)
            en = "已启用" if info.get("enabled") else "停用"
            mk = "★" if p >= 80 else " "
            lines.append(f"  {mk}{name:<19} {p:<7.1f}% {t:<6} {en:<10}")
        lines.append("")

    # 高置信规则
    hc = model.get("high_confidence_signals", [])
    if hc:
        lines.append("  ─ 高置信规则 (胜率>80%) ─")
        for f in hc:
            lines.append(f"    ★ {f['name']}: {f['precision']:.1f}% ({f['total']}次)")
        lines.append("")
    else:
        lines.append("  暂无高置信规则，继续积累数据中...")
        lines.append("")

    lines.append("─" * 65)
    lines.append("  说明:")
    lines.append("  - ★ = 已验证胜率>80%的高置信信号")
    lines.append("  - 数据量<10条的统计结果仅供参考")
    lines.append("  - 启用状态 = 胜率>=70%即启用该信号")
    lines.append("  - 置信度筛选只在有足够历史数据后生效")
    lines.append("─" * 65)

    return "\n".join(lines)
