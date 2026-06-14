#!/usr/bin/env python3
"""
通达信数据读取模块
解析 .day 日K线文件，计算技术指标
"""

import struct
import os
import math
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path

TDX_ROOT = "D:/new_tdx/vipdoc"

@dataclass
class KLine:
    """日K线数据"""
    date: date
    open: float
    high: float
    low: float
    close: float
    amount: float   # 成交额(元)
    volume: float   # 成交量(股)
    pct_chg: float = 0.0  # 涨跌幅百分比

@dataclass
class StockInfo:
    """股票信息"""
    code: str       # 完整代码，如 sh600519
    name: str = ""
    klines: List[KLine] = None

    @property
    def market(self) -> str:
        return self.code[:2]

    @property
    def short_code(self) -> str:
        return self.code[2:]


# ==================== 通达信 .day 文件解析 ====================

def parse_day_file(filepath: str, max_records: int = 0) -> List[KLine]:
    """
    解析通达信 .day 日K线文件
    格式: 每条32字节
      - date(4) open(4) high(4) low(4) close(4) amount_float(4) volume_int(4) reserve(4)
    价格 = int值/100, 成交量单位=股
    """
    if not os.path.exists(filepath):
        return []

    file_size = os.path.getsize(filepath)
    record_count = file_size // 32
    if record_count == 0:
        return []

    if max_records > 0:
        record_count = min(record_count, max_records)

    klines = []
    with open(filepath, 'rb') as f:
        for _ in range(record_count):
            rec = f.read(32)
            if len(rec) != 32:
                break

            date_int, open_int, high_int, low_int, close_int, amount_f, volume_i, _ = \
                struct.unpack('iiiiifii', rec)

            # date_int 格式 YYYYMMDD
            try:
                dt = datetime.strptime(str(date_int), '%Y%m%d').date()
            except:
                continue

            klines.append(KLine(
                date=dt,
                open=open_int / 100.0,
                high=high_int / 100.0,
                low=low_int / 100.0,
                close=close_int / 100.0,
                amount=amount_f,
                volume=volume_i / 100.0,  # 转为手
            ))

    return klines


def get_stock_filepath(code: str) -> str:
    """获取股票 .day 文件路径"""
    market = code[:2]
    return os.path.join(TDX_ROOT, market, "lday", f"{code}.day")


def get_all_stock_codes() -> List[str]:
    """获取所有有日K线数据的股票代码"""
    codes = []
    for market in ['sh', 'sz', 'bj']:
        lday_dir = os.path.join(TDX_ROOT, market, "lday")
        if not os.path.exists(lday_dir):
            continue
        for f in sorted(os.listdir(lday_dir)):
            if f.endswith('.day'):
                codes.append(f.replace('.day', ''))
    return codes


# ==================== 技术指标计算 ====================

def calc_ma(klines: List[KLine], period: int = 5) -> List[float]:
    """计算移动平均线"""
    closes = [k.close for k in klines]
    mas = []
    for i in range(len(closes)):
        if i < period - 1:
            mas.append(0.0)
        else:
            mas.append(sum(closes[i-period+1:i+1]) / period)
    return mas


def calc_ema(values: List[float], period: int) -> List[float]:
    """计算指数移动平均线"""
    emas = []
    multiplier = 2.0 / (period + 1)
    for i, v in enumerate(values):
        if i == 0 or not emas:
            emas.append(v)
        else:
            emas.append((v - emas[-1]) * multiplier + emas[-1])
    return emas


def calc_macd(klines: List[KLine],
              fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
    """计算MACD指标"""
    closes = [k.close for k in klines]
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    dif = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    dea = calc_ema(dif, signal)
    macd = [2 * (dif[i] - dea[i]) for i in range(len(closes))]
    return {"DIF": dif, "DEA": dea, "MACD": macd}


def calc_rsi(klines: List[KLine], period: int = 6) -> List[float]:
    """计算RSI指标"""
    closes = [k.close for k in klines]
    rsis = []
    gains, losses = 0.0, 0.0

    for i in range(len(closes)):
        if i == 0:
            rsis.append(50.0)
            continue
        change = closes[i] - closes[i-1]
        if change > 0:
            gains += change
        else:
            losses += abs(change)

        if i >= period:
            old_change = closes[i-period+1] - closes[i-period]
            if old_change > 0:
                gains -= old_change
            else:
                losses -= abs(old_change)

        if losses == 0:
            rsis.append(100.0 if gains > 0 else 50.0)
        else:
            rs = gains / losses
            rsis.append(100.0 - 100.0 / (1.0 + rs))

    return rsis


def calc_volume_ratio(klines: List[KLine], period: int = 5) -> List[float]:
    """量比: 今日量 / 过去N日均量"""
    vols = [k.volume for k in klines]
    ratios = []
    for i in range(len(vols)):
        if i < period:
            ratios.append(0.0)
        else:
            avg_vol = sum(vols[i-period:i]) / period
            if avg_vol > 0:
                ratios.append(vols[i] / avg_vol)
            else:
                ratios.append(1.0)
    return ratios


def calc_bollinger(klines: List[KLine], period: int = 20, sigma: float = 2.0) -> Dict:
    """布林带"""
    closes = [k.close for k in klines]
    mid = calc_ma(klines, period)
    upper, lower = [], []

    for i in range(len(closes)):
        if i < period - 1:
            upper.append(0.0)
            lower.append(0.0)
        else:
            window = closes[i-period+1:i+1]
            std = (sum((x - sum(window)/period)**2 for x in window) / period) ** 0.5
            upper.append(mid[i] + sigma * std)
            lower.append(mid[i] - sigma * std)

    return {"MID": mid, "UPPER": upper, "LOWER": lower}


# ==================== 条件筛选 ====================

def check_ma_multi_head(klines: List[KLine]) -> bool:
    """检查均线多头排列 (MA5 > MA10 > MA20 > MA60 > MA120)"""
    if len(klines) < 120:
        return False

    closes = [k.close for k in klines]
    ma5 = [sum(closes[i-4:i+1])/5 for i in range(len(closes))]
    ma10 = [sum(closes[i-9:i+1])/10 for i in range(len(closes))]
    ma20 = [sum(closes[i-19:i+1])/20 for i in range(len(closes))]
    ma60 = [sum(closes[i-59:i+1])/60 for i in range(len(closes))]
    ma120 = [sum(closes[i-119:i+1])/120 for i in range(len(closes))]

    c = len(closes) - 1  # 最新
    return (ma5[c] > ma10[c] > ma20[c] > ma60[c] > ma120[c] and
            ma5[c-1] > ma10[c-1] > ma20[c-1] > ma60[c-1] > ma120[c-1])


def check_ma_golden_cross(klines: List[KLine]) -> bool:
    """检查MA5金叉MA10 (刚发生)"""
    if len(klines) < 11:
        return False
    ma5 = calc_ma(klines, 5)
    ma10 = calc_ma(klines, 10)
    c = len(klines) - 1
    return (ma5[c] > ma10[c] and ma5[c-1] <= ma10[c-1])


def check_macd_golden_cross(klines: List[KLine]) -> bool:
    """检查MACD金叉 (DIF上穿DEA)"""
    if len(klines) < 35:
        return False
    macd = calc_macd(klines)
    dif, dea = macd["DIF"], macd["DEA"]
    c = len(dif) - 1
    return (dif[c] > dea[c] and dif[c-1] <= dea[c-1])


def check_volume_breakout(klines: List[KLine], ratio: float = 2.0) -> bool:
    """检查放量突破 (今日量 > 过去5日均量 * ratio)"""
    if len(klines) < 6:
        return False
    ratios = calc_volume_ratio(klines, 5)
    return ratios[-1] >= ratio


def check_bollinger_breakout(klines: List[KLine]) -> bool:
    """检查突破布林带上轨"""
    if len(klines) < 20:
        return False
    bb = calc_bollinger(klines, 20)
    c = len(klines) - 1
    return klines[c].close > bb["UPPER"][c] > 0


def check_n_shape_reversal(klines: List[KLine]) -> bool:
    """N字反包: 前期涨停/大涨 -> 缩量回调 -> 再次走强"""
    if len(klines) < 15:
        return False

    # 前5日中是否有涨幅>5%的大阳线
    has_big_up = False
    for i in range(-15, -5):
        chg = (klines[i].close - klines[i-1].close) / klines[i-1].close * 100
        if chg > 5:
            has_big_up = True
            break

    if not has_big_up:
        return False

    c = len(klines) - 1
    # 今日涨幅>2%
    today_chg = (klines[c].close - klines[c-1].close) / klines[c-1].close * 100

    return today_chg > 2


def get_realtime_prices(codes: List[str]) -> Dict[str, Dict]:
    """
    通过 pytdx 获取实时行情。

    Args:
        codes: 股票代码列表

    Returns:
        {code: {"price": float, "pct_chg": float, "volume": float, "amount": float}}
    """
    result = {}
    try:
        from pytdx.hq import TDX_HQ_API

        api = TDX_HQ_API()
        api.connect('119.147.212.81', 7709)

        # 分批查询（每批最多50只）
        batch_size = 50
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            # 转换代码格式
            quotes = []
            for code in batch:
                code = code.strip()
                if code.startswith(("6", "9", "5")):
                    market = 1
                elif code.startswith(("0", "3", "2")):
                    market = 0
                elif code.startswith(("4", "8")):
                    market = 4
                else:
                    continue
                quotes.append((market, code))

            if not quotes:
                continue

            try:
                data = api.get_security_quotes(quotes)
                if data:
                    for item in data:
                        code = str(item.get("code", ""))
                        result[code] = {
                            "price": item.get("price", 0),
                            "pct_chg": item.get("buy", [0])[1] / 100 if item.get("buy") else 0,
                            "volume": item.get("zongVol", 0),
                            "amount": item.get("amount", 0),
                        }
            except Exception:
                continue

        api.disconnect()

    except Exception:
        pass

    return result


def check_price_near_low(klines: List[KLine], days: int = 20) -> bool:
    """股价在N日低位（低位放量用）"""
    if len(klines) < days:
        return False
    recent = [k.low for k in klines[-days:]]
    return klines[-1].close <= sorted(recent)[int(days * 0.3)] * 1.05


# ==================== 加载股票 ====================

def load_stock(code: str, max_records: int = 500) -> Optional[StockInfo]:
    """加载一只股票的全部数据"""
    fp = get_stock_filepath(code)
    klines = parse_day_file(fp, max_records)
    if not klines:
        return None

    # 补涨跌幅
    for i in range(1, len(klines)):
        prev_close = klines[i-1].close
        if prev_close > 0:
            klines[i].pct_chg = (klines[i].close - prev_close) / prev_close * 100

    name_map = {"sh": "沪", "sz": "深", "bj": "京"}
    return StockInfo(
        code=code,
        name=f"{code}_{name_map.get(code[:2], '?')}",
        klines=klines
    )


def quick_screen() -> List[Dict]:
    """
    快速扫描全市场，使用本地数据筛选
    返回格式: [{code, name, price, chg, volume_ratio, signals}]
    """
    results = []
    codes = get_all_stock_codes()

    print(f"加载 {len(codes)} 只股票的日K线数据...")

    count = 0
    for code in codes:
        # 跳过指数
        if code[3:6] in ('000', '001') and len(code) == 8:
            if code[2:] in ('000001', '000002', '000003', '000688',
                           '399001', '399006', '399005', '399016'):
                pass  # 保留主要指数
            elif code[:2] == 'sh' and code[3] == '0':
                continue  # 跳过其他上证指数

        stock = load_stock(code, 250)  # 最近一年
        if not stock or len(stock.klines) < 60:
            continue

        k = stock.klines
        c = len(k) - 1  # 最新索引

        # 计算基础指标
        chg = (k[c].close - k[c-1].close) / k[c-1].close * 100 if c > 0 else 0
        vr = calc_volume_ratio(k, 5)[-1]
        ma5 = calc_ma(k, 5)[-1]
        ma20 = calc_ma(k, 20)[-1]
        macd = calc_macd(k)
        dif, dea = macd["DIF"][-1], macd["DEA"][-1]

        signals = []

        # 多头排列
        if ma5 > ma20:
            signals.append("多头")
        if check_ma_multi_head(k):
            signals.append("多头排列")
        if check_volume_breakout(k, 2.0):
            signals.append("放量")
        if check_macd_golden_cross(k):
            signals.append("MACD金叉")
        if chg > 5:
            signals.append("大涨")
        if dif > dea:
            signals.append("MACD多头")
        if check_n_shape_reversal(k):
            signals.append("N字反包")
        if k[c].close > calc_bollinger(k, 20)["UPPER"][c] > 0:
            signals.append("突破布林上轨")

        if signals:
            results.append({
                "代码": code[2:],
                "名称": code,
                "最新价": round(k[c].close, 2),
                "涨跌幅": round(chg, 2),
                "量比": round(vr, 2),
                "均线5日": round(ma5, 2),
                "均线20日": round(ma20, 2),
                "信号": " | ".join(signals),
            })

        count += 1
        if count % 500 == 0:
            print(f"  已扫描 {count} 只...")

    return results


if __name__ == "__main__":
    # 测试读取茅台
    stock = load_stock("sh600519", 5)
    if stock:
        print("茅台最近5日K线:")
        for k in stock.klines:
            print(f"  {k.date} 收:{k.close:.2f} 量:{k.volume:.0f}手 额:{k.amount/10000:.0f}万")

    # 测试MACD
    stock = load_stock("sh600519", 120)
    if stock:
        macd = calc_macd(stock.klines, 12, 26, 9)
        c = len(stock.klines) - 1
        print(f"\n茅台最新MACD: DIF={macd['DIF'][c]:.2f} DEA={macd['DEA'][c]:.2f} MACD={macd['MACD'][c]:.2f}")

    print(f"\n全市场股票数: {len(get_all_stock_codes())}")
