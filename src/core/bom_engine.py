#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
bom_engine.py —— 投标文件清单（BOM）提取与交叉比对
==================================================
问题：客户只买结果。「AI 写标书」到底写哪一部分？不能靠感觉，要靠证据。
做法：从两份真实招标文件里，把「投标文件组成」这一节原文抓出来，
      逐项归类，再交叉比对——两份不同的标，哪些件每次都出现。
      每次都出现的，就是"固定的、重复的那一部分"，也就是 AI 该承担的部分。

纯规则、无 AI、无网络。用法：
  python bom_engine.py A.docx B.docx 清单.html
"""
import sys, os, re, json, hashlib, html, zipfile
import xml.etree.ElementTree as ET

NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
ANCHOR = ('投标文件组成', '投标文件的组成', '投标文件构成')
NUM = re.compile(r'^(?:\d+[\.、]|（\d+）|\([0-9]+\)|（[一二三四五六七八九十]+）)')

# 四类分工——这是全文的核心判定
RULES = [
    ('模板填空', 'AI 全自动', ('投标函', '承诺函', '证明书', '授权委托书', '委托书',
                            '确认书', '自查表', '基本情况表', '封面', '目录', '一览表')),
    ('模板填空', '表由 AI 填，价由人定', ('报价表', '报价', '开标一览')),
    ('其他', '内容不固定，单独看', ('补充', '其他内容', '其它', '其他')),
    ('逐条对表', 'AI 最强', ('偏离表', '响应表', '响应情况表', '参数响应')),
    ('材料调取', 'AI 不能编，只索引', ('资格', '业绩', '团队', '网点', '节能', '诚信',
                                    '知识产权', '融资', '证书', '声明函', '中小企业')),
    ('方案起草', 'AI 起草、人审', ('实施方案', '设计方案', '技术保障', '售后', '服务方案',
                                 '总体方案', '组织', '进度')),
]


def txt(el):
    s = ''.join((t.text or '') for t in el.iter(NS + 't'))
    return re.sub(r'[ \t\u3000]+', ' ', s).strip()


def paras(path):
    raw = open(path, 'rb').read()
    root = ET.fromstring(zipfile.ZipFile(path).read('word/document.xml'))
    body = root.find(NS + 'body')
    return [txt(p) for p in body.iter(NS + 'p') if txt(p)], hashlib.sha256(raw).hexdigest()


def norm(s):
    s = re.sub(r'^[（(]?\d+[）)．.、]\s*', '', s)
    s = re.sub(r'[（(]\s*[一二三四五六七八九十]+\s*[）)]', '', s)
    return re.sub(r'[\s、，。：:；;（）()]', '', s).strip()


def classify(name):
    for label, who, keys in RULES:
        if any(k in name for k in keys):
            return label, who
    return '未归类', '需人工判'


def bom(path):
    ps, h = paras(path)
    idx = None
    for i, s in enumerate(ps):
        if any(k in s for k in ANCHOR) and len(s) < 40:
            idx = i
            break
    if idx is None:
        return None
    group, items = '待定', []
    for s in ps[idx + 1: idx + 70]:
        if '正文' in s and ('公开' in s or '组成' in s):
            group = '正文（公开）'
            continue
        if '附件' in s and ('不公开' in s or '组成' in s):
            group = '附件（不公开）'
            continue
        if len(s) > 60:
            if items:
                break
            continue
        if NUM.match(s):
            name = norm(s)
            if 1 <= len(name) <= 24:
                items.append({'group': group, 'name': name, 'raw': s})
        elif items and len(s) < 20 and not NUM.match(s):
            break
    return {'file': path.split('\\')[-1], 'sha256': h, 'items': items}



# 同义归一：不同代理写法的件名，归到同一个"件"上。
# 不归一，两份文件永远对不上（分项报价表 vs 项目详细报价）。
CANON = [
    (('投标函',), '投标函'),
    (('承诺函',), '履约承诺函'),
    (('资格要求', '情况介绍'), '投标人情况及资格'),
    (('报价',), '报价'),
    (('法定代表人',), '法人证明'),
    (('授权委托书',), '授权委托书'),
    (('实质性条款响应', '实质性响应'), '实质性响应表'),
    (('技术规格偏离', '技术要求偏离', '技术偏离', '参数响应', '▲号'), '技术偏离表'),
    (('商务要求偏离', '商务偏离'), '商务偏离表'),
    (('总体方案设计', '设计方案', '方案设计'), '设计方案'),
    (('实施方案',), '实施方案'),
    (('技术保障',), '技术保障'),
    (('售后',), '售后服务'),
    (('知识产权',), '知识产权'),
    (('业绩',), '业绩'),
    (('节能',), '节能环保'),
    (('诚信',), '诚信'),
    (('风险知悉',), '风险知悉确认'),
    (('自查',), '自查表'),
    (('团队',), '项目团队'),
    (('网点',), '服务网点'),
    (('融资',), '订单融资'),
    (('基本情况表',), '供应商基本情况'),
    (('补充', '其他内容', '其它'), '其他'),
]


def canon(name):
    for keys, tag in CANON:
        if any(k in name for k in keys):
            return tag
    return name


def similar(a, b):
    if canon(a) == canon(b):
        return 1.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    sa, sb = set(a), set(b)
    return len(sa & sb) / max(len(sa | sb), 1)


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    A, B = bom(sys.argv[1]), bom(sys.argv[2])
    out_html = sys.argv[3]
    # 安全闸：输出必须是 .html，且绝不能与任何输入同路径
    _ins = {os.path.abspath(p) for p in sys.argv[1:3]}
    if not out_html.lower().endswith('.html') or os.path.abspath(out_html) in _ins:
        sys.exit('拒绝写入：输出路径必须是新的 .html 文件，且不得与输入相同')
    used = set()
    pairs, only_a = [], []
    for it in A['items']:
        best, bj = 0, -1
        for j, jt in enumerate(B['items']):
            if j in used:
                continue
            s = similar(it['name'], jt['name'])
            if s > best:
                best, bj = s, j
        if best >= 0.5:
            used.add(bj)
            pairs.append((it, B['items'][bj], best))
        else:
            only_a.append(it)
    only_b = [jt for j, jt in enumerate(B['items']) if j not in used]

    for it in A['items']:
        it['cls'], it['who'] = classify(it['name'])

    common = [p[0] for p in pairs]
    auto = [i for i in common if classify(i['name'])[0] in ('模板填空', '逐条对表')]
    mat = [i for i in common if classify(i['name'])[0] == '材料调取']
    plan = [i for i in common if classify(i['name'])[0] == '方案起草']

    print(f"A {A['file'][:34]}  件数 {len(A['items'])}")
    print(f"B {B['file'][:34]}  件数 {len(B['items'])}")
    print(f"共有 {len(common)}  仅A {len(only_a)}  仅B {len(only_b)}")
    print(f"AI 可全自动（模板填空+逐条对表）：{len(auto)} 件")
    print(f"材料调取（不能编）：{len(mat)} 件")
    print(f"方案起草（人审）：{len(plan)} 件")

    out = {'A': A, 'B': B,
           'common': [{'name': p[0]['name'], 'raw': p[0]['raw'], 'group': p[0]['group'],
                       'match': round(p[2], 2)} for p in pairs],
           'only_a': only_a, 'only_b': only_b}
    if len(sys.argv) > 4:
        json.dump(out, open(sys.argv[4], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # ---- 渲染 ----
    def rows(lst, show_group=True):
        r = []
        for i in lst:
            c, w = classify(i['name'])
            g = f'<span class="g">{i["group"]}</span>' if show_group else ''
            r.append(f'<tr><td><b>{html.escape(i["name"])}</b>{g}</td>'
                     f'<td class="c"><span class="k k{c}">{c}</span></td>'
                     f'<td class="c who">{w}</td></tr>')
        return ''.join(r)

    css = """
@page{size:A4;margin:15mm}
body{font-family:"Noto Serif SC","SimSun",serif;color:#1a1a1a;margin:0;font-size:10pt;line-height:1.5}
h1{font-size:18pt;margin:0 0 4px;letter-spacing:1px}
.sub{font-size:8.5pt;color:#666;font-family:Consolas,monospace;border-bottom:2px solid #1a1a1a;padding-bottom:8px;margin-bottom:14px}
h2{font-size:12pt;margin:16px 0 6px;padding-left:8px;border-left:3px solid #8a1c1c}
table{width:100%;border-collapse:collapse;font-size:9pt}
th{background:#f2f0ec;text-align:left;padding:5px;border-bottom:1.2px solid #1a1a1a}
td{padding:5px;border-bottom:.5px solid #dcd8d2;vertical-align:middle}
td.c{text-align:center}.who{font-size:8.5pt;color:#555}
.g{font-size:7.5pt;color:#999;margin-left:6px;font-family:sans-serif}
.k{display:inline-block;padding:1px 6px;border-radius:2px;font-size:8pt;font-family:sans-serif;color:#fff}
.k模板填空{background:#1f4e79}.k逐条对表{background:#8a1c1c}.k材料调取{background:#5b5b5b}.k方案起草{background:#7a5c00}.k未归类{background:#bbb}
.sum{display:flex;gap:8px;margin:12px 0}
.sum div{flex:1;border:1px solid #dcd8d2;padding:8px;text-align:center}
.sum .n{font-size:16pt;font-weight:700;font-family:Consolas,monospace}
.sum .l{font-size:8pt;color:#666}
.note{background:#faf6ec;border-left:3px solid #7a5c00;padding:8px 10px;font-size:8.5pt;margin:10px 0}
"""
    body = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><style>{css}</style></head><body>
<h1>投标文件固定件清单</h1>
<div class="sub">证据来源：两份真实招标文件「投标文件组成」原文 · A={html.escape(A['file'][:40])} · B={html.escape(B['file'][:40])}<br>
提取文件指纹：{A['sha256'][:16]}… / {B['sha256'][:16]}… · 规则引擎 bom_engine v0.1，无 AI 参与</div>

<div class="sum">
<div><div class="n">{len(A['items'])}</div><div class="l">A 要求件数</div></div>
<div><div class="n">{len(B['items'])}</div><div class="l">B 要求件数</div></div>
<div><div class="n">{len(common)}</div><div class="l"><b>两份都要求</b>（固定重复）</div></div>
<div><div class="n">{len(auto)}</div><div class="l">其中 AI 可全自动</div></div>
</div>

<div class="note"><b>怎么读这张表</b>：同一个招标代理、同一类项目，两份文件要求的投标件有 {len(common)} 项重合。
重合的这 {len(common)} 项，就是「每次都一样、只换项目名和金额」的部分——也就是 AI 该承担的部分。
不重合的 {len(only_a) + len(only_b)} 项，是本项目特有的，人要判断。</div>

<h2>一、固定重复件（两份都要求）</h2>
<table><tr><th style="width:52%">投标件名称</th><th style="width:24%">分工归类</th><th>谁来做</th></tr>
{rows(common)}</table>

<h2>二、仅 A 要求（{html.escape(A['file'][:20])}）</h2>
<table><tr><th style="width:52%">投标件名称</th><th style="width:24%">分工归类</th><th>谁来做</th></tr>
{rows(only_a) if only_a else '<tr><td colspan="3" style="color:#999">无</td></tr>'}</table>

<h2>三、仅 B 要求（{html.escape(B['file'][:20])}）</h2>
<table><tr><th style="width:52%">投标件名称</th><th style="width:24%">分工归类</th><th>谁来做</th></tr>
{rows(only_b) if only_b else '<tr><td colspan="3" style="color:#999">无</td></tr>'}</table>

<h2>四、四类分工的实际数量</h2>
<table><tr><th>类别</th><th style="width:22%">共几件</th><th>含义</th></tr>
<tr><td><span class="k k模板填空">模板填空</span></td><td class="c">{len([i for i in common if classify(i['name'])[0]=='模板填空'])}</td><td>招标方给格式，只换项目名、金额、日期、公司信息。AI 全自动，风险≈0</td></tr>
<tr><td><span class="k k逐条对表">逐条对表</span></td><td class="c">{len([i for i in common if classify(i['name'])[0]=='逐条对表'])}</td><td>把招标要求逐条搬进来，标响应/偏离，指向证据。AI 最强的一环</td></tr>
<tr><td><span class="k k材料调取">材料调取</span></td><td class="c">{len(mat)}</td><td>资质、业绩、团队、证书。AI 只负责"从你的资料库里取出来放对位置并核对有效期"，一个字都不能编</td></tr>
<tr><td><span class="k k方案起草">方案起草</span></td><td class="c">{len(plan)}</td><td>实施方案、设计方案、售后方案。AI 起草，必须人审</td></tr>
</table>

<div class="note"><b>这张表说明了一件事</b>：AI 能全自动的部分（模板填空＋逐条对表）在固定件里占 {len(auto)}/{len(common)}。
这就是「固定、重复」的准确定义——不是笼统的"标书"，是这 {len(auto)} 件。剩下的靠客户材料和人。
报告末尾的清单可作销售材料：客户一眼看到"哪些活你不用再干了"。</div>
</body></html>"""
    open(out_html, 'w', encoding='utf-8').write(body)
    print('html ->', out_html)


if __name__ == '__main__':
    main()
