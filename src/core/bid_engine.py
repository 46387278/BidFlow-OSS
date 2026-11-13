#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
bid_engine.py —— 标书拆解引擎（v0.1 确定性内核）
=================================================
目的：证明「同一份招标文件，跑两次，结果字节级一致」。
      这是部署包能不能成立的地基：客户不接受"你上次说的和这次不一样"。

设计原则：
  1. 不用 AI。全部为规则 + XML 解析。确定性来自"没有随机源"。
  2. 只用标准库（zipfile / xml.etree / json / hashlib）。
  3. 每一行结论都带定位符（表号/行号），可回源。
  4. 校验不过不撒谎：分值合计对不上就标 fail，由上层决定是否出报告。

用法：
  python bid_engine.py <标书.docx> [--json 输出.json]
"""
import sys, os, re, io, json, hashlib, zipfile
import xml.etree.ElementTree as ET

NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
HEAD_SCORE = ('评分因素', '评分项', '评审因素', '评分内容')
HEAD_WEIGHT = ('权重', '分值', '标准分', '分数')
# 「评分标准 / 评分细则 / 评分依据」是最常见的写法，早期只认「评分方式」，
# 会把这类明细表误判成汇总表，导致评分项提取为 0（v1.0.2 修）。
HEAD_METHOD = ('评分方式', '评审方式', '评分方法',
               '评分标准', '评分细则', '评分办法', '评审标准', '评分依据')


def _txt(el):
    parts = []
    for t in el.iter(NS + 't'):
        parts.append(t.text or '')
    s = ''.join(parts)
    return re.sub(r'[ \t\u3000]+', ' ', s).strip()


def _parent_map(root):
    return {c: p for p in root.iter() for c in p}


def _is_nested(tbl, pmap):
    p = pmap.get(tbl)
    while p is not None:
        if p.tag == NS + 'tbl':
            return True
        p = pmap.get(p)
    return False


def _expand(tbl):
    """把一张表展开成行列表；嵌套子表整体插到父行之后（样本 B 式结构）。"""
    rows = []
    for tr in tbl.findall(NS + 'tr'):
        cells, nested = [], []
        for tc in tr.findall(NS + 'tc'):
            cells.append(_txt(tc))
            for nt in tc.findall(NS + 'tbl'):
                nested.append(nt)
        if cells:
            rows.append(cells)
        for nt in nested:
            rows.extend(_expand(nt))
    return rows


def load_doc(path):
    raw = open(path, 'rb').read()
    if not zipfile.is_zipfile(path):
        # 老 .doc 是 OLE2 二进制；加密 docx 也是 OLE2。都不能装作能解析继续跑。
        raise ValueError('不是有效的 .docx 文件（可能是老 .doc、加密文档或已损坏）。'
                         '请用 Word 打开后另存为 .docx，再重新上传。')
    try:
        xml = zipfile.ZipFile(path).read('word/document.xml')
    except KeyError:
        raise ValueError('这个 .docx 里没有正文（word/document.xml 缺失），文件可能不完整或被特殊工具处理过。')
    root = ET.fromstring(xml)
    body = root.find(NS + 'body')
    pmap = _parent_map(root)
    tables = [_expand(t) for t in body.iter(NS + 'tbl') if not _is_nested(t, pmap)]
    paras = []
    for p in body.iter(NS + 'p'):
        s = _txt(p)
        if s:
            paras.append(s)
    return {
        'file_sha256': _content_digest(raw),
        'tables': [t for t in tables if t],
        'paras': paras,
    }


def _content_digest(raw):
    """按「解压后的内容」算摘要，不按压缩后的字节算。

    为什么不让它算原始字节：zip 的 deflate 输出跟 zlib 版本走，
    同一份 XML 在 Python 3.8 / 3.11 / 3.13 上压出来的字节可能不一样，
    指纹就跟着漂 —— CI 三版本矩阵必然红两个，而且红得毫无意义。
    解压后按条目名排序再做摘要：同一份文档，到哪台机器都是同一个指纹。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = sorted(n for n in z.namelist() if not n.endswith('/'))
            h = hashlib.sha256()
            for n in names:
                h.update(n.encode('utf-8') + b'\0')
                h.update(z.read(n) + b'\0')
            return h.hexdigest()
    except Exception:
        return hashlib.sha256(raw).hexdigest()


def _is_score_header(row):
    """表头必须是短标签行：格子少、每格短。避免把整段正文误判成表头。"""
    if len(row) < 3:
        return False
    if max(len(c) for c in row) > 24:
        return False
    joined = ' '.join(row)
    return (any(k in joined for k in HEAD_SCORE) and any(k in joined for k in HEAD_WEIGHT))


def _num(s):
    m = re.search(r'\d+(?:\.\d+)?', s.replace('％', '%'))
    return float(m.group(0)) if m else None


def find_scoring(doc):
    """返回 (评分项列表, 校验结果)。纯规则，无随机。

    两张表要分开处理：
      - 明细表：表头含「评分准则/评分方式」，逐行是评分项 → 提取 items
      - 汇总表：只有 序号|评分项|权重 三列 → 只做结构校验，不当 items
    一张大表里可能夹着多段明细表（样本 B 就是：技术段、商务段各一个表头），
    所以按表头出现的位置切段，逐段提取。
    """
    items, summary = [], []
    for ti, rows in enumerate(doc['tables']):
        ri = 0
        while ri < len(rows):
            header = rows[ri]
            if not _is_score_header(header):
                ri += 1
                continue
            is_detail = any(any(k in h for k in HEAD_METHOD) for h in header) or len(header) >= 5
            ci = {}
            for idx, h in enumerate(header):
                if any(k in h for k in HEAD_SCORE) and 'name' not in ci:
                    ci['name'] = idx
                elif any(k in h for k in HEAD_WEIGHT) and 'w' not in ci:
                    ci['w'] = idx
                elif any(k in h for k in HEAD_METHOD) and 'm' not in ci:
                    ci['m'] = idx
            if 'name' not in ci or 'w' not in ci:
                ri += 1
                continue
            if not is_detail:
                summary.append({'table': ti, 'header_row': ri,
                                'rows': [r for r in rows[ri:ri + 8] if len(r) >= 2]})
                ri += 1
                continue
            # 逐行提取，直到遇到下一个表头
            j = ri + 1
            while j < len(rows) and not _is_score_header(rows[j]):
                r = rows[j]
                if len(r) < len(header) - 1:      # 段落行/合并行，跳过
                    j += 1
                    continue
                name = r[ci['name']] if ci['name'] < len(r) else ''
                w = _num(r[ci['w']]) if ci['w'] < len(r) else None
                if w is None or not name:
                    j += 1
                    continue
                items.append({
                    'table': ti, 'row': j,
                    'no': r[0] if r else '',
                    'name': name,
                    'method': r[ci['m']] if 'm' in ci and ci['m'] < len(r) else '',
                    'weight': w,
                    'rule': r[ci['w'] + 1] if ci['w'] + 1 < len(r) else '',
                    'locator': f'表{ti}·行{j}',
                })
                j += 1
            ri = j

    total = round(sum(i['weight'] for i in items), 4)
    return {
        'items': items,
        'summary_tables': summary,
        'checks': {
            'item_count': len(items),
            'weight_sum': total,
            'weight_sum_is_100': abs(total - 100) < 0.01,
            'has_locator': all(i['locator'] for i in items),
            'name_weight_rule_all_present': all(i['name'] and i['weight'] and i['rule'] for i in items),
        },
    }


def build(path):
    doc = load_doc(path)
    sc = find_scoring(doc)
    out = {
        'engine': 'bid_engine v0.1 (rule-only, deterministic)',
        'source': {
            'name': os.path.basename(path),
            'sha256': doc['file_sha256'],
            'tables': len(doc['tables']),
            'paragraphs': len(doc['paras']),
        },
        'scoring': sc,
    }
    # 指纹只依赖文件内容与解析结果，不含文件名——同一份文件改名后指纹不变
    body = dict(out)
    body['source'] = {k: v for k, v in out['source'].items() if k != 'name'}
    canon = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    out['result_sha256'] = hashlib.sha256(canon.encode('utf-8')).hexdigest()
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    out = build(path)
    js = json.dumps(out, ensure_ascii=False, indent=2)
    if '--json' in sys.argv:
        dst = sys.argv[sys.argv.index('--json') + 1]
        open(dst, 'w', encoding='utf-8').write(js)
        print('json ->', dst)
    c = out['scoring']['checks']
    print('file      :', out['source']['name'])
    print('tables    :', out['source']['tables'])
    print('评分项    :', c['item_count'])
    print('分值合计  :', c['weight_sum'], '=100?', c['weight_sum_is_100'])
    print('result_sha256:', out['result_sha256'])


if __name__ == '__main__':
    main()
