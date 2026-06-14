"""
短线选股策略系统 - 核心策略模块
集成5大2026年A股短线策略，基于妙想智能选股API
"""

import sys
import traceback
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

# 导入妙想选股引擎
from config import MX_XUANGU_DIR
if MX_XUANGU_DIR not in sys.path:
    sys.path.insert(0, MX_XUANGU_DIR)

from mx_xuangu import MXSelectStock

from config import (
    LOW_VOLUME_FIRST_BOARD,
    CHAIN_BOARD_WEAK_TO_STRONG,
    TREND_ACCELERATION,
    N_SHAPE_REVERSAL,
    MULTI_DIMENSION,
    COMBINED,
    OUTPUT_DIR,
)
from utils import write_csv, safe_filename, get_timestamp, normalize_row, filter_st_stocks, find_field


# ==================== 数据结构 ====================

@dataclass
class StrategyResult:
    """单个策略的执行结果"""
    name: str
    description: str
    stocks: List[Dict[str, str]] = field(default_factory=list)
    count: int = 0
    query: str = ""
    error: Optional[str] = None


# ==================== 策略基类 ====================

class BaseStrategy:
    """所有策略的基类，封装妙想API调用"""

    def __init__(self):
        self._client = None

    def _get_client(self) -> MXSelectStock:
        if self._client is None:
            self._client = MXSelectStock()
        return self._client

    def _query(self, query: str) -> Tuple[List[Dict[str, str]], Optional[str]]:
        try:
            client = self._get_client()
            resp = client.search(query)
            rows, data_source, err = client.extract_data(resp)
            if err:
                return [], f"API返回错误: {err}"
            if not rows:
                return [], None
            # 统一字段名并过滤ST
            rows = [normalize_row(r) for r in rows]
            rows = filter_st_stocks(rows)
            return rows, None
        except Exception as e:
            return [], f"查询异常: {type(e).__name__}: {e}"

    def run(self) -> StrategyResult:
        raise NotImplementedError


# ==================== 策略实现 ====================

class LowVolumeFirstBoardStrategy(BaseStrategy):
    """
    策略1: 低位放量首板
    逻辑：低位首次放量大涨/涨停，均线多头排列，趋势启动信号
    来源：龙头战法手册、国盛量价淘金因子研究
    """

    def run(self) -> StrategyResult:
        cfg = LOW_VOLUME_FIRST_BOARD
        result = StrategyResult(
            name="低位放量首板",
            description="低位首次放量突破 + 均线多头排列，首板启动信号",
            query=cfg["query"],
        )

        rows, err = self._query(cfg["query"])
        if err:
            result.error = err
            return result

        # 按涨幅降序排列
        rows.sort(key=lambda x: float(x.get("涨跌幅", 0) or 0), reverse=True)
        result.stocks = rows[:cfg["top_n"]]
        result.count = len(result.stocks)
        return result


class ChainBoardWeakToStrongStrategy(BaseStrategy):
    """
    策略2: 连板接力弱转强
    逻辑：昨日涨停 -> 今日继续走强 -> 连板接力
    来源：连板接力实战指南、和讯情绪分析
    """

    def run(self) -> StrategyResult:
        cfg = CHAIN_BOARD_WEAK_TO_STRONG
        result = StrategyResult(
            name="连板接力弱转强",
            description="昨日涨停股今日继续走强，连板接力核心信号",
            query=cfg["query"],
        )

        rows, err = self._query(cfg["query"])
        if err:
            result.error = err
            return result

        # 涨幅为负的剔除（昨日涨停今天还跌 = 弱）
        rows = [r for r in rows if (float(r.get("涨跌幅", 0) or 0) > 0)]
        # 涨幅适中的优先（1%-5%最佳接力区间，越接近3%越好）
        rows.sort(key=lambda x: abs(float(x.get("涨跌幅", 0) or 0) - 3.0))
        result.stocks = rows[:cfg["top_n"]]
        result.count = len(result.stocks)
        return result


class TrendAccelerationStrategy(BaseStrategy):
    """
    策略3: 趋势加速
    逻辑：均线多头排列 + 放量 + MACD金叉 -> 主升浪加速段
    来源：国泰海通高频资金流策略、方正量价因子
    """

    def run(self) -> StrategyResult:
        cfg = TREND_ACCELERATION
        result = StrategyResult(
            name="趋势加速",
            description="均线多头排列 + 放量 + MACD金叉，主升浪加速段",
            query=cfg["query"],
        )

        rows, err = self._query(cfg["query"])
        if err:
            result.error = err
            return result

        # 按涨幅降序
        rows.sort(key=lambda x: float(x.get("涨跌幅", 0) or 0), reverse=True)
        result.stocks = rows[:cfg["top_n"]]
        result.count = len(result.stocks)
        return result


class NShapeReversalStrategy(BaseStrategy):
    """
    策略4: N字反包
    逻辑：前期有涨停基因 -> 缩量回调 -> 再次放量走强
    来源：游龙戏凤指标、涨停龙回头策略
    """

    def run(self) -> StrategyResult:
        cfg = N_SHAPE_REVERSAL
        result = StrategyResult(
            name="N字反包",
            description="前期有涨停基因 -> 回调企稳 -> 再次放量走强",
            query=cfg["query"],
        )

        rows, err = self._query(cfg["query"])
        if err:
            result.error = err
            return result

        rows.sort(key=lambda x: float(x.get("涨跌幅", 0) or 0), reverse=True)
        result.stocks = rows[:cfg["top_n"]]
        result.count = len(result.stocks)
        return result


class MultiDimensionStrategy(BaseStrategy):
    """
    策略5: 多维精选（基本面+技术面+资金面）
    逻辑：基本面安全垫(PE合理+ROE高) + 技术面走强 + 资金活跃
    来源：三维度过滤选股模型
    """

    def run(self) -> StrategyResult:
        cfg = MULTI_DIMENSION
        result = StrategyResult(
            name="多维精选",
            description="基本面安全(PE+ROE) + 技术面走强 + 资金活跃，三维共振",
            query=cfg["query"],
        )

        rows, err = self._query(cfg["query"])
        if err:
            result.error = err
            return result

        rows.sort(key=lambda x: float(x.get("涨跌幅", 0) or 0), reverse=True)
        result.stocks = rows[:cfg["top_n"]]
        result.count = len(result.stocks)
        return result


# ==================== 策略引擎 ====================

def run_all_strategies() -> List[StrategyResult]:
    """运行所有启用的策略"""
    strategy_defs = [
        ("低位放量首板", LOW_VOLUME_FIRST_BOARD, LowVolumeFirstBoardStrategy),
        ("连板接力弱转强", CHAIN_BOARD_WEAK_TO_STRONG, ChainBoardWeakToStrongStrategy),
        ("趋势加速", TREND_ACCELERATION, TrendAccelerationStrategy),
        ("N字反包", N_SHAPE_REVERSAL, NShapeReversalStrategy),
        ("多维精选", MULTI_DIMENSION, MultiDimensionStrategy),
    ]

    results = []
    for name, cfg, cls in strategy_defs:
        if not cfg["enabled"]:
            print(f"  [-] {name}: 已禁用")
            continue
        print(f"  [+] {name}...", end=" ")
        try:
            strategy = cls()
            r = strategy.run()
            results.append(r)
            if r.error:
                print(f"[失败] {r.error}")
            else:
                print(f"[OK] 选到 {r.count} 只")
        except Exception as e:
            print(f"[异常] {type(e).__name__}: {e}")
    return results


def combine_results(results: List[StrategyResult]) -> List[Dict[str, Any]]:
    """
    合并多策略结果，综合排名
    - 统计每只股票被多少个策略选中（策略共振）
    - 按共振数 + 涨幅排序
    """
    stock_map: Dict[str, Dict[str, Any]] = {}

    for r in results:
        if r.error or not r.stocks:
            continue
        for s in r.stocks:
            code = s.get("代码", "")
            name = s.get("名称", "")
            price = s.get("最新价", "")
            chg = s.get("涨跌幅", "")

            if not code:
                continue

            if code not in stock_map:
                stock_map[code] = {
                    "代码": code,
                    "名称": name,
                    "最新价": price,
                    "涨跌幅": chg,
                    "_strategies": [],
                }

            stock_map[code]["_strategies"].append(r.name)

            if price and not stock_map[code]["最新价"]:
                stock_map[code]["最新价"] = price
            if chg and not stock_map[code]["涨跌幅"]:
                stock_map[code]["涨跌幅"] = chg
            if name and not stock_map[code]["名称"]:
                stock_map[code]["名称"] = name

    combined = []
    for code, info in stock_map.items():
        info["策略命中数"] = len(info["_strategies"])
        info["策略组合"] = " + ".join(info["_strategies"])
        del info["_strategies"]
        combined.append(info)

    combined.sort(key=lambda x: (
        -x["策略命中数"],
        -(float(x.get("涨跌幅", 0)) if str(x.get("涨跌幅", "")).replace(".", "").replace("-", "").isdigit() else 0)
    ))

    return combined


def print_results(results: List[StrategyResult], combined: List[Dict[str, Any]]):
    """打印结果到终端"""
    print(f"\n{'='*60}")
    print("  [摘要] 各策略执行结果")
    print(f"{'='*60}")
    for r in results:
        if r.error:
            print(f"  [失败] {r.name}: {r.error}")
        else:
            stock_str = ", ".join(
                f"{s.get('名称','?')}({s.get('代码','')})"
                for s in r.stocks[:5]
            )
            print(f"  [OK] {r.name}: {r.count}只")
            if r.stocks:
                print(f"    前5: {stock_str}")
    print()

    min_s = COMBINED["min_strategies"]
    filtered = [s for s in combined if s["策略命中数"] >= min_s]
    top_n = COMBINED["top_n"]

    print(f"{'='*60}")
    print(f"  [综合推荐] Top{top_n}（策略共振 >= {min_s}个）")
    print(f"{'='*60}")
    print(f"  {'代码':<8} {'名称':<10} {'涨幅%':<8} {'命中':<6} {'策略组合'}")
    print(f"  {'-'*8} {'-'*10} {'-'*8} {'-'*6} {'-'*30}")

    shown = 0
    for s in filtered:
        if shown >= top_n:
            break
        print(f"  {s.get('代码',''):<8} {s.get('名称',''):<10} {str(s.get('涨跌幅','')):<8} {s.get('策略命中数',0):<3}* {s.get('策略组合','')}")
        shown += 1

    if not filtered:
        print("  （没有共振股票，各策略独立看）")


def save_results(results: List[StrategyResult],
                 combined: List[Dict[str, Any]]) -> List[str]:
    """保存结果到CSV文件"""
    ts = get_timestamp()
    summary = []

    for r in results:
        if r.stocks:
            fname = safe_filename(f"{r.name}_{ts}")
            path = OUTPUT_DIR / f"策略_{fname}.csv"
            write_csv(path, r.stocks)
            summary.append(f"  [CSV] {path.name} ({r.count}只)")

    if combined:
        path = OUTPUT_DIR / f"综合推荐_{ts}.csv"
        write_csv(path, combined)
        summary.append(f"  [CSV] {path.name} ({len(combined)}只)")

    return summary
