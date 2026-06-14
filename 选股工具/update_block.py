# -*- coding: utf-8 -*-
"""用最新数据更新通达信板块"""
import sys, os, time
sys.path.insert(0, 'D:\\股票分析\\选股工具')
os.chdir('D:\\股票分析\\选股工具')
from local_screener import *

t0 = time.time()
results = run_local_screen()
print(f'选到 {len(results)} 只')

# 更新通达信板块
write_tdx_block(results)

# 找我俩关注的股票
targets = {'603997','600459'}
for r in results:
    if r['代码'] in targets:
        print(f'找到 {r["代码"]} {r["名称"]}: {r["涨跌幅"]}% 量比{r["量比"]} 缠论:{r["缠论买点"]} 中枢:{r["中枢位置"]}')

print(f'耗时 {time.time()-t0:.1f}秒')
