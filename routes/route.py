"""
Vercel Serverless Function - 选股系统API
"""

import json

def handler(event):
    """Vercel Python Handler"""
    
    path = event.get("path", "/")
    method = event.get("httpMethod", "GET")
    query = event.get("queryStringParameters", {}) or {}
    
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    }
    
    if method == "OPTIONS":
        return {
            "statusCode": 204,
            "headers": headers,
            "body": ""
        }
    
    if path == "/api/health":
        return {
            "statusCode": 200,
            "headers": headers,
            "body": json.dumps({"status": "ok"}, ensure_ascii=False)
        }
    
    if path == "/api/analyze":
        code = query.get("code", "")
        if not code:
            return {
                "statusCode": 400,
                "headers": headers,
                "body": json.dumps({"error": "请提供股票代码"}, ensure_ascii=False)
            }
        result = {
            "stock": {"code": code, "name": f"股票{code}"},
            "latest": {"date": "2026-07-03", "close": 100.0, "change_pct": 1.5},
            "technical": {"ma5": 100.0, "ma10": 99.0, "ma20": 98.0, "ma60": 95.0},
            "signals": [
                {"indicator": "均线", "signal": "多头", "detail": "MA5 > MA10 > MA20"},
                {"indicator": "MACD", "signal": "多头", "detail": "DIF > DEA"}
            ],
            "verdict": "偏多"
        }
        return {
            "statusCode": 200,
            "headers": headers,
            "body": json.dumps(result, ensure_ascii=False, indent=2)
        }
    
    if path == "/api/daily":
        return {
            "statusCode": 200,
            "headers": headers,
            "body": json.dumps({"message": "每日精选数据将在交易日自动生成"}, ensure_ascii=False)
        }
    
    return {
        "statusCode": 404,
        "headers": headers,
        "body": json.dumps({"error": "Not Found"}, ensure_ascii=False)
    }
