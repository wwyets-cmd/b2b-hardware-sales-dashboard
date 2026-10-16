# -*- coding: utf-8 -*-
"""
01_extract.py — 提取并合并多份《单位销售明细》（.xls / .xlsx）。

平台无关：仅依赖 pandas / xlrd / openpyxl，不依赖任何平台 API。
自动定位表头、识别字段、合并为一张长表（master.pkl）。

用法：
    python 01_extract.py --input  <明细目录> \
                        --output <输出目录> \
                        [--exclude 误命名文件1.xls 误命名文件2.xls] \
                        [--master-name master.pkl]
"""
import argparse, glob, os, sys
import pandas as pd

# 标准列（管家婆）；字段缺失时按 docs/05 的别名表匹配
STANDARD = ['单据类型', '单据日期', '单据编号', '单位编号', '单位全名', '商品编号',
            '商品全名', '品牌', '职员编号', '职员全名', '仓库全名', '销售数量',
            '单价', '金额', '折扣', '折后金额', '含税金额', '成本金额', '摘要', '单据备注']

# 别名表：标准字段 -> 可接受的表头候选
ALIASES = {
    '单据类型': ['单据类型', '类型'],
    '单据日期': ['单据日期', '日期', '出库日期', '销售日期', '开单日期'],
    '单据编号': ['单据编号', '单号', '单据号', '销售单号'],
    '单位编号': ['单位编号', '客户编号', '客户编码'],
    '单位全名': ['单位全名', '客户名称', '客户全名', '单位名称', '往来单位'],
    '商品编号': ['商品编号', '商品编码', '货号', '产品编号'],
    '商品全名': ['商品全名', '商品名称', '品名', '产品名称', '货品名称'],
    '品牌': ['品牌', '品牌名称', '商标'],
    '职员编号': ['职员编号', '业务员编号', '经办人编号'],
    '职员全名': ['职员全名', '业务员', '经办人', '销售员', '客服'],
    '仓库全名': ['仓库全名', '仓库', '库房'],
    '销售数量': ['销售数量', '数量', '出库数量', '销售数'],
    '单价': ['单价', '售价'],
    '金额': ['金额'],
    '折扣': ['折扣'],
    '折后金额': ['折后金额', '实际金额', '销售额', '实收金额'],
    '含税金额': ['含税金额'],
    '成本金额': ['成本金额', '成本', '成本价金额'],
    '摘要': ['摘要'],
    '单据备注': ['单据备注', '备注'],
}

# 定位表头时必须存在的关键列
HEADER_MUST = ['单位全名']
HEADER_MUST_ANY = ['折后金额', '含税金额', '金额']


def _norm_header(h):
    return str(h).strip().replace('　', '')


def _build_index(hdr):
    """返回 {标准字段: 列号}，按别名匹配。"""
    idx = {}
    for std, cands in ALIASES.items():
        for c in cands:
            if c in hdr:
                idx[std] = hdr.index(c)
                break
    return idx


def _parse_date_xls(cell, datemode, xlrd):
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate_as_datetime(cell.value, datemode).date()
        except Exception:
            return None
    if cell.ctype == xlrd.XL_CELL_NUMBER and 30000 < cell.value < 60000:
        try:
            return xlrd.xldate_as_datetime(cell.value, datemode).date()
        except Exception:
            return None
    s = str(cell.value).strip()
    if s and len(s) >= 8 and s[:4].isdigit():
        return pd.to_datetime(s[:10].replace('/', '-'), errors='coerce')
    return None


def _num(v):
    try:
        return float(v if v not in (None, '') else 0)
    except Exception:
        return 0.0


def _get(col, row, idx):
    i = idx.get(col)
    return row[i] if i is not None and i < len(row) else ''


def parse_xls(path):
    import xlrd
    wb = xlrd.open_workbook(path)
    sh = wb.sheet_by_index(0)
    hrow = None
    for r in range(min(20, sh.nrows)):
        rv = [_norm_header(sh.cell(r, c).value) for c in range(sh.ncols)]
        if all(m in rv for m in HEADER_MUST) and any(m in rv for m in HEADER_MUST_ANY):
            hrow = r
            break
    if hrow is None:
        raise RuntimeError("表头未找到: " + os.path.basename(path))
    hdr = [_norm_header(sh.cell(hrow, c).value) for c in range(sh.ncols)]
    idx = _build_index(hdr)
    dm = wb.datemode
    recs = []
    for r in range(hrow + 1, sh.nrows):
        row = [sh.cell(r, c).value for c in range(sh.ncols)]
        typ = str(_get('单据类型', row, idx)).strip()
        cust = str(_get('单位全名', row, idx)).strip()
        if not typ and not cust:
            continue
        if any(x in cust for x in ('合计', '总计', '小计', '累计')):
            continue
        rec = {
            'date': _parse_date_xls(sh.cell(r, idx['单据日期']), dm, xlrd) if '单据日期' in idx else None,
            'doc_type': typ,
            'doc_no': str(_get('单据编号', row, idx)).strip(),
            'cust_id': str(_get('单位编号', row, idx)).strip(),
            'cust_name': cust,
            'product_id': str(_get('商品编号', row, idx)).strip(),
            'product_name': str(_get('商品全名', row, idx)).strip(),
            'brand': str(_get('品牌', row, idx)).strip(),
            'staff_id': str(_get('职员编号', row, idx)).strip(),
            'staff': str(_get('职员全名', row, idx)).strip(),
            'warehouse': str(_get('仓库全名', row, idx)).strip(),
            'qty': _num(_get('销售数量', row, idx)),
            'price': _num(_get('单价', row, idx)),
            'amount': _num(_get('金额', row, idx)),
            'sales': _num(_get('折后金额', row, idx)) or _num(_get('含税金额', row, idx)),
            'cost': _num(_get('成本金额', row, idx)),
            'summary': str(_get('摘要', row, idx)).strip(),
            'remark': str(_get('单据备注', row, idx)).strip(),
            'source': os.path.basename(path),
        }
        recs.append(rec)
    df = pd.DataFrame(recs)
    if len(df):
        df['date'] = pd.to_datetime(df['date'])
    return df


def parse_xlsx(path):
    df = pd.read_excel(path, sheet_name=0, header=None, engine='openpyxl')
    hrow = None
    for r in range(min(20, len(df))):
        rv = [_norm_header(v) for v in df.iloc[r].tolist()]
        if all(m in rv for m in HEADER_MUST) and any(m in rv for m in HEADER_MUST_ANY):
            hrow = r
            break
    if hrow is None:
        raise RuntimeError("表头未找到: " + os.path.basename(path))
    hdr = [_norm_header(v) for v in df.iloc[hrow].tolist()]
    idx = _build_index(hdr)
    out = []
    for r in range(hrow + 1, len(df)):
        row = df.iloc[r].tolist()
        typ = str(_get('单据类型', row, idx)).strip()
        cust = str(_get('单位全名', row, idx)).strip()
        if not typ and not cust:
            continue
        if any(x in cust for x in ('合计', '总计', '小计', '累计')):
            continue
        date_v = _get('单据日期', row, idx)
        out.append({
            'date': pd.to_datetime(date_v, errors='coerce'),
            'doc_type': typ, 'doc_no': str(_get('单据编号', row, idx)).strip(),
            'cust_id': str(_get('单位编号', row, idx)).strip(), 'cust_name': cust,
            'product_id': str(_get('商品编号', row, idx)).strip(),
            'product_name': str(_get('商品全名', row, idx)).strip(),
            'brand': str(_get('品牌', row, idx)).strip(),
            'staff_id': str(_get('职员编号', row, idx)).strip(),
            'staff': str(_get('职员全名', row, idx)).strip(),
            'warehouse': str(_get('仓库全名', row, idx)).strip(),
            'qty': _num(_get('销售数量', row, idx)),
            'price': _num(_get('单价', row, idx)),
            'amount': _num(_get('金额', row, idx)),
            'sales': _num(_get('折后金额', row, idx)) or _num(_get('含税金额', row, idx)),
            'cost': _num(_get('成本金额', row, idx)),
            'summary': str(_get('摘要', row, idx)).strip(),
            'remark': str(_get('单据备注', row, idx)).strip(),
            'source': os.path.basename(path),
        })
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True, help='明细 xls/xlsx 所在目录')
    ap.add_argument('--output', required=True, help='输出目录')
    ap.add_argument('--exclude', nargs='*', default=[], help='要剔除的文件名')
    ap.add_argument('--master-name', default='master.pkl')
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.input, '*.xls'))
                   + glob.glob(os.path.join(a.input, '*.xlsx')))
    files = [f for f in files if os.path.basename(f) not in set(a.exclude)]
    if not files:
        sys.exit("未找到 .xls/.xlsx 文件: " + a.input)

    dfs = []
    for f in files:
        df = parse_xlsx(f) if f.lower().endswith('.xlsx') else parse_xls(f)
        if len(df) == 0:
            print("（空文件跳过）", os.path.basename(f))
            continue
        print(os.path.basename(f), len(df), df['date'].min().date(), df['date'].max().date())
        dfs.append(df)
    if not dfs:
        sys.exit("所有文件均为空")
    all_df = pd.concat(dfs, ignore_index=True).sort_values(['date', 'doc_no']).reset_index(drop=True)
    os.makedirs(a.output, exist_ok=True)
    out = os.path.join(a.output, a.master_name)
    all_df.to_pickle(out)
    print("TOTAL", len(all_df), all_df['date'].min().date(), all_df['date'].max().date(), "→", out)


if __name__ == '__main__':
    main()
