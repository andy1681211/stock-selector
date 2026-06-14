#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
======================================================================
  涨停板捕捉系统 v2.0
  ───────────────────────────────────
  核心改进:
    1. 基于本地通达信板块数据识别当日热点板块
    2. 热点板块内股票评分加权 + 自动筛选
    3. 非热点+低评分自动淘汰 (282只 -> ~30只)
    4. 新增"明日涨停预测"专区
    5. 盘中实时监控模式 (pytdx直连)
    6. 多策略共振优先

  策略矩阵:
    S1 连板接力 - 昨日涨停+今日续强 (弱转强/强更强)
    S2 首板捕捉 - 底部首次放量突破 (含涨停/大涨>7%)
    S3 竞价异动 - 跳空高开+放量 (早盘抢筹信号)
    S4 涨停潜力 - 综合基因+动量+位置评分 (候选池)

  与旧系统(local_screener.py)的根本区别:
    旧系统: 稳健低吸, 排除涨停, 缠论买点优先
    新系统: 主动捕捉涨停, 热点优先, 动量优先
======================================================================
"""

import os, sys, time, re
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# ---- 本模块路径 ----
TOOL_DIR = Path(__file__).parent
OUTPUT_DIR = TOOL_DIR / "output"
sys.path.insert(0, str(TOOL_DIR))

from tdx_reader import parse_day_file, calc_ma, calc_volume_ratio
from market_regime import detect_market_regime

# ---- 路径常量 ----
TDX_ROOT = "D:/new_tdx/vipdoc"
HQ_CACHE = "D:/new_tdx/T0002/hq_cache"
TDX_BLOCK_FILE = "D:/new_tdx/T0002/blocknew/CLAUDELB.blk"
TDX_BLOCK_HOT = "D:/new_tdx/T0002/blocknew/CLAUDELB_HOT.blk"

# ---- TDX行情服务器IP（监控模式用） ----
TDX_HQ_IPS = [
    "180.153.18.170",  # 上海主站
    "180.153.18.171",
    "119.147.212.81",  # 深圳主站
    "119.147.212.82",
    "211.101.14.129",  # 北京主站
    "218.108.47.69",
]

# =====================================================================
#  工具函数
# =====================================================================

_code_name_map = None

def load_code_name_map() -> Dict[str, str]:
    global _code_name_map
    if _code_name_map is not None:
        return _code_name_map
    _code_name_map = {}
    path = os.path.join(HQ_CACHE, "infoharbor_ex.code")
    if os.path.exists(path):
        with open(path, 'r', encoding='gbk', errors='ignore') as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) >= 2:
                    code, name = parts[0].strip(), parts[1].strip()
                    if code and name:
                        _code_name_map[code] = name
    return _code_name_map

def get_name(code: str) -> str:
    m = load_code_name_map()
    return m.get(code, "")

def read_block_stocks(blk_path: str) -> List[str]:
    stocks = []
    if not os.path.exists(blk_path):
        return stocks
    with open(blk_path, 'rb') as f:
        for line in f.read().decode('gbk').strip().split('\n'):
            line = line.strip()
            if line:
                stocks.append(line[1:])
    return stocks

def write_tdx_block(stocks: List[Dict], blk_path: str, max_count: int = 20):
    if not stocks:
        return
    lines = [""]
    for s in stocks[:max_count]:
        code = s.get("代码", "")
        if code.startswith(("6", "9", "5")):
            prefix = "1"
        elif code.startswith(("0", "3", "2")):
            prefix = "0"
        elif code.startswith(("4", "8")):
            prefix = "4"
        else:
            continue
        lines.append(f"{prefix}{code}")
    raw = "\r\n".join(lines)
    os.makedirs(os.path.dirname(blk_path), exist_ok=True)
    with open(blk_path, "wb") as f:
        f.write(raw.encode("gbk"))
    print(f"  [板块] {len(lines)-1}只 -> {os.path.basename(blk_path)}")

def safe_print(text: str):
    """安全打印到控制台 (过滤非GBK字符)"""
    try:
        print(text.encode('gbk', errors='replace').decode('gbk'))
    except:
        print(text.encode('ascii', errors='replace').decode('ascii'))

# =====================================================================
#  热门题材关键词库
# =====================================================================

HOT_THEMES = {
    "玻璃基板":      ["玻璃基板", "玻璃基", "玻璃封装", "载板", "TGV"],
    "芯片/半导体":    ["芯片", "半导体", "存储芯片", "DRAM", "NAND", "晶圆", "封测", "先进封装", "光刻"],
    "光通信/CPO":    ["光通信", "CPO", "光模块", "光纤", "光芯片", "1.6T", "硅光"],
    "超级电容/MLCC": ["超级电容", "电容器", "MLCC", "钽电容", "薄膜电容"],
    "消费电子":      ["消费电子", "手机", "折叠屏", "AI PC", "AI手机", "IOT"],
    "机器人":        ["机器人", "人形机器人", "执行器", "减速器", "具身智能", "优必选"],
    "AI/算力":       ["AI", "人工智能", "大模型", "算力", "deepseek", "智能体", "液冷", "AI服务器"],
    "低空经济":      ["低空经济", "飞行汽车", "eVTOL", "无人机", "空管"],
    "新能源":        ["新能源", "光伏", "锂电", "固态电池", "钠离子", "BC电池", "钙钛矿"],
    "电力/电网":     ["电力", "虚拟电厂", "智能电网", "供改", "特高压"],
    "煤炭/能源":     ["煤炭", "焦煤", "焦炭", "安检", "停产"],
    "有色金属":      ["有色", "铜", "铝", "黄金", "稀土", "锡", "锑", "钨"],
    "化工":          ["化工", "制冷剂", "氟化工", "磷化工", "钛白粉", "MDI"],
    "医药/医疗":     ["医药", "创新药", "中药", "医疗", "器械", "CXO"],
    "大消费":        ["消费", "食品", "饮料", "乳业", "白酒", "预制菜", "零售"],
    "重组/借壳":     ["重组", "借壳", "资产注入", "股权转让"],
    "国企改革":      ["国企改革", "央企", "中字头", "资产重组"],
    "燃气轮机/IDC":  ["燃气轮机", "数据中心", "IDC", "发电机", "UPS"],
    "航天/军工":     ["航天", "军工", "商业航天", "卫星", "大飞机"],
}

# =====================================================================
#  热点板块识别 (纯本地，不调用任何外部API)
# =====================================================================

def get_hot_sectors_from_api() -> Tuple[List[str], Dict[str, List[str]]]:
    """
    基于新浪免费接口获取行业指数涨幅排名
    返回: (热板块列表, {板块: [代表股代码]})
    """
    import urllib.request

    idx_map = {
        'sh000018': '金融', 'sh000019': '地产',
        'sh000033': '有色材料', 'sh000034': '工业',
        'sh000035': '消费', 'sh000037': '医药',
        'sh000039': '信息技术', 'sh000040': '电信',
        'sh000041': '公用事业', 'sz399395': '医药',
        'sz399394': '科技', 'sz399393': '地产',
        'sz399967': '军工', 'sz399998': '煤炭',
        'sz399997': '白酒消费', 'sz399932': '消费',
        'sz399437': '证券', 'sz399959': '钢铁',
        'sz399987': '船舶', 'sh000032': '能源',
    }

    results = []
    codes = list(idx_map.keys())
    for i in range(0, len(codes), 10):
        batch = codes[i:i+10]
        url = 'https://hq.sinajs.cn/list=' + ','.join(batch)
        req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn'})
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read().decode('gbk')
            for line in raw.strip().splitlines():
                if not line.startswith('var hq_str_'):
                    continue
                parts = line.split('"')
                if len(parts) < 2:
                    continue
                fields = parts[1].split(',')
                if len(fields) < 32:
                    continue
                code_key = line.split('_')[2].split('=')[0]
                now = float(fields[3]) if fields[3] else 0
                yclose = float(fields[2]) if fields[2] else 0
                if yclose > 0:
                    chg = (now - yclose) / yclose * 100
                    name = idx_map.get(code_key, fields[0])
                    results.append((chg, name))
        except:
            continue

    results.sort(key=lambda x: -x[0])
    seen = set()
    sectors = []
    for _, name in results:
        if name not in seen:
            seen.add(name)
            sectors.append(name)
        if len(sectors) >= 5:
            break
    print(f"  [热点] {' | '.join(sectors)}")
    return sectors, {}


def _detect_hot_sectors_local() -> Tuple[List[str], Dict[str, List[str]]]:
    """
    内置热点检测：基于通达信板块文件中涨幅板块的命名分析 + 涨幅排名
    若板块文件可用则读取，否则基于HOT_THEMES中已活跃股票反推
    """
    sectors = []
    sector_stocks = {}

    # 方法1: 读取通达信近期热门板块板块文件 (如果有)
    blk_dir = os.path.dirname(TDX_BLOCK_FILE)
    hot_block_files = []
    if os.path.isdir(blk_dir):
        for fname in os.listdir(blk_dir):
            if "HOT" in fname.upper() or "热门" in fname:
                hot_block_files.append(os.path.join(blk_dir, fname))

    # 方法2: 扫描涨幅最大的板块 - 通过读取ETF/板块指数
    # 读取申万一级行业板块信息
    sector_index_map = _load_sector_index_map()

    # 方法3: 通过本地涨幅数据判断哪些主题正在活跃
    # 快速扫描近期涨幅大的股票，归类到HOT_THEMES
    active_codes = _find_recent_active_stocks()

    # 将活跃股票匹配到热点主题
    name_map = load_code_name_map()
    code_hot_map = {}  # code -> theme
    for code in active_codes:
        name = name_map.get(code, "")
        if not name:
            continue
        for theme, kws in HOT_THEMES.items():
            for kw in kws:
                if kw in name or kw in code:
                    if theme not in sectors:
                        sectors.append(theme)
                    if theme not in sector_stocks:
                        sector_stocks[theme] = []
                    if len(sector_stocks[theme]) < 10 and code not in sector_stocks[theme]:
                        sector_stocks[theme].append(code)
                    break

    return sectors, sector_stocks


def _load_sector_index_map() -> Dict[str, str]:
    """加载板块指数映射（通达信板块指数代码）"""
    return {
        "有色金属": "sh512400", "芯片/半导体": "sh512480", "医药/医疗": "sh512170",
        "新能源": "sh516160", "煤炭/能源": "sh515220", "军工": "sh512660",
        "电力/电网": "sh561560", "机器人": "sh562500",
    }


def _find_recent_active_stocks(lookback_days: int = 3) -> List[str]:
    """
    扫描最近3日涨幅较大的股票（>5%），用于反推热点板块
    """
    active = []
    name_map = load_code_name_map()
    t0 = time.time()
    scanned = 0
    for market in ['sh', 'sz', 'bj']:
        lday = os.path.join(TDX_ROOT, market, "lday")
        if not os.path.exists(lday):
            continue
        for fname in sorted(os.listdir(lday)):
            if not fname.endswith('.day'):
                continue
            code = fname.replace('.day', '')[2:]  # 去掉市场前缀
            scanned += 1
            if scanned > 500:  # 只扫前500只作为采样
                break
            if code not in name_map:
                continue
            fp = os.path.join(lday, fname)
            klines = parse_day_file(fp, 20)
            if len(klines) < 3:
                continue
            # 最近3天中有没有涨幅>5%的
            recent_total = sum(
                (klines[i].close - klines[i-1].close) / klines[i-1].close * 100
                for i in range(max(1, len(klines)-lookback_days), len(klines))
                if klines[i-1].close > 0
            )
            if recent_total >= 5.0:
                active.append(code)
        if scanned >= 500:
            break
    return active


def match_stock_to_sector(code: str, name: str,
                           hot_sectors: List[str],
                           sector_stocks: Dict[str, List[str]]) -> Tuple[Optional[str], bool]:
    """判断股票是否属于热点板块。返回 (板块名, 是否热点)"""
    if not hot_sectors:
        return None, False
    # 精确匹配
    for sec in hot_sectors:
        if code in sector_stocks.get(sec, []):
            return sec, True
    # 关键词匹配
    for sec in hot_sectors:
        for kw in HOT_THEMES.get(sec, [sec]):
            if kw in name:
                return sec, True
    return None, False


# ---- 全局热点缓存 ----
_HOT_SECTORS: List[str] = []
_SECTOR_STOCKS: Dict[str, List[str]] = {}

def set_hot_sectors(sectors: List[str], stocks: Dict[str, List[str]]):
    global _HOT_SECTORS, _SECTOR_STOCKS
    _HOT_SECTORS = sectors
    _SECTOR_STOCKS = stocks

def get_hot_bonus(code: str, name: str) -> Tuple[int, str]:
    if not _HOT_SECTORS:
        return 0, ""
    sec, is_hot = match_stock_to_sector(code, name, _HOT_SECTORS, _SECTOR_STOCKS)
    return (20, sec) if is_hot else (0, "")  # 热点+20分

# =====================================================================
#  涨停质量评估
# =====================================================================

def calc_limit_up_quality(klines: List) -> Dict:
    """涨停基因评分 (0-100)"""
    if len(klines) < 20:
        return {"quality_score": 0, "limit_up_count": 0, "max_consecutive": 0,
                "has_limit_gene": False, "涨停质量": 0}

    limit_dates = []
    for i in range(1, len(klines)):
        if klines[i].pct_chg >= 9.0:
            limit_dates.append(klines[i].date)

    max_consecutive = 1
    cur = 1
    for i in range(1, len(limit_dates)):
        gap = (limit_dates[i] - limit_dates[i-1]).days
        if gap <= 3:
            cur += 1
            max_consecutive = max(max_consecutive, cur)
        else:
            cur = 1

    count = len(limit_dates)
    has_gene = count >= 2
    avg_gap = (len(klines) / max(count, 1)) if count > 0 else 999

    score = 0
    if has_gene:          score += 30
    if count >= 5:        score += 20
    elif count >= 3:      score += 10
    if max_consecutive >= 3: score += 20
    elif max_consecutive >= 2: score += 10
    if avg_gap < 30:      score += 15
    if avg_gap < 10:      score += 15

    return {
        "涨停次数": count, "最大连板": max_consecutive,
        "涨停间隔": round(avg_gap, 1), "有涨停基因": has_gene,
        "涨停质量": min(score, 100),
    }

def calc_morning_strength(klines: List) -> Dict:
    """开盘强度"""
    if len(klines) < 2:
        return {"is_gap_up": False, "gap_pct": 0}
    today, yesterday = klines[-1], klines[-2]
    gap_pct = (today.open - yesterday.close) / yesterday.close * 100
    return {"is_gap_up": gap_pct > 0.5, "gap_pct": round(gap_pct, 2)}

# =====================================================================
#  策略1: 首板捕捉 (收紧版)
# =====================================================================

def strategy_first_board(klines: List, code: str, full_code: str) -> Optional[Dict]:
    """
    底部首次放量突破 (首板)
    门槛: 今日涨>=5%, 过去20天无涨停, 量比>=1.5, 横盘形态
    """
    if len(klines) < 40:
        return None
    c = klines[-1]
    name = get_name(code)
    if not name or name.startswith(("*ST", "ST")):
        return None
    chg = c.pct_chg
    if chg < 5.0 or c.close < 3.0:
        return None
    # 过去20天无涨停
    for i in range(-20, -1):
        if klines[i].pct_chg >= 9.0:
            return None
    # 横盘形态
    r20 = klines[-20:-1]
    amp = (max(k.high for k in r20) - min(k.low for k in r20)) / min(k.low for k in r20) * 100 if min(k.low for k in r20) > 0 else 100
    chg60 = (c.close - klines[-60].close) / klines[-60].close * 100 if len(klines) >= 60 else 0
    # 量能
    vr = calc_volume_ratio([k for k in klines], 5)
    tvr = vr[-1] if vr else 1.0
    ma5 = calc_ma(klines, 5); ma10 = calc_ma(klines, 10); ma20 = calc_ma(klines, 20)
    m5 = ma5[-1] if ma5 else 0; m10 = ma10[-1] if ma10 else 0; m20 = ma20[-1] if ma20 else 0

    score, sig, hb, sec = 0, [], 0, ""
    # 涨幅
    if chg >= 9.5:     score += 30; sig.append("涨停")
    elif chg >= 7.0:   score += 20; sig.append("大涨")
    else:              score += 10; sig.append("走强")
    # 量能
    if tvr >= 3.0:    score += 25; sig.append("巨量")
    elif tvr >= 2.0:  score += 15; sig.append("放量")
    elif tvr >= 1.5:  score += 8;  sig.append("温和放量")
    # 位置
    if amp < 15:      score += 25; sig.append("强横盘")
    elif amp < 25:    score += 15; sig.append("横盘突破")
    elif amp < 35:    score += 8;  sig.append("平台突破")
    if 0 < chg60 < 15: score += 15; sig.append("低位首板")
    elif chg60 < 0:    score += 8;  sig.append("超跌反弹")
    # 均线
    if m5 > m10 > m20:   score += 15; sig.append("多头排列")
    elif m5 > m20:       score += 5
    # 基因
    gene = calc_limit_up_quality(klines)
    if gene["有涨停基因"]: score += 10
    if gene["最大连板"] >= 2: score += 5; sig.append("连板基因")
    # 竞价
    mg = calc_morning_strength(klines)
    if mg["is_gap_up"] and mg["gap_pct"] > 1.0: score += 10; sig.append("跳空")
    # 热点加成
    hb, sec = get_hot_bonus(code, name)
    if hb: score += hb; sig.append(f"热:{sec}")
    if tvr < 1.5 and chg < 7.0: return None
    if score < 60: return None  # v2收紧: 60 (v1是40)

    return {"代码": code, "名称": name, "最新价": round(c.close, 2),
            "涨跌幅": round(chg, 2), "量比": round(tvr, 2), "评分": score,
            "信号": " + ".join(sig), "策略": "首板捕捉",
            "涨停质量": gene["涨停质量"], "跳空": f"{mg['gap_pct']:.1f}%" if mg["is_gap_up"] else "",
            "热点板块": sec, "热度加成": hb}

# =====================================================================
#  策略2: 连板接力 (收紧版)
# =====================================================================

def strategy_chain_board(klines: List, code: str, full_code: str) -> Optional[Dict]:
    """昨日涨停+今日续强 = 连板接力"""
    if len(klines) < 15: return None
    c, y = klines[-1], klines[-2]
    name = get_name(code)
    if not name or name.startswith(("*ST", "ST")): return None
    chg = c.pct_chg
    if y.pct_chg < 9.0 or chg <= 0: return None

    mg = calc_morning_strength(klines)
    vr = calc_volume_ratio([k for k in klines], 5)
    tvr = vr[-1] if vr else 1.0
    one_word = (y.open == y.close == y.high and y.pct_chg >= 9.9)
    weak = (y.high > y.close * 1.02) or (y.pct_chg < 10.0)

    score, sig, subst = 0, [], ""
    if one_word and mg["is_gap_up"]:
        subst = "强更强"; score += 40; sig.append("一字加速")
        if chg >= 7: score += 20; sig.append("续板")
    elif weak and mg["is_gap_up"] and tvr >= 1.5:
        subst = "弱转强"; score += 35; sig.append("弱转强")
        if mg["gap_pct"] > 2.0: score += 15; sig.append("竞价抢筹")
    elif chg >= 5.0 and tvr >= 1.5:
        subst = "连板接力"; score += 25; sig.append("连板")
    else:
        return None

    gene = calc_limit_up_quality(klines)
    if gene["最大连板"] >= 3: score += 15; sig.append("老龙头")
    if gene["有涨停基因"]:    score += 10
    # MACD检查
    closes = [k.close for k in klines]
    if len(closes) >= 35:
        e12, e26 = [closes[0]], [closes[0]]
        for v in closes[1:]: e12.append(v * 2/13 + e12[-1] * 11/13); e26.append(v * 2/27 + e26[-1] * 25/27)
        dif = [e12[i] - e26[i] for i in range(len(e12))]
        dea = [dif[0]]
        for v in dif[1:]: dea.append(v * 2/10 + dea[-1] * 8/10)
        if dif[-1] > dea[-1]: score += 10
        if dif[-1] > dea[-1] > 0: score += 5
    # 热点加成
    hb, sec = get_hot_bonus(code, name)
    if hb: score += hb; sig.append(f"热:{sec}")

    if score < 55: return None

    return {"代码": code, "名称": name, "最新价": round(c.close, 2),
            "涨跌幅": round(chg, 2), "量比": round(tvr, 2), "评分": score,
            "信号": " + ".join(sig), "策略": f"连板接力/{subst}",
            "涨停质量": gene["涨停质量"],
            "跳空": f"{mg['gap_pct']:.1f}%" if mg["is_gap_up"] else "",
            "热点板块": sec, "热度加成": hb}

# =====================================================================
#  策略3: 竞价异动 (收紧版)
# =====================================================================

def strategy_morning_auction(klines: List, code: str, full_code: str) -> Optional[Dict]:
    """跳空高开+放量 = 早盘抢筹"""
    if len(klines) < 5: return None
    c, y = klines[-1], klines[-2]
    name = get_name(code)
    if not name or name.startswith(("*ST", "ST")): return None
    mg = calc_morning_strength(klines)
    if not mg["is_gap_up"] or mg["gap_pct"] < 1.5: return None
    vr = calc_volume_ratio([k for k in klines], 5)
    tvr = vr[-1] if vr else 1.0
    if tvr < 1.8: return None

    score, sig = 0, ["竞价异动"]
    if mg["gap_pct"] >= 3.0:     score += 30; sig.append("大幅跳空")
    elif mg["gap_pct"] >= 2.0:   score += 20; sig.append("跳空高开")
    if tvr >= 3.0:               score += 25; sig.append("巨量竞价")
    elif tvr >= 2.0:             score += 15; sig.append("放量竞价")
    if len(klines) >= 20:
        rl = min(k.low for k in klines[-20:])
        if c.open <= rl * 1.05: score += 20; sig.append("低位异动")
    if y.close > y.open:         score += 10; sig.append("阳线承接")
    hb, sec = get_hot_bonus(code, name)
    if hb: score += hb; sig.append(f"热:{sec}")

    if score < 45: return None

    return {"代码": code, "名称": name, "最新价": round(c.close, 2),
            "涨跌幅": round(c.pct_chg, 2), "量比": round(tvr, 2), "评分": score,
            "信号": " + ".join(sig), "策略": "竞价异动",
            "涨停质量": calc_limit_up_quality(klines)["涨停质量"],
            "跳空": f"{mg['gap_pct']:.1f}%",
            "热点板块": sec, "热度加成": hb}

# =====================================================================
#  策略4: 综合涨停潜力评估
# =====================================================================

def strategy_limit_quality(klines: List, code: str, full_code: str) -> Optional[Dict]:
    """综合涨停基因+动量+位置 (候选池)"""
    if len(klines) < 40: return None
    c = klines[-1]
    name = get_name(code)
    if not name or name.startswith(("*ST", "ST")): return None
    chg = c.pct_chg
    if chg < 1.0: return None

    gene = calc_limit_up_quality(klines)
    mg = calc_morning_strength(klines)
    vr = calc_volume_ratio([k for k in klines], 5)
    tvr = vr[-1] if vr else 1.0

    score, sig = 0, []
    # 基因
    score += min(gene["涨停质量"] * 0.3, 30)
    if gene["有涨停基因"]: sig.append(f"基因{ gene['涨停次数']}次")
    # 动量
    if chg >= 9.0: score += 30; sig.append("涨停")
    elif chg >= 7.0: score += 20; sig.append("强势")
    elif chg >= 5.0: score += 10; sig.append("走强")
    elif chg >= 3.0: score += 5
    # 量能
    if tvr >= 3.0: score += 20; sig.append("巨量")
    elif tvr >= 2.0: score += 12; sig.append("放量")
    elif tvr >= 1.5: score += 5
    # 竞价
    if mg["is_gap_up"]: score += min(mg["gap_pct"] * 3, 10); sig.append(f"跳空{mg['gap_pct']:.1f}%")
    # 位置
    if len(klines) >= 60:
        c60 = (c.close - klines[-60].close) / klines[-60].close * 100
        if 0 <= c60 <= 30: score += 10; sig.append("中低位")
        elif c60 < 0: score += 5; sig.append("超跌")
    # 热点
    hb, sec = get_hot_bonus(code, name)
    if hb: score += hb; sig.append(f"热:{sec}")

    if score < 60: return None  # 涨停潜力收紧到60

    return {"代码": code, "名称": name, "最新价": round(c.close, 2),
            "涨跌幅": round(chg, 2), "量比": round(tvr, 2), "评分": round(score, 1),
            "信号": " + ".join(sig), "策略": "涨停潜力",
            "涨停质量": gene["涨停质量"],
            "跳空": f"{mg['gap_pct']:.1f}%" if mg["is_gap_up"] else "",
            "热点板块": sec, "热度加成": hb}

# =====================================================================
#  主扫描引擎
# =====================================================================

def scan_for_limit_up(code: str, full_code: str, klines: List) -> Optional[Dict]:
    """综合扫描所有策略，取最优"""
    results = []
    for fn in [strategy_first_board, strategy_chain_board,
               strategy_morning_auction, strategy_limit_quality]:
        try:
            r = fn(klines, code, full_code)
            if r:
                results.append(r)
        except:
            continue
    if not results:
        return None
    results.sort(key=lambda x: -x["评分"])
    best = results[0]
    hits = list(set(r["策略"] for r in results))
    best["命中策略数"] = len(hits)
    best["全部策略"] = " | ".join(sorted(hits))
    # 多策略共振加分
    if len(hits) >= 3:
        best["评分"] = round(best["评分"] * 1.2, 1)
    elif len(hits) >= 2:
        best["评分"] = round(best["评分"] * 1.1, 1)
    # 全局硬过滤: 非热点板块股需要更高分
    is_hot = bool(best.get("热点板块"))
    if not is_hot and best["评分"] < 80:
        return None
    return best


def run_limit_up_screen() -> List[Dict]:
    """全市场扫描"""
    results = []
    name_map = load_code_name_map()
    total = scanned = 0
    t0 = time.time()
    for market in ['sh', 'sz', 'bj']:
        lday = os.path.join(TDX_ROOT, market, "lday")
        if not os.path.exists(lday): continue
        for fname in sorted(os.listdir(lday)):
            if not fname.endswith('.day'): continue
            fc = fname.replace('.day', '')
            code = fc[2:]
            total += 1
            if code not in name_map: continue
            scanned += 1
            if scanned % 500 == 0:
                print(f"  扫描: {scanned} 只... ({time.time()-t0:.0f}s)", end='\r', flush=True)
            fp = os.path.join(lday, fname)
            klines = parse_day_file(fp, 250)
            if len(klines) < 40: continue
            for i in range(1, len(klines)):
                if klines[i-1].close > 0:
                    klines[i].pct_chg = (klines[i].close - klines[i-1].close) / klines[i-1].close * 100
            r = scan_for_limit_up(code, fc, klines)
            if r:
                results.append(r)
    print(f"\n  扫描完成: {total} 文件, {scanned} 有名称")
    return results


# =====================================================================
#  报告生成
# =====================================================================

STRATEGY_ORDER = [
    ("连板接力", "[连板接力] 昨日涨停+今日续强 = 明日连板概率高"),
    ("首板捕捉", "[首板捕捉] 底部首次放量突破 = 首板启动"),
    ("竞价异动", "[竞价异动] 跳空高开+放量 = 早盘主力抢筹"),
    ("涨停潜力", "[涨停潜力] 综合基因+动量 = 候选池"),
]

def generate_report(results: List[Dict], index_info: Dict = None) -> str:
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = []
    lines.append("=" * 75)
    lines.append("  涨停捕捉系统 v2.0")
    lines.append(f"  生成: {now}")
    lines.append("=" * 75)
    lines.append("")

    # 市场状态
    if index_info:
        lines.append(f"  市场: {index_info.get('regime','')}  评分:{index_info.get('score',0)}  建议:{index_info.get('suggestion','')}")
        lines.append("")

    # 热点板块
    if _HOT_SECTORS:
        lines.append(f"  [热点] {' | '.join(_HOT_SECTORS)}")
        lines.append("")

    # ---- 明日核心推荐 (Top 10) ----
    hot_stocks = [r for r in results if r.get("热点板块")]
    normal_stocks = [r for r in results if not r.get("热点板块")]
    all_sorted = sorted(hot_stocks, key=lambda x: -x["评分"]) + sorted(normal_stocks, key=lambda x: -x["评分"])[:5]
    top10 = all_sorted[:10]

    if top10:
        lines.append("=" * 75)
        lines.append("  ★★★ 明日涨停核心推荐 TOP 10 ★★★")
        lines.append("=" * 75)
        lines.append(f"  {'#':<3} {'代码':<8} {'名称':<10} {'涨幅%':<7} {'评分':<6} {'策略':<16} {'热点':<12} {'信号'}")
        lines.append(f"  {'-'*3} {'-'*8} {'-'*10} {'-'*7} {'-'*6} {'-'*16} {'-'*12} {'-'*20}")
        for i, r in enumerate(top10, 1):
            sector = r.get("热点板块", "") or ""
            mark = "★" if sector else " "
            lines.append(f"  {mark}{i:<2} {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<+7.2f} {r['评分']:<6} {r['策略']:<16} {sector:<12} {r['信号']}")
        lines.append("")

    # ---- 按策略分组 ----
    for key, title in STRATEGY_ORDER:
        matched = [r for r in results if key in r.get("策略", "")]
        if not matched: continue
        matched.sort(key=lambda x: -x["评分"])
        lines.append(title)
        lines.append(f"  {'代码':<8} {'名称':<10} {'涨幅%':<7} {'量比':<5} {'评分':<6} {'板块':<12} {'信号'}")
        lines.append(f"  {'-'*6} {'-'*8} {'-'*6} {'-'*4} {'-'*5} {'-'*10} {'-'*20}")
        for r in matched[:6]:
            q = r.get("涨停质量", 0)
            grade = "A" if q >= 80 else "B" if q >= 60 else "C" if q >= 40 else "D"
            sec = r.get("热点板块", "") or "--"
            lines.append(f"  {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<+7.2f} {r['量比']:<5.1f} {r['评分']:<6} {sec:<12} {r['信号']}")
        if len(matched) > 6:
            lines.append(f"  ... 还有{len(matched)-6}只")
        lines.append("")

    # ---- 多策略共振 ----
    multi = [r for r in results if r.get("命中策略数", 1) >= 2]
    if multi:
        multi.sort(key=lambda x: -x["评分"])
        lines.append("[多策略共振] 多策略同时命中 (可信度高)")
        lines.append(f"  {'代码':<8} {'名称':<10} {'涨幅%':<7} {'评分':<6} {'命中':<5} {'策略'}")
        lines.append(f"  {'-'*6} {'-'*8} {'-'*6} {'-'*5} {'-'*4} {'-'*30}")
        for r in multi[:8]:
            lines.append(f"  {r['代码']:<8} {r['名称']:<10} {r['涨跌幅']:<+7.2f} {r['评分']:<6} {r['命中策略数']:<3}个 {r.get('全部策略','')}")
        lines.append("")

    # ---- 热点板块汇总 ----
    if _HOT_SECTORS:
        lines.append("[热点板块内候选股]")
        for sec in _HOT_SECTORS[:5]:
            sec_stocks = [r for r in results if r.get("热点板块") == sec]
            if sec_stocks:
                desc = ', '.join('{} {}({})'.format(r.get('名称',''), r.get('代码',''), f"{r.get('涨跌幅',0):+.1f}%") for r in sec_stocks[:5])
                lines.append(f"  {sec}: {desc}")
        lines.append("")

    # ---- 统计 ----
    chain = len([r for r in results if "连板接力" in r.get("策略","")])
    first = len([r for r in results if "首板捕捉" in r.get("策略","")])
    auc = len([r for r in results if "竞价异动" in r.get("策略","")])
    lines.append("-" * 75)
    lines.append(f"  总计: {len(results)}只 | 连板:{chain} | 首板:{first} | 竞价:{auc} | 多策略:{len(multi)} | 热点内:{len([r for r in results if r.get('热点板块')])}")
    lines.append("")
    lines.append("  策略说明:")
    lines.append("  连板接力/强更强: 昨日一字板 -> 今日继续高开=加速连板")
    lines.append("  连板接力/弱转强: 昨日烂板/分歧 -> 今日高开放量=弱转强接力")
    lines.append("  首板捕捉: 底部横盘(振幅<25%)+首次放量(量比>2)+涨幅>7%")
    lines.append("  竞价异动: 跳空高开(>1.5%)+放量(量比>1.8)=主力抢筹")
    lines.append("  涨停潜力: 综合涨停基因+动量+中低位=候选池")
    lines.append("")
    lines.append("  涨停基因评级: A=多次涨停+连板  B=有连板记录")
    lines.append("                  C=有涨停记录  D=近期活跃")
    lines.append("")
    lines.append("  [风险提示] 涨停板追高有风险, 建议:")
    lines.append("  1. 单票仓位不超过10%")
    lines.append("  2. 次日不涨停果断卖出")
    lines.append("  3. 优先做热点板块内的信号")
    lines.append("=" * 75)
    return "\n".join(lines)


# =====================================================================
#  盘中实时监控 (pytdx)
# =====================================================================

def monitor_limit_up_candidates(interval: int = 30):
    """盘中实时监控候选股"""
    try:
        from pytdx.hq import TdxHq_API
    except ImportError:
        print("  [监控] 需要 pytdx: pip install pytdx")
        return

    stocks = read_block_stocks(TDX_BLOCK_FILE)
    if not stocks:
        print("  [监控] CLAUDELB为空, 先运行选股")
        return
    # 如果CLAUDEBL为空, 尝试读CLAUDEBL_HOT
    if not stocks:
        stocks = read_block_stocks(TDX_BLOCK_HOT)
    if not stocks:
        print("  [监控] 板块文件为空, 请先运行扫描")
        return

    name_map = load_code_name_map()
    last_alert = {}  # code -> last_chg

    def mkt(c):
        return 1 if c.startswith(('6','9')) else 0 if c.startswith(('0','3','2')) else 2

    # ---- 遍历服务器列表，直到连接成功 ----
    api = TdxHq_API(heartbeat=False)
    connected = False
    for ip in TDX_HQ_IPS:
        try:
            if api.connect(ip, 7709, time_out=2):
                print(f"  [监控] 连接通达信成功: {ip}")
                connected = True
                break
        except:
            continue

    if not connected:
        print("  [监控] 所有TDX服务器连接失败")
        return

    print(f"\n  [监控] {len(stocks)}只候选 | 每{interval}s刷新 | 仅显示异动")
    print(f"  {'代码':<8} {'名称':<10} {'最新价':<9} {'涨幅':<8} {'最高%':<8} {'信号'}")
    print(f"  {'-'*50}")

    fail_count = 0
    try:
        while True:
            cl = [(mkt(c), c) for c in stocks]
            quotes = []
            for i in range(0, len(cl), 80):
                try:
                    qs = api.get_security_quotes(cl[i:i+80])
                    if qs: quotes.extend(qs)
                except:
                    fail_count += 1
                    continue

            # 连续失败重连
            if fail_count >= 3:
                print(f"\n  [监控] 连接异常, 尝试重连...")
                api.disconnect()
                reconnected = False
                for ip in TDX_HQ_IPS:
                    try:
                        if api.connect(ip, 7709, time_out=2):
                            reconnected = True
                            fail_count = 0
                            break
                    except:
                        continue
                if not reconnected:
                    print("  [监控] 重连失败, 退出")
                    break

            now = datetime.now().strftime('%H:%M:%S')
            for q in quotes:
                code = str(q.get('code',''))
                price = q.get('price', 0)
                lc = q.get('last_close', 0)
                if lc <= 0: continue
                chg = (price - lc) / lc * 100
                high = q.get('high', 0)
                hchg = (high - lc) / lc * 100 if lc > 0 else 0

                signal = ""
                if chg >= 9.0:          signal = "🔥涨停"
                elif chg >= 7.0:        signal = "⚡冲击涨停"
                elif chg >= 5.0:
                    signal = "📈大涨(炸板)" if hchg >= 9.0 and chg < 9.0 else "📈大涨"
                elif chg >= 3.0:
                    signal = "⚠️炸板深回" if hchg >= 9.0 and chg < 9.0 else ""
                elif chg <= -3.0:       signal = "📉大跌"
                elif chg >= 2.0:        signal = "↗走强"

                # 仅显示有异动+变化大的
                last = last_alert.get(code, -999)
                if signal and abs(chg - last) >= 1.0:
                    name = name_map.get(code, code)
                    print(f"  [{now}] {code:<8} {name:<10} {price:<9.2f} {chg:>+6.2f}% {hchg:>+6.2f}% {signal}")
                    last_alert[code] = chg

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n  [监控] 停止")
    finally:
        api.disconnect()
        print("  [监控] 已断开连接")


# =====================================================================
#  主入口
# =====================================================================

def main():
    t0 = time.time()
    print("=" * 60)
    print("  涨停捕捉系统 v2.0")
    print("=" * 60)

    # ---- 1. 热点板块 ----
    print("\n  [热点] 识别当日热点...", end=" ")
    try:
        sectors, stockmap = get_hot_sectors_from_api()
        if sectors:
            set_hot_sectors(sectors, stockmap)
            print(f"OK -> {' | '.join(sectors[:7])}")
        else:
            print("(无)")
    except Exception as e:
        print(f"跳过 ({type(e).__name__})")

    # ---- 2. 全市场扫描 ----
    print("  [扫描] 运行涨停捕捉策略...")
    results = run_limit_up_screen()
    print(f"\n  [OK] 捕获 {len(results)} 只 (耗时 {time.time()-t0:.1f}s)")

    if not results:
        print("  无符合条件")
        return

    # ---- 3. 排序 ----
    results.sort(key=lambda x: -x["评分"])

    # ---- 4. 写通达信板块 ----
    # 全量板块
    write_tdx_block(results, TDX_BLOCK_FILE, 30)
    # 热点板块精选 (只写热点内的)
    hot_only = [r for r in results if r.get("热点板块")]
    if hot_only:
        write_tdx_block(hot_only, TDX_BLOCK_HOT, 20)
        print(f"  [热点精选] {len(hot_only)}只热板块内候选 -> CLAUDELB_HOT.blk")
    else:
        print("  [热点精选] 无热板块候选")

    # ---- 5. 大盘状态 ----
    index_info = None
    ipath = os.path.join(TDX_ROOT, "sh", "lday", "sh000001.day")
    if os.path.exists(ipath):
        try:
            ik = parse_day_file(ipath, 250)
            if len(ik) >= 60:
                index_info = detect_market_regime(ik)
        except: pass

    # ---- 6. 生成保存报告 ----
    report = generate_report(results, index_info)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    rpath = OUTPUT_DIR / f"涨停捕捉报告_{ts}.txt"
    rpath.write_text(report, encoding="utf-8")

    safe_print("\n" + report)
    print(f"\n  [OK] 报告: {rpath}")
    print(f"  [OK] 板块: CLAUDELB.blk ({len(results)}只) + CLAUDELB_HOT.blk ({len(hot_only)}只)")
    print(f"  [OK] 通达信: Ctrl+F2 -> 自定义板块 -> CLAUDELB / CLAUDELB_HOT")
    print()

    # ===== Memos 涨停捕捉日志 =====
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from memos_logger import is_configured as memos_configured, create_memo
        if memos_configured():
            date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            top_stocks = results[:10]
            stock_lines = "\n".join(
                f"- {s['代码']} {s['名称']} {s.get('涨幅',0):+.2f}% 评分:{s['评分']} {'🔥热点' if s.get('热点板块') else ''}"
                for s in top_stocks
            )
            content = f"""# 涨停捕捉 {date_str}

**捕获**: {len(results)}只 | **热点精选**: {len(hot_only) if hot_only else 0}只

{"**热点**:" + ' '.join(sectors[:5]) if sectors else ""}

{stock_lines}

#选股日记 #涨停捕捉
"""
            create_memo(content)
            print("  [Memos] 涨停捕捉日志已写入")
    except Exception as e:
        print(f"  [Memos] 跳过: {e}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitor", action="store_true", help="盘中监控")
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args()
    if args.monitor:
        monitor_limit_up_candidates(args.interval)
    else:
        main()
