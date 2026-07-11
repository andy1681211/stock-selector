# -*- coding: utf-8 -*-
import sys
import os
import json
from datetime import datetime

# 添加 scripts 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# 导入选股记忆系统
try:
    from stock_memory import get_accuracy_stats, get_daily_summary
except ImportError:
    def get_accuracy_stats(): return {"total_tracked": 0}
    def get_daily_summary(*args, **kwargs): return {"count": 0, "recommendations": []}

# 导入资金流向模块
try:
    from fund_flow import get_sector_fund_flow, get_concept_sector_ranking
except ImportError:
    def get_sector_fund_flow(*args, **kwargs): return []
    def get_concept_sector_ranking(*args, **kwargs): return []

# 导入自动推送模块
try:
    from auto_push import push_daily_picks, push_stock_analysis
except ImportError:
    def push_daily_picks(*args, **kwargs): return None
    def push_stock_analysis(*args, **kwargs): return None

app = Flask(__name__, static_folder='.')
CORS(app)  # 允许所有来源跨域访问

WORKSPACE = os.path.dirname(__file__)
SCRIPTS_DIR = os.path.join(WORKSPACE, '..', 'scripts')

# 股票名称缓存
_STOCK_NAMES = None

def get_stock_names():
    """从通达信 profile.dat 解析股票名称"""
    global _STOCK_NAMES
    if _STOCK_NAMES is not None:
        return _STOCK_NAMES
    
    _STOCK_NAMES = {}
    profile_path = r'D:\new_tdx\T0002\hq_cache\profile.dat'
    if not os.path.exists(profile_path):
        return _STOCK_NAMES
    
    try:
        with open(profile_path, 'rb') as f:
            data = f.read()
        import re
        # 匹配: 6位数字 + \x00 + 名称(GBK字节, 2-15字节, 不含\x00) + \x00
        pattern = rb'(\d{6})\x00([\x80-\xff\x20-\x7f]{2,15})\x00'
        matches = re.findall(pattern, data)
        for code_bytes, name_bytes in matches:
            code = code_bytes.decode('ascii')
            name = name_bytes.decode('gbk', errors='ignore').strip()
            if name and code not in _STOCK_NAMES:
                _STOCK_NAMES[code] = name
    except Exception:
        pass
    return _STOCK_NAMES

def get_stock_name(code):
    """获取股票名称"""
    names = get_stock_names()
    return names.get(code, '未知')

def analyze_stock(code):
    """分析单只股票的技术面"""
    try:
        from tdx_analyzer import analyze_stock as tdx_analyze
        # 判断沪市(sh)还是深市(sz)
        if code.startswith(('6', '9')):
            prefix = 'sh'
        else:
            prefix = 'sz'
        tdx_path = rf'D:\new_tdx\vipdoc\{prefix}\lday\{prefix}{code}.day'
        if not os.path.exists(tdx_path):
            return {'error': f'未找到 {code} 的日线数据: {tdx_path}'}
        result = tdx_analyze(tdx_path, '测试', code)
        # 覆盖名称字段
        result['stock'] = {'code': code, 'name': get_stock_name(code)}
        return result
    except Exception as e:
        return {'error': str(e)}

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

@app.route('/api/memory/stats')
def memory_stats():
    """选股记忆统计"""
    return jsonify(get_accuracy_stats())

@app.route('/api/memory/daily/<date_str>')
def memory_daily(date_str):
    """某天的选股记录"""
    return jsonify(get_daily_summary(date_str))

@app.route('/api/memory/daily/latest')
def memory_daily_latest():
    """最新一天的选股记录"""
    return jsonify(get_daily_summary())

@app.route('/api/fund-flow/sectors')
def fund_flow_sectors():
    """板块资金流向"""
    sectors = get_sector_fund_flow(page=1, size=20)
    return jsonify({"sectors": sectors, "timestamp": datetime.now().isoformat()})

@app.route('/api/fund-flow/concepts')
def fund_flow_concepts():
    """概念板块资金流向"""
    concepts = get_concept_sector_ranking(top_n=10)
    return jsonify({"concepts": concepts, "timestamp": datetime.now().isoformat()})

@app.route('/api/analyze')
def api_analyze():
    code = request.args.get('code', '')
    if not code:
        return jsonify({'error': '请提供股票代码'}), 400
    result = analyze_stock(code)
    return jsonify(result)

@app.route('/api/daily')
def api_daily():
    """返回每日精选"""
    today = datetime.now().strftime('%Y-%m-%d')
    # 尝试今天的文件
    test_file = os.path.join(WORKSPACE, 'data', f'daily_{today}.json')
    if not os.path.exists(test_file):
        # 尝试 workspace/data/ 下的 daily_pick_*.json
        workspace_data = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', f'daily_pick_{today}.json')
        if os.path.exists(workspace_data):
            test_file = workspace_data
    # 如果今天没有，找最近一次的
    if not os.path.exists(test_file):
        workspace_data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
        pick_files = [f for f in os.listdir(workspace_data_dir) if f.startswith('daily_pick_') and f.endswith('.json')]
        # 提取日期部分排序（daily_pick_YYYY-MM-DD.json 或 daily_pick_v3_YYYY-MM-DD.json）
        import re
        def extract_date(fname):
            m = re.search(r'(\d{4}-\d{2}-\d{2})', fname)
            return m.group(1) if m else '0000-00-00'
        pick_files.sort(key=extract_date, reverse=True)
        if pick_files:
            test_file = os.path.join(workspace_data_dir, pick_files[0])
    
    if os.path.exists(test_file):
        with open(test_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 自动推送到微信
        push_file = push_daily_picks(data)
        if push_file:
            data['push_sent'] = True
            data['push_file'] = push_file
        
        return jsonify(data)
    
    return jsonify({'message': '暂无每日精选数据'})

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=False)
