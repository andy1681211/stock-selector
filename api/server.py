# -*- coding: utf-8 -*-
"""
海哥选股系统 Web API
提供技术分析 + 每日精选选股
"""
import sys
import os
import json
from flask import Flask, jsonify, request

app = Flask(__name__)

# 添加 scripts 目录到路径
scripts_path = os.path.join(os.path.dirname(__file__), '..', 'scripts')
if scripts_path not in sys.path:
    sys.path.insert(0, scripts_path)

from tdx_analyzer import TDXAnalyzer
from auction_picker import get_daily_candidates

# 初始化分析器
analyzer = TDXAnalyzer()


@app.route('/api/analyze', methods=['GET'])
def analyze():
    """分析个股技术面"""
    code = request.args.get('code', '000006')
    
    if not code or len(code) != 6:
        return jsonify({'error': '请输入6位股票代码'})
    
    result = analyzer.analyze_stock(code)
    
    if not result:
        return jsonify({'error': '未能获取数据，请检查股票代码'})
    
    return jsonify({
        'code': code,
        'name': result.get('name', '未知'),
        'price': result.get('close', 0),
        'macd': result.get('macd', {}),
        'kdj': result.get('kdj', {}),
        'boll': result.get('boll', {}),
        'score': result.get('score', 0),
        'signal': result.get('signal', '观望')
    })


@app.route('/api/daily', methods=['GET'])
def daily():
    """获取每日精选候选股"""
    candidates = get_daily_candidates()
    
    if not candidates:
        return jsonify({'error': '未能获取候选股数据'})
    
    return jsonify({
        'date': '2026-07-03',
        'candidates': candidates[:5]  # 返回前5只
    })


@app.route('/api/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({'status': 'ok', 'message': '海哥选股系统运行正常'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=True)
