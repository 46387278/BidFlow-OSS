# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
写标书（五环节第②环）—— 规则拼装，不是让模型自由发挥。

输入：评分表 JSON（plan_engine 已处理好）+ 内容块库 blocks.md
输出：带编号的初稿 DOCX + 覆盖报告

原则：
  1. 每一节标题直接用评分细则的原文措辞（评委按细则找分，措辞对齐）；
  2. 每一节带 S-### 编号，与台账一一对应，写完可回填状态；
  3. 不含事实的内容一律留【待填：X】，全篇黄块数量＝离可提交还差多远；
  4. 图纸类不生成，只列清单并标"须我方出图"。
"""
import os, re, json
import plan_engine as P
import docx_out as D

PLACEHOLDER = re.compile(r'【待填[^】]*】')


def load_blocks(path):
    txt = open(path, encoding='utf-8').read()
    out = []
    for part in re.split(r'(?m)^@@\s*', txt)[1:]:
        lines = part.split('\n')
        kws = [k.strip() for k in lines[0].split('|') if k.strip()]
        body = '\n'.join(lines[1:]).strip()
        if kws and body:
            out.append({'kw': kws, 'body': body})
    return out


def pick(blocks, text):
    """按关键词命中数选块，命中相同取靠前者。"""
    best, score = None, 0
    for b in blocks:
        s = sum(1 for k in b['kw'] if k in text)
        if s > score:
            best, score = b, s
    return best if score >= 1 else None


def split_paras(body):
    """正文按空行拆段；表格行转成项目符号串。"""
    res = []
    for chunk in re.split(r'\n\s*\n', body):
        lines = [l.rstrip() for l in chunk.split('\n') if l.strip()]
        if not lines:
            continue
        head = None
        if lines[0].startswith('## '):
            head = lines[0][3:].strip()
            lines = lines[1:]
        rows = [l for l in lines if l.strip().startswith('|')]
        if rows and len(rows) > 2:
            cells = []
            for r in rows:
                if set(r.strip()) <= set('|-: '):
                    continue
                cells.append('　'.join(c.strip() for c in r.strip().strip('|').split('|')))
            res.append({'head': head, 'text': '\n'.join('· ' + c for c in cells)})
        else:
            res.append({'head': head, 'text': '\n'.join(lines)})
    return res


def make_draft(scoring_json, out_dir, prefix, blocks_path, meta=None):
    meta = meta or {}
    m = P.build(scoring_json)
    blocks = load_blocks(blocks_path)

    doc = []
    cover = []
    n_fill = 0

    title = meta.get('项目名称') or os.path.splitext(os.path.basename(m['source']))[0]
    doc.append(('h1', '技术方案（AI 初稿）'))
    doc.append(('p', f'项目名称：{title}'))
    if meta.get('投标人'):
        doc.append(('p', f'投标人：{meta["投标人"]}'))
    doc.append(('note', '本稿由评分细则逐项反推生成：每节编号对应要求台账 S-###，'
                        '标题沿用细则原文措辞。文中【待填：…】为必须由投标人确认或提供的内容，'
                        '未填完不得提交。图纸类只列清单，不出图。'))

    for it in m['buckets']['方案']:
        if not it['sections']:
            # 无逐点枚举的评分项：整段响应
            doc.append(('h2', f"{it['name']}（{it['weight']:g} 分）"))
            doc.append(('note', f"评分细则未逐点枚举，须整段响应。出处：{it['locator']}"))
            cover.append({'item': it['name'], 'id': '-', 'state': '需整段人工编写', 'todo': 0})
            continue

        for s in it['sections']:
            n_fill += 1
            sid = f'S-{n_fill:03d}'
            label = s['text']
            doc.append(('h2', f"{sid}　{label}"))
            cover_row = {'item': it['name'], 'id': sid, 'point': label, 'state': '', 'todo': 0}

            if s['ai'] == 0:
                doc.append(('note', f'【本节须由投标人提供，AI 不生成】{s["desc"]}'))
                doc.append(('p', f'（此处应插入：{label}）'))
                cover_row['state'] = '须提供素材'
                cover_row['todo'] = 0   # 这一节没有【待填】占位，缺的是整节素材，另计
                cover.append(cover_row)
                continue

            b = pick(blocks, label + ' ' + (s['group'] or ''))
            if not b:
                doc.append(('note', '本节无匹配内容块，须人工编写或补充块库。'))
                cover_row['state'] = '无块·待人工'
                cover_row['todo'] = 1
                cover.append(cover_row)
                continue

            for seg in split_paras(b['body']):
                if seg['head']:
                    doc.append(('h3', seg['head']))
                for line in seg['text'].split('\n'):
                    if line.strip():
                        doc.append(('p', line.strip()))
            n_todo = len(PLACEHOLDER.findall(b['body']))
            cover_row['state'] = '已生成' if n_todo == 0 else f'已生成·{n_todo} 处待填'
            cover_row['todo'] = n_todo
            cover.append(cover_row)

    doc.append(('pagebreak', ''))
    doc.append(('h1', '附：本稿覆盖情况'))
    doc.append(('p', f'方案类评分项 {len(m["buckets"]["方案"])} 个，'
                      f'计分点 {n_fill} 个，已生成正文 {sum(1 for c in cover if c["state"].startswith("已生成"))} 节，'
                      f'须投标人提供 {sum(1 for c in cover if c["state"] == "须提供素材")} 节，'
                      f'待填内容共 {sum(c["todo"] for c in cover)} 处。'))
    doc.append(('note', '对标审核环节按本表逐条核：状态非"已生成"的节，视为未响应。'))

    os.makedirs(out_dir, exist_ok=True)
    # 版本化：同一任务重跑不覆盖旧稿——旧稿可能已被人工编辑，必须保住
    path = os.path.join(out_dir, f'{prefix}_技术方案初稿.docx')
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(out_dir, f'{prefix}_v{n}_技术方案初稿.docx')
    cov_path = os.path.join(out_dir, os.path.splitext(os.path.basename(path))[0].replace('_技术方案初稿', '_coverage') + '.json')
    D.write(doc, path, title=None)
    json.dump(cover, open(cov_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return {'docx': path, 'cover': cover, 'n_points': n_fill,
            'n_gen': sum(1 for c in cover if c['state'].startswith('已生成')),
            'n_todo': sum(c['todo'] for c in cover)}
