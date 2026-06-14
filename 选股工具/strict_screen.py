# -*- coding: utf-8 -*-
"""
精选模式：严格条件，只保留最优质信号
条件:
  1. 必须有缠论买点（二买/三买/一买）
  2. 中枢位置 = 上方（趋势强势区）
  3. 量比 >= 1.5（放量确认）
  4. MA角度 >= 30度（趋势强度）
  5. 涨幅 0.5%~5%（温和上涨，非高潮）
  6. 股价 5~50元（排除垃圾股和百元股）

最终只写入前10只到通达信板块
"""
import sys, os, time
sys.path.insert(0, 'D:\\股票分析\\选股工具')
os.chdir('D:\\股票分析\\选股工具')
from local_screener import *

t0 = time.time()
results = run_local_screen()

# 精选过滤
strict = []
for r in results:
    # 必须有缠论买点
    chan = r.get('缠论买点', '')
    if not chan:
        continue
    # 中枢在上方
    if r.get('中枢位置', '') != '上方':
        continue
    # 量比
    vr = float(r.get('量比', 0) or 0)
    if vr < 1.5:
        continue
    # MA角度
    angle_raw = r.get('MA角度', '0')
    angle = float(angle_raw.replace('°', '')) if isinstance(angle_raw, str) else float(angle_raw)
    if angle < 30:
        continue
    # 涨幅
    chg = float(r.get('涨跌幅', 0) or 0)
    if not (0.5 <= chg <= 5.0):
        continue
    # 股价
    price = float(r.get('最新价', 0) or 0)
    if not (5 <= price <= 50):
        continue

    strict.append(r)

print(f'总选到: {len(results)} 只')
print(f'严格精选: {len(strict)} 只')
print()

if not strict:
    print('无股票通过精选条件！')
    # 放宽条件：只保留量比>=1.0
    for r in results:
        chan = r.get('缠论买点', '')
        if not chan:
            continue
        if r.get('中枢位置', '') != '上方':
            continue
        vr = float(r.get('量比', 0) or 0)
        if vr < 1.0:
            continue
        chg = float(r.get('涨跌幅', 0) or 0)
        if not (0.5 <= chg <= 5.0):
            continue
        price = float(r.get('最新价', 0) or 0)
        if not (5 <= price <= 50):
            continue
        strict.append(r)
    print(f'放宽条件后: {len(strict)} 只')

# 评分排序
scored = []
for r in strict:
    score = 0
    if '二买' in r.get('缠论买点', ''):
        score += 30
    if '三买' in r.get('缠论买点', ''):
        score += 20
    score += r.get('策略命中', 0) * 5
    chg = float(r.get('涨跌幅', 0) or 0)
    if 1.0 <= chg <= 4.0:
        score += 5
    vr = float(r.get('量比', 0) or 0)
    if vr >= 2.0:
        score += 5
    scored.append((score, r))

scored.sort(key=lambda x: -x[0])

# 取前10只
top = scored[:10]
top_n = len(top)

# 写入通达信板块（覆盖旧数据）
lines = []
for s, r in top:
    code = r['代码']
    if code.startswith(('6', '9')):
        prefix = '1'
    elif code.startswith(('0', '3', '2')):
        prefix = '0'
    elif code.startswith(('4', '8')):
        prefix = '4'
    else:
        continue
    lines.append(f'{prefix}{code}')

blk_path = 'D:/new_tdx/T0002/blocknew/CLAUDEXG.blk'
with open(blk_path, 'w', encoding='gbk') as f:
    f.write('\n'.join(lines))

print(f'\n{"="*70}')
print(f'  CLAUDEXG.blk 已更新！写入 {len(lines)} 只精选股')
print(f'{"="*70}')

for i, (s, r) in enumerate(top):
    pos = r.get('仓位建议', '')
    print(f'\n#{i+1} {r["代码"]} {r["名称"]}')
    print(f'   价格:{r["最新价"]}  涨幅:{r["涨跌幅"]}%  量比:{r["量比"]}')
    print(f'   缠论:{r["缠论买点"]}  中枢:{r["中枢位置"]}  角度:{r["MA角度"]}')
    print(f'   信号:{r["信号"]}  策略命中:{r["策略命中"]}  评分:{s}')
    print(f'   仓位:{pos}')

print(f'\n耗时: {time.time()-t0:.1f}秒')
