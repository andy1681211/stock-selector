"""
Vercel Serverless Functions - 选股系统API
"""

import json
import os

# 模拟分析数据（Vercel云端无法访问通达信本地数据）
SAMPLE_DATA = {
    "stock": {"code": "300308", "name": "中际装备"},
    "latest": {
        "date": "2026-07-03",
        "close": 1116.0,
        "change_pct": -2.36,
        "volume_gu": 1359770566,
        "amount_yi": 0.33
    },
    "technical": {
        "ma5": 1194.43, "ma10": 1189.63, "ma20": 1175.20, "ma60": 1150.80,
        "macd_dif": 5.20, "macd_dea": 3.80, "macd_hist": 2.80,
        "rsi_14": 53.42
    },
    "key_levels": {
        "support": 865.24, "resistance": 1141.51,
        "boll_upper": 1493.85, "boll_mid": 912.03, "boll_lower": 330.21
    },
    "signals": [
        {"indicator": "均线", "signal": "多头", "detail": "MA5 > MA10 > MA20"},
        {"indicator": "MACD", "signal": "多头", "detail": "DIF > DEA"},
        {"indicator": "RSI", "signal": "中性", "detail": "RSI=53.42 正常区间"},
        {"indicator": "布林带", "signal": "中轨区域", "detail": "收盘价在中轨附近"},
        {"indicator": "成交量", "signal": "正常", "detail": "成交量处于正常水平"}
    ],
    "chanlun": {
        "detail": "无明确买卖点",
        "buy_point": None
    },
    "verdict": "偏多"
}

def app(event, context):
    """Vercel Serverless Handler"""
    
    path = event.get("path", event.get("requestContext", {}).get("httpPath", "/"))
    method = event.get("httpMethod", event.get("requestContext", {}).get("httpMethod", "GET"))
    
    # CORS headers
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    }
    
    if method == "OPTIONS":
        return {"statusCode": 204, "headers": headers, "body": ""}
    
    # 路由分发
    if path == "/api/health":
        return {
            "statusCode": 200,
            "headers": headers,
            "body": json.dumps({"status": "ok", "timestamp": "2026-07-04T20:00:00Z"}, ensure_ascii=False)
        }
    
    if path == "/api/analyze":
        query = event.get("queryStringParameters", {})
        code = query.get("code", "") if query else ""
        if not code:
            return {"statusCode": 400, "headers": headers, "body": json.dumps({"error": "请提供股票代码"}, ensure_ascii=False)}
        
        result = SAMPLE_DATA.copy()
        result["stock"]["code"] = code
        result["stock"]["name"] = f"股票{code}"  # 云端无法查真实名称
        return {"statusCode": 200, "headers": headers, "body": json.dumps(result, ensure_ascii=False, indent=2)}
    
    if path == "/api/daily":
        return {"statusCode": 200, "headers": headers, "body": json.dumps({"message": "每日精选数据将在交易日自动生成"}, ensure_ascii=False)}
    
    # 静态文件
    if path == "/" or path == "/index.html":
        return {"statusCode": 302, "headers": {"Location": "/index.html"}, "body": ""}
    
    return {"statusCode": 404, "headers": headers, "body": json.dumps({"error": "Not Found"}, ensure_ascii=False)}
