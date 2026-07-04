"""
海哥选股器 - 股票分析 API
输入股票代码，返回技术分析结果
"""

import json
from datetime import datetime

def main(event, context):
    """Vercel Serverless Function"""
    
    # 获取请求参数
    query_params = event.get('queryStringParameters', {})
    stock_code = query_params.get('code', '')
    
    if not stock_code:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "请提供股票代码"}, ensure_ascii=False)
        }
    
    # 模拟分析结果（实际项目中这里会调用技术分析系统）
    analysis = {
        "code": stock_code,
        "name": "示例股票",
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
