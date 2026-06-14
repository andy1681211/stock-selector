#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
复盘分析模块 v1.0
================
基于 Sequential-thinking 思路的结构化复盘分析。
每日收盘后自动从大盘→板块→个股→信号 四个维度复盘。

步骤:
  1. 大盘分析：上证/深证/创业板趋势、量能、市场状态
  2. 板块轮动：当日最强/最弱板块，持续性判断
  3. 个股回顾：选股结果中的重点股走势分析
  4. 信号评估：过去选股信号的命中/miss分析
  5. 次日策略：根据市场状态给出次日操作建议
"""

import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"

# ===== 步骤1: 大盘分析 =====

def step1_market_analysis() -> Dict:
    """
    分析大盘状态：趋势、量能、技术指标。

    Returns:
        {
            "status": "趋势市/震荡市/弱势市/急跌市",
            "score": 0-10,
            "summary": "综合分析",
            "details": {...}
        }
    """
    result = {"status": "未知", "score": 5, "summary": "", "details": {}}

    try:
        # 获取上证指数数据
        from local_screener import parse_day_file, TDX_ROOT
        idx_path = os.path.join(TDX_ROOT, "sh", "lday", "sh000001.day")
        klines = parse_day_file(idx_path, 250)
        if not klines or len(klines) < 60:
            # 降级
            from web_data_fallback import get_market_index
            klines = get_market_index(250)

        if not klines or len(klines) < 60:
            return result

        from market_regime import detect_market_regime
        regime = detect_market_regime(klines)
        result["status"] = regime.get("regime", "未知")
        result["score"] = regime.get("score", 5)
        result["summary"] = regime.get("suggestion", "")
        result["details"] = {
            "大盘评分": regime.get("score", 0),
            "建议": regime.get("suggestion", ""),
            "策略权重": regime.get("weights", {}),
        }

        # 补充技术指标
        closes = [k.close for k in klines]
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else 0
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else 0
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else 0

        latest = klines[-1]
        result["details"]["最新收盘"] = f"{latest.close:.2f}"
        result["details"]["涨跌幅"] = f"{latest.pct_chg:+.2f}%"
        result["details"]["MA5"] = f"{ma5:.2f}"
        result["details"]["MA20"] = f"{ma20:.2f}"
        result["details"]["MA60"] = f"{ma60:.2f}"
        result["details"]["均线关系"] = "多头" if ma5 > ma20 > ma60 else ("空头" if ma5 < ma20 < ma60 else "震荡")

        # 量能分析
        avg_vol = sum(k.volume for k in klines[-20:]) / 20 if len(klines) >= 20 else 0
        curr_vol = latest.volume
        vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1
        result["details"]["量比(20日均量)"] = f"{vol_ratio:.2f}"
        result["details"]["量能状态"] = "放量" if vol_ratio > 1.2 else ("缩量" if vol_ratio < 0.8 else "正常")

    except Exception as e:
        result["summary"] = f"大盘分析异常: {e}"

    return result


# ===== 步骤2: 板块轮动 =====

def step2_sector_rotation() -> Dict:
    """
    分析当日板块轮动。

    Returns:
        {"top_sectors": [...], "weak_sectors": [...], "summary": ""}
    """
    result = {"top_sectors": [], "weak_sectors": [], "hot_sectors": [], "summary": ""}

    try:
        # 从本地或API获取板块数据
        sectors = []
        try:
            from hot_sectors_local import get_all_sector_performance
            sectors = get_all_sector_performance()
        except Exception:
            pass

        if not sectors:
            try:
                from sector_rotation import get_sector_rankings
                sectors = get_sector_rankings()
            except Exception:
                pass

        if sectors:
            sectors.sort(key=lambda x: -abs(x.get("涨幅", 0)))
            result["top_sectors"] = [s for s in sectors[:5] if s.get("涨幅", 0) > 0]
            result["weak_sectors"] = [s for s in sectors[-3:] if s.get("涨幅", 0) < 0]
            result["hot_sectors"] = [s for s in sectors[:8] if abs(s.get("涨幅", 0)) > 1]

        if result["top_sectors"]:
            top_names = [s.get("名称", "") for s in result["top_sectors"]]
            result["summary"] = f"强势板块: {' '.join(top_names[:3])}"

    except Exception as e:
        result["summary"] = f"板块分析跳过: {e}"

    return result


# ===== 步骤3: 个股分析 =====

def step3_stock_review(report_path: str = None) -> Dict:
    """
    回顾选股结果中的重点股。

    Args:
        report_path: 前一次选股报告路径

    Returns:
        {"yesterday_picks": [...], "signals": [...], "summary": ""}
    """
    result = {"yesterday_picks": [], "signals": [], "summary": ""}

    try:
        # 查找最近一次选股报告
        if not report_path:
            reports = sorted(OUTPUT_DIR.glob("本地选股报告_*.txt"))
            if not reports:
                return result
            report_path = str(reports[-1])

        # 从报告中解析选股结果
        content = Path(report_path).read_text(encoding="utf-8")
        lines = content.split("\n")

        # 提取高置信推荐
        picks = []
        in_section = False
        for line in lines:
            if "高置信推荐" in line:
                in_section = True
                continue
            if in_section and (line.startswith("【") or line.startswith("=")):
                in_section = False
                continue
            if in_section and line.strip() and not line.startswith("  -") and not line.startswith("  标记"):
                # 格式: [★+...] 600593 大连圣亚 4.55  ...
                parts = line.split()
                for i, p in enumerate(parts):
                    if len(p) == 6 and p.isdigit():
                        code = p
                        name = parts[i + 1] if i + 1 < len(parts) else ""
                        chg = parts[i + 2] if i + 2 < len(parts) else ""
                        picks.append({"代码": code, "名称": name, "涨幅": chg})
                        break

        result["yesterday_picks"] = picks[:10]
        result["summary"] = f"前次选股 {len(picks)} 只"

    except Exception as e:
        result["summary"] = f"个股分析跳过: {e}"

    return result


# ===== 步骤4: 信号评估 =====

def step4_signal_evaluation() -> Dict:
    """
    评估历史选股信号表现。

    Returns:
        {"stats": {...}, "summary": ""}
    """
    result = {"stats": {}, "summary": ""}

    try:
        from local_screener import load_tracker as load_tracker_fn

        tracker = load_tracker_fn()
        if not tracker:
            return result

        # 统计概览
        total = len(tracker)
        active = sum(1 for s in tracker.values() if s.get("status") != "考虑删除")
        to_del = sum(1 for s in tracker.values() if s.get("status") == "考虑删除")

        # 平均表现
        profits = []
        for s in tracker.values():
            p = s.get("total_pnl", 0)
            if isinstance(p, (int, float)):
                profits.append(p)

        avg_profit = sum(profits) / len(profits) if profits else 0
        positive = sum(1 for p in profits if p > 0)
        negative = sum(1 for p in profits if p < 0)

        result["stats"] = {
            "跟踪总数": total,
            "活跃": active,
            "建议删除": to_del,
            "盈利数": positive,
            "亏损数": negative,
            "平均收益": f"{avg_profit:+.2f}%",
            "胜率": f"{positive / len(profits) * 100:.1f}%" if profits else "N/A",
        }
        result["summary"] = f"跟踪池 {total}只 胜率{result['stats'].get('胜率', 'N/A')}"

    except Exception as e:
        result["summary"] = f"信号评估跳过: {e}"

    return result


# ===== 步骤5: 次日策略 =====

def step5_nextday_strategy(market: Dict, sectors: Dict, signals: Dict) -> Dict:
    """
    综合以上分析，给出次日策略建议。

    Returns:
        {"strategy": "", "focus": [], "risk": "", "summary": ""}
    """
    regime = market.get("status", "未知")
    score = market.get("score", 5)

    strategy_map = {
        "趋势市": "顺势而为，持股为主，回调低吸加仓",
        "震荡市": "高抛低吸，不追涨，回调企稳低吸",
        "弱势市": "降低仓位，多看少动，仅做超跌反弹",
        "急跌市": "空仓观望，等待企稳信号",
    }

    strategy = strategy_map.get(regime, "谨慎操作")
    risk_level = "高" if score < 4 else ("中" if score < 7 else "低")

    # 关注板块
    focus = []
    if sectors.get("hot_sectors"):
        for s in sectors["hot_sectors"][:3]:
            focus.append(s.get("名称", ""))

    return {
        "strategy": strategy,
        "focus_sectors": focus,
        "risk_level": risk_level,
        "summary": f"{regime} | 风险:{risk_level} | 策略:{strategy[:20]}...",
    }


# ===== 生成完整复盘报告 =====

def generate_review(report_path: str = None) -> str:
    """
    生成完整复盘分析报告（5步法）。
    报告内容会自动推送到微信和Memos。
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d %H:%M")

    print(f"\n{'='*60}")
    print(f"  复盘分析 - {now.strftime('%Y-%m-%d')}")
    print(f"{'='*60}")

    # 步骤1: 大盘分析
    print(f"\n  [步骤1/5] 大盘分析...")
    market = step1_market_analysis()
    print(f"  状态: {market['status']} (评分:{market['score']}/10)")
    print(f"  建议: {market['summary']}")

    # 步骤2: 板块轮动
    print(f"\n  [步骤2/5] 板块轮动...")
    sectors = step2_sector_rotation()
    if sectors["top_sectors"]:
        print(f"  强势: {' '.join(s['名称'] for s in sectors['top_sectors'][:3])}")
    if sectors["weak_sectors"]:
        print(f"  弱势: {' '.join(s['名称'] for s in sectors['weak_sectors'][:3])}")

    # 步骤3: 个股回顾
    print(f"\n  [步骤3/5] 个股回顾...")
    stocks = step3_stock_review(report_path)
    print(f"  {stocks['summary']}")

    # 步骤4: 信号评估
    print(f"\n  [步骤4/5] 信号评估...")
    sig_eval = step4_signal_evaluation()
    print(f"  {sig_eval['summary']}")

    # 步骤5: 次日策略
    print(f"\n  [步骤5/5] 次日策略...")
    strategy = step5_nextday_strategy(market, sectors, sig_eval)
    print(f"  策略: {strategy['strategy']}")
    print(f"  风险: {strategy['risk_level']}")
    if strategy['focus_sectors']:
        print(f"  关注: {' '.join(strategy['focus_sectors'])}")

    # 构建报告
    lines = []
    lines.append("=" * 60)
    lines.append(f"  复盘分析报告 - {now.strftime('%Y-%m-%d')}")
    lines.append(f"  生成时间: {date_str}")
    lines.append("=" * 60)
    lines.append("")

    # 步骤1
    lines.append("【步骤1/5】大盘分析")
    lines.append(f"  市场状态: {market['status']} (评分:{market['score']}/10)")
    if market["details"]:
        for k, v in market["details"].items():
            lines.append(f"  {k}: {v}")
    lines.append(f"  建议: {market['summary']}")
    lines.append("")

    # 步骤2
    lines.append("【步骤2/5】板块轮动")
    if sectors["top_sectors"]:
        lines.append("  强势板块:")
        for s in sectors["top_sectors"][:5]:
            lines.append(f"    {s.get('名称','')} {s.get('涨幅',0):+.2f}%")
    if sectors["weak_sectors"]:
        lines.append("  弱势板块:")
        for s in sectors["weak_sectors"][:3]:
            lines.append(f"    {s.get('名称','')} {s.get('涨幅',0):+.2f}%")
    if sectors["hot_sectors"]:
        lines.append(f"  热点: {' '.join(s.get('名称','') for s in sectors['hot_sectors'][:5])}")
    lines.append("")

    # 步骤3
    lines.append("【步骤3/5】个股回顾 - 前次选股表现")
    if stocks["yesterday_picks"]:
        lines.append(f"  {'代码':<8} {'名称':<10} {'涨幅':<8}")
        lines.append(f"  {'-'*8} {'-'*10} {'-'*8}")
        for s in stocks["yesterday_picks"]:
            lines.append(f"  {s.get('代码',''):<8} {s.get('名称',''):<10} {s.get('涨幅',''):<8}")
    lines.append("")

    # 步骤4
    lines.append("【步骤4/5】信号评估 - 跟踪池表现")
    for k, v in sig_eval["stats"].items():
        lines.append(f"  {k}: {v}")
    lines.append("")

    # 步骤5
    lines.append("【步骤5/5】次日策略")
    lines.append(f"  市场状态: {market['status']}")
    lines.append(f"  风险等级: {strategy['risk_level']}")
    lines.append(f"  操作策略: {strategy['strategy']}")
    if strategy['focus_sectors']:
        lines.append(f"  关注板块: {' '.join(strategy['focus_sectors'])}")
    lines.append("")
    lines.append("-" * 60)
    lines.append("  风险提示: 以上分析基于历史数据，不构成投资建议")
    lines.append("=" * 60)

    report = "\n".join(lines)

    # 保存报告
    ts = now.strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"复盘分析_{ts}.txt"
    out_path.write_text(report, encoding="utf-8")
    print(f"\n  [OK] 复盘报告已保存: {out_path}")

    # 推送到Memos
    try:
        from memos_logger import is_configured, create_memo
        if is_configured():
            memo_content = f"""# 复盘分析 {now.strftime('%Y-%m-%d')}

**市场**: {market['status']} (评分:{market['score']}/10)
**策略**: {strategy['strategy']}
**风险**: {strategy['risk_level']}

**板块**: {' '.join(s.get('名称','') for s in sectors.get('top_sectors',[])[:3]) or 'N/A'}

**跟踪池**: {sig_eval['stats'].get('跟踪总数', 0)}只 | 胜率{sig_eval['stats'].get('胜率', 'N/A')}

**关注**: {' '.join(strategy.get('focus_sectors',[])) or 'N/A'}

#复盘分析 #{now.strftime('%Y%m%d')}
"""
            create_memo(memo_content)
            print(f"  [Memos] 复盘日志已写入")
    except Exception as e:
        print(f"  [Memos] 跳过: {e}")

    return report


def show_latest():
    """显示最近一次复盘报告"""
    reports = sorted(OUTPUT_DIR.glob("复盘分析_*.txt"))
    if reports:
        print(reports[-1].read_text(encoding="utf-8"))
    else:
        print("暂无复盘报告，先运行 python review_analysis.py")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="复盘分析工具 - 5步结构化复盘")
    ap.add_argument("--report", help="前次选股报告路径（可选）")
    ap.add_argument("--show", action="store_true", help="显示最近复盘报告")
    args = ap.parse_args()

    if args.show:
        show_latest()
    else:
        generate_review(args.report)
