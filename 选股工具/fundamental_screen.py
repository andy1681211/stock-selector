# -*- coding: utf-8 -*-
"""
基本面筛选模块
基于akshare获取财务数据，对选股结果做基本面过滤和评分

关键财务指标阈值:
  净利润增速: >0% (正增长)
  营收增速:   >-5% (不能大幅下滑)
  ROE:        >3% (有盈利能力)
  资产负债率: <70% (债务安全)
  毛利率:     >15% (有利润空间)
"""
import time
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime


# ==================== 财务数据缓存 ====================
_finance_cache: Dict[str, dict] = {}
_cache_time = 0
_CACHE_TTL = 3600  # 1小时缓存


def get_finance_summary(code: str) -> Optional[dict]:
    """
    获取单只股票的最新财务摘要

    返回字段:
      roe: 净资产收益率(%)
      profit_growth: 净利润同比增长(%)
      revenue_growth: 营业收入同比增长(%)
      gross_margin: 毛利率(%)
      debt_ratio: 资产负债率(%)
      eps: 每股收益
      net_profit: 净利润(亿)
      revenue: 营业收入(亿)
      report_date: 报告期
      score: 基本面综合评分(0-100)
    """
    global _cache_time, _finance_cache

    # 缓存过期检查
    now = time.time()
    if now - _cache_time > _CACHE_TTL:
        _finance_cache = {}
    _cache_time = now

    # 命中缓存
    if code in _finance_cache:
        return _finance_cache[code]

    try:
        import akshare as ak

        # 获取财务摘要（东方财富数据源）
        # 字段：净利润, 净利润同比增长, 扣非净利润, 营收, 营收同比增长,
        #       每股收益, 每股净资产, 销售净利率, 毛利率, ROE, 资产负债率
        df = ak.stock_financial_abstract_ths(symbol=code)
        if df is None or df.empty:
            return None

        # 取最新一期（第一行）
        row = df.iloc[0]
        report_date = str(row.iloc[0]) if len(row) > 0 else ""

        # 提取关键指标
        result = {
            "report_date": report_date,
            "code": code,
        }

        # 净利润(亿)
        net_profit_str = str(row.iloc[1]) if len(row) > 1 else "0"
        result["net_profit"] = _extract_num(net_profit_str)

        # 净利润同比增长(%)
        profit_growth_str = str(row.iloc[2]) if len(row) > 2 else "0"
        result["profit_growth"] = _extract_pct(profit_growth_str)

        # 扣非净利润(亿)
        deduct_str = str(row.iloc[3]) if len(row) > 3 else "0"
        result["deduct_profit"] = _extract_num(deduct_str)

        # 扣非净利润同比增长(%)
        deduct_growth_str = str(row.iloc[4]) if len(row) > 4 else "0"
        result["deduct_growth"] = _extract_pct(deduct_growth_str)

        # 营业收入(亿)
        revenue_str = str(row.iloc[5]) if len(row) > 5 else "0"
        result["revenue"] = _extract_num(revenue_str)

        # 营业收入同比增长(%)
        revenue_growth_str = str(row.iloc[6]) if len(row) > 6 else "0"
        result["revenue_growth"] = _extract_pct(revenue_growth_str)

        # 每股收益
        eps_str = str(row.iloc[7]) if len(row) > 7 else "0"
        result["eps"] = _parse_float(eps_str)

        # 每股净资产
        bvps_str = str(row.iloc[8]) if len(row) > 8 else "0"
        result["bvps"] = _parse_float(bvps_str)

        # 每股资本公积金
        capital_reserve = str(row.iloc[9]) if len(row) > 9 else "0"
        result["capital_reserve"] = _parse_float(capital_reserve)

        # 每股未分配利润
        retained = str(row.iloc[10]) if len(row) > 10 else "0"
        result["retained_profit"] = _parse_float(retained)

        # 销售净利率(%)
        net_margin_str = str(row.iloc[12]) if len(row) > 12 else "0"
        result["net_margin"] = _extract_pct(net_margin_str)

        # 毛利率(%)
        gross_margin_str = str(row.iloc[13]) if len(row) > 13 else "0"
        result["gross_margin"] = _extract_pct(gross_margin_str)

        # ROE(%)
        roe_str = str(row.iloc[14]) if len(row) > 14 else "0"
        result["roe"] = _extract_pct(roe_str)

        # ROE-摊薄(%)
        roe_diluted_str = str(row.iloc[15]) if len(row) > 15 else "0"
        result["roe_diluted"] = _extract_pct(roe_diluted_str)

        # 营业总收入
        total_revenue_str = str(row.iloc[16]) if len(row) > 16 else "0"
        result["total_revenue"] = _extract_num(total_revenue_str)

        # 存货周转率
        inventory_turnover = str(row.iloc[17]) if len(row) > 17 else "0"
        result["inventory_turnover"] = _parse_float(inventory_turnover)

        # 资产负债率(%)
        debt_ratio_str = str(row.iloc[24]) if len(row) > 24 else "0"
        result["debt_ratio"] = _extract_pct(debt_ratio_str)

        # 基本面评分
        result["score"] = _calc_fundamental_score(result)

        # 缓存
        _finance_cache[code] = result
        return result

    except Exception as e:
        return None


def _extract_num(s: str) -> float:
    """提取数字（亿）"""
    s = s.strip().replace(",", "").replace(" ", "")
    if not s or s == "--":
        return 0.0
    if "亿" in s:
        s = s.replace("亿", "")
    elif "万" in s:
        s = s.replace("万", "")
        return round(_parse_float(s) / 10000, 4)
    elif "元" in s:
        s = s.replace("元", "")
        return round(_parse_float(s) / 100000000, 4)
    return _parse_float(s)


def _extract_pct(s: str) -> float:
    """提取百分比数值"""
    s = s.strip().replace(",", "").replace(" ", "")
    if not s or s == "--":
        return 0.0
    if "%" in s:
        s = s.replace("%", "")
    return _parse_float(s)


def _parse_float(s: str) -> float:
    """安全转float"""
    try:
        return float(s)
    except:
        return 0.0


def _calc_fundamental_score(f: dict) -> int:
    """
    基本面综合评分 (0-100)

    权重分配:
      成长性(40分): 净利润增速+营收增速
      盈利能力(30分): ROE+毛利率
      财务安全(20分): 资产负债率
      每股价值(10分): EPS
    """
    score = 0

    # 成长性（40分）
    pg = abs(f.get("profit_growth", 0))
    rg = abs(f.get("revenue_growth", 0))

    if pg > 30:
        score += 25
    elif pg > 15:
        score += 20
    elif pg > 0:
        score += 15
    elif pg > -10:
        score += 5  # 小幅下滑还能接受

    if rg > 20:
        score += 15
    elif rg > 10:
        score += 12
    elif rg > 0:
        score += 10
    elif rg > -5:
        score += 5

    # 盈利能力（30分）
    roe = abs(f.get("roe", 0))
    gm = abs(f.get("gross_margin", 0))

    if roe > 15:
        score += 15
    elif roe > 10:
        score += 12
    elif roe > 5:
        score += 8
    elif roe > 3:
        score += 5

    if gm > 40:
        score += 15
    elif gm > 25:
        score += 12
    elif gm > 15:
        score += 8
    elif gm > 5:
        score += 3

    # 财务安全（20分）
    dr = f.get("debt_ratio", 50)
    if dr < 30:
        score += 20
    elif dr < 45:
        score += 15
    elif dr < 60:
        score += 10
    elif dr < 70:
        score += 5

    # 每股价值（10分）
    eps = abs(f.get("eps", 0))
    if eps > 2:
        score += 10
    elif eps > 1:
        score += 8
    elif eps > 0.5:
        score += 6
    elif eps > 0.2:
        score += 4

    return min(score, 100)


def get_finance_batch(codes: List[str]) -> Dict[str, dict]:
    """批量获取财务数据"""
    result = {}
    for i, code in enumerate(codes):
        if i > 0 and i % 5 == 0:
            time.sleep(0.5)  # 防止API限流
        fin = get_finance_summary(code)
        if fin:
            result[code] = fin
    return result


def fundamental_filter(stocks: List[Dict], verbose: bool = True) -> List[Dict]:
    """
    基本面过滤 + 评分
    对股票列表中的每只股获取财务数据，过滤掉基本面差的

    过滤标准:
      净利润增速 < -30% (严重下滑) → 排除
      资产负债率 > 85% (高负债) → 排除
      ROE < 0 (亏损) → 排除
      营收增速 < -20% (大幅下滑) → 排除
    """
    if not stocks:
        return []

    codes = [s["代码"] for s in stocks if "代码" in s]
    fin_data = get_finance_batch(codes)

    passed = []
    excluded = []
    for s in stocks:
        code = s["代码"]
        fin = fin_data.get(code)

        if not fin:
            # 无财务数据，默认通过（降低误杀）
            fin_score = 50
            s["基本面评分"] = "无数据"
            s["基本面"] = "---"
            passed.append(s)
            continue

        # 获取关键指标
        profit_g = fin.get("profit_growth", 0)
        debt_r = fin.get("debt_ratio", 50)
        roe = fin.get("roe", 5)
        rev_g = fin.get("revenue_growth", 0)
        fin_score = fin.get("score", 50)

        # 过滤规则
        exclude_reason = None
        if profit_g < -30:
            exclude_reason = f"利润下滑{profit_g:.1f}%"
        elif roe < -2:
            exclude_reason = f"ROE={roe:.1f}%亏损"
        elif debt_r > 85:
            exclude_reason = f"负债率{debt_r:.1f}%"
        elif rev_g < -20:
            exclude_reason = f"营收下滑{rev_g:.1f}%"

        if exclude_reason:
            excluded.append((code, s.get("名称", ""), exclude_reason))
            continue

        # 格式化显示
        pg_str = f"{profit_g:+.1f}%" if profit_g != 0 else "0%"
        roe_str = f"{roe:.1f}%" if roe else "N/A"
        dr_str = f"{debt_r:.1f}%" if debt_r else "N/A"
        rev_str = f"{rev_g:+.1f}%" if rev_g else "0%"
        gm = f"{fin.get('gross_margin', 0):.1f}%" if fin.get('gross_margin') else "N/A"

        s["基本面评分"] = fin_score
        s["基本面"] = f"ROE{roe_str} 利润{pg_str} 负债{dr_str}"
        s["利润增速"] = pg_str
        s["营收增速"] = rev_str
        s["ROE"] = roe_str
        s["毛利率"] = gm
        s["负债率"] = dr_str
        s["净利润"] = f"{fin.get('net_profit', 0):.2f}亿" if fin.get('net_profit') else "N/A"
        passed.append(s)

    if verbose and excluded:
        print(f"\n  基本面排除 {len(excluded)} 只:")
        for code, name, reason in excluded:
            print(f"    ❌ {code} {name}: {reason}")

    if verbose:
        print(f"  基本面通过: {len(passed)}/{len(stocks)} 只")

    return passed
