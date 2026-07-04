"""
路由层 - 根据请求路径分发到对应的 API
"""

import json
import sys
import os

# 添加当前目录到路径以便导入其他API模块
sys.path.append(os.path.dirname(__file__))

def main(event, context):
    """统一路由入口"""
    
    # 获取请求路径
    path = event.get('path', '/')
    http_method = event.get('httpMethod', 'GET')
    
    # 路由分发
    if path == '/api/daily_picker.py' or path == '/api/daily_picker':
        return handle_daily_picker(event, context)
    elif path == '/api/analyze.py' or path == '/api/analyze':
        return handle_analyze(event, context)
    else:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "Not Found"}, ensure_ascii=False)
        }

def handle_daily_picker(event, context):
    """处理每日精选请求"""
    try:
        # 这里应该导入并调用 daily_picker.py 的逻辑
        # 为了简化，直接返回模拟数据
        from datetime import datetime
        stocks = [
            {"code": "600941", "name": "中国移动", "score": 8.5, "reason": "5G建设加速"},
            {"code": "002156", "name": "通富微电", "score": 7.8, "reason": "半导体国产化"},
            {"code": "600584", "name": "长电科技", "score": 7.5, "reason": "封测行业复苏"},
            {"code": "002371", "name": "北方华创", "score": 7.2, "reason": "设备国产替代"}
        ]
        
        response = {
            "status": "success",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "data": stocks
        }
        
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps(response, ensure_ascii=False, indent=2)
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}, ensure_ascii=False)
        }

def handle_analyze(event, context):
    """处理股票分析请求"""
    try:
        query_params = event.get('queryStringParameters', {})
        stock_code = query_params.get('code', '')
        
        if not stock_code:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "请提供股票代码"}, ensure_ascii=False)
            }
        
        # 模拟分析结果
        from datetime import datetime
        analysis = {
            "code": stock_code,
            "name": f"股票{stock_code}",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "technical": {
                "macd": "空头排列",
                "kdj": "超卖区域", 
                "boll": "中轨附近",
                "volume": "缩量整理"
            },
            "score": 6.5,
            "recommendation": "观望",
            "risk_level": "中等"
        }
        
        response = {
            "status": "success",
            "data": analysis
        }
        
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps(response, ensure_ascii=False, indent=2)
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}, ensure_ascii=False)
        }
