"""
短线选股策略系统 - 配置文件
2026年A股短线策略参数中心

已验证的API查询模式（测试通过）:
  - 今日涨幅大于x%小于y%
  - 昨日涨停
  - 换手率大于x%
  - 量比大于x
  - 成交额大于x亿
  - 均线多头排列
  - MACD金叉
  - 市盈率大于x小于y
  - 净资产收益率大于x
  - 总市值大于x亿
  - 10日内有过涨停
"""

import os
from pathlib import Path

# ===== 目录配置 =====
TOOL_DIR = Path(__file__).parent
PROJECT_DIR = TOOL_DIR.parent

# 妙想选股脚本路径
MX_XUANGU_DIR = r"C:\Users\Administrator\.claude\skills\mx-xuangu"

# 输出目录
OUTPUT_DIR = TOOL_DIR / "output"

# API Key（从环境变量读取）
MX_APIKEY = os.getenv("MX_APIKEY", "")

# ===== 策略开关与参数 =====

# 策略1: 低位放量首板
# 逻辑：股价低位首次放量大涨/涨停，换手率+量比双高确认资金介入
# 来源：龙头战法手册、国盛量价淘金因子研究
LOW_VOLUME_FIRST_BOARD = {
    "enabled": True,
    "weight": 1.0,
    "top_n": 15,
    "query": "今日涨幅大于3%小于9.5% 换手率大于5% 量比大于2 A股",
}

# 策略2: 连板接力弱转强
# 逻辑：昨日涨停，今日继续走强，连板接力核心信号
# 来源：连板接力实战指南、和讯情绪分析
CHAIN_BOARD_WEAK_TO_STRONG = {
    "enabled": True,
    "weight": 1.2,
    "top_n": 15,
    "query": "昨日涨停 非ST A股",
}

# 策略3: 趋势加速
# 逻辑：均线多头排列 + 放量 + MACD金叉 => 主升浪加速段
# 来源：国泰海通高频资金流策略、方正量价因子
TREND_ACCELERATION = {
    "enabled": True,
    "weight": 1.1,
    "top_n": 15,
    "query": "今日涨幅大于2%小于8% 均线多头排列 量比大于2 A股",
}

# 策略4: N字反包
# 逻辑：前期涨停基因 -> 回调 -> 再次放量走强，N字型突破
# 来源：游龙戏凤指标、涨停龙回头策略
N_SHAPE_REVERSAL = {
    "enabled": True,
    "weight": 0.9,
    "top_n": 15,
    "query": "今日涨幅大于3% 10日内有过涨停 A股",
}

# 策略5: 多维精选（基本面+技术面+资金面共振）
# 逻辑：基本面安全垫(PE合理+ROE高) + 技术面走强 + 资金活跃
# 来源：三维度过滤选股模型
MULTI_DIMENSION = {
    "enabled": True,
    "weight": 1.3,
    "top_n": 15,
    "query": "市盈率大于0小于60 净资产收益率大于10 今日涨幅大于2% 换手率大于3% A股",
}

# ===== 综合排名参数 =====
COMBINED = {
    "top_n": 15,             # 综合推荐前N只
    "min_strategies": 2,     # 至少出现在N个策略中才进入综合推荐
}

# ===== 微信推送密钥 =====
# 使用 Server酱（推荐）: 去 https://sct.ftqq.com 注册获取 SendKey
# 设置方式1(环境变量): set WECHAT_PUSH_KEY=SCT123...
# 设置方式2(写入此文件): 取消下面注释并填入密钥
# WECHAT_PUSH_KEY = "SCT1234567890abcdef"
WECHAT_PUSH_KEY = "SCT363733T5jYOYgRUYOA2C0mUCbUrHHmg"
