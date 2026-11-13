# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""按公告链接去重后导入本地需求表。"""
import csv
import datetime
import glob
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, 'data')
CSV_PATH = os.path.join(DATA, 'requirements.csv')

COLUMNS = ['发现日期', '公告日期', '来源网站', '地区', '类型', '项目名称',
           '采购方', '金额(万元)', '品类', '链接', '状态', '阶段', '备注',
           '报名截止', '投标截止']

# 公告类型 → (阶段, 状态)。宁可标「招标公告/进行中」，也不臆造进度。
STAGE_MAP = [
    ('结果', ('结果公告', '已定标')),
    ('中标', ('结果公告', '已定标')),
    ('成交', ('结果公告', '已定标')),
    ('废标', ('废标公告', '已终止')),
    ('流标', ('废标公告', '已终止')),
    ('终止', ('废标公告', '已终止')),
    ('变更', ('变更公告', '进行中')),
    ('更正', ('变更公告', '进行中')),
    ('澄清', ('变更公告', '进行中')),
    ('意向', ('采购意向', '进行中')),
    ('需求公示', ('采购意向', '进行中')),
]


def latest_jsonl():
    fs = sorted(glob.glob(os.path.join(HERE, 'output', 'notices_*.jsonl')),
                key=os.path.getmtime)
    return fs[-1] if fs else None


def stage_of(ntype):
    t = str(ntype or '')
    for key, val in STAGE_MAP:
        if key in t:
            return val
    return ('招标公告', '进行中')


def row_from_notice(n, today):
    stage, state = stage_of(n.get('notice_type') or n.get('stage'))
    amount = str(n.get('amount') or '').strip()
    return {
        '发现日期': today,
        '公告日期': str(n.get('pub_time') or '')[:10] or today,
        '来源网站': str(n.get('source') or ''),
        '地区': str(n.get('area') or '').strip() or '未标注',
        '类型': str(n.get('notice_type') or n.get('stage') or ''),
        '项目名称': str(n.get('title') or '').strip(),
        '采购方': str(n.get('owner') or ''),
        '金额(万元)': amount if amount else '待确认',
        '品类': str(n.get('stage') or '公厕相关'),
        '链接': str(n.get('source_url') or ''),
        '状态': state,
        '阶段': stage,
        '备注': '雷达采集 %s' % today,
        '报名截止': '',
        '投标截止': str(n.get('deadline') or ''),
    }


def existing_links():
    if not os.path.exists(CSV_PATH):
        return set()
    with io.open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
        return {(r.get('链接') or '').strip() for r in csv.DictReader(f)}


def append_rows(rows):
    """原子追加：先写临时文件再整体替换，中途断电也不会留下半行。"""
    os.makedirs(DATA, exist_ok=True)
    if os.path.exists(CSV_PATH):
        bak = CSV_PATH + '.bak-' + datetime.date.today().strftime('%Y%m%d')
        if not os.path.exists(bak):
            shutil.copy2(CSV_PATH, bak)
        with io.open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
            old = list(csv.DictReader(f))
    else:
        old = []

    tmp = CSV_PATH + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in old:
            w.writerow({k: r.get(k, '') for k in COLUMNS})
        for r in rows:
            w.writerow({k: r.get(k, '') for k in COLUMNS})
    os.replace(tmp, CSV_PATH)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else latest_jsonl()
    if not src or not os.path.isfile(src):
        print('INGEST_FAIL 没找到 notices_*.jsonl')
        return 1

    today = datetime.date.today().strftime('%Y-%m-%d')
    with io.open(src, encoding='utf-8') as f:
        notices = [json.loads(l) for l in f if l.strip()]

    rows = [row_from_notice(n, today) for n in notices]
    rows = [r for r in rows if r['链接'] and r['项目名称']]

    seen = existing_links()
    fresh, batch = [], set()
    for r in rows:
        k = r['链接']
        if k in seen or k in batch:
            continue
        batch.add(k)
        fresh.append(r)

    if fresh:
        append_rows(fresh)

    print('INGEST 源=%s 采集%d条 有效%d条 新增%d条 库内共%d条'
          % (os.path.basename(src), len(notices), len(rows), len(fresh), len(seen) + len(fresh)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
