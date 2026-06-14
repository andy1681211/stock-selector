#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块轮动分析系统 v1.0
====================
基于本地TDX数据 + akshare东方财富API（盘中增强），
识别热点板块轮动趋势。

数据源优先级:
  1. 东方财富板块API（盘中优先，速度快、数据全）
  2. 通达信本地数据（盘后/API不可用时自动降级）

用法:
  from sector_rotation import generate_sector_report
  report = generate_sector_report()
"""

import sys, os, time
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional

TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"

# 行业板块名称关键词映射（本地降级用）
SECTOR_KEYWORDS = {
    "半导体": ["芯片", "半导体", "集成电路", "封测", "晶圆", "光刻", "IGBT"],
    "AI算力": ["AI", "人工智能", "算力", "服务器", "大模型", "智能体"],
    "数字经济": ["数据", "数字", "软件", "IT服务", "云计算", "信创", "鸿蒙"],
    "新能源": ["新能源", "光伏", "锂电", "电池", "风电", "储能", "氢能"],
    "汽车": ["汽车", "新能源车", "整车", "零部件", "一体化压铸"],
    "机器人": ["机器人", "自动化", "减速器", "机器视觉"],
    "军工": ["军工", "航天", "航空", "船舶", "国防", "卫星"],
    "医药": ["医药", "医疗", "生物", "创新药", "中药", "医美"],
    "消费": ["消费", "食品", "饮料", "白酒", "乳业", "调味"],
    "金融": ["银行", "券商", "保险", "地产", "证券", "金融"],
    "周期": ["煤炭", "有色", "钢铁", "化工", "石油", "黄金"],
    "通信": ["通信", "5G", "6G", "光通信", "光模块"],
    "电力": ["电力", "电网", "发电", "核电", "特高压"],
    "机械": ["机械", "装备", "重工", "基建"],
}


# ==================== API模式（盘中优先）====================

def _try_api_industry_rank(top_n: int = 15) -> Optional[List[Dict]]:
    """
    尝试通过东方财富API获取行业板块排名。
    非交易时段可能不可用，此时返回None。
    """
    import akshare as ak
    try:
        df = ak.stock_board_industry_spot_em()
        if df is not None and not df.empty:
            results = []
            for _, row in df.iterrows():
                results.append({
                    "名称": str(row.get("板块名称", "")),
                    "涨跌幅": float(row.get("涨跌幅", 0) or 0),
                    "上涨家数": int(row.get("上涨家数", 0) or 0),
                    "下跌家数": int(row.get("下跌家数", 0) or 0),
                    "领涨股": str(row.get("领涨股", "")),
                    "领涨股涨幅": float(row.get("领涨股涨跌幅", 0) or 0),
                    "换手率": float(row.get("换手率", 0) or 0),
                })
            results.sort(key=lambda x: -x["涨跌幅"])
            return results[:top_n]
    except Exception:
        pass
    return None


def _try_api_concept_rank(top_n: int = 8) -> Optional[List[Dict]]:
    """尝试获取概念板块排名"""
    import akshare as ak
    try:
        df = ak.stock_board_concept_spot_em()
        if df is not None and not df.empty:
            results = []
            for _, row in df.iterrows():
                results.append({
                    "名称": str(row.get("板块名称", "")),
                    "涨跌幅": float(row.get("涨跌幅", 0) or 0),
                    "上涨家数": int(row.get("上涨家数", 0) or 0),
                    "下跌家数": int(row.get("下跌家数", 0) or 0),
                    "领涨股": str(row.get("领涨股", "")),
                })
            results.sort(key=lambda x: -x["涨跌幅"])
            return results[:top_n]
    except Exception:
        pass
    return None


# ==================== 本地降级模式（基于TDX数据）====================

def _local_sector_scan(top_n: int = 10) -> List[Dict]:
    """
    基于通达信本地日K线数据，扫描识别强势板块。
    通过股票名称关键词匹配板块，统计上涨比例和平均涨幅。
    """
    try:
        sys.path.insert(0, str(TOOL_DIR))
        from local_screener import parse_day_file, load_code_name_map

        name_map = load_code_name_map()
        sector_stats = {}

        for code in list(name_map.keys())[:3000]:
            if code.startswith(("688", "689", "300", "301")):
                continue

            market = "sh" if code.startswith(("6", "5")) else "sz" if code.startswith(("0", "3", "2")) else None
            if not market:
                continue

            fp = f"D:/new_tdx/vipdoc/{market}/lday/{market}{code}.day"
            if not os.path.exists(fp):
                continue

            klines = parse_day_file(fp, 5)
            if len(klines) < 2:
                continue

            name = name_map.get(code, "")
            c = klines[-1]

            # 匹配板块
            matched = []
            for sector, keywords in SECTOR_KEYWORDS.items():
                for kw in keywords:
                    if kw in name:
                        matched.append(sector)
                        break
            if not matched:
                continue

            for sector in matched:
                if sector not in sector_stats:
                    sector_stats[sector] = {"count": 0, "up_count": 0, "sum_chg": 0.0, "stocks": []}
                sector_stats[sector]["count"] += 1
                if c.pct_chg > 0:
                    sector_stats[sector]["up_count"] += 1
                    sector_stats[sector]["sum_chg"] += c.pct_chg
                    sector_stats[sector]["stocks"].append(f"{code}({c.pct_chg:+.1f}%)")

        scored = []
        for sector, stats in sector_stats.items():
            if stats["count"] < 3:
                continue
            up_ratio = stats["up_count"] / stats["count"]
            avg_chg = stats["sum_chg"] / max(stats["up_count"], 1)
            score = (up_ratio ** 2) * avg_chg
            scored.append({
                "名称": sector,
                "涨跌幅": round(avg_chg, 2),
                "上涨家数": stats["up_count"],
                "总家数": stats["count"],
                "评分": round(score, 2),
                "代表股": stats["stocks"][:3],
            })

        scored.sort(key=lambda x: -x["评分"])
        return scored[:top_n]
    except Exception:
        return []


# ==================== 汇总分析 ====================

def get_sector_rank(top_n: int = 15) -> List[Dict]:
    """
    获取行业板块排名（API优先 → 本地降级）。
    """
    api_data = _try_api_industry_rank(top_n)
    if api_data:
        return api_data

    # API不可用，降级到本地
    local_data = _local_sector_scan(top_n)
    if local_data:
        return local_data

    return []


def get_concept_rank(top_n: int = 8) -> List[Dict]:
    """获取概念板块排名"""
    data = _try_api_concept_rank(top_n)
    return data or []


def _classify_sectors(sectors: List[str]) -> str:
    """判断板块风格"""
    tech = sum(1 for s in sectors for kw in ["半导体","芯片","AI","算力","软件","通信","机器人","电子"] if kw in s)
    value = sum(1 for s in sectors for kw in ["银行","证券","地产","煤炭","钢铁","有色","化工"] if kw in s)
    consumer = sum(1 for s in sectors for kw in ["白酒","食品","医药","消费","汽车"] if kw in s)
    if tech > value and tech > consumer:
        return "科技成长"
    elif value > consumer:
        return "价值周期"
    return "消费防御"


# ==================== 报告生成 ====================

def generate_sector_report() -> str:
    """生成板块轮动报告"""
    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append("  板块轮动分析")
    lines.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 70)
    lines.append("")

    industries = get_sector_rank(top_n=15)
    if not industries:
        lines.append("  暂无板块数据")
        return "\n".join(lines)

    # 判断数据来源
    is_api = "换手率" in industries[0] if industries else False
    lines.append(f"  数据来源: {'东方财富(盘中)' if is_api else '通达信本地(盘后)'}")
    lines.append("")

    # 涨幅前10
    lines.append(f"  {'排名':<4} {'板块':<14} {'涨幅%':<8} {'上涨/总':<10} {'领涨股':<12}")
    lines.append(f"  {'-'*4} {'-'*14} {'-'*8} {'-'*10} {'-'*12}")
    for i, s in enumerate(industries[:10], 1):
        name = s["名称"][:10]
        chg = s["涨跌幅"]
        if is_api:
            ratio = f"{s['上涨家数']}/{s['上涨家数']+s['下跌家数']}"
            ld = s.get("领涨股", "")[:8]
        else:
            ratio = f"{s['上涨家数']}/{s['总家数']}"
            ld = s.get("代表股", [""])[0].split("(")[0] if s.get("代表股") else ""
        bar = "█" * max(1, min(8, int(abs(chg)))) if chg > 0 else ""
        lines.append(f"  {i:<4} {name:<14} {chg:>+7.2f}% {ratio:<10} {ld:<12} {bar}")
    lines.append("")

    # 风格判断
    top_names = [s["名称"] for s in industries[:5]]
    style = _classify_sectors(top_names)
    lines.append(f"  风格偏向: {style}")
    lines.append("")

    # 概念板块（仅API模式）
    if is_api:
        concepts = get_concept_rank(top_n=6)
        if concepts:
            lines.append(f"  {'概念热点':<14} {'涨幅%':<8} {'领涨股'}")
            lines.append(f"  {'-'*14} {'-'*8} {'-'*12}")
            for s in concepts:
                lines.append(f"  {s['名称'][:10]:<14} {s['涨跌幅']:>+7.2f}% {s['领涨股'][:8]}")
            lines.append("")

    lines.append("  ⚠ 数据仅供参考，板块热度可能日内变化")
    return "\n".join(lines)


def add_sector_to_report(existing_report: str = "") -> str:
    report = generate_sector_report()
    return existing_report + "\n" + report if existing_report else report


if __name__ == "__main__":
    sys.stdout = open(1, 'w', encoding='utf-8', closefd=False)
    report = generate_sector_report()
    print(report)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    rp = OUTPUT_DIR / f"板块轮动报告_{ts}.txt"
    rp.write_text(report, encoding="utf-8")
    print(f"\n[OK] 已保存: {rp}")
