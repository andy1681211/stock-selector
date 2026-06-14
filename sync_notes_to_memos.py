#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略笔记同步到 Memos v1.0
=========================
将 Claude Code memory 中的策略笔记/课程笔记同步到本地 Memos 实例。

笔记列表:
  交易系统 -> 最新操盘笔记.md         #短线交易系统手册
  战法笔记 -> 三步伏击涨停.md         #首板突破20日平台战法
  战法笔记 -> 平步青云.md             #强势股七大特征+主升浪进场
  战法笔记 -> 股海炼金术三.md         #建仓型/洗盘型涨停+二进三战法
  选股框架 -> 股价驱动力.md           #五维选股框架
  盘口语言 -> 游资盘口暗语.md         #游资数字暗号
  竞价策略 -> 决策先机策略.md         #竞价选股六要点
  缠论分析 -> 底分型提醒.md           #上证指数缠论底分型监测
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Memos路径
TOOL_DIR = Path(__file__).parent / "选股工具"
sys.path.insert(0, str(TOOL_DIR))

# Memory 目录
MEMORY_DIR = Path(os.getenv("CLAUDE_PROJECT_DIR",
    str(Path.home() / ".claude" / "projects" / "D------" / "memory")))

# 备选路径
if not MEMORY_DIR.exists():
    alt_path = Path("C:/Users/Administrator/.claude/projects/D------/memory")
    if alt_path.exists():
        MEMORY_DIR = alt_path

NOTES_CONFIG = [
    {
        "file": "最新操盘笔记.md",
        "tag": "#交易系统",
        "title": "短线交易系统手册",
        "desc": "量价关系/洗盘识别/趋势判断",
    },
    {
        "file": "三步伏击涨停.md",
        "tag": "#战法笔记",
        "title": "三步伏击涨停 - 首板突破20日平台战法",
        "desc": "首板突破20日平台战法",
    },
    {
        "file": "平步青云.md",
        "tag": "#战法笔记",
        "title": "平步青云 - 强势股七大特征+主升浪进场法",
        "desc": "强势股七大特征+主升浪两步法",
    },
    {
        "file": "股海炼金术三.md",
        "tag": "#战法笔记",
        "title": "股海炼金术(三) - 建仓型涨停+洗盘型涨停+二进三",
        "desc": "建仓型/洗盘型涨停识别与二进三战法",
    },
    {
        "file": "股价驱动力.md",
        "tag": "#选股框架",
        "title": "五维选股框架 - 股价驱动力分析",
        "desc": "政策/业绩/估值/事件/题材→资金推动",
    },
    {
        "file": "游资盘口暗语.md",
        "tag": "#盘口语言",
        "title": "游资盘口暗语大全",
        "desc": "游资数字暗号传递操盘意图",
    },
    {
        "file": "决策先机策略.md",
        "tag": "#竞价策略",
        "title": "决策先机 - 竞价抓涨停六要点",
        "desc": "竞价选股六要点：昨板/竞价挂涨停/高开3%-6%/涨幅>7%买",
    },
    {
        "file": "底分型提醒.md",
        "tag": "#缠论分析",
        "title": "上证指数缠论底分型监测",
        "desc": "缠论底分型监测方法",
    },
    {
        "file": "止盈止损引擎.md",
        "tag": "#风控",
        "title": "止盈止损规则引擎",
        "desc": "基于策略类型+ATR动态波动率的止盈止损规则",
    },
]


def read_note(note_config: dict) -> str:
    """读取笔记文件内容"""
    filepath = MEMORY_DIR / note_config["file"]
    if not filepath.exists():
        return None
    content = filepath.read_text(encoding="utf-8")
    # 去掉 frontmatter（--- 之间的部分）
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    return content


def push_to_memos(content: str, tag: str, title: str) -> bool:
    """推送笔记到 Memos"""
    try:
        from memos_logger import MEMOS_TOKEN, MEMOS_URL
        import urllib.request
        import json

        if not MEMOS_TOKEN:
            print(f"  [Memos] 未配置 Token，跳过")
            return False

        # 构建内容（加标签和标题）
        full_content = f"# {title}\n\n{content}\n\n{tag} #策略笔记"
        # 截断到合理长度（Memos 支持长文本但建议不要超过20000字）
        if len(full_content) > 15000:
            full_content = full_content[:15000] + "\n\n...(截断)"

        url = f"{MEMOS_URL.rstrip('/')}/api/v1/memos"
        headers = {
            "Authorization": f"Bearer {MEMOS_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        data = json.dumps({
            "content": full_content,
            "visibility": "PRIVATE",
        }).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return "name" in result

    except Exception as e:
        print(f"  [Memos] 推送失败: {e}")
        return False


def check_if_exists(tag: str) -> bool:
    """检查是否已同步过"""
    try:
        from memos_logger import MEMOS_TOKEN, MEMOS_URL
        import urllib.request
        import json

        if not MEMOS_TOKEN:
            return False

        # 搜索标签
        from urllib.parse import quote
        encoded = quote(f'content.contains("{tag}")')
        url = f"{MEMOS_URL.rstrip('/')}/api/v1/memos?filter={encoded}&pageSize=5"
        headers = {
            "Authorization": f"Bearer {MEMOS_TOKEN}",
            "Accept": "application/json",
        }

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            memos = result.get("memos", [])
            for m in memos:
                if tag in m.get("content", ""):
                    return True
        return False

    except Exception:
        return False


def sync_all(force: bool = False):
    """同步所有笔记到 Memos"""
    print(f"{'='*60}")
    print(f"  策略笔记同步到 Memos")
    print(f"  笔记目录: {MEMORY_DIR}")
    print(f"{'='*60}")
    print()

    if not MEMORY_DIR.exists():
        print(f"❌ 笔记目录不存在: {MEMORY_DIR}")
        return

    success = 0
    skipped = 0
    failed = 0

    for note in NOTES_CONFIG:
        title = note["title"]
        tag = note["tag"]

        print(f"  [{tag}] {title}...", end=" ")

        # 检查是否已存在
        if not force and check_if_exists(tag):
            print("已同步（跳过）")
            skipped += 1
            continue

        # 读取内容
        content = read_note(note)
        if content is None:
            print("❌ 文件不存在")
            failed += 1
            continue

        # 截取关键部分（只同步摘要或核心内容）
        lines = content.split("\n")
        # 保留前300行或前5000字符
        summary = "\n".join(lines[:300])[:5000]

        if push_to_memos(summary, tag, title):
            print("✅")
            success += 1
        else:
            print("❌")
            failed += 1

    print()
    print(f"{'='*60}")
    print(f"  同步完成: {success}成功 / {skipped}跳过 / {failed}失败")
    print(f"{'='*60}")

    # 如果全部成功，推一条汇总
    if success > 0:
        try:
            from memos_logger import create_memo
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            memo = f"# 策略笔记库已同步 {now}\n\n已同步笔记:\n"
            for note in NOTES_CONFIG:
                memo += f"- {note['tag']} {note['title']}\n"
            memo += "\n#策略笔记 #笔记库"
            create_memo(memo)
        except Exception:
            pass


def search_notes(keyword: str):
    """在 Memos 中搜索策略笔记"""
    try:
        import urllib.request, json
        from memos_logger import MEMOS_TOKEN, MEMOS_URL
        from urllib.parse import quote

        if not MEMOS_TOKEN:
            print("❌ Memos 未配置")
            return

        encoded = quote(f'content.contains("{keyword}")')
        url = f"{MEMOS_URL.rstrip('/')}/api/v1/memos?filter={encoded}&pageSize=20"
        headers = {
            "Authorization": f"Bearer {MEMOS_TOKEN}",
            "Accept": "application/json",
        }

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        memos = result.get("memos", [])
        print(f"\n找到 {len(memos)} 条相关笔记:\n")
        for m in memos:
            created = m.get("createTime", "")[:16]
            snippet = m.get("snippet", "")[:120]
            print(f"  [{created}] {snippet}...")
            print()

    except Exception as e:
        print(f"搜索失败: {e}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="策略笔记同步到 Memos")
    ap.add_argument("--force", action="store_true", help="强制重新同步")
    ap.add_argument("--search", help="搜索笔记关键词")
    args = ap.parse_args()

    if args.search:
        search_notes(args.search)
    else:
        sync_all(args.force)
