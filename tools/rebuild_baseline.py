#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
rebuild_baseline.py —— 重算样本基线

什么时候用：
    改了 tools/make_sample_bid.py 里的样本内容，或者有意改了引擎的判定逻辑，
    导致 tests/test_split.py 的数值断言失败。这时不要「把期望值改成实得值」了事，
    先确认新结果是对的，再执行本脚本把新基线写进 data/sample/baseline.json。

它做什么：
    对两份样本各跑一遍完整链路，把段落数、评分项、分值、红线、台账、计分点、
    AI 条数、结果指纹写成 JSON。指纹会进基线，所以「引擎行为被无意改动」这件事
    在下次跑测试时一定会被抓到——这是本项目的核心回归手段。

用法：python tools/rebuild_baseline.py
"""
import os
import sys
import json
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PKG, 'src', 'core'))

import bid_engine as BE
import redline_engine as RE
import plan_engine as PE
import pipeline as PL

SAMPLES = [('a', 'sample_bid.docx'), ('b', 'sample_bid_b.docx')]


def measure(path):
    sc = BE.build(path)
    paras = BE.load_doc(path)['paras']
    rows, _ = PL.build(path, _dump(sc), None)
    m = PE.build(_dump(sc))
    return {
        'paras': len(paras),
        'items': sc['scoring']['checks']['item_count'],
        'wsum': sc['scoring']['checks']['weight_sum'],
        'redline': len(RE.dedup(RE.hits(paras))),
        'rows': len(rows),
        'points': sum(len(i['sections']) for i in m['buckets']['方案']),
        'ai': sum(1 for r in rows if r['owner'] == 'AI'),
        'fp16': sc['result_sha256'][:16],
    }


def _dump(sc):
    p = os.path.join(tempfile.mkdtemp(), 'scoring.json')
    json.dump(sc, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    return p


def main():
    out = {}
    for key, fname in SAMPLES:
        p = os.path.join(PKG, 'data', 'sample', fname)
        if not os.path.isfile(p):
            print('缺少样本：%s，先执行 python tools/make_sample_bid.py' % fname)
            return 1
        out[key] = measure(p)
        print('%s  %s' % (fname, json.dumps(out[key], ensure_ascii=False)))
    dst = os.path.join(PKG, 'data', 'sample', 'baseline.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('基线已写入 %s' % dst)
    return 0


if __name__ == '__main__':
    sys.exit(main())
