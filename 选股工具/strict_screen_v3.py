# -*- coding: utf-8 -*-
"""
精选模式V3：修复通达信板块换行符格式
"""
import sys, os, time
sys.path.insert(0, 'D:\\股票分析\\选股工具')
os.chdir('D:\\股票分析\\选股工具')
from local_screener import *

t0 = time.time()
results = run_local_screen()

strict = []
for r in results:
    chan = r.get('缠论买点', '')
    if not chan: continue
    if r.get('中枢位置', '') != '上方': continue
    vr = float(r.get('量比', 0) or 0)
    if vr < 1.5: continue
    angle_raw = r.get('MA角度', '0')
    angle = float(angle_raw.replace('°', '')) if isinstance(angle_raw, str) else float(angle_raw)
    if angle < 30: continue
    chg = float(r.get('涨跌幅', 0) or 0)
    if not (0.5 <= chg <= 5.0): continue
    price = float(r.get('最新价', 0) or 0)
    if not (5 <= price <= 50): continue
    strict.append(r)

scored = []
for r in strict:
    score = 0
    if '二买' in r.get('缠论买点', ''): score += 30
    if '三买' in r.get('缠论买点', ''): score += 20
    score += r.get('策略命中', 0) * 5
    scored.append((score, r))
scored.sort(key=lambda x: -x[0])
top = scored[:10]

print(f'总: {len(results)} | 精选: {len(strict)} | TOP10: {len(top)}')

# ===== 关键修复：二进制模式写入，手动拼接CRLF =====
lines = ['']  # 首行空行
for s, r in top:
    code = r['代码']
    prefix = '1' if code.startswith(('6', '9')) else '0' if code.startswith(('0', '3', '2')) else '4'
    lines.append(f'{prefix}{code}')

# 手动拼接：用 \r\n 连接，然后编码为gbk
text = '\r\n'.join(lines)
data = text.encode('gbk')

with open('D:/new_tdx/T0002/blocknew/CLAUDEXG.blk', 'wb') as f:
    f.write(data)

# 验证
verify = open('D:/new_tdx/T0002/blocknew/CLAUDEXG.blk', 'rb').read()
print(f'文件: {len(verify)} 字节')
print(f'首3字节: {" ".join(f"{b:02X}" for b in verify[:3])}（应为0D 0A 30 = 空行+数字0）')

for i, (s, r) in enumerate(top):
    print(f'#{i+1} {r["代码"]} {r["名称"]} {r["涨跌幅"]}% 量比{r["量比"]} 缠论:{r["缠论买点"]} 评分{s}')

print(f'\n✅ 请重启通达信，按 Ctrl+F2 → 自定义板块 → 找到 CLAUDEXG 查看！')
print(f'耗时: {time.time()-t0:.1f}秒')
