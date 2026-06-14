#!/usr/bin/env python3
"""基于本地数据的智能热点板块识别"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

from local_screener import parse_day_file, load_code_name_map, get_stock_name, calc_vr

# 行业关键词映射（股票名称→板块）
SECTOR_KEYWORDS = {
    "芯片半导体": ["芯片", "半导体", "集成电路", "封测", "晶圆", "光刻", "IGBT", "MCU", "NOR"],
    "AI算力": ["AI", "人工智能", "算力", "服务器", "大模型", "液冷", "智能体"],
    "数字经济": ["数据", "数字", "软件", "IT服务", "云计算", "信创", "鸿蒙"],
    "新能源": ["新能源", "光伏", "锂电", "电池", "风电", "储能", "氢能"],
    "新能源汽车": ["汽车", "新能源车", "整车", "零部件", "一体化压铸"],
    "机器人": ["机器人", "机器", "自动化", "工业母机", "减速器"],
    "军工航天": ["军工", "航天", "航空", "船舶", "国防", "卫星"],
    "医药医疗": ["医药", "医疗", "生物", "创新药", "中药", "医美"],
    "消费食品": ["消费", "食品", "饮料", "白酒", "乳业", "调味"],
    "金融地产": ["银行", "券商", "保险", "地产", "证券", "金融"],
    "资源周期": ["煤炭", "有色", "钢铁", "化工", "石油", "黄金"],
    "通信5G": ["通信", "5G", "6G", "光通信", "光模块", "光纤"],
    "电力能源": ["电力", "电网", "发电", "核电", "特高压"],
    "机械装备": ["机械", "装备", "重工", "工程", "基建"],
}

def detect_hot_sectors(top_n=5):
    """基于本地数据扫描，找出今日涨幅居前的板块"""
    name_map = load_code_name_map()
    print(f'  [热点] 扫描{len(name_map)}只股票识别热点板块...', file=sys.stderr)

    # 统计每个板块的上涨股票数和平均涨幅
    sector_stats = {}  # {板块: {up_count, total_count, sum_chg, stocks}}

    for code in list(name_map.keys())[:3000]:  # 扫描前3000只有效率
        if code.startswith(('9','3','4','8','5')) or code.startswith(('688','689')):
            continue

        # 确定市场
        if code.startswith(('6','5')):
            market = 'sh'
        elif code.startswith(('0','3','2')):
            market = 'sz'
        else:
            continue

        fp = f'D:/new_tdx/vipdoc/{market}/lday/{market}{code}.day'
        if not os.path.exists(fp):
            continue

        klines = parse_day_file(fp, 5)  # 只要最近5天
        if len(klines) < 2:
            continue

        c = klines[-1]
        name = get_stock_name(code) or ''
        if not name:
            continue

        # 对每只股票，判断它属于哪个板块
        matched_sectors = []
        for sector, keywords in SECTOR_KEYWORDS.items():
            for kw in keywords:
                if kw in name or kw in code:
                    matched_sectors.append(sector)
                    break

        if not matched_sectors:
            continue  # 未匹配到任何板块的股票跳过

        # 更新板块统计
        for sector in matched_sectors:
            if sector not in sector_stats:
                sector_stats[sector] = {'count': 0, 'up_count': 0, 'sum_chg': 0.0, 'stocks': []}
            sector_stats[sector]['count'] += 1
            if c.pct_chg > 0:
                sector_stats[sector]['up_count'] += 1
                sector_stats[sector]['sum_chg'] += c.pct_chg
                sector_stats[sector]['stocks'].append(f'{code}({name},{c.pct_chg:+.1f}%)')

    # 计算评分：上涨比例 * 平均涨幅 * 权重
    scored = []
    for sector, stats in sector_stats.items():
        if stats['count'] < 3:
            continue  # 样本太少跳过
        up_ratio = stats['up_count'] / stats['count']
        avg_chg = stats['sum_chg'] / stats['up_count'] if stats['up_count'] > 0 else 0
        # 评分 = 上涨比例^2 * 平均涨幅（突出普涨+大涨的板块）
        score = (up_ratio ** 2) * avg_chg * 10
        scored.append((score, sector, stats))

    scored.sort(key=lambda x: -x[0])

    hot_sectors = []
    print(f'\n  【今日热点板块（本地扫描）】', file=sys.stderr)
    print(f'  {"板块":<14} {"评分":<6} {"上涨/总数":<10} {"均涨幅":<8} {"代表股"}', file=sys.stderr)
    for score, sector, stats in scored[:top_n]:
        hot_sectors.append(sector)
        avg = stats['sum_chg'] / stats['up_count'] if stats['up_count'] > 0 else 0
        top_stocks = '|'.join([s.split('(')[0] for s in stats['stocks'][:3]])
        print(f'  {sector:<14} {score:<6.1f} {stats["up_count"]}/{stats["count"]:<6} {avg:<+6.1f}%  {top_stocks}', file=sys.stderr)

    return hot_sectors[:top_n]


if __name__ == '__main__':
    sectors = detect_hot_sectors(8)
    print(f'\n  推荐热点: {" | ".join(sectors)}')
