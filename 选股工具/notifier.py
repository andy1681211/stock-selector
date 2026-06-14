#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信推送通知模块 v1.0
====================
支持渠道:
  1. Server酱（sct.ftqq.com）— 推荐，免费，通过企业微信服务号推送到微信
  2. PushPlus（pushplus.plus）— 备用，免费

用法:
  from notifier import push_wechat, push_daily_report
  push_wechat("标题", "内容")
  push_daily_report(stocks_summary, lhb_info)

配置:
  在 config.py 中设置以下环境变量:
    WECHAT_PUSH_KEY = "SCT..."  # Server酱 SendKey
    # 或
    PUSHPLUS_TOKEN = "..."       # PushPlus Token
"""

import json, os, sys, time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"


# ==================== 配置 ====================

def get_push_key() -> Optional[str]:
    """获取推送密钥（环境变量 > config文件）"""
    key = os.getenv("WECHAT_PUSH_KEY", "")
    if key:
        return ("serverchan", key)

    key = os.getenv("PUSHPLUS_TOKEN", "")
    if key:
        return ("pushplus", key)

    # 尝试从config.py读取
    try:
        sys.path.insert(0, str(TOOL_DIR))
        import importlib
        spec = importlib.util.spec_from_file_location("config", TOOL_DIR / "config.py")
        if spec:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            key = getattr(mod, "WECHAT_PUSH_KEY", "") or os.getenv("WECHAT_PUSH_KEY", "")
            if key:
                return ("serverchan", key)
            key = getattr(mod, "PUSHPLUS_TOKEN", "") or os.getenv("PUSHPLUS_TOKEN", "")
            if key:
                return ("pushplus", key)
    except Exception:
        pass

    return None


def is_configured() -> bool:
    """检查推送是否已配置"""
    return get_push_key() is not None


# ==================== Server酱 ====================

def _push_serverchan(title: str, content: str, key: str) -> bool:
    """
    通过 Server酱 推送微信消息。

    Args:
        title: 标题（最长80字）
        content: 内容（支持Markdown）

    Returns:
        是否成功
    """
    import requests

    url = f"https://sctapi.ftqq.com/{key}.send"

    # Server酱有长度限制，截断过长内容
    if len(content) > 30000:
        content = content[:28000] + "\n\n...（内容过长已截断）"

    try:
        resp = requests.post(url, data={
            "title": title[:80],
            "desp": content,
        }, timeout=15)

        result = resp.json()
        if result.get("code") == 0 or result.get("data", {}).get("error") == "SUCCESS":
            return True
        else:
            print(f"  [推送] Server酱失败: {result.get('message', str(result)[:200])}")
            return False
    except Exception as e:
        print(f"  [推送] Server酱异常: {e}")
        return False


# ==================== PushPlus ====================

def _push_pushplus(title: str, content: str, token: str) -> bool:
    """
    通过 PushPlus 推送微信消息。

    Args:
        title: 标题
        content: 内容（支持HTML/Markdown）
        token: PushPlus 令牌

    Returns:
        是否成功
    """
    import requests

    url = "https://www.pushplus.plus/send"

    try:
        resp = requests.post(url, json={
            "token": token,
            "title": title[:100],
            "content": content,
            "template": "markdown",
        }, timeout=15)

        result = resp.json()
        if result.get("code") == 200:
            return True
        else:
            print(f"  [推送] PushPlus失败: {result.get('msg', str(result)[:200])}")
            return False
    except Exception as e:
        print(f"  [推送] PushPlus异常: {e}")
        return False


# ==================== 统一推送接口 ====================

def push_wechat(title: str, content: str, channel: str = "auto") -> bool:
    """
    统一推送接口，自动选择可用渠道。

    Args:
        title: 标题
        content: 内容
        channel: "auto" / "serverchan" / "pushplus"

    Returns:
        是否成功
    """
    config = get_push_key()
    if not config:
        print("  [推送] 未配置推送密钥")
        print("    方式1(推荐): 去 https://sct.ftqq.com 注册 → 复制SendKey")
        print("    方式2: 去 https://www.pushplus.plus 注册 → 复制Token")
        print("    然后设置环境变量 WECHAT_PUSH_KEY 或 写入 config.py")
        return False

    ch_type, key = config

    if channel == "serverchan" or (channel == "auto" and ch_type == "serverchan"):
        return _push_serverchan(title, content, key)
    elif channel == "pushplus" or (channel == "auto" and ch_type == "pushplus"):
        return _push_pushplus(title, content, key)
    else:
        # 自动选
        if ch_type == "serverchan":
            return _push_serverchan(title, content, key)
        else:
            return _push_pushplus(title, content, key)


# ==================== 选股报告推送 ====================

def build_stocks_summary(results: List[Dict], top_n: int = 8) -> str:
    """
    从选股结果生成摘要文本。

    Args:
        results: run_local_screen() 返回的结果列表
        top_n: 显示前几只

    Returns:
        摘要文本（Markdown格式，适合微信推送）
    """
    if not results:
        return "今日无符合条件的选股结果"

    sorted_results = sorted(results, key=lambda x: -(
        x.get("置信度", 0) or x.get("策略命中", 0) * 10
    ))

    lines = []
    lines.append(f"📊 **选股结果** | 共{len(results)}只")
    lines.append("")

    # 头部
    lines.append(f"| {'代码':<6} | {'名称':<8} | {'涨幅':<6} | {'量比':<4} | {'信号'}")
    lines.append(f"| {'-'*6} | {'-'*8} | {'-'*6} | {'-'*4} | {'-'*20}")

    # 高置信标记
    high_conf = 0
    for r in sorted_results[:top_n]:
        code = r.get("代码", "")
        name = r.get("名称", "")
        chg = r.get("涨跌幅", 0) or 0
        vr = r.get("量比", 0) or 0

        # 收集信号标签
        tags = []
        if r.get("平步青云强") == "是":
            tags.append("🔥青云")
        elif r.get("平步青云", ""):
            try:
                pbq = int(str(r.get("平步青云", "0")).replace("分", ""))
                if pbq >= 60:
                    tags.append("青云")
            except:
                pass
        if r.get("建仓型涨停", ""):
            tags.append("建仓板")
        if r.get("洗盘型涨停", ""):
            tags.append("洗盘板")
        if r.get("二进三信号", ""):
            tags.append("二进三")
        if r.get("主升浪起爆", ""):
            tags.append("🚀起爆")
        if r.get("飞龙在天", ""):
            tags.append("🐉飞龙")
        if r.get("洗盘结束", ""):
            tags.append("洗毕")
        if r.get("倍量突破", ""):
            tags.append("倍量")
        chan = r.get("缠论买点", "")
        if chan:
            tags.append(f"缠{chan.replace('二买','2买').replace('三买','3买').replace('一买','1买')}")
        conf = r.get("置信度", 0)
        if conf >= 60:
            tags.append(f"★{conf}分")
            high_conf += 1

        tag_str = " ".join(tags[:4]) if tags else "—"
        arrow = "🔴" if chg >= 9 else ("🟠" if chg >= 5 else ("🟢" if chg > 0 else "🔵"))
        lines.append(f"| {code:<6} | {name:<8} | {arrow}{chg:>+5.2f} | {vr:<4} | {tag_str}")

    lines.append("")

    # 统计
    if high_conf:
        lines.append(f"⭐ 高置信推荐: {high_conf}只")

    return "\n".join(lines)


def build_market_summary(regime_info: Dict = None) -> str:
    """生成市场状态一句话摘要"""
    if not regime_info:
        return ""
    regime = regime_info.get("regime", "")
    score = regime_info.get("score", 0)
    suggestion = regime_info.get("suggestion", "")
    return f"📈 **市场状态**: {regime}（评分{score}）\n💡 **策略**: {suggestion}"


def build_report_markdown(results: List[Dict], regime_info: Dict = None,
                           lhb_summary: str = "") -> str:
    """
    生成完整的Markdown推送内容。

    包含:
      1. 市场状态
      2. 精选个股（含标签）
      3. 高置信推荐
      4. 龙虎榜简讯

    Args:
        results: 选股结果
        regime_info: 市场状态
        lhb_summary: 龙虎榜摘要（可选）

    Returns:
        Markdown文本
    """
    parts = []

    # 市场状态
    if regime_info:
        parts.append(build_market_summary(regime_info))
        parts.append("")

    # 个股
    parts.append(build_stocks_summary(results))

    # 龙虎榜
    if lhb_summary:
        parts.append("")
        parts.append("---")
        parts.append(lhb_summary)

    # 附注
    parts.append("")
    parts.append("---")
    parts.append(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    parts.append("⚡ 短线交易，严格止损，单票<25%仓位")
    parts.append("🤖 由AI量化选股系统自动推送")

    return "\n".join(parts)


def push_daily_report(results: List[Dict], regime_info: Dict = None,
                       lhb_summary: str = "") -> bool:
    """
    推送每日选股报告到微信。

    Args:
        results: 选股结果
        regime_info: 市场状态
        lhb_summary: 龙虎榜热讯

    Returns:
        是否成功
    """
    today = datetime.now().strftime("%m-%d")
    total = len(results)
    title = f"📊 选股日报 {today} | 选出{total}只"

    content = build_report_markdown(results, regime_info, lhb_summary)

    print(f"  [推送] 正在推送微信通知...")
    success = push_wechat(title, content)
    if success:
        print(f"  [推送] ✅ 微信推送成功")
    else:
        print(f"  [推送] ❌ 推送失败（未配置密钥请忽略）")

    return success


def push_alert(title: str, message: str):
    """
    推送紧急提醒（用于盘中异动等）。

    Args:
        title: 提醒标题
        message: 提醒内容
    """
    push_wechat(f"⚠️ {title}", message)


# ==================== 配置写入 ====================

def setup_push_key(send_key: str):
    """
    将推送密钥写入 config.py。

    用法:
      from notifier import setup_push_key
      setup_push_key("SCT123456...")
    """
    config_path = TOOL_DIR / "config.py"
    try:
        content = config_path.read_text("utf-8", errors="ignore")
        if "WECHAT_PUSH_KEY" in content:
            # 替换
            import re
            content = re.sub(
                r'WECHAT_PUSH_KEY\s*=\s*"[^"]*"',
                f'WECHAT_PUSH_KEY = "{send_key}"',
                content
            )
        else:
            content += f'\n\n# ===== 微信推送密钥 =====\nWECHAT_PUSH_KEY = "{send_key}"\n'

        config_path.write_text(content, encoding="utf-8")
        os.environ["WECHAT_PUSH_KEY"] = send_key
        print(f"  [推送] ✅ 密钥已保存到 config.py")
        return True
    except Exception as e:
        print(f"  [推送] 写入配置失败: {e}")
        return False


# ==================== 集成为独立参数 ====================

if __name__ == "__main__":
    import sys
    sys.stdout = open(1, 'w', encoding='utf-8', closefd=False)

    if len(sys.argv) >= 3 and sys.argv[1] == "setup":
        # python notifier.py setup SCT123...
        send_key = sys.argv[2]
        setup_push_key(send_key)
    elif len(sys.argv) >= 2 and sys.argv[1] == "test":
        # python notifier.py test
        success = push_wechat("🔔 测试消息", "这是来自A股选股系统的测试推送\n\n如果收到这条消息，说明推送配置正确！")
        if success:
            print("✅ 推送测试成功！请在微信中查看。")
        else:
            print("❌ 推送测试失败")
            print()
            print("使用方法:")
            print("  1. 去 https://sct.ftqq.com 注册获取 SendKey")
            print("  2. 运行: python notifier.py setup 你的SendKey")
            print("  3. 或设置环境变量: set WECHAT_PUSH_KEY=你的SendKey")
    else:
        print("=" * 50)
        print("  微信推送模块")
        print("=" * 50)
        print()
        if is_configured():
            print("  ✅ 推送密钥已配置")
        else:
            print("  ❌ 推送密钥未配置")
        print()
        print("  配置方法:")
        print("  1. 去 https://sct.ftqq.com 注册")
        print("  2. 复制你的 SendKey")
        print(f"  3. 运行: python notifier.py setup 你的SendKey")
        print(f"  或: set WECHAT_PUSH_KEY=你的SendKey")
        print()
        print("  测试推送: python notifier.py test")
