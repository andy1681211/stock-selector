#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
将每日选股结果同步到 web_stock_picker/data/ 目录
供 GitHub Pages 前端直接读取
"""
import os
import json
import shutil
from datetime import datetime

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_SRC = os.path.join(WORKSPACE, 'data')
WEB_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

def sync_daily_pick():
    """同步最新的 daily_pick_*.json 到 web 数据目录"""
    os.makedirs(WEB_DATA, exist_ok=True)
    
    # 找最新的 daily_pick 文件
    pick_files = [f for f in os.listdir(DATA_SRC) 
                  if f.startswith('daily_pick_') and f.endswith('.json')]
    
    if not pick_files:
        print("⚠️ 未找到 daily_pick 数据文件")
        return False
    
    # 按日期排序
    def extract_date(fname):
        m = fname.replace('daily_pick_', '').replace('.json', '')
        return m
    
    pick_files.sort(key=extract_date, reverse=True)
    latest = pick_files[0]
    
    src = os.path.join(DATA_SRC, latest)
    dst = os.path.join(WEB_DATA, 'latest_pick.json')
    
    with open(src, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 简化数据结构，去掉冗余字段
    simplified = {
        'date': extract_date(latest),
        'timestamp': datetime.now().isoformat(),
        'recommendations': data.get('recommendations', data.get('picks', [])),
        'market_overview': data.get('market_overview', data.get('summary', '')),
        'overall_signal': data.get('overall_signal', '观望')
    }
    
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(simplified, f, ensure_ascii=False, indent=2)
    
    print("[OK] 已同步 %s -> web_stock_picker/data/latest_pick.json" % latest)
    return True

def sync_sector():
    """同步板块数据"""
    os.makedirs(WEB_DATA, exist_ok=True)
    
    # 如果有 sector 数据文件，也同步
    sector_files = [f for f in os.listdir(DATA_SRC) 
                    if 'sector' in f.lower() and f.endswith('.txt')]
    
    if sector_files:
        src = os.path.join(DATA_SRC, sector_files[-1])
        dst = os.path.join(WEB_DATA, 'sectors.txt')
        shutil.copy2(src, dst)
        print("[OK] 已同步板块数据")

if __name__ == '__main__':
    sync_daily_pick()
    sync_sector()
    print("Data sync complete")
