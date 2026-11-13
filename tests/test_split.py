# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
test_split.py —— 拆标结果验收（结果二）
不联网、不起服务，直接调引擎。四类断言：
  1 数值断言：评分项/分值/红线数/台账条数/计分点数，与基线一致
  2 确定性断言：同一文件跑两次，结果指纹一致
  3 回源断言：台账每条要求的原文片段能在招标文件中检索到
  4 泛化断言：样本 B（结构完全不同）也能正确处理，证明引擎不是对单一文件调参

样本来源
  两份样本都由 tools/make_sample_bid.py 程序化生成，不是二进制附件。
  改动样本内容 → 基线数字必然变化 → 这是设计意图：样本是活的，基线必须跟着重算。
  重算方法：python tools/rebuild_baseline.py

用法：python tests/test_split.py
退出码：0 全过 / 1 有失败
"""
import os
import sys
import re
import json
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PKG, 'src', 'core'))

import bid_engine as BE
import redline_engine as RE
import plan_engine as PE
import pipeline as PL

SAMPLE = os.path.join(PKG, 'data', 'sample')
BASE = json.load(open(os.path.join(SAMPLE, 'baseline.json'), encoding='utf-8'))
OK, FAIL = [], []


def check(name, got, want):
    if got == want:
        OK.append(name)
        print('  [PASS] %-34s %s' % (name, got))
    else:
        FAIL.append(name)
        print('  [FAIL] %-34s 期望 %s，实得 %s' % (name, want, got))


def _dump(sc):
    p = os.path.join(tempfile.mkdtemp(), 'scoring.json')
    json.dump(sc, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    return p


def run_once(path):
    sc = BE.build(path)
    paras = BE.load_doc(path)['paras']
    rl = RE.dedup(RE.hits(paras))
    m = PE.build(_dump(sc))
    rows, _ = PL.build(path, _dump(sc), None)
    pts = sum(len(i['sections']) for i in m['buckets']['方案'])
    return {
        'fp': sc['result_sha256'],
        'items': sc['scoring']['checks']['item_count'],
        'wsum': sc['scoring']['checks']['weight_sum'],
        'paras': len(paras),
        'redline': len(rl),
        'rows': len(rows),
        'points': pts,
        'ai': sum(1 for r in rows if r['owner'] == 'AI'),
    }


def traceability(path, rows):
    """每条要求的原文片段能否在招标文件正文里检索到（去组名、去【】）"""
    txt = re.sub(r'\s+', '', ''.join(BE.load_doc(path)['paras']))
    miss = []
    # 只核 R（废标红线）与 S（得分项）：这两类的正文必须是原文片段。
    # Q/F 两类的正文是系统生成的提示语，可核性靠出处定位符，不按原文检索。
    for r in rows:
        if r['cat'] not in ('废标红线', '得分项'):
            continue
        s = re.sub(r'^\[[^\]]*\]\s*', '', r['text'])
        s = re.sub(r'【[^】]*】', '', s)
        frag = re.sub(r'\s+', '', s)[:20]
        if frag and frag not in txt:
            miss.append(r['id'])
    return miss


def verify(label, fname, expect):
    print('\n%s' % label)
    p = os.path.join(SAMPLE, fname)
    a = run_once(p)
    check('段落数', a['paras'], expect['paras'])
    check('评分项数', a['items'], expect['items'])
    check('分值合计', a['wsum'], expect['wsum'])
    check('废标红线条数', a['redline'], expect['redline'])
    check('要求台账条数', a['rows'], expect['rows'])
    check('方案计分点数', a['points'], expect['points'])
    check('AI 承担条数', a['ai'], expect['ai'])
    check('结果指纹（固定值）', a['fp'][:16], expect['fp16'])

    b = run_once(p)
    check('再跑一次指纹一致', b['fp'] == a['fp'], True)

    rows, _ = PL.build(p, _dump(BE.build(p)), None)
    miss = traceability(p, rows)
    check('台账回源失败数(R/S)', len(miss), 0)
    check('Q/F 条目均有出处定位',
          all(r['src'] for r in rows if r['cat'] not in ('废标红线', '得分项')), True)
    if miss:
        print('       失败编号：%s' % miss[:8])
    return a


def main():
    print('=' * 62)
    print('test_split · 拆标结果验收')
    print('=' * 62)

    print('\n[1/2] 样本 A（3 列表格 / ①②③ 枚举 / 100 分制）')
    verify('  样本 A', 'sample_bid.docx', BASE['a'])

    print('\n[2/2] 样本 B（5 列表格 / 1.2.3. 枚举 / 70 分制）')
    verify('  样本 B', 'sample_bid_b.docx', BASE['b'])

    print('\n' + '-' * 62)
    print('通过 %d 项，失败 %d 项' % (len(OK), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
