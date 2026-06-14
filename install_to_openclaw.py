#!/usr/bin/env python3
"""
Install stock trading skills into OpenClaw.
"""
import json, os, shutil, sys

OPENCLAW_SKILLS = r"C:\Program Files\nodejs\node_modules\openclaw\skills"
OPENCLAW_CONFIG = os.path.expanduser(r"~\.openclaw\openclaw.json")

# Skills to install - name -> description
SKILLS = {
    "cn-stock-trading-master": "A股综合交易系统 — 量价关系/洗盘识别/趋势判断/涨停战法/竞价选股/缠论底分型/游资暗语/五维驱动力",
    "cn-short-term-trading-system": "短线交易系统 — 量价关系/洗盘识别/趋势判断/分时买点/筹码理论/盘口语言",
    "cn-three-step-limit-up": "三步伏击涨停战法 — 首板突破20日平台选股/筛股/时机判断",
    "cn-decision-premise-strategy": "决策先机策略 — 竞价选股六要点+隔日超短套利战法",
    "cn-bottom-fractal-chan": "缠论底分型监测 — 上证指数日线底分型判断+MACD辅助验证",
    "cn-hot-money-codes": "游资盘口暗语 — 数字暗号识别/操盘意图判断/盘口辅助信号",
    "cn-stock-price-drivers": "股价五维驱动力框架 — 政策/业绩/估值/事件/题材→资金推动选股方法论",
    "cn-watchlist-management": "通达信自选股管理 — 核心池/观察池/三破七入三层文件结构维护",
    "cn-pingbuqingyun-strategy": "平步青云战法 — 强势股持续强势七大特征+主升浪判断两步法+5日线持股纪律",
}

# Check if skills dir is writable
if not os.access(OPENCLAW_SKILLS, os.W_OK):
    print(f"WARNING: Cannot write to {OPENCLAW_SKILLS}")
    print("Trying alternate approach...")
    # Try writing to user's openclaw extensions dir
    ext_dir = os.path.expanduser(r"~\.openclaw\extensions")
    if os.path.isdir(ext_dir):
        OPENCLAW_SKILLS = os.path.join(ext_dir, "custom-skills")
        os.makedirs(OPENCLAW_SKILLS, exist_ok=True)
        print(f"Using: {OPENCLAW_SKILLS}")
    else:
        print("ERROR: No writable skills directory found!")
        sys.exit(1)

# First, check what content we need
# Since we can't access the markdown files from here, let's create inline content

def get_skill_md(name, description):
    """Generate SKILL.md content for each skill."""

    if name == "cn-stock-trading-master":
        return f'''---
name: {name}
description: "{description}"
metadata:
  openclaw:
    emoji: "📈"
---

# A股综合交易系统

## 📌 核心交易原则
1. **止损纪律**：不止损就是等死，趋势破了必须出，破重要均线/支撑位止盈也要出
2. **止损点设置**：设在下方均线或支撑位，有效跌破立刻执行
3. **趋势为王**：上涨趋势中，前高不是压力而是支撑
4. **量价核心口诀**：价格 = 成交量 + 趋势 + 氛围 + 题材 + 资金
5. **洗盘口诀**：缩量小阴小阳，量越小越好；量越来越小，钱越来越多
6. **缺口理论**：缺口只要不回补，前面平台就是支撑

## 📊 成交量分析
- **缩量小阴小阳** = 洗盘（量越小越好）
- **放量突破** = 确认信号
- **高位放量滞涨** = 风险信号（天量天价）
- **缩量回调后放量启动** = N字反包形态买点
- 均线多头排列 + 缩量回调后放量启动 = 优选形态

## 🎯 涨停战法 - 三步伏击涨停
**第一步：选（竞价选股）** 首板涨停突破20日平台 + 底部反弹超1倍 + 开盘价-3%~6%
**第二步：筛** 时间/量能/集合竞价形态
**第三步：时（时机）** 开盘首单拉升 + 首单低于5日均量 + 分时回踩不破开盘价→介入

## ⚡ 决策先机策略
**买入六要点：** ①昨板 ②9:20前竞价挂涨停 ③9:25高开3%-6% ④涨幅>7%=买点 ⑤9:50前上板最佳 ⑥热点+主力资金
**卖出原则：** 不封板就走 + 有溢价就跑（隔日超短套利）

## 🔍 缠论底分型
连续3根日K线，中间低点最低 + MACD绿柱缩短 + 缩量 = 高概率买点

## 🃏 游资盘口暗语
AAAA(11.11)=强烈指令 / AAA(7.77)=持续性 / ABA(7.87)=测试抛压 / ABB(7.99)=延续 / AABB(22.33)=分阶段 / ABC(7.65)=趋势信号

## 📈 五维驱动力
政策→资金 / 业绩→资金 / 估值→资金 / 事件→资金 / 题材→资金

## 📁 通达信自选股管理
三层：核心池(zxg.blk) / 观察池(CLAUDE_观察池.blk) / 三破七入(SPQR6.5.blk)
'''
    elif name == "cn-pingbuqingyun-strategy":
        return f'''---
name: {name}
description: "{description}"
metadata:
  openclaw:
    emoji: "☁️"
---

# 平步青云战法

## 核心理念：什么决定了强势股持续强势？

## ⭐ 强势股七大特征
1. **涨幅发生在短期** — 快速拉升不拖泥带水
2. **放量突破启动** — 启动必有量，无量不启动
3. **上涨前有长期横盘洗盘** — 横有多长竖有多高
4. **必有一根倍量阳线** — 主力进场信号
5. **目标在左侧压力位附近** — 前高/筹码峰是目标
6. **所有强势股都符合** — 模式可复制
7. **5日线不下弯=没结束** — 强势股的命线

## 两步法
**第一步：判断趋势形成** — 口诀"任尔东南西北风"
- 长期横盘缩量→放量突破
- 倍量阳线→回踩不破
- 筹码密集+均线多头排列

**第二步：主升浪进场**
- 方式1：突破前高进场（放量突破+回踩不破加仓）
- 方式2：强势涨停进场（封板坚决+次日高开3%-6%）

## 风险控制
- 5日线拐头向下=强势结束，必须出局
- 放量滞涨=出货信号
- 跌破启动阳线最低点=无效突破

## 两课互补
| 决策先机（第一课） | 平步青云（第二课） |
|发现强势股 | 抱住强势股 |
|隔日超短套利 | 趋势持有到5日线拐头 |
'''
    else:
        return f'''---
name: {name}
description: "{description}"
metadata:
  openclaw:
    emoji: "📊"
---

# {name}

Stock analysis knowledge module for A-share trading.
'''
    return ""

print("=== Installing skills to OpenClaw ===")

for skill_name, skill_desc in SKILLS.items():
    skill_dir = os.path.join(OPENCLAW_SKILLS, skill_name)
    os.makedirs(skill_dir, exist_ok=True)

    skill_path = os.path.join(skill_dir, "SKILL.md")
    content = get_skill_md(skill_name, skill_desc)
    with open(skill_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  ✅ {skill_name}")

# Update openclaw.json to enable skills
print(f"\n=== Updating {OPENCLAW_CONFIG} ===")

with open(OPENCLAW_CONFIG, 'r', encoding='utf-8-sig') as f:
    config = json.load(f)

skills_entries = config.setdefault('skills', {}).setdefault('entries', {})
for skill_name in SKILLS:
    if skill_name not in skills_entries:
        skills_entries[skill_name] = {"enabled": True}
        print(f"  ✅ Enabled: {skill_name}")
    else:
        skills_entries[skill_name]["enabled"] = True
        print(f"  ✅ Already exists, enabled: {skill_name}")

with open(OPENCLAW_CONFIG, 'w', encoding='utf-8-sig') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print("\n✅ All skills installed and enabled in OpenClaw!")
