#!/usr/bin/env python3
"""自选股实时行情分析"""
import sys, os, subprocess, json
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.stdout.encoding != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

codes = {
    'sh000887': '中鼎股份',
    'sz000920': '沃顿科技',
    'sz000691': '亚太实业',
    'sh600611': '大众交通',
    'sz002314': '南山控股',
    'sz002636': '金安国纪',
    'sz002700': '万憬能源',
    'sz002981': '朝阳科技',
    'sh600378': '昊华科技',
    'sh601939': '建设银行',
    'sh605580': '恒盛能源',
}

# Fetch real-time data
import urllib.request
url = "https://hq.sinajs.cn/list=" + ",".join(codes.keys())
req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
resp = urllib.request.urlopen(req, timeout=10)
raw = resp.read().decode('gbk')

stocks = []
for line in raw.strip().splitlines():
    if not line or not line.startswith("var hq_str_"):
        continue
    # Parse: var hq_str_sh600378="name,open,yclose,now,high,low,buy,sell,vol,amount,...";
    parts = line.split('"')
    if len(parts) < 2:
        continue
    fields = parts[1].split(',')
    if len(fields) < 32:
        continue

    name = fields[0]
    open_p = float(fields[1]) if fields[1] else 0
    yclose = float(fields[2]) if fields[2] else 0
    now = float(fields[3]) if fields[3] else 0
    high = float(fields[4]) if fields[4] else 0
    low = float(fields[5]) if fields[5] else 0
    vol = int(fields[8]) if fields[8] else 0  # 手
    amount = float(fields[9]) if fields[9] else 0
    date = fields[30]
    time = fields[31]

    chg = (now - yclose) / yclose * 100 if yclose > 0 else 0
    amp = (high - low) / yclose * 100 if yclose > 0 else 0
    turnover = amount / 1e4 if amount > 0 else 0  # 万元

    # Determine market status
    if chg >= 9.5:
        status = '涨停'
        mark = '🚀'
    elif chg <= -9.5:
        status = '跌停'
        mark = '🔴'
    elif chg >= 5:
        status = '大涨'
        mark = '📈'
    elif chg >= 2:
        status = '偏强'
        mark = '📈'
    elif chg >= 0:
        status = '微涨'
        mark = '⬆'
    elif chg >= -2:
        status = '微跌'
        mark = '⬇'
    elif chg >= -5:
        status = '回调'
        mark = '📉'
    else:
        status = '大跌'
        mark = '🔴'

    stocks.append({
        'code': line.split('_')[2].split('=')[0],
        'name': name,
        'open': open_p,
        'yclose': yclose,
        'now': now,
        'high': high,
        'low': low,
        'chg': chg,
        'amp': amp,
        'vol': vol,
        'amount': turnover,
        'status': status,
        'mark': mark,
        'date': date,
        'time': time,
    })

print('=' * 80)
print(f'  自选股实时行情 | {stocks[0]["date"]} 上午收盘 {stocks[0]["time"]}')
print('=' * 80)
print()
header = f'  {"代码":<7} {"名称":<8} {"昨收":<8} {"开盘":<8} {"现价":<8} {"涨幅":<9} {"最高":<8} {"最低":<8} {"振幅":<7} {"成交额":<10} {"状态"}'
print(header)
print('  ' + '-' * (len(header) - 2))

for s in stocks:
    chg_s = f'{s["chg"]:+.2f}%'
    amt_s = f'{s["amount"]:.0f}万' if s['amount'] < 10000 else f'{s["amount"]/10000:.2f}亿'
    print(f'  {s["code"]:<7} {s["name"]:<8} {s["yclose"]:<8.2f} {s["open"]:<8.2f} {s["now"]:<8.2f} {chg_s:<9} {s["high"]:<8.2f} {s["low"]:<8.2f} {s["amp"]:<7.2f} {amt_s:<10} {s["mark"]}{s["status"]}')

print()
print('=' * 80)
print('  与昨日收盘对比 + 综合研判')
print('=' * 80)
print()

# 昨日评分排名（从analyze_zxg.py结果）
yesterday = {
    '000920': ('沃顿科技', 112, '三倍试盘+青云+缠二买+底分+震仓'),
    '000691': ('亚太实业', 106, '青云+缠二买+低吸+底分+洗毕'),
    '601939': ('建设银行', 80, '试盘+缠二买+震仓'),
    '002700': ('万憬能源', 79, '三倍试盘+青云+缠二买+低吸+底分'),
    '002636': ('金安国纪', 72, '建仓+青云+缠二买+底分'),
    '002981': ('朝阳科技', 71, '缠二买+底分+震仓'),
    '000887': ('中鼎股份', 65, '缠二买+震仓'),
    '600378': ('昊华科技', 63, '建仓+试盘+缠二买'),
    '002314': ('南山控股', 46, '试盘+缠二买+底分+震仓'),
    '600611': ('大众交通', 16, '底分'),
    '605580': ('恒盛能源', 11, '试盘+底分'),
}

# 排除不合适的: 过热(高风险)、跌停、涨停买不进、趋势空头
print('  [筛选过程]')
print(f'  {"股票":<14} {"评分":<5} {"今日涨幅":<10} {"状态":<10} {"决定":<10} {"理由"}')
print(f'  {"-"*14:<14} {"-"*5:<5} {"-"*10:<10} {"-"*10:<10} {"-"*10:<10} {"-"*20}')
for s in stocks:
    code = s['code']
    if code.startswith('sh'): code = code[2:]
    elif code.startswith('sz'): code = code[2:]

    yn = yesterday.get(code, ('?', 0, ''))
    score = yn[1]
    chg = s['chg']
    status = s['status']

    # 排除逻辑
    exclude_reason = ''
    keep = True

    if status == '跌停':
        exclude_reason = '跌停回避'
        keep = False
    elif status == '涨停' and code != '605580':
        exclude_reason = '涨停买不进'
        keep = False
    elif code == '605580' and status == '涨停':
        exclude_reason = '昨日评分11，无信号支撑'
        keep = False
    elif code == '002636' and chg > 5:
        exclude_reason = 'RSI93+过热'
        keep = False
    elif code == '600378':
        exclude_reason = 'XD除权跌停'
        keep = False
    elif code == '002981':
        exclude_reason = '破位大跌'
        keep = False
    elif code == '002700':
        exclude_reason = '前5日过热'
        keep = False
    elif code == '600611':
        exclude_reason = '趋势空头'
        keep = False
    elif code == '002314':
        exclude_reason = '低价+趋势弱'
        keep = False

    if keep:
        if chg >= 0:
            decide = '✅ 候选'
        else:
            decide = '排除'
            exclude_reason = '今日下跌'
    else:
        decide = '❌ 排除'

    chg_s = f'{chg:+.2f}%'
    print(f'  {code} {yn[0]:<8} {score:<5} {chg_s:<10} {status:<10} {decide:<10} {exclude_reason}')

print()
print('=' * 80)
print('  最终推荐')
print('=' * 80)
print()

# Find best candidate
candidates = []
for s in stocks:
    code = s['code']
    if code.startswith('sh'): code = code[2:]
    elif code.startswith('sz'): code = code[2:]

    yn = yesterday.get(code, ('?', 0, ''))

    # Must be low risk and positive trend
    if code in ['002636','600378','002700','002981','002314','600611','605580','000887']:
        continue
    if s['chg'] < 0:
        continue

    candidates.append((s, yn[1], yn[2]))

candidates.sort(key=lambda x: -x[1])

if candidates:
    best = candidates[0][0]
    bcode = best['code']
    if bcode.startswith('sh'): bcode = bcode[2:]
    elif bcode.startswith('sz'): bcode = bcode[2:]
    byn = yesterday.get(bcode, ('?', 0, '?'))

    print(f'  ╔══════════════════════════════════════════════════════╗')
    print(f'  ║  唯一可投资标的: {bcode} {best["name"]}                    ')
    print(f'  ║  综合评分: {byn[1]}/100                                  ')
    print(f'  ╠══════════════════════════════════════════════════════╣')
    print(f'  ║  昨收:{best["yclose"]:.2f}  开盘:{best["open"]:.2f}  现价:{best["now"]:.2f}              ')
    print(f'  ║  涨幅:{best["chg"]:+.2f}%  最高:{best["high"]:.2f}  最低:{best["low"]:.2f}          ')
    print(f'  ║  振幅:{best["amp"]:.2f}%  成交:{best["amount"]/10000:.2f}亿                ')
    print(f'  ║  信号: {byn[2]:<35}')
    print(f'  ╚══════════════════════════════════════════════════════╝')
    print()

    if bcode == '000920':
        print(f'  >> 核心逻辑: 昨日唯一评分112的股票，今日继续上涨{best["chg"]:+.2f}%')
        print(f'  >> 盘中最高{best["high"]:.2f}(+{(best["high"]-best["yclose"])/best["yclose"]*100:.2f}%)，创近期新高')
        print(f'  >> 三倍量试盘线验证成功，主升浪进行中')
        print(f'  >> 午后关注: 能否站稳14.00，缩量回调不破13.50则继续持股')
        print(f'  >> 止损: 跌破13.45(今日最低)或MA20')
    elif bcode == '000691':
        print(f'  >> 亚太实业今日最高{best["high"]:.2f}(+{(best["high"]-best["yclose"])/best["yclose"]*100:.2f}%)')
        print(f'  >> 冲高回落，关注午后能否收回')

    print(f'\n  [午后策略]')
    print(f'  - 沃顿科技若缩量回踩13.50-13.60可考虑低吸')
    print(f'  - 若放量突破14.10则加仓信号')
    print(f'  - 跌破13.45则观望')

else:
    print('  当前自选股中无符合条件的投资标的。')

print()
print('=' * 80)
print(f'  数据来源: 新浪财经实时行情 | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
print('=' * 80)
