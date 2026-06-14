#!/usr/bin/env python3
"""
三级选股管道 — 初选→精选→精中选精→唯一推荐
目标: 选出一只上涨概率>90%的股票
"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

from datetime import datetime
from local_screener import (
    parse_day_file, calc_ma, calc_macd, calc_rsi, calc_vr, get_stock_name,
    load_code_name_map, is_ma_bullish, is_macd_bullish, is_macd_golden_cross,
    is_pullback_entry, is_first_buy_point, is_second_buy_point, is_third_buy_point,
    get_中枢_position, is_bottom_divergence,
)
from advanced_signals import (
    detect_bottom_fractal, pingbu_qingyun_score, is_washout_complete,
    is_volume_surge_breakout, is_position_building_limit_up, is_washout_limit_up,
    is_erjin_san_pattern, detect_test_line, is_main_wave_ignition,
    detect_base_consolidation, is_feilongzaitian, is_qianlonghuishou,
)
from chip_distribution import calc_chip_metrics, chip_screen_conditions
from seven_roles import seven_roles_analysis

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def stage1_prescreen() -> list:
    """初选: 全市场扫描 → 技术面合格"""
    name_map = load_code_name_map()
    results = []
    total = 0
    print(f'[阶段1/3] 全市场初选...')
    for market in ['sh', 'sz']:
        lday = f'D:/new_tdx/vipdoc/{market}/lday'
        if not os.path.exists(lday):
            continue
        for fname in sorted(os.listdir(lday)):
            if not fname.endswith('.day'):
                continue
            code = fname.replace('.day', '')[2:]
            if code not in name_map:
                continue
            if code.startswith(('9','3','4','8','5')) or code.startswith(('688','689')):
                continue
            total += 1
            if total % 1000 == 0:
                print(f'  扫描: {total}...', end='\r', flush=True)

            fp = os.path.join(lday, fname)
            klines = parse_day_file(fp, 250)
            if len(klines) < 60:
                continue

            c = klines[-1]
            n = get_stock_name(code)
            if not n or n.startswith(('*ST','ST')):
                continue
            if c.close < 5 or c.pct_chg <= 0:
                continue

            ma5 = calc_ma(klines,5)[-1]
            ma10 = calc_ma(klines,10)[-1]
            ma20 = calc_ma(klines,20)[-1]
            dif, dea, hist = calc_macd(klines)
            rsi6 = calc_rsi(klines,6)[-1]
            vr = calc_vr(klines,5)[-1]
            prev_5d = sum(k.pct_chg for k in klines[-6:-1])

            if prev_5d > 10:
                continue
            if rsi6 > 80:
                continue

            hit = 0
            if ma5 > ma10: hit += 1
            if c.close > ma20: hit += 1
            if dif[-1] > dea[-1]: hit += 1
            if vr > 1.2: hit += 1
            if hit >= 3:
                results.append({'code':code, 'name':n, 'market':market, 'klines':klines})

    print(f'  初选完成: {total}只 → {len(results)}只')
    return results

def stage2_quality_filter(candidates: list) -> list:
    """精选: 多维度评分过滤"""
    print(f'\n[阶段2/3] 多维评分精选({len(candidates)}只)...')
    scored = []
    for i, item in enumerate(candidates):
        if i % 50 == 0:
            print(f'  评分: {i}/{len(candidates)}...', end='\r', flush=True)

        klines = item['klines']
        c = klines[-1]
        code, name = item['code'], item['name']

        # ---- 基础指标 ----
        ma5 = calc_ma(klines,5)[-1]
        ma10 = calc_ma(klines,10)[-1]
        ma20 = calc_ma(klines,20)[-1]
        ma60 = calc_ma(klines,60)[-1]
        vr = calc_vr(klines,5)[-1]
        rsi6 = calc_rsi(klines,6)[-1]
        dif, dea, hist = calc_macd(klines)
        prev_5d = sum(k.pct_chg for k in klines[-6:-1])

        # ---- 全部信号检测 ----
        buy2 = is_second_buy_point(klines, dif, dea, hist)
        buy3 = is_third_buy_point(klines, hist, dif, dea)
        buy1 = is_first_buy_point(klines, dif, dea, hist)
        zhong = get_中枢_position(klines)
        bf, bfd = detect_bottom_fractal(klines)
        pbq = pingbu_qingyun_score(klines, vr)
        wo, _ = is_washout_complete(klines)
        tl, tli = detect_test_line(klines, 30)
        mw, mwd = is_main_wave_ignition(klines)
        base, _ = detect_base_consolidation(klines, 45)
        cm = calc_chip_metrics(klines, 250)
        cs = chip_screen_conditions(klines)
        seven = seven_roles_analysis(klines, cm, {})

        # ---- 综合评分(满分100) ----
        score = 0

        # 均线(15)
        if ma5 > ma10 > ma20 and ma20 > ma60:
            score += 15
        elif ma5 > ma10 and ma20 > ma60:
            score += 10
        elif ma5 > ma10:
            score += 5

        # MACD(10)
        if dif[-1] > dea[-1] and hist[-1] > hist[-2]:
            score += 10
        elif dif[-1] > dea[-1]:
            score += 5

        # 量价(10)
        if vr > 1.5: score += 5
        if 0 < c.pct_chg < 6: score += 5

        # 缠论(15)
        if buy2: score += 15
        elif buy1 or buy2: score += 8

        # 中枢(5)
        if zhong == '上方': score += 5

        # 信号(15)
        if bf: score += 3
        if pbq['is_strong']: score += 5
        if wo: score += 3
        if tl and tli.get('has_triple_vol'): score += 8
        elif tl: score += 3
        if mw: score += 10

        # 筹码(10)
        if cm['profit_chip'] > 50: score += 4
        if cm['locked_chip'] < 20: score += 3
        if cs['score'] >= 50: score += 3

        # 七角色(15)
        yz = seven.get('overall_pct', 0)
        score += yz * 0.15

        # 安全(5)
        if prev_5d < 8: score += 3
        if abs((c.close-ma20)/ma20*100) < 15: score += 2

        # 扣分
        if rsi6 > 80: score -= 10
        if prev_5d > 10: score -= 8
        if cm['locked_chip'] > 50: score -= 5
        if cm['profit_chip'] < 20: score -= 5

        score = max(0, min(100, score))

        if score >= 72:
            scored.append({
                'code': code, 'name': name, 'score': score,
                'klines': klines, 'cm': cm, 'cs': cs, 'seven': seven,
                'c': c, 'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
                'vr': vr, 'rsi6': rsi6, 'prev_5d': prev_5d,
                'macd': '多' if dif[-1]>dea[-1] else '空',
                'buy': '二买' if buy2 else ('一买' if buy1 else '无'),
                'zhong': zhong,
            })


    scored.sort(key=lambda x: -x['score'])
    print(f'  精选完成: {len(scored)}只(阈值>=72分)')
    return scored[:8]

def stage3_deep_dive(candidates: list) -> None:
    """精中选精: 深度分析→唯一推荐"""
    print(f'\n[阶段3/3] 深度精析({len(candidates)}只)...')
    print()

    best = None
    for item in candidates:
        klines = item['klines']
        c = item['c']
        item['mw_ok'], item['mw_desc'] = is_main_wave_ignition(klines)
        item['tl_ok'], item['tli'] = detect_test_line(klines, 30)
        item['ql_ok'], item['ql_desc'] = is_qianlonghuishou(klines)
        item['fl_ok'], item['fl_info'] = is_feilongzaitian(klines)
        item['pb_zt'], item['pd_zt'] = is_position_building_limit_up(klines)
        item['wo_zt'], item['wd_zt'] = is_washout_limit_up(klines)
        item['ej_ok'], item['ed_ok'] = is_erjin_san_pattern(klines)
        item['pbq_detail'] = pingbu_qingyun_score(klines, item['vr'])

        # 最终评分微调(不设上限,区分度更重要)
        item['final_score'] = item['score']
        if item['mw_ok']: item['final_score'] += 8
        if item['tl_ok'] and item['tli'].get('has_triple_vol'): item['final_score'] += 5
        if item['pb_zt']: item['final_score'] += 6
        if item['wo_zt']: item['final_score'] += 4
        if item['ej_ok']: item['final_score'] += 8
        if item['fl_ok']: item['final_score'] += 10
        if item['ql_ok']: item['final_score'] += 6
        if item['pbq_detail']['is_strong']: item['final_score'] += item['pbq_detail']['score'] * 0.05
        # 筹码加分
        cm = item['cm']
        if cm['concentration_desc'] == '高度集中(获利)': item['final_score'] += 5
        if cm['locked_chip'] < 5: item['final_score'] += 3
        if cm['profit_chip'] > 80: item['final_score'] += 3
        # 均线排列加分
        klines = item['klines']
        ma5, ma10, ma20, ma60 = item['ma5'], item['ma10'], item['ma20'], item['ma60']
        if ma20 > ma60: item['final_score'] += 3

        if best is None or item['final_score'] > best['final_score']:
            best = item

    # 按最终分排序
    candidates.sort(key=lambda x: -x['final_score'])

    # 输出详细分析
    print('=' * 70)
    print(f'  精中选精报告 | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'  第一轮: 全市场初选  | 第二轮: 多维度评分 | 第三轮: 深度精析')
    print('=' * 70)
    print()

    for i, item in enumerate(candidates[:5]):
        c = item['c']
        klines = item['klines']
        ma5 = item['ma5']; ma10 = item['ma10']; ma20 = item['ma20']; ma60 = item['ma60']
        cm = item['cm']; seven = item['seven']

        tags = []
        if item['buy'] == '二买': tags.append('缠二买')
        if item['mw_ok']: tags.append('🔥起爆')
        if item['tl_ok'] and item['tli'].get('has_triple_vol'): tags.append('💪三倍试盘')
        elif item['tl_ok']: tags.append('📍试盘')
        if item['fl_ok']: tags.append('🐉飞龙')
        if item['ql_ok']: tags.append('🐲潜龙')
        if item['pb_zt']: tags.append('建仓')
        if item['wo_zt']: tags.append('洗盘板')
        if item['ej_ok']: tags.append('二进三')
        if item['pbq_detail']['is_strong']: tags.append('青云')
        tag_str = ' '.join(tags[:5]) if tags else '无'

        print(f'  [{i+1}] {item["code"]} {item["name"]}  综合评分:{item["final_score"]}/100')
        print(f'  {"─" * 60}')
        print(f'      价格:{c.close:.2f}  涨幅:{c.pct_chg:+.1f}%  量比:{item["vr"]:.2f}  RSI:{item["rsi6"]:.1f}')
        print(f'      均线:MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f} MA60={ma60:.2f}')
        if ma5 > ma10 > ma20 and ma20 > ma60:
            print(f'      均线状态: ✅ 完美多头排列')
        elif ma5 > ma10:
            print(f'      均线状态: ⬆️ 短期向上')
        else:
            print(f'      均线状态: ⬇️ 回调')
        print(f'      MACD:{item["macd"]}头  缠论:{item["buy"]}  中枢:{item["zhong"]}')
        print(f'      信号:{tag_str}')
        print(f'      前5日:{item["prev_5d"]:+.1f}%  前20日:{sum(k.pct_chg for k in klines[-21:-1]):+.1f}%')

        # 七角色展示
        seven_roles = seven.get('roles', {})
        if seven_roles:
            parts = []
            for rn, rd in [('趋势跟踪者','📈'),('动量交易者','⚡'),('逆向投资者','📉'),
                           ('风险管理师','🛡️'),('事件驱动交易者','🎯')]:
                if rn in seven_roles:
                    parts.append(f'{rd}{seven_roles[rn].get("verdict","")}')
            print(f'      圆桌会议: {" | ".join(parts[:4])}')

        # 筹码
        print(f'      筹码:获利{cm["profit_chip"]:.0f}% 浮动{cm["float_chip"]:.0f}% 套牢{cm["locked_chip"]:.0f}%  {cm["concentration_desc"]}')

        if item['mw_ok']: print(f'      🔥 主升浪起爆: {item["mw_desc"]}')
        if item['tl_ok']: print(f'      📍 试盘线: {item["tli"].get("latest_desc","")} ({item["tli"].get("count",0)}次)')
        if item['fl_ok']: print(f'      🐉 飞龙在天: {item["fl_info"].get("描述","")}')
        if item['ql_ok']: print(f'      🐲 潜龙回首: {item["ql_desc"]}')
        print()

    # ===== 唯一推荐 =====
    if best:
        c = best['c']
        print('=' * 70)
        print('  ★ 唯一推荐')
        print('=' * 70)
        print(f'''
  ╔══════════════════════════════════════════════════════╗
  ║  {best["code"]} {best["name"]}                    ║
  ║  综合评分: {best["final_score"]}/100 (目标>90分)      ║
  ╠══════════════════════════════════════════════════════╣
  ║  现价:{c.close:.2f}  涨幅:{c.pct_chg:+.1f}%  量比:{best["vr"]:.2f}            ║
  ║  均线: MA5={best["ma5"]:.2f} MA10={best["ma10"]:.2f}             ║
  ║        MA20={best["ma20"]:.2f} MA60={best["ma60"]:.2f}             ║
  ║  缠论:{best["buy"]}  中枢:{best["zhong"]}  MACD:{best["macd"]}头               ║
  ║  信号: {" ".join(tags):<45}  ║
  ╚══════════════════════════════════════════════════════╝''')

        # 上涨概率估算
        prob = min(95, 60 + best['final_score'] * 0.35)
        prob = max(50, prob)
        print(f'''  📊 预估上涨概率: {prob:.0f}%
  🔑 核心逻辑:''')
        if best['mw_ok']:
            print(f'     ✅ 主升浪起爆确认 — 试盘→缩量整理→放量突破')
        if best['tl_ok'] and best['tli'].get('has_triple_vol'):
            print(f'     ✅ 三倍量试盘线 — 主力大资金测试抛压')
        if best['buy'] == '二买':
            print(f'     ✅ 缠论二买 — 确定性最高的缠论买点')
        if best['pbq_detail']['is_strong']:
            print(f'     ✅ 平步青云{best["pbq_detail"]["score"]}分 — 7大特征启动信号')

        print(f'''
  📋 周一操作计划:
     买入: 集合竞价或开盘回踩不破MA5
     价格: {best["ma5"]:.2f}附近
     止损: {best["ma20"]*0.95:.2f} (MA20下方)
     仓位: 总资金25-40%
     目标: 波段持有至前高
  ⚠️ 风险提示:
     若周一大幅低开破MA5-3%或集合竞价量异常，暂停买入
     RSI {best["rsi6"]:.1f} {'偏强注意回调' if best['rsi6'] > 70 else '中性'}
''')

        # 保存结果
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(OUTPUT_DIR, f"最终推荐_{best['code']}_{ts}.txt")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"唯一推荐: {best['code']} {best['name']}\n")
            f.write(f"评分: {best['final_score']}/100\n")
            f.write(f"现价: {c.close:.2f}  涨幅: {c.pct_chg:+.1f}%\n")
            f.write(f"预估上涨概率: {prob:.0f}%\n")
            f.write(f"周一操作: MA5({best['ma5']:.2f})附近买入 止损{best['ma20']*0.95:.2f}\n")
        print(f'  [保存] {path}')

def main():
    candidates = stage1_prescreen()
    if not candidates:
        print('初选无结果')
        return
    filtered = stage2_quality_filter(candidates)
    if not filtered:
        print('精选无结果')
        return
    stage3_deep_dive(filtered)

if __name__ == '__main__':
    main()
