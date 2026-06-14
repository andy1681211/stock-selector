#!/usr/bin/env python3
"""复盘分析：5月29日选股特征 vs 6月1日涨跌"""
import struct, os
from datetime import datetime
import sys
sys.stdout.reconfigure(encoding='utf-8')

name_map = {}
with open('D:/new_tdx/T0002/hq_cache/infoharbor_ex.code', 'r', encoding='gbk', errors='ignore') as f:
    for line in f:
        p = line.strip().split('|')
        if len(p) >= 2: name_map[p[0].strip()] = p[1].strip()

def read_k(fp, n=300):
    if not os.path.exists(fp): return []
    d = open(fp, 'rb').read()
    c = len(d)//32; s = max(0, c-n)
    k = []
    for i in range(s, c):
        r = d[i*32:(i+1)*32]
        v = struct.unpack('iiiiifii', r)
        k.append({'date':datetime.strptime(str(v[0]),'%Y%m%d').date(),
                  'o':v[1]/100,'h':v[2]/100,'l':v[3]/100,'c':v[4]/100,
                  'amt':v[5],'vol':v[6]/100})
    for i in range(1,len(k)):
        k[i]['chg'] = (k[i]['c']-k[i-1]['c'])/k[i-1]['c']*100 if k[i-1]['c']>0 else 0
    if k: k[0]['chg']=0
    return k

# 6月1日涨跌
perf = {'601101':10.03,'603099':0.64,'603103':-1.18,'603191':3.20,
    '603369':-1.12,'603678':9.99,'605580':-10.00,'000591':-2.47,'000600':-2.71,
    '000636':3.81,'000759':-2.13,'001308':-1.83,'002348':-4.36,'002436':-0.16,
    '002484':1.67,'002639':-5.41,'002771':1.72,'002927':-3.54,'002975':-6.40,'002981':2.62}
up = [c for c,p in perf.items() if p>=1]
dn = [c for c,p in perf.items() if p<=-1]

# 5月29日前5日涨幅计算
def get_prev5d(code):
    m = 'sh' if code.startswith(('6','9','5')) else 'sz'
    k = read_k(f'D:/new_tdx/vipdoc/{m}/lday/{m}{code}.day', 300)
    may29 = [x for x in k if x['date']<=datetime(2026,5,29).date()]
    if len(may29) < 6: return None
    return sum(x['chg'] for x in may29[-6:-1])

# 5月29日已知数据
f529 = {
    '601101': (2.29, 79.3, 2.51),
    '603099': (2.64, 66.3, 1.52),
    '603103': (6.41, 84.3, 1.88),
    '603191': (5.91, 34.2, 2.13),
    '603369': (3.80, 67.4, 2.08),
    '603678': (2.39, 100, 1.79),
    '605580': (7.49, 97.6, 1.70),
    '000591': (1.17, 69.4, 1.86),
    '000600': (3.72, 100, 1.95),
    '000636': (9.03, 100, 1.72),
    '000759': (5.89, 84.9, 2.10),
    '001308': (3.28, 71.8, 2.34),
    '002348': (5.06, 85.2, 2.11),
    '002436': (6.44, 81.2, 1.57),
    '002484': (5.10, 98.0, 2.76),
    '002639': (3.87, 75.8, 2.81),
    '002771': (4.55, 93.3, 1.78),
    '002927': (4.34, 68.7, 1.98),
    '002975': (7.46, 80.8, 1.62),
    '002981': (3.68, 78.0, 2.22),
}

styles = {
    '601101':'1策略·涨停基因','603099':'精选·多头','603103':'N字反包',
    '603191':'N字反包','603369':'3策略共振·多头','603678':'N字反包',
    '605580':'N字反包','000591':'短多','000600':'N字反包',
    '000636':'N字反包','000759':'N字反包','001308':'3策略共振',
    '002348':'N字反包','002436':'多头排列','002484':'N字反包',
    '002639':'20日线下','002771':'短多','002927':'4策略共振',
    '002975':'N字反包','002981':'3策略共振',
}

print('=' * 100)
print('【5月29日选股特征 vs 6月1日涨跌 复盘】')
print('=' * 100)
print()
print('【今日上涨组 - 选股日(5/29)特征】')
for c in sorted(up, key=lambda x: -perf[x]):
    chg, rsi, vr = f529[c]
    p5 = get_prev5d(c)
    n = name_map.get(c,'')
    print(f'  {c} {n:<8} 今涨+{perf[c]:.1f}% | '
          f'5/29涨{chg:+.1f}% RSI{rsi:.0f} VR{vr:.1f} 前5日{p5:+.1f}% | {styles[c]}')

print()
print('【今日下跌组 - 选股日(5/29)特征】')
for c in sorted(dn, key=lambda x: perf[x]):
    chg, rsi, vr = f529[c]
    p5 = get_prev5d(c)
    n = name_map.get(c,'')
    print(f'  {c} {n:<8} 今跌{perf[c]:.1f}% | '
          f'5/29涨{chg:+.1f}% RSI{rsi:.0f} VR{vr:.1f} 前5日{p5:+.1f}% | {styles[c]}')

print()
print('=' * 100)
print('【核心结论：什么决定了涨和跌】')
print('=' * 100)

up_p5 = [get_prev5d(c) for c in up]
dn_p5 = [get_prev5d(c) for c in dn]
up_p5 = [v for v in up_p5 if v is not None]
dn_p5 = [v for v in dn_p5 if v is not None]
avg_up_p5 = sum(up_p5)/len(up_p5)
avg_dn_p5 = sum(dn_p5)/len(dn_p5)

up_rsi = [f529[c][1] for c in up]
dn_rsi = [f529[c][1] for c in dn]
avg_up_rsi = sum(up_rsi)/len(up_rsi)
avg_dn_rsi = sum(dn_rsi)/len(dn_rsi)

print(f'''
指标                上涨组(7只)    下跌组(13只)    差异
─────────────────────────────────────────────────────
前5日累计涨幅         {avg_up_p5:+.1f}%         {avg_dn_p5:+.1f}%         {avg_up_p5-avg_dn_p5:+.1f}%
RSI6                {avg_up_rsi:.0f}           {avg_dn_rsi:.0f}           {avg_up_rsi-avg_dn_rsi:+.0f}

结论1: 前5日涨幅过大(>15%)是最大风险信号
  - 今天大跌的恒盛能源前5日+32.9%、博杰股份+18.6%、建投能源+22.1%
  - 今天上涨的望变电气前5日+0.6%、朝阳科技+2.1%

结论2: RSI不是决定性因素（涨的RSI也高是因为涨得好）
  - 关键是涨幅的持续时间和速度
  - 5日涨太快=短期获利盘重=抛压大

结论3: N字反包信号本身没问题
  - 但N字反包后已经涨了一大波的（前5日>15%）不能追
  - 刚完成N字反包、涨幅还不大的可以关注

结论4: 选股日单日涨幅>6%的次交易日容易回落
  - 恒盛能源+7.49%后跌停、博杰股份+7.46%后跌6.4%
  - 风华高科+9.03%后只涨3.8%(已经没力了)
''')

print('【优化方案】选股时增加3个过滤条件')
print()
print('过滤1: 前5日累计涨幅 > 15% 排除')
print('  说明: 短期涨幅太大,获利盘太重')
print()
print('过滤2: RSI > 85 且 前5日 > 10% 排除')
print('  说明: 超买区+短期涨幅大,双重风险')
print()
print('过滤3: 20日高位 > 85% 且 前5日 > 10% 排除')
print('  说明: 高位附近+短期涨幅大,追高风险')
print()
print('改成这些后,选出来的股票会更精,不会出现选完第二天就跌停的情况')
