#!/usr/bin/env python3
"""
2026年A股短线选股策略系统
===========================
数据源: 通达信本地日K线 (D:\new_tdx\vipdoc)
策略: 5大短线共振策略 + 涨停捕捉系统

用法:
  python run_selector.py                     # 本地扫盘（稳健低吸 + 缠论买点）
  python run_selector.py --mode limit-up     # 涨停捕捉模式（热点优先）
  python run_selector.py --mode combined     # 综合模式（同时运行两套系统）
  python run_selector.py --mode limit-up --monitor  # 盘中实时监控
  python run_selector.py --api               # 在线API选股（补充）
  python run_selector.py --summary           # 显示最近报告
  python run_selector.py --learn             # 信号跟踪+置信度优化
  python run_selector.py --report-learn      # 查看学习报告
"""

import sys
from pathlib import Path

TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"

if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

# ----- 通达信板块 -----
TDX_BLOCK_FILE = "D:/new_tdx/T0002/blocknew/CLAUDEXG.blk"

# 市场前缀: sh->1, sz->0, bj->4
MARKET_PREFIX = {
    "sh": "1",
    "sz": "0",
    "bj": "4",
}


def write_tdx_block(stocks: list):
    """将选股结果写入通达信自定义板块（覆盖写入，首行空行）"""
    if not stocks:
        return

    lines = [""]  # 首行空行（通达信格式要求）
    for s in stocks:
        code = s.get("代码", "")
        # 判断市场
        if code.startswith(("6", "9", "5")):
            prefix = "1"  # 上海
        elif code.startswith(("0", "3", "2")):
            prefix = "0"  # 深圳
        elif code.startswith(("4", "8")):
            prefix = "4"  # 北京
        else:
            continue
        lines.append(f"{prefix}{code}")

    # 写文件（二进制模式，CRLF换行，GBK编码）
    raw_text = '\r\n'.join(lines)
    with open(TDX_BLOCK_FILE, "wb") as f:
        f.write(raw_text.encode('gbk'))

    print(f"\n  [通达信] {len(lines)-1}只股票已写入板块 CLAUDEXG.blk（首行空行格式）")
    print(f"    打开通达信 -> Ctrl+F2 -> 自定义板块 -> CLAUDEXG 即可查看")


def show_latest_report():
    """显示最近一次选股报告"""
    reports = sorted(OUTPUT_DIR.glob("本地选股报告_*.txt"))
    if not reports:
        reports = sorted(OUTPUT_DIR.glob("选股报告_*.txt"))
    if not reports:
        reports = sorted(OUTPUT_DIR.glob("综合选股报告_*.txt"))
    if not reports:
        reports = sorted(OUTPUT_DIR.glob("涨停捕捉报告_*.txt"))
    if not reports:
        print("暂无选股报告，先运行 `python run_selector.py`")
        return
    latest = reports[-1]
    print(latest.read_text(encoding="utf-8"))


def _save_api_report(path: Path, results, combined):
    """生成API选股报告（兼容旧格式）"""
    from config import COMBINED
    lines = [
        "=" * 60,
        "  2026年 A股 短线选股策略系统 - 在线选股报告",
        f"  生成时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 60,
        "",
        "【策略执行摘要】",
    ]
    for r in results:
        if r.error:
            lines.append(f"  [失败] {r.name}: {r.error}")
        else:
            lines.append(f"  [OK] {r.name}: 选到 {r.count} 只")

    min_s = COMBINED["min_strategies"]
    top_n = COMBINED["top_n"]
    filtered = [s for s in combined if s["策略命中数"] >= min_s]
    lines.append(f"\n【综合推荐 (共振>={min_s}) Top{top_n}】")
    if filtered:
        shown = 0
        for s in filtered:
            if shown >= top_n: break
            lines.append(f"  {s.get('代码',''):<8} {s.get('名称',''):<10} 涨幅:{s.get('涨跌幅','')}%")
            shown += 1

    lines.extend(["", "=" * 60, "【风险提示】", "  ⚠️ 本系统基于历史数据和量化模型筛选，不构成投资建议。", "=" * 60])
    path.write_text("\n".join(lines), encoding="utf-8")


def _run_local_mode():
    """运行本地扫盘模式（稳健低吸 + 缠论买点）"""
    import time
    from datetime import datetime

    print("[模式] 通达信本地数据扫盘（稳健低吸 + 缠论买点）")
    print(f"  策略: 缠论精选 | 放量首板 | 连板接力 | 趋势加速 | N字反包 | 多维精选")
    print()

    from local_screener import run_local_screen, get_daily_report

    t0 = time.time()
    results = run_local_screen()

    elapsed = time.time() - t0
    print(f"\n[OK] 完成! 耗时 {elapsed:.1f}秒, 选到 {len(results)} 只")
    print()

    # ===== 市场状态识别（基于上证指数）=====
    regime_info = None
    try:
        from local_screener import parse_day_file, TDX_ROOT
        from market_regime import detect_market_regime, get_strategy_weights
        import os
        idx_path = os.path.join(TDX_ROOT, "sh", "lday", "sh000001.day")
        idx_klines = parse_day_file(idx_path, 500)
        if len(idx_klines) >= 60:
            regime_info = detect_market_regime(idx_klines)
            print(f"  [市场] {regime_info['regime']} 评分:{regime_info['score']} 建议:{regime_info['suggestion']}")
    except Exception as e:
        print(f"  [市场] 状态识别跳过: {e}")

    # 高亮推荐
    sorted_results = sorted(results, key=lambda x: -x["策略命中"])
    resonance = [r for r in sorted_results if r["策略命中"] >= 2]
    top5 = [r for r in sorted_results if r["策略命中"] >= 3]

    # 策略标记函数
    def _tag(r):
        tags = []
        lc = r.get("低吸买点", "")
        if lc:
            tags.append("低吸")
        chan = r.get("缠论买点", "")
        if chan:
            short = chan.replace(" + ","+").replace("二买","2买").replace("三买","3买").replace("一买","1买")
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
        # 新增高级信号
        if r.get("平步青云强") == "是":
            tags.append("青云")
        elif r.get("平步青云", "") and int(r.get("平步青云", "0").replace("分","")) >= 50:
            tags.append("青云")
        if r.get("底分型", ""):
            tags.append("底分")
        if r.get("洗盘结束", ""):
            tags.append("洗毕")
        if r.get("回踩买点", ""):
            tags.append("回踩")
        if r.get("倍量突破", ""):
            tags.append("倍量")
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
        if r.get("筹码评分", 0) >= 70:
            tags.append("筹码优")
        elif r.get("筹码评分", 0) >= 50:
            tags.append("筹码好")
        # 置信度标记
        conf_level = r.get("置信等级", "")
        if conf_level == "高置信":
            tags.insert(0, "★")  # 高置信在最前面
        return "[" + "+".join(tags[:5]) + "]" if tags else "[其他]"

    print("-" * 65)
    if top5:
        print(f"  >> 强烈关注 (共振>=3个策略):")
        print(f"  {'标记':<14} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'量比':<6} {'共振':<4} {'青云'}")
        print(f"  {'-'*14} {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*4} {'-'*6}")
        for r in top5[:8]:
            chg = r['涨跌幅']
            pbq = r.get("平步青云", "") or ""
            print(f"  {_tag(r):<14} {r['代码']:<8} {r['名称']:<10} {chg:>6.2f}% {r['量比']:<6} {r['策略命中']:<3}个 {pbq:<6}")
    if resonance:
        print(f"\n  >> 关注列表 (共振>=2个策略): {len(resonance)}只")
    else:
        print(f"\n  >> 各策略独立股票: {len(sorted_results)}只")
    print("-" * 65)

    # ===== 持续跟踪池 =====
    from local_screener import load_tracker, merge_into_tracker, get_tracking_report
    tracker = load_tracker()
    merge_into_tracker(tracker, results)
    tracking_report = get_tracking_report(tracker)
    to_del_count = sum(1 for e in tracker.values() if e.get("status") == "考虑删除")
    print(f"\n  [跟踪] 池中共 {len(tracker)} 只（历史累计）", end="")
    if to_del_count:
        print(f"  ⚠️ {to_del_count} 只建议删除", end="")
    print()

    # ===== 止盈止损规则引擎 =====
    try:
        from stop_engine import enhance_tracker_with_stops, get_stop_report
        tracker = enhance_tracker_with_stops(tracker, results)
        stop_report = get_stop_report(tracker)
        tracking_report += stop_report
        stop_alerts = [s for s in tracker.values() if s.get("stop_engine", {}).get("建议", "").startswith("🛑")]
        if stop_alerts:
            print(f"  [止损预警] {len(stop_alerts)}只!")
            for s in stop_alerts[:5]:
                e = s["stop_engine"]
                print(f"    [止损] {s['name']}({s['code']}) {e['当前利润']:+.1f}% 止损{e['止损价']}")
    except Exception as e:
        print(f"  [止盈止损] 跳过: {e}")

    # ===== 高级信号高亮 =====
    qy_stocks = [r for r in sorted_results if r.get("平步青云强") == "是"]
    ws_stocks = [r for r in sorted_results if r.get("洗盘结束", "")]
    bv_stocks = [r for r in sorted_results if r.get("倍量突破", "")]
    gh_stocks = [r for r in sorted_results if r.get("建仓型涨停", "") or r.get("洗盘型涨停", "") or r.get("二进三信号", "")]
    if gh_stocks:
        zt_jc = sum(1 for r in results if r.get('建仓型涨停',''))
        zt_xp = sum(1 for r in results if r.get('洗盘型涨停',''))
        zt_ej = sum(1 for r in results if r.get('二进三信号',''))
        print(f"\n  [股海炼金术] 建仓型涨停:{zt_jc}只 洗盘型涨停:{zt_xp}只 二进三:{zt_ej}只")
        for r in gh_stocks[:5]:
            zt_type = r.get("涨停类型", "")
            zt_count = r.get("涨停板数", 0)
            print(f"    ★{_tag(r):<14} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {zt_count}板 {zt_type}")
    # ===== 主升浪起爆信号 =====
    mw_stocks = [r for r in sorted_results if r.get("主升浪起爆", "")]
    if mw_stocks:
        print(f"\n  [主升浪起爆] 试盘→缩量整理→放量突破: {len(mw_stocks)}只")
        for r in mw_stocks[:5]:
            mw_desc = r.get("主升浪起爆", "")
            print(f"    ★{_tag(r):<14} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {mw_desc}")
    tl_stocks = [r for r in sorted_results if r.get("试盘线", "") and not r.get("主升浪起爆", "")]
    if tl_stocks:
        print(f"\n  [试盘线信号] 放量上影线测试抛压(起爆待确认): {len(tl_stocks)}只")
        for r in tl_stocks[:5]:
            tl_desc = r.get("试盘线", "")
            print(f"    {_tag(r):<14} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {tl_desc}")

    # ===== 飞龙在天 =====
    fl_stocks = [r for r in sorted_results if r.get("飞龙在天", "")]
    if fl_stocks:
        print(f"\n  [飞龙在天] 三连板→断板洗盘→反包确认(龙头主升浪): {len(fl_stocks)}只")
        for r in fl_stocks[:5]:
            zt_cnt = r.get("飞龙连板数", 0)
            entry = r.get("飞龙介入价", 0)
            stop = r.get("飞龙止损价", 0)
            desc = r.get("飞龙在天", "")
            print(f"    ★{_tag(r):<14} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {zt_cnt}连板 介入{entry:.2f} 止损{stop:.2f} {desc}")

    # ===== 潜龙回首 =====
    ql_stocks = [r for r in sorted_results if r.get("潜龙回首", "")]
    if ql_stocks:
        print(f"\n  [潜龙回首] 前期大涨→回调2-8天→企稳(龙回头): {len(ql_stocks)}只")
        for r in ql_stocks[:5]:
            desc = r.get("潜龙回首", "")
            print(f"    {_tag(r):<14} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {desc}")

    if qy_stocks or ws_stocks or bv_stocks:
        print(f"\n  [高级信号] 平步青云★:{len(qy_stocks)}只 洗盘结束:{len(ws_stocks)}只 倍量突破:{len(bv_stocks)}只")
        for r in qy_stocks[:5]:
            pbq = r.get("平步青云详情", "")[:50]
            print(f"    ★{_tag(r):<14} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {pbq}")

    # ===== 新增：置信度评分 + 高置信推荐 =====
    from signal_tracker import add_confidence_to_results, get_high_confidence_picks
    results = add_confidence_to_results(results)
    sorted_results = sorted(results, key=lambda x: -x.get("置信度", 0))
    high_conf = get_high_confidence_picks(results, min_score=60)
    if high_conf:
        print()
        print(f"  >> ★ 高置信推荐 (上涨概率 > 80% 目标): {len(high_conf)} 只")
        print(f"  {'标记':<14} {'代码':<8} {'名称':<10} {'涨幅%':<8} {'量比':<6} {'置信':<6} {'理由'}")
        print(f"  {'-'*14} {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*6} {'-'*20}")
        for r in high_conf[:8]:
            conf = r.get("置信度", 0)
            reason = r.get("置信理由", "")
            print(f"  {_tag(r):<14} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<8} {r['量比']:<6} {conf:<5}分 {reason:<20}")
        print()

    report = get_daily_report(results, regime_info)
    report += tracking_report

    # ===== 龙虎榜游资追踪 =====
    try:
        from lhb_tracker import add_lhb_to_report, check_my_stocks
        codes = [r.get("代码", "") for r in results if r.get("代码", "")]
        lhb_hits = check_my_stocks(codes)
        if lhb_hits:
            print(f"  [龙虎榜] 自选股上榜 {len(lhb_hits)}只!")
            for h in lhb_hits:
                print(f"    {h['代码']} {h['名称']} {h['涨跌幅']:+.2f}% {h['游资']} {h['信号']}")
            print()
        report = add_lhb_to_report(report)
    except Exception as e:
        print(f"  [龙虎榜] 跳过: {e}")

    # ===== 北向资金追踪 =====
    try:
        from north_flow import add_north_to_report
        report = add_north_to_report(report)
    except Exception as e:
        print(f"  [北向] 跳过: {e}")

    # ===== 板块轮动分析 =====
    try:
        from sector_rotation import add_sector_to_report
        report = add_sector_to_report(report)
    except Exception as e:
        print(f"  [板块] 跳过: {e}")

    # ===== 走势可视化 =====
    try:
        from charts import generate_market_chart
        # 读取大盘数据画图
        import os as _os
        from local_screener import parse_day_file
        idx_path = _os.path.join(TDX_ROOT, "sh", "lday", "sh000001.day")
        idx_klines = parse_day_file(idx_path, 250)
        if len(idx_klines) >= 20:
            chart = generate_market_chart(idx_klines)
            report += "\n" + chart + "\n"
    except Exception as e:
        print(f"  [图表] 跳过: {e}")

    # ===== Ollama AI 智能分析（如可用）=====
    try:
        from ollama_analyzer import enhance_report_with_ai
        report = enhance_report_with_ai(report, results, regime_info)
    except Exception as e:
        print(f"  [Ollama] AI分析跳过: {e}")

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = OUTPUT_DIR / f"本地选股报告_{ts}.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n[OK] 报告已保存: {report_path}")

    # ===== 信号跟踪流水线（记录→评估→回测→优化）=====
    from signal_tracker import run_tracker_pipeline
    run_tracker_pipeline(results)

    # ===== 严格精选 + 写入通达信板块 =====
    from local_screener import screen_strict_top, write_stock_blocks
    print("  [精选] 技术面+基本面筛选...")
    top_results = screen_strict_top(results, top_n=10)
    print(f"  [精选] {len(top_results)} 只精选中")
    write_stock_blocks(top_results)
    print()

    # ===== 微信推送通知 =====
    try:
        from notifier import push_daily_report, is_configured
        if is_configured():
            lhb_msg = ""
            try:
                from lhb_tracker import scan_longhubang
                lhb_scanned = scan_longhubang(max_stocks=5)
                if lhb_scanned:
                    lhb_msg = "**龙虎榜游资**\n"
                    for s in lhb_scanned[:3]:
                        sig = s["信号"][0] if s["信号"] else ""
                        lhb_msg += f"- {s['名称']}({s['代码']}) {s['游资列表']} {sig}\n"
            except:
                pass
            push_daily_report(results, regime_info, lhb_msg)
        else:
            print("  [推送] 跳过（未配置密钥，不影响选股）")
    except Exception as e:
        print(f"  [推送] 跳过: {e}")

    # ===== Memos 交易日志 =====
    try:
        from memos_logger import is_configured as memos_configured, push_daily_summary, push_stock_card
        if memos_configured():
            push_daily_summary(results, regime_info, str(report_path))
            # 高置信个股单独推送
            high_conf = [r for r in results if r.get("置信度", 0) >= 60]
            for r in high_conf[:5]:
                push_stock_card(r)
            print(f"  [Memos] 交易日志已写入 ({len(high_conf)}只高置信个股)")
        else:
            print("  [Memos] 跳过（未配置 Memos Token）")
    except Exception as e:
        print(f"  [Memos] 跳过: {e}")

    # ===== 走势图截图 =====
    try:
        from chart_screenshot import screenshot_top_stocks
        top_for_screenshot = sorted_results[:5]  # 前5只
        chart_paths = screenshot_top_stocks(top_for_screenshot)
        if chart_paths:
            print(f"  [截图] {len(chart_paths)}张走势图已保存")
            # 将截图信息追加到报告
            from chart_screenshot import append_chart_report
            report = append_chart_report(report, chart_paths)
    except Exception as e:
        print(f"  [截图] 跳过: {e}")

    # 同时显示完整报告
    print("\n" + report)


def _run_limit_up_mode(monitor=False, interval=30):
    """运行涨停捕捉模式（热点优先 + 动量优先）"""
    if monitor:
        print("[模式] 盘中实时监控（涨停捕捉候选股）")
        from limit_up_catcher import monitor_limit_up_candidates
        monitor_limit_up_candidates(interval)
        return

    import time
    from datetime import datetime

    print("[模式] 涨停捕捉 v2.0（热点优先 + 动量优先）")
    print(f"  策略: 连板接力 | 首板捕捉 | 竞价异动 | 涨停潜力")
    print()

    from limit_up_catcher import main as limit_up_main
    limit_up_main()


def _run_combined_mode():
    """综合模式：同时运行两套系统，生成合并报告"""
    import time
    from datetime import datetime

    print("[模式] 综合选股（同时运行local_screener + limit_up_catcher）")
    print()

    # ---- 系统A: local_screener（稳健低吸 + 缠论）----
    print("─" * 50)
    print("  [系统A] 稳健低吸 + 缠论买点")
    print("─" * 50)
    t0 = time.time()
    from local_screener import run_local_screen, get_daily_report
    results_a = run_local_screen()
    elapsed_a = time.time() - t0
    print(f"\n  [OK] 系统A: {len(results_a)} 只 (耗时 {elapsed_a:.1f}s)")

    # ---- 系统B: limit_up_catcher（涨停捕捉 + 热点）----
    print()
    print("─" * 50)
    print("  [系统B] 涨停捕捉 + 热点板块")
    print("─" * 50)
    from limit_up_catcher import (run_limit_up_screen, set_hot_sectors,
                                  get_hot_sectors_from_api, generate_report,
                                  _HOT_SECTORS)
    t1 = time.time()
    sectors, stockmap = get_hot_sectors_from_api()
    if sectors:
        set_hot_sectors(sectors, stockmap)
        print(f"  [热点] {' | '.join(sectors[:7])}")
    else:
        print("  [热点] 无")
    results_b = run_limit_up_screen()
    elapsed_b = time.time() - t1
    print(f"\n  [OK] 系统B: {len(results_b)} 只 (耗时 {elapsed_b:.1f}s)")

    # ---- 生成综合报告 ----
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')

    # 交叉命中（两套系统都选中的 = 高置信度）
    codes_a = {r["代码"] for r in results_a if "代码" in r}
    codes_b = {r["代码"] for r in results_b if "代码" in r}
    overlap = codes_a & codes_b

    report_lines = [
        "=" * 70,
        "  综合选股报告",
        f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"  两套系统同时运行, 取交集 + 各自特色信号",
        "=" * 70,
        "",
    ]

    # 交集：最高置信度
    if overlap:
        report_lines.append("★ 星级推荐: 两套系统同时命中 ★")
        report_lines.append(f"  {'代码':<8} {'名称':<10} {'涨幅%':<8} {'系统A信号':<25} {'系统B信号':<20}")
        report_lines.append(f"  {'-'*8} {'-'*10} {'-'*8} {'-'*25} {'-'*20}")

        map_a = {r["代码"]: r for r in results_a}
        map_b = {r["代码"]: r for r in results_b}
        for code in sorted(overlap):
            ra = map_a.get(code, {})
            rb = map_b.get(code, {})
            name = ra.get("名称", "") or rb.get("名称", "")
            chg = ra.get("涨跌幅", 0) or rb.get("涨跌幅", 0)
            sig_a = ra.get("信号", "").replace(" + ", "|")[:25]
            sig_b = rb.get("信号", "").replace(" + ", "|")[:20]
            report_lines.append(f"  {code:<8} {name:<10} {chg:>+6.2f}% {sig_a:<25} {sig_b:<20}")
        report_lines.append("")
    else:
        report_lines.append("  [交集] 两套系统无重叠股票")
        report_lines.append("")

    report_lines.append("-" * 70)
    report_lines.append(f"  汇总: 系统A {len(results_a)}只 | 系统B {len(results_b)}只 | 交集 {len(overlap)}只")
    report_lines.append("")

    # 系统A详细
    report_lines.append("─" * 70)
    report_lines.append("【系统A】稳健低吸 + 缠论买点")
    report_lines.append("─" * 70)
    report_lines.append(get_daily_report(results_a, None))
    report_lines.append("")

    # 系统B详细
    report_lines.append("─" * 70)
    report_lines.append("【系统B】涨停捕捉 + 热点板块")
    report_lines.append("─" * 70)
    report_lines.append(generate_report(results_b))
    report_lines.append("")

    report = "\n".join(report_lines)
    report_path = OUTPUT_DIR / f"综合选股报告_{ts}.txt"
    report_path.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"\n[OK] 报告已保存: {report_path}")
    print(f"[OK] 交集 {len(overlap)}只 — 两套系统同时选中的高置信度信号")

    # ===== Memos 综合选股日志 =====
    try:
        from memos_logger import is_configured as memos_configured, create_memo
        if memos_configured():
            date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            content = f"""# 综合选股 {date_str}

**系统A**: {len(results_a)}只 | **系统B**: {len(results_b)}只 | **交集**: {len(overlap)}只

**热点**: {', '.join(sectors[:5]) if sectors else '无'}

{"**交集个股**" if overlap else ""}
{chr(10).join(f"- {c}" for c in list(overlap)[:10]) if overlap else ""}

#选股日记 #综合模式
"""
            create_memo(content)
            print("  [Memos] 综合选股日志已写入")
    except Exception as e:
        print(f"  [Memos] 跳过: {e}")

    # 写入通达信板块（交集优先 + 各系统前N只补全）
    combined_codes = list(overlap)
    for r in sorted(results_a + results_b,
                    key=lambda x: -x.get("评分", 0) if "评分" in x else -x.get("策略命中", 0)):
        if len(combined_codes) >= 30:
            break
        if r["代码"] not in combined_codes:
            combined_codes.append(r["代码"])
    write_tdx_block([{"代码": c} for c in combined_codes])


def _run_api_mode():
    """运行API选股模式"""
    import time
    from datetime import datetime

    print("[模式] 在线API选股（东方财富）")
    from strategies import run_all_strategies, combine_results, print_results, save_results
    from config import COMBINED

    t0 = time.time()
    results = run_all_strategies()
    combined = combine_results(results)
    print_results(results, combined)
    summary = save_results(results, combined)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = OUTPUT_DIR / f"选股报告_{ts}.txt"
    _save_api_report(report_path, results, combined)
    for line in summary:
        print(f"  {line}")
    print(f"  [报告] {report_path.name}")


def _try_enable_fallback():
    """尝试启用网页数据降级（通达信读不到时自动切到网页）"""
    try:
        from web_data_fallback import patch_tdx_reader
        patch_tdx_reader()
        return True
    except Exception:
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="2026年A股短线选股策略系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python run_selector.py                     # 默认: 本地扫盘（稳健低吸 + 缠论买点）
  python run_selector.py --mode limit-up     # 涨停捕捉模式（热点优先 + 动量优先）
  python run_selector.py --mode combined     # 综合模式（同时运行两套系统）
  python run_selector.py --mode limit-up --monitor  # 盘中实时监控
  python run_selector.py --api               # 在线API选股（补充，需联网）
  python run_selector.py --summary           # 查看最近报告
  python run_selector.py --learn             # 信号跟踪+置信度优化
  python run_selector.py --report-learn      # 查看学习报告""",
    )
    parser.add_argument("--summary", action="store_true", help="显示最近报告")
    parser.add_argument("--api", action="store_true", help="使用API选股（在线补充）")
    parser.add_argument("--learn", action="store_true", help="运行信号跟踪流水线（记录+评估+回测+优化）")
    parser.add_argument("--report-learn", action="store_true", help="查看信号跟踪学习报告")
    parser.add_argument("--review", action="store_true", help="运行复盘分析（5步法:大盘→板块→个股→信号→策略）")
    parser.add_argument("--debate", action="store_true", help="多智能体辩论模式（分析师→多空辩论→交易员→风控→PM决策）")
    parser.add_argument("--debate-top", type=int, default=5, help="辩论前N只股票")
    parser.add_argument("--mode", choices=["local", "limit-up", "combined"],
                        default="local", help="选股模式 (默认: local)")
    parser.add_argument("--monitor", action="store_true", help="盘中实时监控 (仅limit-up模式)")
    parser.add_argument("--interval", type=int, default=30, help="监控刷新间隔(秒)")
    args = parser.parse_args()

    if args.summary:
        show_latest_report()
        return

    if args.report_learn:
        from signal_tracker import generate_learning_report
        report = generate_learning_report()
        print("\n" + report + "\n")
        return

    if args.review:
        from review_analysis import generate_review
        generate_review()
        return

    if args.debate:
        from debate_engine import debate_top_stocks, format_debate_report
        # 先跑本地选股获取数据
        _try_enable_fallback()
        from local_screener import run_local_screen
        print("[模式] 多智能体辩论分析（TradingAgents架构）")
        print(f"       辩论前 {args.debate_top} 只高置信股票")
        print()
        results = run_local_screen()
        # 检测市场状态
        regime_info = None
        try:
            from local_screener import parse_day_file, TDX_ROOT
            from market_regime import detect_market_regime
            import os
            idx_path = os.path.join(TDX_ROOT, "sh", "lday", "sh000001.day")
            idx_klines = parse_day_file(idx_path, 500)
            if len(idx_klines) >= 60:
                regime_info = detect_market_regime(idx_klines)
        except Exception:
            pass
        decisions = debate_top_stocks(results, regime_info, top_n=args.debate_top)
        report = format_debate_report(decisions)
        print("\n" + report)
        # 保存
        from datetime import datetime as _dt
        ts = _dt.now().strftime('%Y%m%d_%H%M%S')
        report_path = OUTPUT_DIR / f"辩论报告_{ts}.txt"
        report_path.write_text(report, encoding="utf-8")
        print(f"\n[OK] 报告已保存: {report_path}")
        return

    if args.api:
        args.mode = "api"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 启用网页数据降级（通达信数据不足时自动切到akshare/Playwright）
    _try_enable_fallback()

    print()
    print("=" * 60)
    print("  2026年 A股 短线选股策略系统")
    print("=" * 60)
    print()

    if args.learn:
        print("[模式] 信号跟踪+置信度优化流水线")
        from signal_tracker import run_tracker_pipeline
        run_tracker_pipeline()
        return

    if args.mode == "api":
        _run_api_mode()
    elif args.mode == "limit-up":
        _run_limit_up_mode(args.monitor, args.interval)
    elif args.mode == "combined":
        _run_combined_mode()
    else:
        _run_local_mode()

    print(f"\n{'='*60}")
    print("  [数据源说明]")
    print("  系统A: 通达信本地数据 -> 日K线技术指标 -> 6策略共振 -> 推荐")
    print("  系统B: 本地K线 + 热点板块识别 -> 4策略矩阵（涨停捕捉）")
    print("  补充:  东方财富API   -> 实时行情条件筛选")
    print(f"\n{'='*60}")
    print("  [风险] 基于历史数据筛选，仅供参考，不构成投资建议")
    print("  [风险] 短线交易风险较高，请严格止损，单票仓位不超过25%")
    print(f"{'='*60}")
    print()


if __name__ == "__main__":
    main()
