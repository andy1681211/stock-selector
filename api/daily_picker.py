"""
海哥选股器 - 每日精选 API
返回每日精选的候选股列表
"""

import json
from datetime import datetime

def main(event, context):
    """Vercel Serverless Function"""
    
    # 模拟选股数据（实际项目中这里会调用选股系统）
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
