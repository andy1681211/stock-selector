#!/usr/bin/env python3
"""
盘中实时监控 - 基于pytdx直连通达信行情服务器
配合通达信本地选股系统，实时监控精选股票的盘中异动

用法:
  python realtime_monitor.py              # 一次快照
  python realtime_monitor.py --watch      # 持续监控（每60秒刷新）
  python realtime_monitor.py --watch --interval 30  # 自定义间隔
"""

import sys
import time
from datetime import datetime
from pathlib import Path

TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"

# 通达信板块文件
TDX_BLOCK_FILE = "D:/new_tdx/T0002/blocknew/CLAUDEXG.blk"
NAME_MAP_FILE = "D:/new_tdx/T0002/hq_cache/infoharbor_ex.code"

# 通达信行情服务器
TDX_SERVERS = [
    ('180.153.18.170', 7709),
    ('180.153.18.171', 7709),
]

# 市场映射: sh->1, sz->0, bj->2
MARKET_MAP = {'sh': 1, 'sz': 0, 'bj': 2}


def load_block_stocks() -> list:
    """读取通达信自定义板块的股票"""
    stocks = []
    try:
        with open(TDX_BLOCK_FILE, 'rb') as f:
            for line in f.read().decode('gbk').strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                prefix, code = line[0], line[1:]
                if prefix == '1':
                    stocks.append(('sh', code))
                elif prefix == '0':
                    stocks.append(('sz', code))
                elif prefix == '4':
                    stocks.append(('bj', code))
    except FileNotFoundError:
        pass
    return stocks


def load_name_map() -> dict:
    """加载股票名称"""
    name_map = {}
    try:
        with open(NAME_MAP_FILE, 'r', encoding='gbk', errors='ignore') as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) >= 2:
                    name_map[parts[0].strip()] = parts[1].strip()
    except FileNotFoundError:
        pass
    return name_map


def get_quotes(stocks: list) -> list:
    """用pytdx获取实时行情"""
    from pytdx.hq import TdxHq_API

    api = TdxHq_API(heartbeat=False)
    conn_ok = False
    for ip, port in TDX_SERVERS:
        try:
            api.connect(ip, port, time_out=5)
            # 验证连接
            test = api.get_security_quotes([(1, '600519')])
            if test:
                conn_ok = True
                break
            api.disconnect()
        except:
            continue

    if not conn_ok:
        return []

    # 按市场分组查询（北交所独立处理，避免整批失败）
    results = []
    groups = {}
    for market, code in stocks:
        # 北交所股票(92xxxx)用市场码2
        if code.startswith("92"):
            groups.setdefault("bj", []).append(code)
        else:
            groups.setdefault(market, []).append(code)

    for m, codes in groups.items():
        market_code = MARKET_MAP.get(m)
        if market_code is None:
            continue
        codes_list = [(market_code, c) for c in codes]
        for i in range(0, len(codes_list), 80):
            batch = codes_list[i:i+80]
            try:
                quotes = api.get_security_quotes(batch)
                if quotes:
                    results.extend(quotes)
            except:
                continue

    api.disconnect()
    return results


def parse_quote(q, name_map: dict) -> dict:
    """解析单条行情数据"""
    code = str(q.get('code', ''))
    market = q.get('market', 0)
    # pytdx返回的价格单位是元（不是分）
    price = q.get('price', 0)
    last_close = q.get('last_close', 0)
    chg_pct = (price - last_close) / last_close * 100 if last_close > 0 else 0
    chg_amount = price - last_close
    high = q.get('high', 0)
    low = q.get('low', 0)
    open_p = q.get('open', 0)
    vol = q.get('vol', 0)  # 手
    amount = q.get('amount', 0)  # 元
    bid1 = q.get('bid1', 0)
    ask1 = q.get('ask1', 0)

    return {
        "代码": code,
        "名称": name_map.get(code, code),
        "最新价": price,
        "涨幅": round(chg_pct, 2),
        "涨跌额": round(chg_amount, 2),
        "今开": open_p,
        "最高": high,
        "最低": low,
        "昨收": last_close,
        "成交量": vol,
        "成交额": amount,
        "买一": bid1,
        "卖一": ask1,
        "server_time": q.get('servertime', ''),
    }


def print_snapshot(parsed: list):
    """打印行情快照"""
    if not parsed:
        print("  暂无数据（非交易时间或连接失败）")
        return

    now = datetime.now().strftime('%H:%M:%S')
    sorted_q = sorted(parsed, key=lambda x: x["涨幅"], reverse=True)

    print()
    print(f"{'='*75}")
    print(f"  实时行情快照 @ {now}")
    print(f"{'='*75}")
    print(f"  {'代码':<8} {'名称':<10} {'最新价':<9} {'涨幅':<8} {'最高':<9} {'最低':<9} {'成交量':<10}")
    print(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*6} {'-'*8} {'-'*8} {'-'*10}")

    movers_up = []
    movers_down = []

    for q in sorted_q:
        chg = q["涨幅"]
        marker = ""
        if chg >= 5:
            marker = " << 大涨"
            movers_up.append(q)
        elif chg <= -3:
            marker = " << 大跌"
            movers_down.append(q)

        vol_str = f"{q['成交量']//10000}万手" if q['成交量'] >= 10000 else f"{q['成交量']}手"

        print(f"  {q['代码']:<8} {q['名称']:<10} {q['最新价']:<9.2f} {chg:>+6.2f}% {q['最高']:<9.2f} {q['最低']:<9.2f} {vol_str:<10}{marker}")

    if movers_up:
        print(f"\n  >> 大涨(>=5%): ", end="")
        print(", ".join(f"{q['名称']}({q['代码']}){q['涨幅']:+.1f}%" for q in movers_up))
    if movers_down:
        print(f"  >> 大跌(<=-3%): ", end="")
        print(", ".join(f"{q['名称']}({q['代码']}){q['涨幅']:+.1f}%" for q in movers_down))
    if not movers_up and not movers_down:
        print(f"\n  >> 暂无显著异动")


def watch_loop(interval=60):
    """持续监控"""
    stocks = load_block_stocks()
    name_map = load_name_map()

    if not stocks:
        print("错误: CLAUDEXG板块为空")
        print("请先运行 python run_selector.py")
        return

    print(f"启动盘中监控 (间隔: {interval}秒)")
    print(f"监控: {len(stocks)}只 | 数据源: 通达信行情服务器")
    print("按 Ctrl+C 停止")
    print()

    first = True
    prev = {}

    try:
        while True:
            raw = get_quotes(stocks)
            parsed = [parse_quote(q, name_map) for q in raw]

            if parsed:
                if first:
                    print_snapshot(parsed)
                    first = False
                else:
                    check_alerts(parsed, prev)
                prev = {q["代码"]: q for q in parsed}
            else:
                now = datetime.now()
                h = now.hour
                if h < 9 or h >= 15:
                    print(f"\r[{now.strftime('%H:%M:%S')}] 已收盘，等待明日...", end="")
                else:
                    print(f"\r[{now.strftime('%H:%M:%S')}] 获取数据中...", end="")

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n\n监控已停止")


def check_alerts(parsed: list, prev: dict):
    """异动提醒"""
    now = datetime.now().strftime('%H:%M:%S')

    for q in parsed:
        code = q["代码"]
        name = q["名称"]
        chg = q["涨幅"]

        if chg >= 5:
            print(f"[{now}] 大涨 {name}({code}) {chg:+.1f}%")
        elif chg <= -3:
            print(f"[{now}] 大跌 {name}({code}) {chg:+.1f}%")

        if code in prev:
            diff = chg - prev[code]["涨幅"]
            if diff >= 2:
                print(f"[{now}] 拉升 {name}({code}) {prev[code]['涨幅']:+.1f}% -> {chg:+.1f}%")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="盘中实时监控")
    parser.add_argument("--watch", action="store_true", help="持续监控")
    parser.add_argument("--interval", type=int, default=60, help="刷新秒数")
    args = parser.parse_args()

    stocks = load_block_stocks()
    if not stocks:
        print("CLAUDEXG板块为空，请先选股")
        return

    print(f"股票: {len(stocks)}只 | 数据源: 通达信行情直连")

    if args.watch:
        watch_loop(args.interval)
    else:
        name_map = load_name_map()
        raw = get_quotes(stocks)
        parsed = [parse_quote(q, name_map) for q in raw]
        print_snapshot(parsed)


if __name__ == "__main__":
    main()
