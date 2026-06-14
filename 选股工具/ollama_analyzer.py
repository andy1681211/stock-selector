#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ollama 本地大模型分析模块
=========================
用本地 Qwen/DeepSeek 模型对选股结果进行 AI 智能解读，
生成：市场点评、个股分析、风险提示、操作建议。

依赖: pip install requests (已内置)
模型: ollama pull qwen2:0.5b (已安装)
      可换 qwen2:7b / deepseek-r1:7b 效果更好

用法:
  from ollama_analyzer import analyze_results, generate_daily_commentary
  commentary = analyze_results(stock_list, market_state)
"""

import json
import requests
import time
from typing import List, Dict, Optional
from datetime import datetime

# ==================== 配置 ====================
OLLAMA_HOST = "http://localhost:11434"

# 模型优先级（按速度/质量排序）
# 主力模型：qwen2:1.5b（934MB，完整装入GTX960M 4GB显存，~4秒，日常首选）
# 均衡模型：qwen2.5:3b（1.9GB，完整装入显存，~15秒，质量更好）
# 深度模式：qwen2.5:7b（4.7GB，GPU+CPU混合，需等待数分钟适合深度分析）
# 降级模式：qwen2:0.5b（352MB，纯CPU飞快）
MODEL_PRIORITY = ["qwen2:1.5b", "qwen2.5:3b", "qwen2.5:7b", "qwen2:0.5b"]

# 自动选择当前可用的最佳模型
DEFAULT_MODEL = None  # 启动时自动检测
TIMEOUT = 120  # 单次请求超时秒数（大模型慢一些）
_DETECTED = False  # 模型检测标记


# ==================== Ollama API 调用 ====================

def _get_best_model() -> str:
    """
    自动检测当前可用的最佳模型
    按 MODEL_PRIORITY 顺序检查本地已安装的模型
    """
    global DEFAULT_MODEL, _DETECTED
    if DEFAULT_MODEL and _DETECTED:
        return DEFAULT_MODEL

    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        if resp.status_code == 200:
            local_models = [m["name"] for m in resp.json().get("models", [])]
            for m in MODEL_PRIORITY:
                if m in local_models:
                    DEFAULT_MODEL = m
                    _DETECTED = True
                    return m
    except:
        pass

    # 都不可用，用第一个配置的
    DEFAULT_MODEL = MODEL_PRIORITY[0]
    _DETECTED = False
    return DEFAULT_MODEL


def _call_ollama(prompt: str, model: str = None,
                 system: str = "", temperature: float = 0.3,
                 max_retry: int = 2) -> str:
    """
    调用 Ollama 本地模型

    Args:
        prompt: 用户提示
        model: 模型名称
        system: 系统提示词
        temperature: 生成温度 (越低越确定)
        max_retry: 最大重试次数

    Returns:
        模型生成的文本
    """
    # 自动选择最佳可用模型
    if model is None:
        model = _get_best_model()

    url = f"{OLLAMA_HOST}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "temperature": temperature,
        "stream": False,
        "options": {
            "num_predict": 1024,
            "stop": ["<|im_end|>", "<|endoftext|>"],
        }
    }

    for attempt in range(max_retry + 1):
        try:
            resp = requests.post(url, json=payload, timeout=TIMEOUT)
            if resp.status_code == 200:
                result = resp.json()
                text = result.get("response", "").strip()
                if text:
                    return text
            else:
                if attempt < max_retry:
                    time.sleep(1)
                    continue
                return f"[API错误 {resp.status_code}]"
        except requests.exceptions.ConnectionError:
            if attempt < max_retry:
                time.sleep(2)
                continue
            return "[连接失败: Ollama未启动]"
        except requests.exceptions.Timeout:
            if attempt < max_retry:
                time.sleep(1)
                continue
            return "[超时]"
        except Exception as e:
            return f"[错误: {e}]"

    return "[重试失败]"


def _check_ollama_alive() -> bool:
    """检查 Ollama 服务是否在运行"""
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        return resp.status_code == 200
    except:
        return False


# ==================== AI 分析函数 ====================

def analyze_market_state(regime_info: Dict) -> str:
    """
    对市场状态进行 AI 解读

    Args:
        regime_info: market_regime.detect_market_regime() 的返回值

    Returns:
        市场状态解读文本（几句话）
    """
    if not regime_info:
        return ""

    regime = regime_info.get("regime", "未知")
    trend = regime_info.get("trend", "未知")
    strength = regime_info.get("strength", "中")
    score = regime_info.get("score", 0)
    recent_5d = regime_info.get("recent_5d", 0)
    recent_20d = regime_info.get("recent_20d", 0)
    suggestion = regime_info.get("suggestion", "")
    vol_ratio = regime_info.get("vol_ratio", 1.0)
    macd = regime_info.get("macd_bull", "未知")

    prompt = f"""你是资深A股市场分析师。请根据以下市场技术指标，给出简洁专业的市场点评（80-150字）。

市场状态: {regime}
趋势方向: {trend}
综合评分: {score}/100
近5日涨幅: {recent_5d}%
近20日涨幅: {recent_20d}%
量能比: {vol_ratio}
MACD: {macd}
策略建议: {suggestion}

请指出当前市场核心矛盾、适合什么操作策略、需要注意什么风险。"""

    system = "你是一位从业15年的A股市场分析师，擅长技术分析和市场情绪判断。回答简洁专业，不说废话。"

    return _call_ollama(prompt, system=system)


def analyze_top_stocks(stocks: List[Dict], top_n: int = 5) -> str:
    """
    对精选个股进行 AI 分析

    Args:
        stocks: 选股结果列表（含策略命中/信号等字段）
        top_n: 分析前几只

    Returns:
        个股分析文本
    """
    if not stocks:
        return ""

    # 按策略命中排序
    sorted_stocks = sorted(
        stocks,
        key=lambda x: (
            x.get("策略命中", 0),
            x.get("置信度", 0),
            abs(float(x.get("涨跌幅", 0) or 0))
        ),
        reverse=True,
    )

    top = sorted_stocks[:top_n]
    if not top:
        return ""

    # 构建股票信息摘要
    stock_lines = []
    for i, s in enumerate(top, 1):
        code = s.get("代码", "")
        name = s.get("名称", "")
        chg = s.get("涨跌幅", "")
        vol_ratio = s.get("量比", "")
        pbq = s.get("平步青云", "无评分")
        signals = s.get("策略组合", s.get("信号", ""))
        chip = s.get("筹码评分", "")
        conf = s.get("置信度", "")
        conf_level = s.get("置信等级", "")

        # 收集所有信号标签
        tags = []
        for k in ["低吸买点", "缠论买点", "洗盘结束", "倍量突破", "回踩买点",
                  "底分型", "建仓型涨停", "洗盘型涨停", "二进三信号",
                  "主升浪起爆", "试盘线", "平步青云强", "飞龙在天", "潜龙回首"]:
            if s.get(k, ""):
                tags.append(k)
        tag_str = "、".join(tags[:5]) if tags else "—"

        stock_lines.append(
            f"股票{i}: {name}({code}) "
            f"涨幅{chg}% 量比{vol_ratio} "
            f"平步青云:{pbq} "
            f"策略: {signals[:40] if signals else '—'} "
            f"信号: {tag_str} "
            f"筹码评分: {chip} "
            f"置信度: {conf}({conf_level})"
        )

    stock_text = "\n".join(stock_lines)

    prompt = f"""你是资深短线交易员。以下是一组AI量化选股系统今天选出的潜力股，请针对前{top_n}只逐一给出简短点评（每只1-2句话），最后用一两句话总结共同特征。

选股结果：
{stock_text}

点评要求：
1. 指出每只股票的核心亮点（为什么值得关注）
2. 指出每只股票的操作注意事项（什么位置介入、什么风险）
3. 说明这些股票的共同特征（当前市场风格）"""

    system = "你是一位实战派短线交易员，每天复盘选股结果。点评要求专业、简洁、有操作性。不敷衍不套话。"

    return _call_ollama(prompt, system=system)


def generate_daily_summary(stock_count: int, strategies_used: List[str],
                            top_picks: List[Dict], market_state: str = "") -> str:
    """
    生成每日交易策略总结

    Args:
        stock_count: 总共选出多少只
        strategies_used: 用了哪些策略
        top_picks: 强烈关注的股票
        market_state: 市场状态

    Returns:
        每日总结文本
    """
    strategy_text = "、".join(strategies_used) if strategies_used else "本地扫盘"

    # 精选股票摘要
    picks_text = ""
    for s in top_picks[:3]:
        features = []
        for k in ["平步青云强", "建仓型涨停", "主升浪起爆", "飞龙在天", "洗盘结束"]:
            if s.get(k, ""):
                features.append(k)
        feat_str = "、".join(features) if features else "多策略共振"
        picks_text += f"- {s.get('名称','')}({s.get('代码','')}) 涨幅{s.get('涨跌幅','')}% [{feat_str}]\n"

    prompt = f"""你是A股短线交易复盘助手。请根据以下选股结果生成一份简短的每日交易策略总结（100-150字）。

今日选股概况：
- 启动策略: {strategy_text}
- 共选出: {stock_count} 只
- 市场状态: {market_state}

强烈关注:
{picks_text}

请指出：
1. 今天选出的股票属于什么风格（进攻型/防守型/均衡）
2. 明天操作的策略重点
3. 一句核心提醒"""

    system = "你是一位实战交易员，总结要简明扼要，直击重点，有操作指导性。"

    return _call_ollama(prompt, system=system)


def analyze_single_stock(stock_info: Dict, kline_summary: str = "") -> str:
    """
    对单只股票进行深度分析

    Args:
        stock_info: 单只股票的所有字段
        kline_summary: 近期K线走势摘要

    Returns:
        分析建议文本
    """
    name = stock_info.get("名称", "")
    code = stock_info.get("代码", "")
    chg = stock_info.get("涨跌幅", "")
    price = stock_info.get("最新价", "")
    pbq = stock_info.get("平步青云", "")
    pbq_strong = stock_info.get("平步青云强", "") == "是"
    signals = []

    signal_map = {
        "洗盘结束": "洗盘结束信号",
        "倍量突破": "倍量突破信号",
        "底分型": "缠论底分型",
        "回踩买点": "回踩买点",
        "缠论买点": "缠论买点",
        "低吸买点": "低吸买点",
        "九爆发": "九爆发信号",
        "三破七入": "三破七入信号",
        "建仓型涨停": "建仓型涨停",
        "洗盘型涨停": "洗盘型涨停",
        "二进三信号": "二进三战法",
        "主升浪起爆": "主升浪起爆信号",
        "飞龙在天": "飞龙在天模式",
        "潜龙回首": "潜龙回首模式",
    }
    for field, label in signal_map.items():
        val = stock_info.get(field, "")
        if val:
            signals.append(f"{label}({str(val)[:30]})")

    signal_text = "；".join(signals) if signals else "基础选股信号"
    ma_angle = stock_info.get("MA角度", "未知")
    ma5 = stock_info.get("MA5", "")
    ma20 = stock_info.get("MA20", "")

    prompt = f"""你是短线交易顾问。以下是今日量化系统选出的个股信息，请给出操作建议。

股票: {name}({code})
现价: {price}  当日涨幅: {chg}%
平步青云评分: {pbq}  {'★强信号' if pbq_strong else ''}
均线: MA5={ma5} MA20={ma20} 角度={ma_angle}
触发信号: {signal_text}
{Kline走势: {kline_summary} if kline_summary else ''}

请给出（100字以内）：
1. 核心逻辑一句话
2. 明日关注要点
3. 止损参考"""

    system = "你是一位谨慎的短线交易顾问。回答要具体、有可操作性、不模棱两可。"

    return _call_ollama(prompt, system=system)


# ==================== 一键集成 ====================

def enhance_report_with_ai(report_text: str, stocks: List[Dict],
                            regime_info: Dict = None,
                            model: str = None) -> str:
    """
    给现有选股报告添加AI分析内容

    Args:
        report_text: 原始报告文本
        stocks: 选股结果列表
        regime_info: 市场状态信息
        model: 模型名称（None=自动选最佳）

    Returns:
        增强后的报告（原始报告 + AI分析部分）
    """
    alive = _check_ollama_alive()
    if not alive:
        print("  [Ollama] 服务未运行，跳过AI分析")
        return report_text

    model = model or _get_best_model()
    print(f"  [Ollama] 使用 {model} 模型生成AI分析...")

    # 1. 市场分析
    market_analysis = ""
    if regime_info:
        print("    → 分析市场状态...")
        market_analysis = analyze_market_state(regime_info)

    # 2. 个股分析
    print("    → 分析精选个股...")
    top = sorted(stocks, key=lambda x: (
        x.get("策略命中", 0), x.get("置信度", 0),
        abs(float(x.get("涨跌幅", 0) or 0))
    ), reverse=True)[:5]
    stock_analysis = analyze_top_stocks(stocks, top_n=5)

    # 3. 汇总
    strategies = list(set(
        s.get("策略组合", "").replace(" + ", "、")
        for s in stocks if s.get("策略组合", "")
    )) or ["多策略共振"]

    summary = generate_daily_summary(
        stock_count=len(stocks),
        strategies_used=strategies,
        top_picks=top,
        market_state=regime_info.get("regime", "") if regime_info else "",
    )

    # 组装AI分析部分
    model_name = model or _get_best_model()
    ai_section = f"""
╔══ AI 智能分析（{model_name}）══════════════════════════════╗
║  {datetime.now().strftime('%Y-%m-%d %H:%M')} 生成
╚═════════════════════════════════════════════════╝

【今日小结】
{summary}

【市场状态点评】
{market_analysis}

【精选个股点评】
{stock_analysis}

【风险提示】
⚠ 以上分析由AI辅助生成，仅供参考，不构成投资建议。
⚠ 短线交易请严格止损，单票仓位不超过25%。
"""

    return report_text + ai_section


def print_ai_banner() -> str:
    """
    返回Ollama服务状态的横幅提示
    """
    alive = _check_ollama_alive()
    if alive:
        model = _get_best_model()
        return f"  [Ollama] {model} 在线"
    else:
        return f"  [Ollama] 未启动"


# ==================== 独立运行测试 ====================

if __name__ == "__main__":
    import os
    # 设置UTF-8环境避免打印emoji报错
    os.environ["PYTHONIOENCODING"] = "utf-8"

    print("=" * 50)
    print("  Ollama 分析模块测试")
    print("=" * 50)

    alive = _check_ollama_alive()
    if not alive:
        print("!! Ollama 服务未运行！请先执行: ollama serve")
        print("   或检查: http://localhost:11434")
        exit(1)

    best = _get_best_model()
    print(f"[OK] Ollama 服务运行中，模型: {best}")
    print()

    # 测试1: 简单对话
    print("--- 测试1: 基础对话 ---")
    resp = _call_ollama("请用一句话描述A股短线交易的核心原则。",
                         system="你是资深交易员，回答简洁。")
    print(f"  {resp}")
    print()

    # 测试2: 市场分析
    print("--- 测试2: 市场分析 ---")
    regime_test = {
        "regime": "振荡市",
        "trend": "横盘",
        "strength": "中",
        "score": 35,
        "recent_5d": -1.2,
        "recent_20d": 2.5,
        "vol_ratio": 0.85,
        "macd_bull": "空头",
        "suggestion": "N字反包 + 低位放量首板（高抛低吸）",
    }
    result = analyze_market_state(regime_test)
    print(f"  {result}")
    print()

    # 测试3: 个股分析
    print("--- 测试3: 个股分析 ---")
    stocks_test = [
        {"代码": "600519", "名称": "贵州茅台", "涨跌幅": "2.5",
         "量比": "1.8", "平步青云": "72分", "策略组合": "趋势加速",
         "洗盘结束": "放量确认", "置信度": 75, "置信等级": "关注"},
        {"代码": "000858", "名称": "五粮液", "涨跌幅": "3.2",
         "量比": "2.1", "平步青云": "65分", "策略组合": "低位放量首板",
         "倍量突破": "倍量+阳线", "置信度": 68, "置信等级": "关注"},
    ]
    result = analyze_top_stocks(stocks_test, top_n=2)
    print(f"  {result}")
    print()

    print("[OK] 全部测试完成！")
