# -*- coding: utf-8 -*-
"""
精选模式V2：修复通达信板块格式（首行必须是空行）
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
    chan = r.get('缠论买点', '')
    if not chan:
        continue
    if r.get('中枢位置', '') != '上方':
        continue
    vr = float(r.get('量比', 0) or 0)
    if vr < 1.5:
        continue
    angle_raw = r.get('MA角度', '0')
    angle = float(angle_raw.replace('°', '')) if isinstance(angle_raw, str) else float(angle_raw)
    if angle < 30:
        continue
    chg = float(r.get('涨跌幅', 0) or 0)
    if not (0.5 <= chg <= 5.0):
        continue
    price = float(r.get('最新价', 0) or 0)
    if not (5 <= price <= 50):
        continue
    strict.append(r)

print(f'总选到: {len(results)} 只')
print(f'严格精选: {len(strict)} 只')

# 评分
scored = []
for r in strict:
    score = 0
    if '二买' in r.get('缠论买点', ''): score += 30
    if '三买' in r.get('缠论买点', ''): score += 20
    score += r.get('策略命中', 0) * 5
    scored.append((score, r))
scored.sort(key=lambda x: -x[0])

top = scored[:10]
top_n = len(top)

# ===== 修复：写入通达信格式，空行开头 =====
lines_list = [""]  # 首行空行
for s, r in top:
    code = r['代码']
    prefix = '1' if code.startswith(('6', '9')) else '0' if code.startswith(('0', '3', '2')) else '4'
    lines_list.append(f'{prefix}{code}')

# 用CRLF换行符，ANSI编码
raw_text = '\r\n'.join(lines_list)
blk_path = 'D:/new_tdx/T0002/blocknew/CLAUDEXG.blk'
with open(blk_path, 'w', encoding='gbk', newline='\r\n') as f:
    f.write(raw_text)

print(f'\n写入通达信板块: {top_n} 只（首行空行格式）')

# 验证
verify = open(blk_path, 'rb').read()
print(f'文件大小: {len(verify)} 字节')
print(f'首2字节: {verify[0]:02X} {verify[1]:02X}（应为0D 0A = 空行）')

print(f'\n{"="*70}')
for i, (s, r) in enumerate(top):
    pos = r.get('仓位建议', '')
    print(f'#{i+1} {r["代码"]} {r["名称"]}')
    print(f'   价格:{r["最新价"]}  涨幅:{r["涨跌幅"]}%  量比:{r["量比"]}  MA角度:{r["MA角度"]}')
    print(f'   缠论:{r["缠论买点"]}  中枢:{r["中枢位置"]}  策略命中:{r["策略命中"]}')
    print(f'   仓位:{pos}')

print(f'\n耗时: {time.time()-t0:.1f}秒')
print(f'\n请重启通达信，然后按 Ctrl+F2 或打开自定义板块查看 CLAUDEXG！')
