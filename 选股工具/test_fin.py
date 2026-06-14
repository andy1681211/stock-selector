# -*- coding: utf-8 -*-
"""测试基本面筛选"""
import sys
sys.path.insert(0, 'D:\\股票分析\\选股工具')
from fundamental_screen import get_finance_summary

for code in ['600459','603997','002823','002700','000960','603687']:
    fin = get_finance_summary(code)
    if fin:
        print(code + ': ROE=' + str(fin.get("roe","N/A")) + '% 利润增=' + str(fin.get("profit_growth",0)) + '% 营收增=' + str(fin.get("revenue_growth",0)) + '% 毛利率=' + str(fin.get("gross_margin","N/A")) + '% 负债率=' + str(fin.get("debt_ratio","N/A")) + '% 评分=' + str(fin.get("score",0)))
    else:
        print(code + ': 无财务数据')
