# -*- coding: utf-8 -*-
"""
03_aggregate.py — 销售看板数据聚合。

平台无关：读取 01_extract 产出的 master.pkl，完成清洗、客户主数据、分层输入数据、
新客/沉睡/激活/流失/骤降、月度与多维（业务员/品牌/品类）聚合，产出 dashboard_data.json。

用法：
    python 03_aggregate.py --master  <输出目录>/master.pkl \
                          --output  <输出目录>/dashboard_data.json \
                          [--classifier <02_classifier.py>]
"""
import argparse, importlib.util, json, os
from collections import defaultdict
import pandas as pd, numpy as np, re

# 全局常量（与 docs/03 指标字典一致，便于统一调整）
CUST_MIN_YUAN = 1000      # 客户分层/气泡门槛
SLEEP_WINDOW_M = 6        # 沉睡滚动窗口
SLEEP_YUAN = 1000
ACTIVATE_YUAN = 1000
VALID_NEW_MONTHS = 3      # 有效新客：连续 >3
QUALITY_NEW_YUAN = 10000
CHURN_WINDOW_M = 3
DROP_BIG_YUAN = 50000
DROP_BIG_KEEP = 0.90
DROP_MID_YUAN = 10000
DROP_MID_KEEP = 0.80
NON_PRODUCT_CATEGORIES = ['费用/订货/杂项', '纯型号待确认']


def run(master, classifier_path, out_json, role_hint=None):
    df = pd.read_pickle(master)

    # ---------- 1. 基础清洗 ----------
    def norm_id(x):
        x = str(x).strip()
        return x[:-2] if x.endswith('.0') else x
    for c in ('cust_id', 'staff_id', 'product_id'):
        df[c] = df[c].map(norm_id)

    PREFIX_OWNER = {'许': '许静', '珍': '李珍珍', '方': '方芳', '芳': '方芳', '赵': '赵华翠',
                    '吕': '吕明明', '苏': '苏建桥', '月': '王月', '帅': '刘帅', '丽': '姜丽丽',
                    '林': '林(离职分流)', '明': '明(离职分流)', '刘': '刘(待确认)'}
    def fix_staff(row):
        s = row['staff']
        if s in ('A', 'B', 'C'):
            m = re.match(r'^([一-龥A-Za-z])[-★●=]', row['cust_name'])
            if m and m.group(1) in PREFIX_OWNER:
                return PREFIX_OWNER[m.group(1)]
            return '店面/其他'
        if s in ('店面', ''):
            return '店面/其他'
        return s
    df['staff'] = df.apply(fix_staff, axis=1)
    df['brand'] = df['brand'].fillna('').replace('', '未标注品牌')

    # SKU 归一：按商品编号合并改名
    _disp = df.sort_values('date').groupby('product_id')['product_name'].last()
    _sku_before = df['product_name'].nunique()
    df['product_name'] = df['product_id'].map(_disp)
    print(f'SKU 归一：{_sku_before} 个名称 → {df["product_name"].nunique()} 个 SKU')

    # 品牌/品类分类器
    spec = importlib.util.spec_from_file_location('bc', classifier_path)
    bc = importlib.util.module_from_spec(spec); spec.loader.exec_module(bc)
    _res = df.apply(lambda r: bc.finalize(r['brand'], r['product_name']), axis=1)
    df['brand'] = [x[0] for x in _res]
    df['category'] = [x[2] for x in _res]

    df['ym'] = df['date'].dt.to_period('M').astype(str)
    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month

    RETAIL_IDS = set(df.loc[df['cust_name'] == '零售', 'cust_id'].unique())
    INTERNAL = {'昌源店', '供'}
    df['is_retail'] = df['cust_id'].isin(RETAIL_IDS)
    df['is_internal'] = df['cust_name'].isin(INTERNAL)

    # ---------- 2. 调货候选标记 ----------
    STRONG_EXACT = {'昌源店', '供', '诺米代理', '济南诺米', '泰安诺米', '滨州李涛悍高',
                    '三友建材', '德州-潜水艇厨卫优品'}
    def tag_transfer(name):
        n = str(name)
        if n in STRONG_EXACT or '同行' in n or '代理' in n:
            return 2
        if re.match(r'^(济南|临沂|沧州|泰安|枣庄|济宁)-', n) and re.search(r'五金|悍高|诺米|建材', n):
            return 2
        if re.search(r'五金|锁业|锁具|胶业|批发|商贸|商行|工贸|化工|卫浴|电器|建材', n):
            return 1
        return 0

    # ---------- 3. 客户主数据 ----------
    names = (df.sort_values('date').groupby('cust_id')
             .agg(display=('cust_name', lambda s: s.iloc[-1]),
                  all_names=('cust_name', lambda s: sorted(set(s))),
                  first=('date', 'min'), last=('date', 'max'),
                  sales=('sales', 'sum'), qty=('qty', 'sum'), cost=('cost', 'sum'),
                  staff=('staff', lambda s: s.value_counts().index[0]),
                  rows=('sales', 'size')))
    names['transfer_tag'] = names['display'].map(tag_transfer)
    names['is_retail'] = names.index.isin(RETAIL_IDS)
    names['is_internal'] = names['display'].isin(INTERNAL)

    cm = df.groupby(['cust_id', 'ym']).agg(sales=('sales', 'sum'), qty=('qty', 'sum'),
                                           cost=('cost', 'sum')).reset_index()
    months = sorted(df['ym'].unique())
    pv = cm.pivot_table(index='cust_id', columns='ym', values='sales', fill_value=0)
    pv = pv.reindex(columns=months, fill_value=0)

    # ---------- 4. 新客 / 沉睡 / 激活 ----------
    first_ym = df.groupby('cust_id')['ym'].min()
    new_cust_month = first_ym[first_ym != months[0]].value_counts().to_dict()
    sleeping_now, activation_month, sleeping_ever = [], defaultdict(list), set()
    M = len(months)
    for cid, row in pv.iterrows():
        vals = row.values
        for i in range(M):
            if i < SLEEP_WINDOW_M:
                continue
            window = vals[i-SLEEP_WINDOW_M:i]
            had_older = (vals[:i-SLEEP_WINDOW_M] > 0).any()
            if had_older and window.sum() < SLEEP_YUAN:
                sleeping_ever.add(cid)
                if vals[i] > ACTIVATE_YUAN:
                    activation_month[months[i]].append(cid)
    last_i = M - 1
    for cid, row in pv.iterrows():
        vals = row.values
        if cid in RETAIL_IDS:
            continue
        w = vals[max(0, last_i-5):last_i+1]
        older = vals[:max(0, last_i-5)]
        if (older > 0).any() and w.sum() < SLEEP_YUAN:
            sleeping_now.append(cid)
    names['first_ym'] = first_ym
    names['sleeping_now'] = names.index.isin(sleeping_now)
    activated_set = set(c for v in activation_month.values() for c in v)
    names['ever_activated'] = names.index.isin(activated_set)

    # ---------- 5. 全局月度（区分调货） ----------
    def month_agg(d):
        g = d.groupby('ym').agg(sales=('sales', 'sum'), qty=('qty', 'sum'), cost=('cost', 'sum'),
                                orders=('doc_no', 'nunique'),
                                cust=('cust_id', lambda s: s[d.loc[s.index, 'sales'] > 0].nunique()))
        return g
    trans_ids = set(names[names['transfer_tag'] == 2].index)
    df['is_transfer'] = df['cust_id'].isin(trans_ids)
    df['is_analyzable'] = ~(df['is_retail'] | df['is_internal'])
    monthly_all = month_agg(df).reindex(months, fill_value=0)
    monthly_non = month_agg(df[~df['is_transfer']]).reindex(months, fill_value=0)
    monthly_tra = month_agg(df[df['is_transfer']]).reindex(months, fill_value=0)

    base = df[df['is_analyzable']]
    initial_cust_n = int(((first_ym == months[0]) & ~first_ym.index.isin(RETAIL_IDS)
                          & ~names['is_internal']).sum())
    new_by_month = {m: (0 if m == months[0] else int(((first_ym == m)
                     & ~first_ym.index.isin(RETAIL_IDS)).sum())) for m in months}
    act_by_month = {m: len(set(activation_month.get(m, [])) - RETAIL_IDS) for m in months}

    _excl_ids = RETAIL_IDS | set(names.index[names['is_internal']])
    def _streak(cid):
        if cid not in pv.index:
            return 0
        fi = months.index(first_ym[cid]); vals = pv.loc[cid].values; st = 0
        for i in range(fi, len(vals)):
            if vals[i] > 0:
                st += 1
            else:
                break
        return st
    def _q3(cid):
        if cid not in pv.index:
            return False
        v = pv.loc[cid].values
        return any(v[i:i+3].sum() >= QUALITY_NEW_YUAN for i in range(len(v)-2))
    valid_new_by_month, quality_new_by_month = {}, {}
    for m in months:
        if m == months[0]:
            valid_new_by_month[m] = 0; quality_new_by_month[m] = 0; continue
        _ids = [c for c in first_ym.index[first_ym == m] if c not in _excl_ids]
        valid_new_by_month[m] = int(sum(1 for c in _ids if _streak(c) > VALID_NEW_MONTHS))
        quality_new_by_month[m] = int(sum(1 for c in _ids if _q3(c)))
    _active_cm = base.groupby(['cust_id', 'ym'])['sales'].sum().reset_index()
    active_by_month = (_active_cm[_active_cm['sales'] > ACTIVATE_YUAN].groupby('ym')['cust_id']
                       .nunique().reindex(months, fill_value=0).astype(int).to_dict())

    monthly = []
    for m in months:
        monthly.append({
            'ym': m,
            'sales': round(float(monthly_all.loc[m, 'sales']), 2),
            'qty': round(float(monthly_all.loc[m, 'qty']), 2),
            'cost': round(float(monthly_all.loc[m, 'cost']), 2),
            'orders': int(monthly_all.loc[m, 'orders']),
            'cust': int(monthly_all.loc[m, 'cust']),
            'non_sales': round(float(monthly_non.loc[m, 'sales']), 2),
            'non_qty': round(float(monthly_non.loc[m, 'qty']), 2),
            'non_cost': round(float(monthly_non.loc[m, 'cost']), 2),
            'non_orders': int(monthly_non.loc[m, 'orders']),
            'non_cust': int(monthly_non.loc[m, 'cust']),
            'tra_sales': round(float(monthly_tra.loc[m, 'sales']), 2),
            'tra_qty': round(float(monthly_tra.loc[m, 'qty']), 2),
            'new_cust': new_by_month.get(m, 0),
            'valid_new_cust': valid_new_by_month.get(m, 0),
            'quality_new_cust': quality_new_by_month.get(m, 0),
            'activated': act_by_month.get(m, 0),
            'active_cust': active_by_month.get(m, 0),
        })

    # ---------- 6. 职员 × 月 ----------
    def staff_agg(d):
        g = d.groupby(['staff', 'ym']).agg(sales=('sales', 'sum'), qty=('qty', 'sum'),
                                           cost=('cost', 'sum'), orders=('doc_no', 'nunique'),
                                           active=('cust_id', 'nunique')).reset_index()
        owner = names['staff'].to_dict()
        fy = first_ym[first_ym != months[0]]
        newc = fy.to_frame('ym')
        newc['staff'] = [owner.get(c, '') for c in newc.index]
        newc = newc.reset_index().groupby(['staff', 'ym']).size().rename('newc').reset_index()
        g = g.merge(newc, on=['staff', 'ym'], how='outer').fillna({'newc': 0})
        act_rows = []
        for mm, ids in activation_month.items():
            c = pd.Series(ids).map(owner).value_counts()
            for s, n in c.items():
                act_rows.append({'staff': s, 'ym': mm, 'act': int(n)})
        g = g.merge(pd.DataFrame(act_rows), on=['staff', 'ym'], how='outer').fillna({'act': 0})
        g = g.fillna({'sales': 0, 'qty': 0, 'cost': 0, 'orders': 0, 'active': 0,
                      'newc': 0, 'act': 0})
        return g[g['staff'].notna()]
    sa_all = staff_agg(df[~df['is_internal']])
    stra = df[~df['is_internal']].groupby(['staff', 'ym', 'is_transfer']).agg(
        sales=('sales', 'sum'), qty=('qty', 'sum'), cost=('cost', 'sum'),
        orders=('doc_no', 'nunique')).reset_index()
    stra_map = {(r['staff'], r['ym'], int(r['is_transfer'])):
                (float(r['sales']), float(r['qty']), float(r['cost']), int(r['orders']))
                for _, r in stra.iterrows()}
    staff_month = []
    for _, r in sa_all.iterrows():
        key = (r['staff'], r['ym'])
        ntr = stra_map.get(key+(0,), (0, 0, 0, 0)); trr = stra_map.get(key+(1,), (0, 0, 0, 0))
        staff_month.append({'staff': r['staff'], 'ym': r['ym'],
            'sales': round(float(r['sales']), 2), 'qty': round(float(r['qty']), 2),
            'cost': round(float(r['cost']), 2), 'orders': int(r['orders']),
            'active': int(r['active']), 'new': int(r['newc']), 'act': int(r['act']),
            'non_sales': round(ntr[0], 2), 'non_qty': round(ntr[1], 2),
            'non_cost': round(ntr[2], 2), 'non_orders': int(ntr[3]),
            'tra_sales': round(trr[0], 2), 'tra_qty': round(trr[1], 2),
            'tra_cost': round(trr[2], 2)})

    # ---------- 7. 品牌 × 月 ----------
    def brand_monthly(d):
        g = d.groupby(['brand', 'ym']).agg(sales=('sales', 'sum'), cost=('cost', 'sum')).reset_index()
        out_s, out_c = {}, {}
        for b in d['brand'].unique():
            sub = g[g['brand'] == b].set_index('ym').reindex(months, fill_value=0)
            out_s[b] = [round(float(x), 2) for x in sub['sales'].values]
            out_c[b] = [round(float(x), 2) for x in sub['cost'].values]
        return out_s, out_c
    bm_all, bm_all_c = brand_monthly(df)
    bm_non, bm_non_c = brand_monthly(df[~df['is_transfer']])
    bm_tra, bm_tra_c = brand_monthly(df[df['is_transfer']])
    brand_tot = df.groupby('brand')['sales'].sum().sort_values(ascending=False)
    brand_month = []
    for b in brand_tot.index:
        brand_month.append({'brand': b, 'total': round(float(brand_tot[b]), 2),
            'series': bm_all[b], 'non_series': bm_non.get(b, [0]*len(months)),
            'tra_series': bm_tra.get(b, [0]*len(months)),
            'cost_series': bm_all_c[b],
            'non_cost_series': bm_non_c.get(b, [0]*len(months)),
            'tra_cost_series': bm_tra_c.get(b, [0]*len(months))})

    # ---------- 品类 × 月 ----------
    def category_monthly(d):
        g = d.groupby(['category', 'ym']).agg(sales=('sales', 'sum'), cost=('cost', 'sum')).reset_index()
        out_s, out_c = {}, {}
        for c in d['category'].unique():
            sub = g[g['category'] == c].set_index('ym').reindex(months, fill_value=0)
            out_s[c] = [round(float(x), 2) for x in sub['sales'].values]
            out_c[c] = [round(float(x), 2) for x in sub['cost'].values]
        return out_s, out_c
    cm_all, cm_all_c = category_monthly(df)
    cm_non, cm_non_c = category_monthly(df[~df['is_transfer']])
    cat_tot = df.groupby('category')['sales'].sum().sort_values(ascending=False)
    category_month = []
    for c in cat_tot.index:
        category_month.append({'category': c, 'total': round(float(cat_tot[c]), 2),
            'series': cm_all[c], 'non_series': cm_non.get(c, [0]*len(months)),
            'cost_series': cm_all_c[c], 'non_cost_series': cm_non_c.get(c, [0]*len(months))})

    scd = df[~df['is_internal']].groupby(['staff', 'category', 'is_transfer', 'ym']).agg(
        sales=('sales', 'sum'), cost=('cost', 'sum')).reset_index()
    staff_category = []
    for (s, c, tr), g in scd.groupby(['staff', 'category', 'is_transfer']):
        gg = g.set_index('ym').reindex(months, fill_value=0)
        staff_category.append([s, c, int(tr),
            [round(float(x), 2) for x in gg['sales'].values],
            [round(float(x), 2) for x in gg['cost'].values]])
    bcd = df.groupby(['brand', 'category', 'is_transfer', 'ym']).agg(
        sales=('sales', 'sum'), cost=('cost', 'sum')).reset_index()
    brand_category = []
    for (b, c, tr), g in bcd.groupby(['brand', 'category', 'is_transfer']):
        gg = g.set_index('ym').reindex(months, fill_value=0)
        brand_category.append([b, c, int(tr),
            [round(float(x), 2) for x in gg['sales'].values],
            [round(float(x), 2) for x in gg['cost'].values]])

    bs_all = df.groupby(['brand', 'is_transfer']).agg(
        sales=('sales', 'sum'), qty=('qty', 'sum'), cost=('cost', 'sum')).reset_index()
    brand_split = [[r['brand'], int(r['is_transfer']), round(float(r['sales']), 2),
                    round(float(r['qty']), 2), round(float(r['cost']), 2)]
                   for _, r in bs_all.iterrows()]
    sbd = df[~df['is_internal']].groupby(['staff', 'brand', 'is_transfer', 'ym']).agg(
        sales=('sales', 'sum'), cost=('cost', 'sum')).reset_index()
    staff_brand = []
    for (s, b, tr), g in sbd.groupby(['staff', 'brand', 'is_transfer']):
        gg = g.set_index('ym').reindex(months, fill_value=0)
        staff_brand.append([s, b, int(tr),
            [round(float(x), 2) for x in gg['sales'].values],
            [round(float(x), 2) for x in gg['cost'].values]])

    bp = df.groupby(['brand', 'product_name']).agg(sales=('sales', 'sum'), qty=('qty', 'sum')).reset_index()
    bp = bp.sort_values(['brand', 'sales'], ascending=[True, False]).groupby('brand').head(12)
    brand_products = {}
    for b, g in bp.groupby('brand'):
        brand_products[b] = [[str(r['product_name'])[:40], round(float(r['sales']), 2),
                             round(float(r['qty']), 2)] for _, r in g.iterrows() if r['sales'] > 0]

    def product_month_by(key):
        g = df.groupby([key, 'product_name', 'is_transfer', 'ym']).agg(
            sales=('sales', 'sum'), cost=('cost', 'sum')).reset_index()
        tot = df.groupby([key, 'product_name'])['sales'].sum().reset_index()
        tot = tot.sort_values([key, 'sales'], ascending=[True, False]).groupby(key).head(20)
        keep = set(zip(tot[key], tot['product_name']))
        out = []
        for (k, p, tr), gg in g.groupby([key, 'product_name', 'is_transfer']):
            if (k, p) not in keep:
                continue
            rr = gg.set_index('ym').reindex(months, fill_value=0)
            out.append([k, str(p)[:40], int(tr),
                [round(float(x), 2) for x in rr['sales'].values],
                [round(float(x), 2) for x in rr['cost'].values]])
        return out
    brand_product_month = product_month_by('brand')
    category_product_month = product_month_by('category')

    # ---------- 7.5 产品 SKU 主数据 ----------
    def _prod_piv(d, val, agg):
        return d.pivot_table(index='product_name', columns='ym', values=val, aggfunc=agg,
                             fill_value=0).reindex(columns=months, fill_value=0)
    p_sales = _prod_piv(df, 'sales', 'sum')
    p_cost = _prod_piv(df, 'cost', 'sum')
    p_nsales = _prod_piv(df[~df['is_transfer']], 'sales', 'sum')
    p_ncost = _prod_piv(df[~df['is_transfer']], 'cost', 'sum')
    p_days = _prod_piv(df.assign(_d=df['date'].dt.strftime('%Y-%m-%d')), '_d', 'nunique')
    # 对日裁剪：今年各月实际有数据的"日"范围，去年同月仅取相同日范围（避免跨年误删）
    cur_year = int(df['year'].max()); prev_year = cur_year - 1
    df['day'] = df['date'].dt.day
    rng = df[df['year'] == cur_year].groupby('month')['day'].agg(['min', 'max'])
    keep_days = pd.Series(True, index=df.index)
    for mo, rr in rng.iterrows():
        bad = (df['year'] == prev_year) & (df['month'] == mo) & \
              ((df['day'] < rr['min']) | (df['day'] > rr['max']))
        keep_days &= ~bad
    _aln25 = df[keep_days & (df['ym'] == '%04d-02' % prev_year)]
    _a25 = _aln25.groupby('product_name')['sales'].sum()
    _a25n = _aln25[~_aln25['is_transfer']].groupby('product_name')['sales'].sum()
    _bc = df.loc[df.groupby('product_name')['sales'].idxmax()].set_index('product_name')[['brand', 'category']]
    products = []
    for p in sorted(p_sales.index.tolist()):
        br = _bc.loc[p, 'brand'] if p in _bc.index else '未标注品牌'
        cat = _bc.loc[p, 'category'] if p in _bc.index else '未分类'
        products.append([
            str(p)[:40], str(br), str(cat),
            [round(float(x), 2) for x in p_sales.loc[p].values],
            [round(float(x), 2) for x in p_cost.loc[p].values],
            [round(float(x), 2) for x in p_nsales.loc[p].values] if p in p_nsales.index else [0]*len(months),
            [round(float(x), 2) for x in p_ncost.loc[p].values] if p in p_ncost.index else [0]*len(months),
            [int(x) for x in p_days.loc[p].values] if p in p_days.index else [0]*len(months),
            round(float(_a25.get(p, 0)), 2), round(float(_a25n.get(p, 0)), 2)])

    # ---------- 8. 客户输出 + 客户月序列 ----------
    analyzable = ~(names['is_retail'] | names['is_internal'])
    cust_out = []
    for cid, r in names.iterrows():
        cust_out.append({
            'id': cid, 'name': r['display'], 'staff': r['staff'],
            'first': r['first'].strftime('%Y-%m-%d'), 'last': r['last'].strftime('%Y-%m-%d'),
            'sales': round(float(r['sales']), 2), 'qty': round(float(r['qty']), 2),
            'cost': round(float(r['cost']), 2), 'tag': int(r['transfer_tag']),
            'retail': bool(r['is_retail']), 'internal': bool(r['is_internal']),
            'new_ym': r['first_ym'] if r['first_ym'] != months[0] else '',
            'sleep': bool(r['sleeping_now']) and bool(analyzable[cid]),
            'act_ever': bool(r['ever_activated']) and bool(analyzable[cid]),
            'aliases': r['all_names'] if len(r['all_names']) > 1 else []})

    cm2 = cm.merge(names[['is_retail', 'is_internal', 'transfer_tag']], left_on='cust_id', right_index=True)
    cust_month = [[r['cust_id'], r['ym'], round(float(r['sales']), 2),
                   round(float(r['qty']), 2), round(float(r['cost']), 2)]
                  for _, r in cm2.iterrows()]

    # ---------- 对日（同月同日）同比 ----------
    df['day'] = df['date'].dt.day
    df_aln = df[keep_days]
    ALN_MONTH = '%04d-02' % prev_year
    ALN_PSEUDO = ALN_MONTH + 'A'
    ma_all = month_agg(df_aln).reindex(months)
    ma_non = month_agg(df_aln[~df_aln['is_transfer']]).reindex(months)
    active_aln = (df_aln[df_aln['is_analyzable'] & (df_aln['sales'] > 0)]
                  .groupby('ym')['cust_id'].nunique().reindex(months, fill_value=0))
    for rec in monthly:
        if rec['ym'] == ALN_MONTH:
            rec['a_sales'] = round(float(ma_all.loc[ALN_MONTH, 'sales']), 2)
            rec['a_qty'] = round(float(ma_all.loc[ALN_MONTH, 'qty']), 2)
            rec['a_cost'] = round(float(ma_all.loc[ALN_MONTH, 'cost']), 2)
            rec['a_non_sales'] = round(float(ma_non.loc[ALN_MONTH, 'sales']), 2)
            rec['a_non_qty'] = round(float(ma_non.loc[ALN_MONTH, 'qty']), 2)
            rec['a_non_cost'] = round(float(ma_non.loc[ALN_MONTH, 'cost']), 2)
            rec['a_active_cust'] = int(active_aln[ALN_MONTH])
            rec['a_orders'] = int(ma_all.loc[ALN_MONTH, 'orders'])
            rec['a_non_orders'] = int(ma_non.loc[ALN_MONTH, 'orders'])

    sal_a = df_aln[~df_aln['is_internal']].groupby(['staff', 'ym']).agg(
        sales=('sales', 'sum'), qty=('qty', 'sum'), cost=('cost', 'sum'),
        orders=('doc_no', 'nunique'), active=('cust_id', 'nunique'))
    stra_a = df_aln[~df_aln['is_internal']].groupby(['staff', 'ym', 'is_transfer']).agg(
        sales=('sales', 'sum'), qty=('qty', 'sum'), cost=('cost', 'sum'),
        orders=('doc_no', 'nunique')).reset_index()
    stra_a_map = {(r['staff'], r['ym'], int(r['is_transfer'])):
                  (float(r['sales']), float(r['qty']), float(r['cost']), int(r['orders']))
                  for _, r in stra_a.iterrows()}
    for rec in staff_month:
        if rec['ym'] == ALN_MONTH:
            key = (rec['staff'], ALN_MONTH)
            if key in sal_a.index:
                row = sal_a.loc[key]
                rec['a_sales'] = round(float(row['sales']), 2)
                rec['a_qty'] = round(float(row['qty']), 2)
                rec['a_cost'] = round(float(row['cost']), 2)
                rec['a_orders'] = int(row['orders'])
                rec['a_active'] = int(row['active'])
            ntr = stra_a_map.get(key+(0,), (0, 0, 0, 0)); trr = stra_a_map.get(key+(1,), (0, 0, 0, 0))
            rec['a_non_sales'] = round(ntr[0], 2); rec['a_non_qty'] = round(ntr[1], 2)
            rec['a_non_cost'] = round(ntr[2], 2); rec['a_non_orders'] = int(ntr[3])
            rec['a_tra_sales'] = round(trr[0], 2)

    ba_a = df_aln.groupby(['brand', 'ym']).agg(sales=('sales', 'sum'), cost=('cost', 'sum')).reset_index()
    ba_non_a = df_aln[~df_aln['is_transfer']].groupby(['brand', 'ym']).agg(
        sales=('sales', 'sum'), cost=('cost', 'sum')).reset_index()
    for b in brand_month:
        sub = ba_a[ba_a['brand'] == b['brand']].set_index('ym').reindex(months, fill_value=0)
        subn = ba_non_a[ba_non_a['brand'] == b['brand']].set_index('ym').reindex(months, fill_value=0)
        a_ser = list(b['series']); a_non = list(b['non_series']); a_cost = list(b['cost_series'])
        if ALN_MONTH in months:
            k = months.index(ALN_MONTH)
            a_ser[k] = round(float(sub['sales'].iloc[k]), 2)
            a_non[k] = round(float(subn['sales'].iloc[k]), 2)
            a_cost[k] = round(float(sub['cost'].iloc[k]), 2)
        b['a_series'] = a_ser; b['a_non_series'] = a_non; b['a_cost_series'] = a_cost

    ca_a = df_aln.groupby(['category', 'ym']).agg(sales=('sales', 'sum'), cost=('cost', 'sum')).reset_index()
    ca_non_a = df_aln[~df_aln['is_transfer']].groupby(['category', 'ym']).agg(
        sales=('sales', 'sum'), cost=('cost', 'sum')).reset_index()
    for cmr in category_month:
        sub = ca_a[ca_a['category'] == cmr['category']].set_index('ym').reindex(months, fill_value=0)
        subn = ca_non_a[ca_non_a['category'] == cmr['category']].set_index('ym').reindex(months, fill_value=0)
        a_ser = list(cmr['series']); a_non = list(cmr['non_series']); a_cost = list(cmr['cost_series'])
        if ALN_MONTH in months:
            k = months.index(ALN_MONTH)
            a_ser[k] = round(float(sub['sales'].iloc[k]), 2)
            a_non[k] = round(float(subn['sales'].iloc[k]), 2)
            a_cost[k] = round(float(sub['cost'].iloc[k]), 2)
        cmr['a_series'] = a_ser; cmr['a_non_series'] = a_non; cmr['a_cost_series'] = a_cost

    cm_a = df_aln.groupby(['cust_id', 'ym']).agg(sales=('sales', 'sum'), qty=('qty', 'sum'),
                                                 cost=('cost', 'sum')).reset_index()
    for _, r in cm_a[cm_a['ym'] == ALN_MONTH].iterrows():
        cust_month.append([r['cust_id'], ALN_PSEUDO, round(float(r['sales']), 2),
                           round(float(r['qty']), 2), round(float(r['cost']), 2)])

    # ---------- 8.6 流失 / 骤降 ----------
    _lmy = months[-1]; _ly, _lmo = int(_lmy[:4]), int(_lmy[5:7])
    _lost3 = [m for m in (f'{_ly}-{m:02d}' for m in range(_lmo-2, _lmo+1)) if m in months]
    _prev3 = [m for m in (f'{_ly-1}-{m:02d}' for m in range(_lmo-2, _lmo+1)) if m in months]
    _cur_yms = [m for m in months if m.startswith(str(cur_year))]
    _prev_yms = [str(cur_year-1)+m[4:] for m in _cur_yms]
    _prev_yms = [m for m in _prev_yms if m in months]
    _s25 = df_aln[df_aln['ym'].isin(_prev_yms)].groupby('cust_id')['sales'].sum()
    _s26 = df[df['ym'].isin(_cur_yms)].groupby('cust_id')['sales'].sum()
    churn, risk = [], []
    _churn_small_n, _churn_small_amt = 0, 0.0
    for cid, r in names.iterrows():
        if r['is_retail'] or r['is_internal'] or r['transfer_tag'] == 2:
            continue
        row_pv = pv.loc[cid] if cid in pv.index else None
        v_lost3 = float(row_pv[_lost3].sum()) if row_pv is not None else 0.0
        v_prev3 = float(row_pv[_prev3].sum()) if row_pv is not None else 0.0
        if v_lost3 == 0 and v_prev3 > 0:
            churn.append({'id': cid, 'name': r['display'], 'staff': r['staff'],
                'last': r['last'].strftime('%Y-%m-%d'),
                's25': round(v_prev3, 2), 's26': 0, 'loss': round(v_prev3, 2)})
            if v_prev3 < 10000:
                _churn_small_n += 1; _churn_small_amt += v_prev3
            continue
        v25 = float(_s25.get(cid, 0)); v26 = float(_s26.get(cid, 0))
        if v25 >= DROP_BIG_YUAN and 0 < v26 < v25*DROP_BIG_KEEP:
            risk.append({'id': cid, 'name': r['display'], 'staff': r['staff'],
                'last': r['last'].strftime('%Y-%m-%d'), 's25': round(v25, 2), 's26': round(v26, 2),
                'drop': round(v25-v26, 2), 'rate': round((v26-v25)/v25*100, 1), 'tier': '≥5万·降10%'})
        elif DROP_MID_YUAN <= v25 < DROP_BIG_YUAN and 0 < v26 < v25*DROP_MID_KEEP:
            risk.append({'id': cid, 'name': r['display'], 'staff': r['staff'],
                'last': r['last'].strftime('%Y-%m-%d'), 's25': round(v25, 2), 's26': round(v26, 2),
                'drop': round(v25-v26, 2), 'rate': round((v26-v25)/v25*100, 1), 'tier': '1-5万·降30%'})
    churn.sort(key=lambda x: -x['loss']); risk.sort(key=lambda x: x['rate'])

    pt = (df.groupby(['cust_id', 'product_name'])
          .agg(sales=('sales', 'sum'), qty=('qty', 'sum')).reset_index())
    top_prod = pt.sort_values(['cust_id', 'sales'], ascending=[True, False]).groupby('cust_id').head(5)
    cust_prod = {}
    for cid, g in top_prod.groupby('cust_id'):
        cust_prod[cid] = [[r['product_name'][:40], round(float(r['sales']), 2),
                          round(float(r['qty']), 2)] for _, r in g.iterrows() if r['sales'] > 0]

    # ---------- 9. 职员画像 ----------
    _df26 = df[(df['ym'].isin(_cur_yms)) & (~df['is_transfer'])]
    _df25 = df_aln[(df_aln['ym'].isin(_prev_yms)) & (~df_aln['is_transfer'])]
    _s26st = _df26.groupby('staff')['sales'].sum()
    _s25st = _df25.groupby('staff')['sales'].sum()
    _a26st = _df26[_df26['sales'] > 0].groupby('staff')['cust_id'].nunique()
    _a25st = _df25[_df25['sales'] > 0].groupby('staff')['cust_id'].nunique()
    _churn_by_staff = defaultdict(lambda: [0, 0.0])
    for _x in churn:
        _churn_by_staff[_x['staff']][0] += 1
        _churn_by_staff[_x['staff']][1] += _x['loss']
    staff_list = []
    for s, g in df[~df['is_internal']].groupby('staff'):
        staff_list.append({'staff': s,
            'sales': round(float(g['sales'].sum()), 2), 'qty': round(float(g['qty'].sum()), 2),
            'cost': round(float(g['cost'].sum()), 2),
            'first': g['date'].min().strftime('%Y-%m'), 'last': g['date'].max().strftime('%Y-%m'),
            's26': round(float(_s26st.get(s, 0)), 2), 's25': round(float(_s25st.get(s, 0)), 2),
            'active26': int(_a26st.get(s, 0)), 'active25': int(_a25st.get(s, 0)),
            'churn_n': int(_churn_by_staff[s][0]),
            'churn_amt': round(float(_churn_by_staff[s][1]), 2)})
    staff_list.sort(key=lambda x: -x['sales'])

    import datetime
    data = {
        'meta': {
            'generated': datetime.date.today().isoformat(),
            'date_min': str(df['date'].min().date()), 'date_max': str(df['date'].max().date()),
            'months': months,
            'missing_note': '缺口/误命名/部分月需在渲染时按实际情况列出',
            'rows': int(len(df)),
            'threshold_sleep_yuan': SLEEP_YUAN,
            'initial_customers': initial_cust_n,
            'current_year': cur_year,
            'aligned_ym': ALN_MONTH,
            'aligned_pseudo': ALN_PSEUDO,
            'aligned_note': '同比按对日口径：今年各月实际有数据的日期段，去年同月仅取相同日期段对比',
            'partial_months': [] if not (keep_days is not None and ALN_MONTH in months) else [ALN_MONTH],
            'non_product_categories': NON_PRODUCT_CATEGORIES,
            'role_hint': role_hint or {},
        },
        'monthly': monthly, 'staff_month': staff_month, 'brand_month': brand_month,
        'brand_split': brand_split, 'staff_brand': staff_brand, 'brand_products': brand_products,
        'brand_product_month': brand_product_month, 'category_product_month': category_product_month,
        'products': products, 'category_month': category_month, 'staff_category': staff_category,
        'brand_category': brand_category, 'staff_list': staff_list, 'customers': cust_out,
        'cust_month': cust_month, 'cust_prod': cust_prod, 'churn': churn, 'risk': risk,
        'churn_summary': {
            'lost_n': len(churn), 'lost_amt': round(sum(x['loss'] for x in churn), 2),
            'big_n': sum(1 for x in churn if x['loss'] >= 10000),
            'big_amt': round(sum(x['loss'] for x in churn if x['loss'] >= 10000), 2),
            'small_n': _churn_small_n, 'small_amt': round(_churn_small_amt, 2),
            'risk_n': len(risk), 'risk_amt': round(sum(x['drop'] for x in risk), 2)},
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

    # 控制台核对
    print('months:', months)
    print('总销售额(万元):', round(df['sales'].sum()/10000, 2))
    print('总成本(万元):', round(df['cost'].sum()/10000, 2))
    print('毛利(万元):', round((df['sales'].sum()-df['cost'].sum())/10000, 2))
    print('客户数:', names.shape[0], '强标记调货:', len(trans_ids),
          '弱候选:', int((names.transfer_tag == 1).sum()))
    print('滚动流失:', len(churn), '户', '骤降:', len(risk), '户')
    print('json MB:', round(os.path.getsize(out_json)/1e6, 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--master', required=True)
    ap.add_argument('--output', required=True)
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument('--classifier', default=os.path.join(here, '02_classifier.py'))
    ap.add_argument('--role-hint', default=None, help='可选 JSON：业务员/客服名单')
    a = ap.parse_args()
    role_hint = None
    if a.role_hint:
        with open(a.role_hint, encoding='utf-8') as f:
            role_hint = json.load(f)
    run(a.master, a.classifier, a.output, role_hint)


if __name__ == '__main__':
    main()
