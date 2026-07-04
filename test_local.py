"""
本地测试脚本 - 验证选股和分析功能
"""

import json
import sys
import os
from datetime import datetime

# 模拟 Vercel 事件对象
def create_mock_event(path, query_params=None, http_method='GET'):
    return {
        'path': path,
        'queryStringParameters': query_params or {},
        'httpMethod': http_method
    }

# 测试每日选股 API
def test_daily_picker():
    print("🧪 测试每日选股 API...")
    
    # 模拟请求
    event = create_mock_event('/api/daily_picker.py')
    
    # 导入路由处理函数
    sys.path.insert(0, 'api')
    from route import handle_daily_picker
    
    # 执行处理
    response = handle_daily_picker(event, None)
    
    # 验证响应
    assert response['statusCode'] == 200, f"状态码错误: {response['statusCode']}"
    
    body = json.loads(response['body'])
    assert body['status'] == 'success', f"状态错误: {body['status']}"
    assert 'data' in body, "缺少 data 字段"
    assert len(body['data']) > 0, "股票数据为空"
    
    print("PASS: 每日选股 API 测试通过!")
    print(f"   返回 {len(body['data'])} 只股票")
    for stock in body['data'][:2]:  # 只显示前两只
        print(f"   - {stock['code']} {stock['name']} ({stock['score']}分)")
    
    return True

# 测试股票分析 API
def test_stock_analysis():
    print("\n🧪 测试股票分析 API...")
    
    # 测试有效股票代码
    test_cases = [
        {'code': '000006'},
        {'code': '600941'},
        {'code': '002156'}
    ]
    
    sys.path.insert(0, 'api')
    from route import handle_analyze
    
    for test_case in test_cases:
        event = create_mock_event('/api/analyze.py', test_case)
        response = handle_analyze(event, None)
        
        assert response['statusCode'] == 200, f"状态码错误: {response['statusCode']}"
        
        body = json.loads(response['body'])
        assert body['status'] == 'success', f"状态错误: {body['status']}"
        assert 'data' in body, "缺少 data 字段"
        
        analysis = body['data']
        assert 'technical' in analysis, "缺少技术分析数据"
        assert 'score' in analysis, "缺少评分"
        
        print(f"PASS: {test_case['code']} 分析测试通过!")
        print(f"   评分: {analysis['score']}/10")
        print(f"   建议: {analysis['recommendation']}")
    
    # 测试无效请求（缺少股票代码）
    event = create_mock_event('/api/analyze.py', {})
    response = handle_analyze(event, None)
    assert response['statusCode'] == 400, "缺少股票代码时应返回 400"
    print(f"PASS: 错误处理测试通过!")
    
    return True

# 测试前端页面
def test_frontend():
    print("\n🧪 测试前端页面...")
    
    if os.path.exists('dist/index.html'):
        with open('dist/index.html', 'r', encoding='utf-8') as f:
            content = f.read()
            
        assert '<title>海哥选股器</title>' in content, "缺少页面标题"
        assert '每日精选' in content, "缺少每日精选功能"
        assert '个股分析' in content, "缺少个股分析功能"
        assert 'fetch' in content, "缺少 API 调用"
        
        print(f"PASS: 前端页面测试通过!")
        print(f"   页面大小: {len(content)} 字节")
        return True
    else:
        print("FAIL: 前端页面不存在!")
        return False

# 主测试流程
def main():
    print("=" * 50)
    print("TEST: 海哥选股器 - 功能验证测试")
    print("=" * 50)
    
    all_passed = True
    
    try:
        # 测试每日选股
        if not test_daily_picker():
            all_passed = False
    except Exception as e:
        print(f"FAIL: 每日选股测试失败: {e}")
        all_passed = False
    
    try:
        # 测试股票分析
        if not test_stock_analysis():
            all_passed = False
    except Exception as e:
        print(f"FAIL: 股票分析测试失败: {e}")
        all_passed = False
    
    try:
        # 测试前端页面
        if not test_frontend():
            all_passed = False
    except Exception as e:
        print(f"FAIL: 前端测试失败: {e}")
        all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("ALL TESTS PASSED! System ready for deployment!")
        print("=" * 50)
        return 0
    else:
        print("SOME TESTS FAILED, please check!")
        print("=" * 50)
        return 1

if __name__ == '__main__':
    sys.exit(main())
