# -*- coding: utf-8 -*-
"""
run_pipeline.py — 一键串联：提取 → 品牌/品类匹配（在聚合内）→ 聚合。

用法：
    python run_pipeline.py --input  <明细 xls/xlsx 目录> \
                          --output <输出目录> \
                          [--exclude 误命名文件.xls] \
                          [--role-hint role_hint.json]

产出：
    <输出目录>/master.pkl            （合并长表）
    <输出目录>/dashboard_data.json   （结构化数据，供渲染看板）
"""
import argparse, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _py():
    return sys.executable or 'python3'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--exclude', nargs='*', default=[])
    ap.add_argument('--role-hint', default=None)
    a = ap.parse_args()

    os.makedirs(a.output, exist_ok=True)
    master = os.path.join(a.output, 'master.pkl')
    js = os.path.join(a.output, 'dashboard_data.json')

    # 1) 提取
    cmd = [_py(), os.path.join(HERE, '01_extract.py'),
           '--input', a.input, '--output', a.output]
    if a.exclude:
        cmd += ['--exclude'] + a.exclude
    print('▶ 提取：', ' '.join(cmd))
    subprocess.run(cmd, check=True)

    # 2) 聚合（含品牌/品类匹配）
    cmd = [_py(), os.path.join(HERE, '03_aggregate.py'),
           '--master', master, '--output', js]
    if a.role_hint:
        cmd += ['--role-hint', a.role_hint]
    print('▶ 聚合：', ' '.join(cmd))
    subprocess.run(cmd, check=True)

    print('\n完成。请按 docs/04-dashboard-structure.md 渲染看板，或交给 AI 助手生成。')
    print('数据：', js)


if __name__ == '__main__':
    main()
