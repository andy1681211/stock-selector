#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多智能体辩论引擎 v1.0 — TradingAgents 架构移植
===============================================
让多个 AI 角色对选股结果进行多轮辩论后再出最终推荐。

流程:
  ReportAnalyst(整合现有系统数据)
  → BullResearcher + BearResearcher(多空辩论)
  → Trader(出交易计划)
  → RiskTeam(激进/保守/中立三方辩论)
  → PortfolioManager(最终拍板)

支持两种后端:
  1. Ollama 本地模型 (qwen2:1.5b, 免费离线)
  2. DeepSeek API (已配置 OPENAI_API_KEY, 效果更好)
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

TOOL_DIR = Path(__file__).parent

# ===== LLM 调用层 =====

def _call_llm(prompt: str, system: str = "", temperature: float = 0.3) -> str:
    """调用可用的LLM（优先DeepSeek API，备选Ollama）"""
    # 尝试DeepSeek API
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        try:
            from config import MX_APIKEY
        except ImportError:
            sys.path.insert(0, str(TOOL_DIR))
            from config import MX_APIKEY
        api_key = os.getenv("OPENAI_API_KEY", "")

    if api_key:
        return _call_deepseek(prompt, system, temperature)
    else:
        return _call_ollama(prompt, system, temperature)


def _call_deepseek(prompt: str, system: str = "", temperature: float = 0.3) -> str:
    """调用 DeepSeek API（通过兼容OpenAI接口）"""
    import urllib.request
    import json as _json

    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")

    url = f"{base_url.rstrip('/')}/chat/completions"
    data = _json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": 2048,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        })
    try:
        # 绕过代理
        os.environ["no_proxy"] = "*"
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[API错误: {e}]"


def _call_ollama(prompt: str, system: str = "", temperature: float = 0.3) -> str:
    """调用 Ollama 本地模型"""
    try:
        import requests
        resp = requests.post("http://localhost:11434/api/generate",
            json={
                "model": "qwen2:1.5b",
                "prompt": prompt,
                "system": system,
                "temperature": temperature,
                "stream": False,
                "options": {"num_predict": 1024},
            },
            timeout=120,
            proxies={"http": "", "https": ""},
        )
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
        return f"[Ollama错误: {resp.status_code}]"
    except Exception as e:
        return f"[Ollama不可用: {e}]"


# ===== 步骤1: 分析师报告 =====

def _step1_analyst_report(results: List[Dict], regime_info: dict = None) -> str:
    """整合现有系统的扫描结果，生成分析师报告"""
    lines = []
    lines.append("【全市场扫描报告】")
    lines.append(f"  扫描结果: {len(results)} 只符合条件")
    lines.append("")

    # 市场状态
    if regime_info:
        lines.append(f"  市场状态: {regime_info.get('regime','未知')}")
        lines.append(f"  评分: {regime_info.get('score',0)}/10")
        lines.append(f"  建议: {regime_info.get('suggestion','')}")
        lines.append("")

    # 高置信个股
    high_conf = [r for r in results if r.get("置信度", 0) >= 60]
    if high_conf:
        lines.append(f"【高置信个股】{len(high_conf)}只:")
        for r in high_conf[:8]:
            chg = r.get("涨跌幅", 0)
            conf = r.get("置信度", 0)
            tags = []
            for k in ["缠论买点", "平步青云强", "主升浪起爆", "飞龙在天", "潜龙回首", "底分型", "洗盘结束", "倍量突破"]:
                if r.get(k, ""):
                    tags.append(k[:4])
            lines.append(f"  {r['代码']} {r['名称']} 涨幅:{chg:+.1f}% 置信:{conf} {' '.join(tags[:4])}")

    # 热点板块
    try:
        from limit_up_catcher import get_hot_sectors_from_api
        sectors, _ = get_hot_sectors_from_api()
        if sectors:
            lines.append(f"\n【热点板块】{' '.join(sectors[:5])}")
    except Exception:
        pass

    return "\n".join(lines)


# ===== 步骤2: 多空研究员辩论 =====

def _step2_researcher_debate(stock: Dict, market_report: str) -> Tuple[str, str]:
    """看多 vs 看空研究员辩论"""
    code = stock.get("代码", "")
    name = stock.get("名称", "")
    chg = stock.get("涨跌幅", 0)
    conf = stock.get("置信度", 0)
    signals = [s for s in [
        stock.get("缠论买点", ""),
        "青云" if stock.get("平步青云强") == "是" else "",
        stock.get("主升浪起爆", ""),
        stock.get("飞龙在天", ""),
        stock.get("潜龙回首", ""),
        stock.get("洗盘结束", ""),
        stock.get("倍量突破", ""),
    ] if s]

    context = f"""
股票: {code} {name}
涨幅: {chg:+.1f}%
置信度: {conf}分
信号: {' '.join(signals[:5])}
平步青云评分: {stock.get('平步青云','N/A')}
量比: {stock.get('量比','N/A')}
"""

    system = "你是专业股票研究员，基于数据给出客观判断。请用中文回答，不超过200字。"

    # 看多
    bull_prompt = f"""{market_report}

{context}

作为【看多研究员】，请列出3个看多理由。只需输出理由，不要序号外的格式。"""
    bull = _call_llm(bull_prompt, system, 0.2)

    # 看空
    bear_prompt = f"""{market_report}

{context}

作为【看空研究员】，请列出3个看空理由。只需输出理由，不要序号外的格式。"""
    bear = _call_llm(bear_prompt, system, 0.2)

    return bull, bear


# ===== 步骤3: 交易员计划 =====

def _step3_trader_plan(stock: Dict, bull: str, bear: str) -> str:
    """交易员综合多空观点，给出交易计划"""
    code = stock.get("代码", "")
    name = stock.get("名称", "")
    close = stock.get("收盘", 0)
    stop = stock.get("止损价", 0)

    prompt = f"""股票: {code} {name}  当前价: {close}

看多观点: {bull}

看空观点: {bear}

作为交易员，请给出:
1. 操作建议(买入/持有/观望/卖出)
2. 仓位建议(轻仓<30%/半仓30-60%/重仓>60%)
3. 关键价位(支撑位/压力位/止损位)
4. 一句话理由

格式简洁，不超过150字。"""
    return _call_llm(prompt, "你是专业交易员，决策果断，用中文回答。", 0.2)


# ===== 步骤4: 风险团队辩论 =====

def _step4_risk_debate(trader_plan: str) -> Tuple[str, str, str]:
    """激进/保守/中立三方风险辩论"""
    system = "你是专业风控分析师，用中文回答，不超过100字。"

    # 激进风控
    aggressive = _call_llm(f"""交易员计划: {trader_plan}

作为【激进风控官】，你的任务是找机会。请指出：
1. 这个计划最大的机会在哪？
2. 为什么值得冒险？
3. 如果加仓会怎样？""", system, 0.4)

    # 保守风控
    conservative = _call_llm(f"""交易员计划: {trader_plan}

作为【保守风控官】，你的任务是防风险。请指出：
1. 这个计划最大的风险在哪？
2. 如果错了会亏多少？
3. 应该减仓吗？""", system, 0.1)

    # 中立风控
    neutral = _call_llm(f"""交易员计划: {trader_plan}

激进方说: {aggressive}
保守方说: {conservative}

作为【中立风控官】，请权衡双方观点，给出平衡建议。
1. 什么条件下应该执行？
2. 什么条件下应该放弃？""", system, 0.2)

    return aggressive, conservative, neutral


# ===== 步骤5: 投资组合经理最终决策 =====

def _step5_portfolio_decision(stock: Dict, bull: str, bear: str,
                                trader_plan: str, aggressive: str,
                                conservative: str, neutral: str) -> Dict:
    """投资组合经理综合全部信息，做出最终决策"""
    code = stock.get("代码", "")
    name = stock.get("名称", "")
    conf = stock.get("置信度", 0)

    prompt = f"""股票: {code} {name}
置信度: {conf}分

【多空辩论】
看多: {bull}
看空: {bear}

【交易员计划】
{trader_plan}

【风险辩论】
激进方: {aggressive}
保守方: {conservative}
中立方: {neutral}

作为【投资组合经理】，请给出最终决策，格式如下:
评级: 强烈买入/买入/持有/减仓/卖出
仓位: XX%
理由: 一句话
止损: XX
目标: XX"""

    system = "你是投资组合经理，全局视角，果断决策。用中文回答，不超过200字。"
    decision = _call_llm(prompt, system, 0.2)

    # 解析决策
    rating = "持有"
    position = 0
    reason = ""
    stop_loss = 0
    target = 0

    for line in decision.split("\n"):
        line = line.strip()
        if "评级" in line or "rating" in line.lower():
            for r in ["强烈买入", "买入", "持有", "减仓", "卖出"]:
                if r in line:
                    rating = r
                    break
        if "仓位" in line:
            try:
                position = int("".join(c for c in line.split(":")[-1] if c.isdigit() or c == "%").replace("%", ""))
            except:
                position = 50
        if "理由" in line:
            reason = line.split(":")[-1].strip()
        if "止损" in line:
            try:
                stop_loss = float("".join(c for c in line.split(":")[-1] if c.isdigit() or c == "."))
            except:
                pass
        if "目标" in line:
            try:
                target = float("".join(c for c in line.split(":")[-1] if c.isdigit() or c == "."))
            except:
                pass

    return {
        "stock": f"{code} {name}",
        "rating": rating,
        "position_pct": position,
        "reason": reason,
        "stop_loss": stop_loss,
        "target": target,
        "bull_case": bull[:100] + "..." if len(bull) > 100 else bull,
        "bear_case": bear[:100] + "..." if len(bear) > 100 else bear,
        "raw_decision": decision,
    }


# ===== 主函数：对一只股票进行完整辩论 =====

def debate_stock(stock: Dict, results: List[Dict] = None,
                 regime_info: dict = None, verbose: bool = True) -> Dict:
    """
    对一只股票运行完整的多智能体辩论流程。

    Args:
        stock: 单只股票数据
        results: 全量选股结果（用于生成市场报告）
        regime_info: 市场状态
        verbose: 是否打印过程

    Returns:
        {"stock": 名称, "rating": 评级, "position_pct": 仓位, ...}
    """
    if verbose:
        print(f"\n  {'='*50}")
        print(f"  [辩论] {stock.get('代码','')} {stock.get('名称','')}")
        print(f"  {'='*50}")

    # 步骤1: 分析师报告
    if verbose:
        print(f"  [1/5] 分析师报告...")
    market_report = _step1_analyst_report(results or [stock], regime_info)

    # 步骤2: 多空辩论
    if verbose:
        print(f"  [2/5] 多空研究员辩论...")
    bull, bear = _step2_researcher_debate(stock, market_report)

    # 步骤3: 交易员计划
    if verbose:
        print(f"  [3/5] 交易员评估...")
    trader_plan = _step3_trader_plan(stock, bull, bear)

    # 步骤4: 风险辩论
    if verbose:
        print(f"  [4/5] 风控团队辩论...")
    aggressive, conservative, neutral = _step4_risk_debate(trader_plan)

    # 步骤5: 最终决策
    if verbose:
        print(f"  [5/5] 投资组合经理决策...")
    decision = _step5_portfolio_decision(stock, bull, bear, trader_plan,
                                          aggressive, conservative, neutral)

    if verbose:
        print(f"\n  📋 最终决策: {decision['rating']} | 仓位: {decision['position_pct']}%")
        if decision["reason"]:
            print(f"     理由: {decision['reason']}")
        print(f"  {'='*50}")

    return decision


# ===== 批量辩论：对前N只高置信股票 =====

def debate_top_stocks(results: List[Dict], regime_info: dict = None,
                       top_n: int = 5, verbose: bool = True) -> List[Dict]:
    """
    对排名前N的高置信股票进行辩论式分析。

    Args:
        results: 选股结果
        regime_info: 市场状态
        top_n: 辩论几只
        verbose: 是否打印

    Returns:
        [决策1, 决策2, ...]
    """
    # 按置信度排序
    sorted_results = sorted(results, key=lambda r: -r.get("置信度", 0))
    candidates = sorted_results[:top_n]

    decisions = []
    for stock in candidates:
        d = debate_stock(stock, results, regime_info, verbose)
        decisions.append(d)

    return decisions


# ===== 报告格式化 =====

def format_debate_report(decisions: List[Dict]) -> str:
    """格式化辩论报告"""
    lines = ["=" * 60]
    lines.append("  📋 多智能体辩论报告")
    lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"  流程: 分析师→多空辩论→交易员→风控→PM决策")
    lines.append("=" * 60)
    lines.append("")

    for d in decisions:
        rating_icon = {"强烈买入": "⭐⭐⭐", "买入": "⭐⭐", "持有": "⭐",
                       "减仓": "⚠️", "卖出": "❌"}.get(d["rating"], "⭐")
        lines.append(f"  {rating_icon} {d['stock']}")
        lines.append(f"     评级: {d['rating']} | 仓位: {d['position_pct']}%")
        if d.get("reason"):
            lines.append(f"     理由: {d['reason']}")
        if d.get("stop_loss"):
            lines.append(f"     止损: {d['stop_loss']}")
        if d.get("target"):
            lines.append(f"     目标: {d['target']}")
        lines.append(f"     看多要点: {d.get('bull_case','')[:80]}")
        lines.append(f"     看空要点: {d.get('bear_case','')[:80]}")
        lines.append("")

    lines.append("-" * 60)
    lines.append("  * 本报告由AI多角色辩论生成，不构成投资建议 *")
    lines.append("=" * 60)
    return "\n".join(lines)


# ===== 命令行 =====
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="多智能体辩论引擎")
    ap.add_argument("--code", help="股票代码")
    ap.add_argument("--name", default="", help="股票名称")
    ap.add_argument("--top", type=int, default=5, help="辩论前N只")
    args = ap.parse_args()

    if args.code:
        dummy_stock = {"代码": args.code, "名称": args.name or args.code,
                       "涨跌幅": 0, "置信度": 60, "量比": 1.0}
        decision = debate_stock(dummy_stock)
        print(format_debate_report([decision]))
    else:
        # 从最近报告取结果
        from local_screener import run_local_screen
        results = run_local_screen()
        decisions = debate_top_stocks(results, top_n=args.top)
        print(format_debate_report(decisions))
