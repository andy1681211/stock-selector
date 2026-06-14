#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
决策先机 — 竞价抓涨停实时监控系统
=====================================
条件1: 昨日涨停（首板/二板）
条件2: 9:20前竞价涨停报价 [待数据源]
条件3: 9:30高开3%-6%
条件4: 盘中涨幅超7% = 买点
条件5: 9:50前上板最佳 [待分钟数据]
条件6: 热点主线 + 主力资金关注

用法:
  python decision_first.py              # 默认: 全流程（先扫昨日涨停→再查实时）
  python decision_first.py --premarket  # 9:25运行，查高开3%-6%
  python decision_first.py --monitor    # 盘中实时监控（每30秒刷新）
  python decision_first.py --scan       # 扫描全市场昨日涨停
"""
import sys, os, time, urllib.request
from datetime import datetime
from pathlib import Path

TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

from local_screener import parse_day_file, load_code_name_map, get_stock_name
from tdx_reader import calc_ma

if sys.stdout.encoding != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

OUTPUT_DIR = TOOL_DIR / "output"
TDX_ROOT = "D:/new_tdx/vipdoc"

# ============================================================
#  昨日涨停扫描（基于通达信本地数据）
# ============================================================

def scan_yesterday_limit_up(include_second_board=False) -> list:
    """
    扫描全市场，找出昨日涨停/大涨的股票

    Returns:
        [{"code": "000920", "name": "沃顿科技", "昨日涨幅": 9.98,
          "是否首板": True, "是否二板": False, "连板数": 1,
          "market": "sz", "昨收": 13.58}, ...]
    """
    print("  [扫描] 正在扫描全市场昨日涨停股票...")
    name_map = load_code_name_map()

    today = datetime.now().date()
    results = []
    total = 0

    for market in ['sh', 'sz', 'bj']:
        lday = os.path.join(TDX_ROOT, market, "lday")
        if not os.path.exists(lday):
            continue
        for fname in sorted(os.listdir(lday)):
            if not fname.endswith('.day'):
                continue
            full_code = fname.replace('.day', '')
            code = full_code[2:]

            if code.startswith(('9', '3', '4', '8')):
                continue  # 排除北交所/创业板/三板

            if code not in name_map:
                continue

            total += 1
            if total % 1000 == 0:
                print(f"    扫描中: {total} 只...", end='\r', flush=True)

            fp = os.path.join(lday, fname)
            klines = parse_day_file(fp, 30)
            if len(klines) < 3:
                continue

            c = klines[-1]  # 昨日/最新一天

            # 条件1: 昨日涨停（涨幅≥9.5%）
            if c.pct_chg < 9.5:
                continue  # 过滤：非涨停不要

            name = get_stock_name(code) or "?"
            if name.startswith(("*ST", "ST")):
                continue

            # 判断是首板还是连板
            consecutive = 1
            for i in range(len(klines) - 2, max(0, len(klines) - 10), -1):
                if klines[i].pct_chg >= 9.5:
                    consecutive += 1
                else:
                    break

            # 统计前一日涨停数（用于判断首板/二板）
            prev_day_zt = 0
            for i in range(len(klines) - 2, max(0, len(klines) - 6), -1):
                if klines[i].pct_chg >= 9.5:
                    prev_day_zt += 1

            is_first = consecutive == 1
            is_second = consecutive == 2

            results.append({
                "code": code,
                "name": name,
                "market": market,
                "昨日涨幅": c.pct_chg,
                "连板数": consecutive,
                "是否首板": is_first,
                "是否二板": is_second,
                "昨收": c.close,
                "昨日量比": calc_ma(klines, 5)[-1] if len(klines) >= 5 else 0,
            })

    print(f"  [完成] 扫描{total}只 → 找到昨日涨停 {len(results)} 只")
    return results


# ============================================================
#  实时行情获取（新浪财经API）
# ============================================================

def fetch_realtime_quotes(codes: list) -> dict:
    """
    批量获取实时行情

    Args:
        codes: [("000920", "sz"), ("600000", "sh"), ...]

    Returns:
        {"000920": {"name":xx, "now":xx, "open":xx, "high":xx, ...}, ...}
    """
    if not codes:
        return {}

    # 构建新浪API参数
    sina_codes = []
    code_map = {}  # 去掉前缀后的代码 -> 原始信息
    for code, market in codes:
        m = market if market == 'sh' else 'sz'
        sina_codes.append(f"{m}{code}")
        code_map[code] = (code, market)

    url = "https://hq.sinajs.cn/list=" + ",".join(sina_codes)
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})

    try:
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode('gbk')
    except Exception as e:
        print(f"  [错误] 获取行情失败: {e}")
        return {}

    result = {}
    for line in raw.strip().splitlines():
        if not line.startswith("var hq_str_"):
            continue
        parts = line.split('"')
        if len(parts) < 2:
            continue
        fields = parts[1].split(',')
        if len(fields) < 32:
            continue

        # 提取代码
        ident = line.split('_')[2].split('=')[0]  # sh000920
        code_key = ident[2:]  # 000920

        name = fields[0]
        open_p = float(fields[1]) if fields[1] else 0
        yclose = float(fields[2]) if fields[2] else 0
        now = float(fields[3]) if fields[3] else 0
        high = float(fields[4]) if fields[4] else 0
        low = float(fields[5]) if fields[5] else 0
        vol = int(fields[8]) if fields[8] else 0
        amount = float(fields[9]) if fields[9] else 0

        if yclose == 0:
            continue

        chg = (now - yclose) / yclose * 100
        open_chg = (open_p - yclose) / yclose * 100 if yclose > 0 else 0
        high_chg = (high - yclose) / yclose * 100 if yclose > 0 else 0

        result[code_key] = {
            "code": code_key,
            "name": name,
            "昨收": yclose,
            "开盘": open_p,
            "现价": now,
            "最高": high,
            "最低": low,
            "涨幅": chg,
            "开盘涨幅": open_chg,
            "最高涨幅": high_chg,
            "成交量": vol,
            "成交额": amount,
            "涨停价": round(yclose * 1.1, 2),
        }

    return result


# ============================================================
#  热点板块获取
# ============================================================

def get_hot_sectors() -> list:
    """获取当日热点板块（基于新浪免费行情接口）"""
    import urllib.request

    # 行业指数代码映射
    idx_map = {
        'sh000018': '金融', 'sh000019': '地产',
        'sh000032': '能源', 'sh000033': '有色材料',
        'sh000034': '工业', 'sh000035': '可选消费',
        'sh000036': '消费', 'sh000037': '医药',
        'sh000038': '金融', 'sh000039': '信息技术',
        'sh000040': '电信', 'sh000041': '公用事业',
        'sz399395': '医药', 'sz399394': '科技',
        'sz399393': '地产', 'sz399967': '军工',
        'sz399998': '煤炭', 'sz399997': '白酒消费',
        'sz399932': '消费', 'sz399434': '传媒',
        'sz399437': '证券', 'sz399431': '交通运输',
        'sz399959': '钢铁', 'sz399987': '船舶',
    }

    results = []
    codes = list(idx_map.keys())
    # 分批请求，避免URL过长
    for i in range(0, len(codes), 10):
        batch = codes[i:i+10]
        url = 'https://hq.sinajs.cn/list=' + ','.join(batch)
        req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn'})
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read().decode('gbk')
            for line in raw.strip().splitlines():
                if not line.startswith('var hq_str_'):
                    continue
                parts = line.split('"')
                if len(parts) < 2:
                    continue
                fields = parts[1].split(',')
                if len(fields) < 32:
                    continue
                code = line.split('_')[2].split('=')[0]
                now = float(fields[3]) if fields[3] else 0
                yclose = float(fields[2]) if fields[2] else 0
                if yclose > 0:
                    chg = (now - yclose) / yclose * 100
                    name = idx_map.get(code, fields[0])
                    results.append((chg, name))
        except:
            continue

    results.sort(key=lambda x: -x[0])
    seen = set()
    sectors = []
    for _, name in results:
        if name not in seen:
            seen.add(name)
            sectors.append(name)
        if len(sectors) >= 5:
            break
    if not sectors:
        sectors = ['金融', '科技', '消费']
    print(f"  [热点] {' | '.join(sectors)}")
    return sectors


def check_sector_match(code: str, name: str, hot_sectors: list,
                        sector_stock_map: dict = None) -> tuple:
    """
    检查股票是否匹配热点板块

    Returns:
        (是否匹配, 匹配的板块列表)
    """
    matched = []

    # 方式1: 通过板块-成分股映射
    if sector_stock_map:
        for sector, stocks in sector_stock_map.items():
            if code in stocks:
                matched.append(sector)

    # 方式2: 股票名称匹配关键词
    for sector in hot_sectors:
        for kw in [sector]:
            if kw in name:
                if kw not in matched:
                    matched.append(kw)

    return (len(matched) > 0, matched)


# ============================================================
#  决策先机核心逻辑
# ============================================================

def evaluate_candidates(zt_stocks: list, realtime: dict = None,
                         hot_sectors: list = None) -> list:
    """
    对昨日涨停股票进行决策先机评分

    评分规则（满分100）:
      - 昨日涨停: 10分（首板+5, 二板+8）
      - 今日高开3%-6%: 30分
      - 涨幅超7%: 25分
      - 热点板块: 20分
      - 量比>1.5: 15分
    """
    if hot_sectors is None:
        hot_sectors = []

    candidates = []
    for s in zt_stocks:
        code = s["code"]
        market = s["market"]
        name = s["name"]

        # 实时数据
        r = {}
        if realtime and code in realtime:
            r = realtime[code]

        score = 0
        signals = []

        # --- 条件1: 昨日涨停（基础分）---
        score += 10
        if s["是否首板"]:
            score += 5
            signals.append("首板")
        if s["是否二板"]:
            score += 8
            signals.append(f"二板({s['连板数']}连板)")

        # --- 条件3: 高开3%-6%（用开盘涨幅判断）---
        open_chg = r.get("开盘涨幅", 0)
        if 3 <= open_chg <= 6:
            score += 30
            signals.append(f"高开{open_chg:.1f}%✓")
        elif 2 <= open_chg < 3:
            score += 15
            signals.append(f"高开{open_chg:.1f}%(偏低)")
        elif 6 < open_chg <= 8:
            score += 15
            signals.append(f"高开{open_chg:.1f}%(偏高)")
        elif open_chg > 8:
            score += 5
            signals.append(f"高开{open_chg:.1f}%(过高)")
        elif open_chg < 0:
            signals.append(f"低开{open_chg:.1f}%")
        else:
            signals.append(f"平开{open_chg:.1f}%")

        # --- 条件4: 涨幅超7%触发买点 ---
        now_chg = r.get("涨幅", 0)
        high_chg = r.get("最高涨幅", 0)
        if now_chg >= 7:
            score += 25
            signals.append(f"触发买点({now_chg:.1f}%)🔥")
        elif high_chg >= 7:
            score += 20
            signals.append(f"盘中触7%+({high_chg:.1f}%)")
        elif now_chg >= 5:
            score += 10
            signals.append(f"偏强({now_chg:.1f}%)")
        elif now_chg >= 3:
            score += 5
            signals.append(f"上涨({now_chg:.1f}%)")
        elif now_chg < 0:
            signals.append(f"下跌({now_chg:.1f}%)")

        # --- 条件6: 热点匹配 ---
        sector_match, matched_sectors = check_sector_match(code, name, hot_sectors)
        if sector_match:
            score += 20
            signals.append(f"热点:{','.join(matched_sectors[:2])}🔥")

        # --- 量能辅助判断 ---
        vol_ratio = r.get("成交量", 0)
        if vol_ratio > 0:
            # 粗略判断：成交额 > 1亿认为活跃
            amount = r.get("成交额", 0)
            if amount > 100000000:  # 1亿
                score += 10
                signals.append("放量")
            elif amount > 50000000:
                score += 5
                signals.append("量能一般")
        if s.get("昨日量比", 0) > 2:
            score += 5

        # --- 是否封板判断 ---
        is_limit = now_chg >= 9.5
        is_falling = now_chg <= -5

        candidates.append({
            "code": code,
            "name": name,
            "market": market,
            "score": score,
            "signals": signals,
            "昨收": s["昨收"],
            "开盘": r.get("开盘", 0),
            "现价": r.get("现价", 0),
            "开盘涨幅": open_chg,
            "当前涨幅": now_chg,
            "最高涨幅": high_chg,
            "是否首板": s["是否首板"],
            "连板数": s["连板数"],
            "是否涨停": is_limit,
            "是否大跌": is_falling,
            "涨停价": r.get("涨停价", 0),
        })

    candidates.sort(key=lambda x: -x["score"])
    return candidates


# ============================================================
#  报告生成
# ============================================================

def generate_report(candidates: list, mode: str = "实时") -> str:
    """生成决策先机报告"""
    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append(f"  决策先机 — 竞价抓涨停 ({mode})")
    lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  筛选标的: {len(candidates)} 只")
    lines.append("=" * 70)
    lines.append("")
    lines.append("  ★ 条件1: 昨日涨停（首板/二板）")
    lines.append("  ★ 条件3: 高开3%-6%  【已实现】")
    lines.append("  ★ 条件4: 涨幅超7%=买点【已实现】")
    lines.append("  ★ 条件6: 热点主线    【已实现】")
    lines.append("  ☆ 条件2: 竞价涨停报价【待数据源】")
    lines.append("  ☆ 条件5: 9:50前上板  【待分钟数据】")
    lines.append("")

    # 筛选：满足条件的（高开3%-6% 或 涨幅超7%）
    qualified = [c for c in candidates if c["score"] >= 40]
    limit_ups = [c for c in candidates if c["是否涨停"]]
    watching = [c for c in candidates if c not in qualified and c not in limit_ups]

    # ---- 触发买点专区 ----
    triggered = [c for c in qualified if c["当前涨幅"] >= 7 or c["最高涨幅"] >= 7]
    if triggered:
        lines.append("─" * 70)
        lines.append("  立即买入信号（涨幅超7%触发买点）🔥")
        lines.append("─" * 70)
        lines.append(f"  {'评分':<5} {'代码':<7} {'名称':<8} {'涨幅':<8} {'开盘':<7} {'高开%':<7} {'最高%':<7} {'信号'}")
        lines.append(f"  {'-'*5:<5} {'-'*7:<7} {'-'*8:<8} {'-'*8:<8} {'-'*7:<7} {'-'*7:<7} {'-'*7:<7} {'-'*30}")
        for c in triggered[:10]:
            open_s = f"{c['开盘涨幅']:+.1f}%" if c['开盘涨幅'] != 0 else "无数据"
            lines.append(f"  {c['score']:<5} {c['code']:<7} {c['name']:<8} {c['当前涨幅']:<+7.1f}% {c['开盘']:<7.2f} {open_s:<7} {c['最高涨幅']:<+6.1f}% {'|'.join(c['signals'][:4]):<30}")
        lines.append("")

    # ---- 高开专区（条件3）----
    gap_up = [c for c in qualified if 3 <= c["开盘涨幅"] <= 6 and c not in triggered]
    if gap_up:
        lines.append("─" * 70)
        lines.append("  高开3%-6%候选（条件3满足，等待触发买点）")
        lines.append("─" * 70)
        lines.append(f"  {'评分':<5} {'代码':<7} {'名称':<8} {'现价':<7} {'高开%':<7} {'当前%':<7} {'涨停价':<7} {'信号'}")
        lines.append(f"  {'-'*5:<5} {'-'*7:<7} {'-'*8:<8} {'-'*7:<7} {'-'*7:<7} {'-'*7:<7} {'-'*7:<7} {'-'*30}")
        for c in gap_up[:8]:
            lines.append(f"  {c['score']:<5} {c['code']:<7} {c['name']:<8} {c['现价']:<7.2f} {c['开盘涨幅']:<+6.1f}% {c['当前涨幅']:<+6.1f}% {c['涨停价']:<7.2f} {'|'.join(c['signals'][:3]):<30}")
        lines.append("")

    # ---- 已涨停 ----
    if limit_ups:
        lines.append("─" * 70)
        lines.append("  已涨停（封板中，等待次日接力机会）")
        lines.append("─" * 70)
        for c in limit_ups[:5]:
            lines.append(f"    {c['code']} {c['name']} 涨停! {c['当前涨幅']:.1f}% 评分{c['score']}")
        lines.append("")

    # ---- 综合排名 ----
    lines.append("─" * 70)
    lines.append(f"  综合排名（共{len(candidates)}只）")
    lines.append("─" * 70)
    lines.append(f"  {'#':<3} {'评分':<5} {'代码':<7} {'名称':<8} {'昨日涨':<7} {'今开涨':<7} {'现涨':<7} {'连板':<4} {'信号'}")
    lines.append(f"  {'-'*3:<3} {'-'*5:<5} {'-'*7:<7} {'-'*8:<8} {'-'*7:<7} {'-'*7:<7} {'-'*7:<7} {'-'*4:<4} {'-'*30}")
    for i, c in enumerate(candidates[:20]):
        rank_mark = "★" if c['score'] >= 60 else ("☆" if c['score'] >= 40 else " ")
        signal_str = "|".join(c['signals'][:4]) if c['signals'] else "-"
        open_s = f"{c['开盘涨幅']:+.1f}%" if c['开盘涨幅'] != 0 else "N/A"
        lines.append(f"  {rank_mark}{i+1:<2} {c['score']:<5} {c['code']:<7} {c['name']:<8} {c['昨收']:<+7.2f} {open_s:<7} {c['当前涨幅']:<+6.1f}% {c['连板数']:<3}板 {signal_str:<30}")

    lines.append("")
    lines.append("=" * 70)
    lines.append("  策略说明:")
    lines.append("  条件1: 昨日涨停（首板/二板）✅")
    lines.append("  条件2: 9:20前竞价涨停报价 ❌需Level-2数据")
    lines.append("  条件3: 高开3%-6% ✅通过开盘价判断")
    lines.append("  条件4: 盘中涨幅超7%=买点 ✅实时监控")
    lines.append("  条件5: 9:50前上板最佳 ❌需分钟K线")
    lines.append("  条件6: 热点共振 ✅板块匹配")
    lines.append("=" * 70)
    lines.append("  [风险提示] 仅供参考，不构成投资建议")
    lines.append("")

    return "\n".join(lines)


# ============================================================
#  运行模式
# ============================================================

def run_premarket():
    """盘前模式：9:25后运行，查看哪些昨日涨停股高开3%-6%"""
    print("=" * 60)
    print("  决策先机 — 盘前模式")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print()

    # 1. 获取昨日涨停股票
    zt_stocks = scan_yesterday_limit_up()
    if not zt_stocks:
        print("  [结果] 昨日无涨停股票")
        return

    print(f"  昨日涨停: {len(zt_stocks)} 只")
    first = sum(1 for s in zt_stocks if s["是否首板"])
    second = sum(1 for s in zt_stocks if s["是否二板"])
    print(f"    首板: {first}只  二板+: {second}只")
    print()

    # 2. 获取实时行情（今日开盘数据）
    code_list = [(s["code"], s["market"]) for s in zt_stocks]
    print("  [行情] 获取今日开盘数据...")
    realtime = fetch_realtime_quotes(code_list)
    print(f"  [行情] 获取到 {len(realtime)} 只实时数据")
    print()

    # 3. 获取热点板块
    hot = get_hot_sectors()

    # 4. 评分
    candidates = evaluate_candidates(zt_stocks, realtime, hot)

    # 5. 报告
    report = generate_report(candidates, "盘前")
    print(report)

    # 6. 保存
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"决策先机_盘前_{ts}.txt"
    path.write_text(report, encoding="utf-8")
    print(f"  [保存] {path}")

    return candidates


def run_monitor():
    """盘中实时监控模式：每30秒刷新"""
    print("=" * 60)
    print("  决策先机 — 实时监控模式")
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("  刷新间隔: 30秒")
    print("  监控条件: 涨幅超7%触发买点")
    print("=" * 60)
    print()

    # 先扫昨日涨停
    zt_stocks = scan_yesterday_limit_up()
    if not zt_stocks:
        print("  [退出] 昨日无涨停股票，无法监控")
        return

    # 获取热点
    hot = get_hot_sectors()

    code_list = [(s["code"], s["market"]) for s in zt_stocks]

    # 上次已触发的股票（避免重复提醒）
    already_triggered = set()
    refresh_count = 0

    try:
        while True:
            refresh_count += 1
            now = datetime.now()
            print(f"\n{'='*60}")
            print(f"  [{refresh_count}] 刷新: {now.strftime('%H:%M:%S')}")
            print(f"{'='*60}")

            # 获取实时数据
            realtime = fetch_realtime_quotes(code_list)
            candidates = evaluate_candidates(zt_stocks, realtime, hot)

            # 检查新触发的买点
            triggered = [c for c in candidates if c["当前涨幅"] >= 7
                        and c["code"] not in already_triggered]
            for c in triggered:
                print(f"\n  🔥🔥🔥 买入信号触发! {c['code']} {c['name']} 🔥🔥🔥")
                print(f"     现价:{c['现价']:.2f}  涨幅:{c['当前涨幅']:.1f}%")
                print(f"     高开:{c['开盘涨幅']:+.1f}%  最高:{c['最高涨幅']:+.1f}%")
                print(f"     信号: {'|'.join(c['signals'])}")
                already_triggered.add(c["code"])

            # 简表
            active = [c for c in candidates if c["score"] >= 40]
            if active:
                print(f"\n  关注列表({len(active)}只):")
                print(f"  {'代码':<7} {'名称':<8} {'涨幅':<8} {'评分':<5} {'信号'}")
                for c in active[:10]:
                    mark = "🔥" if c["code"] in already_triggered else " "
                    sig = "|".join(c["signals"][:3])
                    print(f"  {mark}{c['code']:<7} {c['name']:<8} {c['当前涨幅']:<+7.1f}% {c['score']:<5} {sig:<30}")

            # 检查是否收盘
            current_hour = now.hour
            current_min = now.min
            if current_hour > 15 or (current_hour == 15 and current_min >= 5):
                print("\n  [收盘] 监控结束")
                break

            # 午休跳过
            if 11 <= current_hour < 13:
                print(f"\n  [午休] 暂停监控至13:00...")
                # 等待到13:00
                while True:
                    now2 = datetime.now()
                    if now2.hour >= 13:
                        break
                    time.sleep(30)
                continue

            time.sleep(30)

    except KeyboardInterrupt:
        print("\n  [停止] 用户中断")

    # 生成最终报告
    print("\n\n  [生成最终报告...]")
    realtime = fetch_realtime_quotes(code_list)
    candidates = evaluate_candidates(zt_stocks, realtime, hot)
    report = generate_report(candidates, "监控")
    print(report)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"决策先机_监控_{ts}.txt"
    path.write_text(report, encoding="utf-8")
    print(f"  [保存] {path}")


def run_scan():
    """扫描全市场昨日涨停"""
    zt_stocks = scan_yesterday_limit_up()

    if not zt_stocks:
        print("  昨日无涨停股票")
        return

    print(f"\n  昨日涨停汇总:")
    print(f"  首板: {sum(1 for s in zt_stocks if s['是否首板'])} 只")
    print(f"  二板: {sum(1 for s in zt_stocks if s['是否二板'])} 只")
    print(f"  三板及以上: {sum(1 for s in zt_stocks if s['连板数'] >= 3)} 只")
    print()

    # 按连板数排序
    zt_stocks.sort(key=lambda x: -x["连板数"])
    print(f"  {'代码':<7} {'名称':<8} {'涨幅':<8} {'连板':<5} {'昨收':<8}")
    print(f"  {'-'*7:<7} {'-'*8:<8} {'-'*8:<8} {'-'*5:<5} {'-'*8:<8}")
    for s in zt_stocks[:30]:
        board = f"{s['连板数']}板" if s['连板数'] >= 2 else "首板"
        print(f"  {s['code']:<7} {s['name']:<8} {s['昨日涨幅']:<+7.1f}% {board:<5} {s['昨收']:<8.2f}")

    print(f"\n  ...共{len(zt_stocks)}只")

    # 保存
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"昨日涨停_{ts}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"昨日涨停股票 ({datetime.now().strftime('%Y-%m-%d')})\n")
        f.write(f"首板:{sum(1 for s in zt_stocks if s['是否首板'])} 二板:{sum(1 for s in zt_stocks if s['是否二板'])} 三板+:{sum(1 for s in zt_stocks if s['连板数'] >= 3)}\n\n")
        for s in zt_stocks:
            board = f"{s['连板数']}连板" if s['连板数'] >= 2 else "首板"
            f.write(f"{s['code']} {s['name']} {s['昨日涨幅']:.1f}% {board}\n")
    print(f"\n  [保存] {path}")


# ============================================================
#  Main
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="决策先机 — 竞价抓涨停")
    parser.add_argument("--premarket", action="store_true", help="盘前模式（查高开3%-6%）")
    parser.add_argument("--monitor", action="store_true", help="盘中实时监控")
    parser.add_argument("--scan", action="store_true", help="扫描昨日涨停")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.scan:
        run_scan()
    elif args.premarket:
        run_premarket()
    elif args.monitor:
        run_monitor()
    else:
        # 默认：扫描+盘前分析
        run_premarket()


if __name__ == "__main__":
    main()
