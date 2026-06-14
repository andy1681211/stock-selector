#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Memos 交易日志模块 v1.0
======================
将每日选股结果自动写入本地 Memos 实例，形成可搜索的交易笔记。

功能:
  1. 推送每日选股小结（含市场状态、高置信推荐、缠论精选等）
  2. 推送高置信个股分析卡（单只股票详细数据）
  3. 推送市场状态更新
  4. 搜索历史选股记录
  5. 打标签分类： #选股日记 #高置信 #缠论 #涨停捕捉 等

配置:
  MEMOS_URL: Memos 实例地址 (默认: http://localhost:5230)
  MEMOS_TOKEN: Personal Access Token (从Memos设置页获取)
"""

import os
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import urllib.request
import urllib.error

TOOL_DIR = Path(__file__).parent

# ===== 配置 =====
MEMOS_URL = os.getenv("MEMOS_URL", "http://localhost:5230")
MEMOS_TOKEN = os.getenv("MEMOS_ACCESS_TOKEN", "")

# 如果环境变量没取到，从 settings.json 读取
if not MEMOS_TOKEN:
    try:
        settings_path = Path(os.getenv("CLAUDE_CONFIG_HOME", str(Path.home() / ".claude"))) / "settings.json"
        if settings_path.exists():
            cfg = json.loads(settings_path.read_text(encoding="utf-8"))
            memos_cfg = cfg.get("mcpServers", {}).get("memos", {}).get("env", {})
            MEMOS_TOKEN = memos_cfg.get("MEMOS_ACCESS_TOKEN", "")
            MEMOS_URL = memos_cfg.get("MEMOS_URL", MEMOS_URL)
    except Exception:
        pass


# ===== API 客户端 =====

def _api_call(method: str, path: str, data: dict = None) -> Optional[dict]:
    """调用 Memos REST API"""
    if not MEMOS_TOKEN:
        return None

    url = f"{MEMOS_URL.rstrip('/')}{path}"
    headers = {
        "Authorization": f"Bearer {MEMOS_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    body = json.dumps(data).encode("utf-8") if data else None

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            if raw:
                return json.loads(raw)
            return {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:200]
        # 写权限错误不报太多
        if e.code == 401:
            return None
        if e.code not in (404, 400):
            print(f"  [Memos] API {method} {path} -> {e.code}: {err_body}")
        return None
    except Exception as e:
        print(f"  [Memos] 连接失败: {e}")
        return None


def is_configured() -> bool:
    """检查 Memos 是否已配置"""
    if not MEMOS_TOKEN:
        return False
    result = _api_call("GET", "/api/v1/auth/me")
    return result is not None and "user" in result


# ===== 创建/搜索 Memo =====

def create_memo(content: str, visibility: str = "PRIVATE") -> Optional[dict]:
    """创建一条 memo（默认私密）"""
    return _api_call("POST", "/api/v1/memos", {
        "content": content,
        "visibility": visibility,
    })


def search_memos(query: str, limit: int = 10) -> List[dict]:
    """搜索历史 memo"""
    from urllib.parse import quote
    encoded = quote(f'content.contains("{query}")')
    result = _api_call("GET", f"/api/v1/memos?filter={encoded}&pageSize={limit}")
    if result and "memos" in result:
        return result["memos"]
    return []


# ===== 每日选股日志推送 =====

def push_daily_summary(results: List[dict], regime_info: dict = None,
                       report_path: str = None) -> bool:
    """
    推送每日选股小结到 Memos。
    生成结构化 Markdown 内容，自动打标签。
    """
    if not is_configured():
        return False

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    # ---- 构建标题 ----
    total = len(results)
    resonance = [r for r in results if r.get("策略命中", 0) >= 2]
    top5 = [r for r in results if r.get("策略命中", 0) >= 3]

    # ---- 市场状态 ----
    market_line = ""
    if regime_info:
        regime = regime_info.get("regime", "未知")
        score = regime_info.get("score", 0)
        suggestion = regime_info.get("suggestion", "")
        market_line = f"\n**市场**: {regime} (评分:{score}) | {suggestion}\n"

    # ---- 高置信推荐 ----
    conf_lines = ""
    high_conf = [r for r in results if r.get("置信度", 0) >= 60]
    if high_conf:
        conf_lines = "\n**高置信推荐**\n"
        for r in high_conf[:6]:
            conf = r.get("置信度", 0)
            chg = r.get("涨跌幅", 0)
            name = r.get("名称", "")
            code = r.get("代码", "")
            tags = _extract_tags(r)
            conf_lines += f"- {code} {name} {chg:+.2f}% 置信:{conf} {tags}\n"

    # ---- 高级信号 ----
    signal_lines = ""
    categories = [
        ("平步青云", lambda r: r.get("平步青云强") == "是"),
        ("主升浪起爆", lambda r: r.get("主升浪起爆", "")),
        ("飞龙在天", lambda r: r.get("飞龙在天", "")),
        ("潜龙回首", lambda r: r.get("潜龙回首", "")),
    ]
    for label, pred in categories:
        items = [r for r in results if pred(r)]
        if items:
            signal_lines += f"\n**{label}**\n"
            for r in items[:4]:
                chg = r.get("涨跌幅", 0)
                signal_lines += f"- {r['代码']} {r['名称']} {chg:+.2f}%\n"

    # ---- 止盈止损预警 ----
    stop_lines = ""
    for r in results:
        se = r.get("stop_engine", {})
        if se.get("建议", "").startswith("🛑"):
            stop_lines += f"- 🛑 {r['代码']} {r['名称']} {se.get('当前利润',''):+.1f}% 止损{se.get('止损价','')}\n"
    if stop_lines:
        stop_lines = f"\n**止损预警**\n{stop_lines}"

    # ---- 构建完整内容 ----
    content = f"""# 选股日记 {date_str} {time_str}

**摘要**: 全市场扫描 {total} 只 | 共振>=2: {len(resonance)} | 共振>=3: {len(top5)}
{market_line}{conf_lines}{signal_lines}{stop_lines}

#选股日记 #{date_str.replace("-","")}
"""
    result = create_memo(content)
    return result is not None


def push_stock_card(stock: dict) -> bool:
    """
    推送单只个股分析卡到 Memos。
    用于高置信个股的详细数据存档。
    """
    if not is_configured():
        return False

    code = stock.get("代码", "")
    name = stock.get("名称", "")
    chg = stock.get("涨跌幅", 0)
    volume_ratio = stock.get("量比", 0)
    confidence = stock.get("置信度", 0)
    tags = _extract_tags(stock)

    # 技术面
    ma_info = ""
    for period in [5, 10, 20, 60]:
        ma_val = stock.get(f"MA{period}", 0)
        if ma_val:
            close = stock.get("收盘", 0)
            pos = "↑" if close > ma_val else "↓"
            ma_info += f" MA{period}:{ma_val:.2f}({pos})"

    chan_info = stock.get("缠论买点", "")
    pbq = stock.get("平步青云详情", "") or stock.get("平步青云", "")

    # 筹码
    chip_score = stock.get("筹码评分", 0)

    content = f"""## {code} {name}

**涨幅**: {chg:+.2f}% | **量比**: {volume_ratio} | **置信度**: {confidence}分 | **筹码**: {chip_score}分

**信号**: {tags}

**均线**: {ma_info}

**缠论**: {chan_info or "无"}

**平步青云**: {pbq}

{_get_advanced_signals(stock)}

#{code} #{name} #个股分析 #{'高置信' if confidence >= 60 else '关注'}
"""
    result = create_memo(content)
    return result is not None


def push_market_update(regime_info: dict, lhb_info: str = "",
                       north_info: str = "", sector_info: str = "") -> bool:
    """推送市场状态更新"""
    if not is_configured():
        return False

    regime = regime_info.get("regime", "未知")
    score = regime_info.get("score", 0)
    suggestion = regime_info.get("suggestion", "")

    content = f"""# 市场状态更新

**大盘**: {regime} (评分:{score})

**建议**: {suggestion}

{lhb_info if lhb_info else ""}
{north_info if north_info else ""}
{sector_info if sector_info else ""}

#市场状态 #{regime}
"""
    result = create_memo(content)
    return result is not None


# ===== 辅助函数 =====

def _extract_tags(r: dict) -> str:
    """提取股票标签字符串"""
    tags = []
    lc = r.get("低吸买点", "")
    if lc:
        tags.append("低吸")
    chan = r.get("缠论买点", "")
    if chan:
        tags.append(chan[:4])
    for name in ["平步青云强", "洗盘结束", "倍量突破", "主升浪起爆",
                  "飞龙在天", "潜龙回首", "建仓型涨停", "洗盘型涨停", "二进三信号"]:
        if r.get(name, ""):
            tags.append(name[:4] if name != "平步青云强" else "青云")
    if r.get("涨停板数", 0) >= 2:
        tags.append(f"{r.get('涨停板数')}板")
    conf = r.get("置信度", 0)
    if conf >= 80:
        tags.insert(0, "★高置信")
    elif conf >= 60:
        tags.insert(0, "高置信")
    return " ".join(tags[:6])


def _get_advanced_signals(r: dict) -> str:
    """获取高级信号描述"""
    parts = []
    for key, label in [
        ("洗盘结束", "洗盘结束"),
        ("倍量突破", "倍量突破"),
        ("回踩买点", "回踩买点"),
        ("主升浪起爆", "主升浪"),
        ("试盘线", "试盘线"),
        ("飞龙在天", "飞龙在天"),
        ("潜龙回首", "潜龙回首"),
        ("建仓型涨停", "建仓型涨停"),
        ("洗盘型涨停", "洗盘型涨停"),
        ("二进三信号", "二进三"),
        ("底分型", "底分型"),
    ]:
        val = r.get(key, "")
        if val:
            parts.append(f"{label}: {val}")
    if parts:
        return "\n".join(f"**{p}**" for p in parts)
    return ""


def query_history(code_or_name: str, days: int = 7) -> List[dict]:
    """查询某只股票的历史选股记录"""
    memos = search_memos(code_or_name, limit=days)
    return memos


# ===== 快捷命令 =====

def print_recent(limit: int = 5):
    """打印最近的选股日记"""
    results = search_memos("#选股日记", limit=limit)
    if not results:
        print("  [Memos] 暂无选股日记")
        return
    for m in results:
        created = m.get("createTime", "")[:16]
        snippet = m.get("snippet", "")[:120]
        print(f"  [{created}] {snippet}...")


if __name__ == "__main__":
    # 测试连接
    if not is_configured():
        print("❌ Memos 未配置或连接失败")
        print(f"   URL: {MEMOS_URL}")
        print(f"   Token: {'已设置' if MEMOS_TOKEN else '未设置'}")
        sys.exit(1)
    print("✅ Memos 连接正常")
    print(f"   URL: {MEMOS_URL}")
    print()
    print_recent()
