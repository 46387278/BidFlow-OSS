# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
test_draft.py —— 标书初稿验收（结果三）

断言四件事：
  1 章节完整：评分细则里 21 个计分点，初稿必须有 21 个 S 编号节，一节不少
  2 结构合法：docx 是合法 zip，word/document.xml 能被 XML 解析器解析
  3 边界守住：没有匹配到内容块的节，不得编造正文，只能给人工提示
  4 待填可见：全部【待填】都带说明，没有裸占位

关于 blocks：测试用的是 data/blocks.example.md（4 个示例块）。
块库越全，能自动生成的节越多；示例库只有 4 块，所以 21 个计分点里
15 节能生成、6 节留人工。这是预期结果，不是缺陷。

用法：python tests/test_draft.py
"""
import os
import sys
import re
import json
import zipfile
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PKG, 'src', 'core'))

import bid_engine as BE
import writer as WR

SAMPLE = os.path.join(PKG, 'data', 'sample')
BLOCKS = os.path.join(PKG, 'data', 'blocks.example.md')
OK, FAIL = [], []

# ---- 基线（改动样本或块库后，用 tools/rebuild_baseline.py 重算并同步这里）----
BASE = {'sections': 21, 'gen': 15, 'manual': 6, 'todo': 79}


def check(name, got, want):
    if got == want:
        OK.append(name)
        print('  [PASS] %-36s %s' % (name, got))
    else:
        FAIL.append(name)
        print('  [FAIL] %-36s 期望 %s，实得 %s' % (name, want, got))


def paras_of(docx):
    xml = zipfile.ZipFile(docx).read('word/document.xml').decode('utf-8')
    out = []
    for p in re.findall(r'<w:p>.*?</w:p>', xml, re.S):
        t = ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', p))
        if t.strip():
            out.append(t)
    return out, xml


def main():
    print('=' * 62)
    print('test_draft · 标书初稿验收')
    print('=' * 62)

    src = os.path.join(SAMPLE, 'sample_bid.docx')
    sc = BE.build(src)
    tmp = tempfile.mkdtemp(prefix='bidflow_draft_')
    scp = os.path.join(tmp, 'scoring.json')
    json.dump(sc, open(scp, 'w', encoding='utf-8'), ensure_ascii=False)

    r = WR.make_draft(scp, tmp, '4-初稿', BLOCKS,
                      {'项目名称': '示例市 A 片区公共卫生间采购项目',
                       '投标人': '示范投标人'})
    docx = r['docx']
    print('\n产物：%s（%d B）' % (os.path.basename(docx), os.path.getsize(docx)))

    check('文件存在', os.path.isfile(docx), True)
    check('是合法 docx(zip)', zipfile.is_zipfile(docx), True)

    paras, xml = paras_of(docx)
    try:
        ET.fromstring(xml)
        xml_ok = True
    except Exception:
        xml_ok = False
    check('document.xml 可解析', xml_ok, True)

    secs = [p for p in paras if re.match(r'^S-\d{3}', p)]
    n = BASE['sections']
    check('S 编号节数', len(secs), n)
    check('S 编号无重复', len(set(s[:5] for s in secs)), n)
    check('S 编号连续', [s[:5] for s in secs], ['S-%03d' % i for i in range(1, n + 1)])

    check('已生成正文节数', r['n_gen'], BASE['gen'])
    check('留人工节数', sum(1 for c in r['cover'] if c['state'] == '无块·待人工'),
          BASE['manual'])
    check('【待填】总数', r['n_todo'], BASE['todo'])

    # 待填必须带说明，不能出现空的【待填】
    bare = [p for p in paras if '【待填】' in p or '【待填：】' in p]
    check('裸待填（无说明）', len(bare), 0)

    # 无块的节不得出现编造正文（该节下只能是提示语）
    bad = []
    for c in r['cover']:
        if c['state'] != '无块·待人工':
            continue
        idx = [k for k, p in enumerate(paras) if p.startswith(c['id'])]
        if idx:
            nxt = paras[idx[0] + 1] if idx[0] + 1 < len(paras) else ''
            if 'AI 不生成' not in nxt and '人工' not in nxt:
                bad.append(c['id'])
    check('无块节未编内容', len(bad), 0)

    cov = json.load(open(os.path.join(tmp, '4-初稿_coverage.json'), encoding='utf-8'))
    check('覆盖表条数', len(cov), n)
    check('覆盖表与正文节数一致',
          sum(1 for c in cov if c.get('id', '-').startswith('S-')), n)

    total_chars = sum(len(p) for p in paras)
    print('\n  正文规模：%d 段 / %d 字' % (len(paras), total_chars))
    print('  说明：示例块库只有 4 块，单节平均约 %d 字；块库越全，初稿越厚。'
          % (total_chars // max(1, len(secs))))

    print('\n' + '-' * 62)
    print('通过 %d 项，失败 %d 项' % (len(OK), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
