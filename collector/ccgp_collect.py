# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""手动采集中国政府采购网公开公告。"""
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ccgp_source as CS   # noqa: E402

OUT = os.path.join(HERE, 'output')
SRC_NAME = '中国政府采购网·全国检索'


def amount_of(text):
    """从摘要里提预算/最高限价（万元）。取不到返回 ''，不猜。"""
    t = (text or '').replace(',', '')
    pats = [
        r'(?:预算金额|采购预算|最高限价|招标控制价|预算价)[^0-9]{0,6}([\d.]+)\s*万元',
        r'(?:预算金额|采购预算|最高限价|招标控制价)[^0-9]{0,6}([\d.]+)\s*元',
    ]
    for i, p in enumerate(pats):
        m = re.search(p, t)
        if not m:
            continue
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        return '%.2f' % (v if i == 0 else v / 10000.0)
    return ''


def to_notice(x):
    stage, relevant = CS.classify(x['title'])
    if not relevant:
        return None
    amt = amount_of(x['desc']) or amount_of(x['title'])
    return {
        'source': SRC_NAME,
        'stage': stage,
        'notice_type': x.get('notice_type') or stage,
        'title': x['title'],
        'source_url': x['url'],
        'area': x.get('area') or '',
        'owner': x.get('owner') or '',
        'pub_time': x.get('pub') or '',
        'crawl_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'attachment': '',
        'amount': amt,
        'amount_type': '预算' if amt else '',
        'amount_raw': '',
        'deadline': CS.parse_dl(x['desc']),
        'amount_missing': not amt,
        'is_new': True,
        '_desc': x.get('desc', '')[:200],
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    kws = args or ['公厕']
    ingest = '--no-ingest' not in sys.argv
    print('=== ccgp 全国检索：%s（近 7 天）===' % '、'.join(kws))
    items, errs, nreq = CS.fetch(keywords=kws, days=7, pages=1)
    print('请求 %d 次，原始 %d 条' % (nreq, len(items)))

    notices, dropped = [], 0
    for x in items:
        nb = to_notice(x)
        if nb is None:
            dropped += 1
            continue
        notices.append(nb)
    print('对口 %d 条，滤掉服务类 %d 条' % (len(notices), dropped))
    if errs:
        print('错误：', errs)

    os.makedirs(OUT, exist_ok=True)
    if not notices:
        print('CCGP_EMPTY 没有对口条目（可能限流或关键词太窄）')
        return 1
    p = os.path.join(OUT, 'notices_ccgp_%s.jsonl' % datetime.datetime.now().strftime('%Y%m%d_%H%M'))
    with open(p, 'w', encoding='utf-8') as f:
        for nb in notices:
            f.write(json.dumps(nb, ensure_ascii=False) + '\n')
    print('已写', p)

    for nb in notices:
        print('  [%s]%s %s | %s' % (nb['area'] or '?', nb['stage'][:4],
                                    nb['deadline'] or '未提截止', nb['title'][:46]))

    if not ingest:
        return 0
    r = subprocess.run([sys.executable, os.path.join(HERE, 'ingest.py'), p],
                       capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print('INGEST_FAIL', r.stderr[-400:])
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
