#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可视化图表模块 v1.0
==================
在终端生成ASCII趋势图，方便直接在报告中查看趋势。

功能:
  1. 大盘指数走势图
  2. 涨跌幅柱状图（板块排名）
  3. 北向资金趋势图
  4. 筹码分布简图

用法:
  from charts import ascii_line_chart, ascii_bar_chart, ascii_chip_chart
"""

import math
from typing import List, Tuple, Optional


def ascii_line_chart(data: List[float], width: int = 40, height: int = 8,
                      title: str = "", show_labels: bool = True) -> str:
    """
    生成ASCII折线图，显示数据趋势。

    Args:
        data: 数据点列表（从旧到新）
        width: 图表宽度（字符数）
        height: 图表高度（行数）
        title: 图表标题
        show_labels: 是否显示最大/最小值标签

    Returns:
        ASCII图表字符串
    """
    if not data or len(data) < 2:
        return f"  {title}: 数据不足"

    # 找最大最小值
    min_val = min(data)
    max_val = max(data)
    val_range = max_val - min_val
    if val_range == 0:
        val_range = 1

    # 构建图表
    lines = []
    if title:
        lines.append(f"  {title}")

    # 坐标轴
    for row in range(height):
        # 当前行的值（从高到低）
        row_val = max_val - (val_range * row / (height - 1))
        line = "  "

        # Y轴标签
        if show_labels and row == 0:
            line += f"{max_val:>8.1f} "
        elif show_labels and row == height - 1:
            line += f"{min_val:>8.1f} "
        elif show_labels:
            line += "         "

        line += "│"

        # 绘制数据点
        for i in range(len(data)):
            col = int(width * i / (len(data) - 1))
            if col >= width:
                continue

            # 该位置对应的数据值
            idx = int(i * (len(data) - 1) / (len(data) - 1))
            data_val = data[idx]

            # 判断数据点是否落在当前行
            if abs(data_val - row_val) <= val_range / (height - 1) / 2:
                line += "●"
            else:
                line += "·"

        lines.append(line)

    # 底部轴
    bottom = "  " + " " * 9 + "└" + "─" * width
    lines.append(bottom)

    # X轴标签（最左和最右）
    if show_labels and len(data) >= 2:
        bottom_label = "  " + " " * 9
        bottom_label += f"{'开始':<{width//2}}{'现在':>{width - width//2}}"
        lines.append(bottom_label)

    return "\n".join(lines)


def ascii_bar_chart(items: List[Tuple[str, float]], width: int = 40,
                     title: str = "", bar_char: str = "█") -> str:
    """
    生成ASCII横向柱状图，适合板块排名等。

    Args:
        items: (名称, 数值) 列表
        width: 柱状图宽度
        title: 标题
        bar_char: 柱状字符

    Returns:
        ASCII图表字符串
    """
    if not items:
        return f"  {title}: 无数据"

    lines = []
    if title:
        lines.append(f"  {title}")

    max_val = max(abs(v) for _, v in items)
    if max_val == 0:
        max_val = 1

    name_width = max(len(str(n)) for n, _ in items)
    name_width = min(name_width, 12)

    for name, val in items:
        bar_len = max(1, int(abs(val) / max_val * width))
        bar = bar_char * bar_len if val >= 0 else "░" * bar_len
        label = str(name)[:name_width].ljust(name_width)
        val_str = f"{val:+.2f}" if abs(val) < 100 else f"{val:+.0f}"
        direction = "←" if val >= 0 else "→"
        lines.append(f"  {label} {bar} {val_str}% {direction}")

    return "\n".join(lines)


def trend_arrow(current: float, prev: float) -> str:
    """返回趋势箭头"""
    if current > prev * 1.01:
        return "↑"
    elif current < prev * 0.99:
        return "↓"
    return "→"


def sparkline(data: List[float], width: int = 20) -> str:
    """
    生成小型Sparkline走势图（单行）。

    Args:
        data: 数据点
        width: 显示宽度

    Returns:
        单行走势图字符串
    """
    if not data or len(data) < 2:
        return ""

    chars = "▁▂▃▄▅▆▇█"
    min_v = min(data)
    max_v = max(data)
    rng = max_v - min_v
    if rng == 0:
        return "▅" * width

    result = ""
    step = max(1, len(data) // width)
    sampled = data[::step][:width] if step > 1 else data[-width:]

    for v in sampled:
        idx = min(len(chars) - 1, int((v - min_v) / rng * (len(chars) - 1)))
        result += chars[idx]

    return result


def generate_market_chart(index_klines: list) -> str:
    """
    基于大盘指数K线生成走势图。

    Args:
        index_klines: KLine对象列表

    Returns:
        走势图文本
    """
    if not index_klines or len(index_klines) < 10:
        return "  大盘数据不足"

    closes = [k.close for k in index_klines[-60:]]
    chgs = [k.pct_chg for k in index_klines[-60:]]

    today_close = closes[-1]
    today_chg = chgs[-1] if chgs else 0
    chg_arrow = "↑" if today_chg > 0 else "↓" if today_chg < 0 else "—"

    lines = []
    lines.append(f"  {'='*50}")
    lines.append(f"  大盘走势可视化  |  当前: {today_close:.2f}  {chg_arrow} {today_chg:+.2f}%")
    lines.append(f"  {'='*50}")
    lines.append("")

    # 60日走势
    lines.append(ascii_line_chart(closes, width=40, height=6,
                                   title="近60日走势"))
    lines.append("")

    # Sparkline
    lines.append(f"  近60日: {sparkline(closes, 30)}")
    lines.append("")

    # 近10日涨跌
    recent_10 = chgs[-10:]
    dates_label = [f"D{-10+i}" for i in range(1, 11)]
    bar_data = [(dates_label[i], recent_10[i]) for i in range(len(recent_10))]
    lines.append(ascii_bar_chart(bar_data, width=20, title="近10日涨跌"))
    lines.append("")

    return "\n".join(lines)


def generate_sector_bar(sector_data: List[Tuple[str, float]], top_n: int = 8) -> str:
    """
    板块涨跌幅柱状图。

    Args:
        sector_data: [(板块名, 涨跌幅%), ...]
        top_n: 显示前N个

    Returns:
        柱状图文本
    """
    if not sector_data:
        return ""

    sorted_data = sorted(sector_data, key=lambda x: -x[1])
    return ascii_bar_chart(sorted_data[:top_n], width=30, title="板块涨跌幅排名")


if __name__ == "__main__":
    import sys, os, random, math
    sys.stdout = open(1, 'w', encoding='utf-8', closefd=False)

    # 测试折线图
    test_data = [math.sin(i * 0.3) * 10 + 3000 for i in range(30)]
    print(ascii_line_chart(test_data, width=30, height=6, title="上证指数模拟"))
    print()

    # 测试柱状图
    test_bars = [
        ("半导体", 5.2), ("AI算力", 4.8), ("机器人", 3.5),
        ("消费电子", 2.8), ("新能源", -1.2), ("煤炭", -2.5),
        ("银行", -0.8), ("军工", 1.5),
    ]
    print(ascii_bar_chart(test_bars, width=30, title="板块排行"))
    print()

    # 测试Sparkline
    test_data2 = [v + random.uniform(-5, 5) for v in [3000, 3010, 2990, 3020, 3050, 3040, 3060, 3080, 3100, 3090]]
    print(f"  Sparkline: {sparkline(test_data2, 15)}")
