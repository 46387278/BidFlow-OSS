# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
投标工作流水线 —— 把五个环节串成一条链，靠"要求台账"贯穿。

核心设计（项目主理人 2026-10-19 11:41 定）：
  拆标时识别出的每一条要求，都发一个编号，带着这个编号走完五个环节：
  拆标 → 识别红线 → 编写方案 → 人工补料 → 对标审核 → 终审排版。
  每个编号能回答三件事：是否已响应、证据在哪、是否需人工确认。

编号规则：
  R-###  废标红线 / 实质性要求     责任：人
  S-###  得分项计分点（方案要写的） 责任：AI
  Q-###  资格与资质取证项           责任：人
  F-###  固定格式件（客户已有）    责任：人（AI 只整理）

产出：requirements.csv（可编辑台账）＋ ledger.html（看板，可转 PDF）
纯规则，零依赖，同输入同输出。
"""
import sys, os, re, csv, json, html

import bid_engine as B
import redline_engine as R
import plan_engine as P


STAGES = ['拆标', '红线识别', '方案编写', '人工补料', '对标审核', '终审排版']

# 每一类要求，走哪几个环节、谁在哪一环动手
FLOW = {
    'R': {'stages': ['拆标', '红线识别', '人工补料', '对标审核'],
          'owner': '人', 'state': '待人工确认',
          'who': {'拆标': 'AI', '红线识别': 'AI', '人工补料': '人', '对标审核': 'AI(核)'}},
    'S': {'stages': ['拆标', '方案编写', '对标审核'],
          'owner': 'AI', 'state': '待编写',
          'who': {'拆标': 'AI', '方案编写': 'AI', '对标审核': 'AI'}},
    'Q': {'stages': ['拆标', '人工补料', '对标审核'],
          'owner': '人', 'state': '待提供原件',
          'who': {'拆标': 'AI', '人工补料': '人', '对标审核': 'AI(核)'}},
    'F': {'stages': ['拆标', '人工补料', '终审排版'],
          'owner': '人', 'state': '待整理',
          'who': {'拆标': 'AI', '人工补料': '人', '终审排版': 'AI(排)'}},
}


def build(docx_path, scoring_json, bom_json=None):
    paras = B.load_doc(docx_path)['paras']
    rows = []

    # ---- R：废标红线 ----
    for i, r in enumerate(R.dedup(R.hits(paras)), 1):
        rows.append({
            'id': f'R-{i:03d}', 'cat': '废标红线', 'src': f'招标文件 段{r["idx"]}',
            'text': r['text'][:110], 'type': r['type'], 'owner': '人',
            'state': '待人工确认', 'evidence': '',
        })

    # ---- S：得分项计分点 ----
    m = P.build(scoring_json)
    n = 0
    for it in m['buckets']['方案']:
        for s in it['sections']:
            n += 1
            rows.append({
                'id': f'S-{n:03d}', 'cat': '得分项',
                'src': f'{it["locator"]} {it["name"]}（{it["weight"]:g}分）',
                'text': f'[{s["group"] or it["name"]}] {s["text"]}'[:110],
                'type': s['src'], 'owner': 'AI' if s['ai'] == 2 else ('共同' if s['ai'] == 1 else '人'),
                'state': '待编写' if s['ai'] >= 1 else '待提供素材', 'evidence': '',
            })

    # ---- Q：资格与资质取证 ----
    q = 0
    for it in m['buckets']['资质'] + m['buckets']['表格']:
        q += 1
        rows.append({
            'id': f'Q-{q:03d}', 'cat': '资格与取证',
            'src': f'{it["locator"]} {it["name"]}（{it["weight"]:g}分）',
            'text': it['name'] + '：按评分准则提供原件/证明，AI 不编造',
            'type': '原件取证' if it['kind'] == '资质' else '逐条对表',
            'owner': '人', 'state': '待提供原件', 'evidence': '',
        })

    # ---- F：固定格式件（客户已有，AI 只整理）----
    f = 0
    if bom_json and os.path.exists(bom_json):
        d = json.load(open(bom_json, encoding='utf-8'))
        for c in d.get('common', []):
            f += 1
            rows.append({
                'id': f'F-{f:03d}', 'cat': '固定格式件', 'src': '招标文件 投标文件组成',
                'text': c['name'] + '：招标文件自带格式，不重做，只整理归位',
                'type': '格式件', 'owner': '人', 'state': '待整理', 'evidence': '',
            })
    return rows, m


def stats(rows):
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r['cat'], {'n': 0, 'ai': 0, 'human': 0, 'both': 0})
        b = by_cat[r['cat']]
        b['n'] += 1
        b['ai' if r['owner'] == 'AI' else ('both' if r['owner'] == '共同' else 'human')] += 1
    return by_cat


def render(src, rows, m, by_cat, fp):
    total = len(rows)
    ai = sum(1 for r in rows if r['owner'] == 'AI')
    both = sum(1 for r in rows if r['owner'] == '共同')
    human = total - ai - both

    cards = ''.join(
        f"""<div class="c"><div class="k">{html.escape(k)}</div><div class="v">{v['n']}</div>
            <div class="u">AI {v['ai']} · 共同 {v['both']} · 人 {v['human']}</div></div>"""
        for k, v in by_cat.items())

    # 环节看板
    stage_rows = []
    for st in STAGES:
        rec = [r for r in rows if st in FLOW.get(r['id'][0], {}).get('stages', [])]
        if not rec:
            continue
        state_cnt = {}
        for r in rec:
            state_cnt[r['state']] = state_cnt.get(r['state'], 0) + 1
        detail = '　'.join(f'{k} {v}' for k, v in state_cnt.items())
        stage_rows.append(f"<tr><td class='st'>{st}</td><td class='num'>{len(rec)}</td>"
                          f"<td class='dim'>{detail}</td></tr>")

    body = ''.join(
        f"<tr><td class='id'>{r['id']}</td><td class='cat'>{r['cat']}</td>"
        f"<td class='tx'>{html.escape(r['text'])}</td>"
        f"<td class='src'>{html.escape(r['src'])}</td>"
        f"<td class='ow'><b>{r['owner']}</b></td>"
        f"<td class='sta'>{html.escape(r['state'])}</td>"
        f"<td class='ev'></td></tr>"
        for r in rows)

    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>投标工作台账 · {html.escape(src)}</title>
<style>
@page {{ size:A4 landscape; margin:12mm 10mm; }}
body {{ font-family:"Songti SC","SimSun","Microsoft YaHei",serif; color:#1a1a1a; font-size:9pt; line-height:1.5; margin:0; }}
h1 {{ font-size:17pt; margin:0 0 3px; }}
.sub {{ color:#666; font-size:8pt; margin-bottom:11px; }}
.lead {{ background:#f7f7f4; border-left:3px solid #333; padding:7px 11px; font-size:9pt; margin:0 0 12px; }}
.lead b {{ color:#b3261e; }}
.cards {{ display:flex; gap:7px; margin:0 0 13px; }}
.c {{ flex:1; border:1px solid #ddd; padding:6px 9px; }}
.c .k {{ font-size:8pt; color:#777; }}
.c .v {{ font-size:15pt; font-weight:700; line-height:1.2; }}
.c .u {{ font-size:7.5pt; color:#999; }}
.two {{ display:flex; gap:14px; margin:0 0 12px; }}
.two > div {{ flex:1; }}
h2 {{ font-size:10.5pt; margin:0 0 5px; padding-bottom:3px; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; font-size:8pt; }}
th {{ background:#efefec; text-align:left; padding:3px 5px; border:1px solid #ddd; font-size:7.5pt; }}
td {{ border:1px solid #e6e6e3; padding:3px 5px; vertical-align:top; }}
.id {{ width:46px; font-weight:700; color:#333; }}
.cat {{ width:62px; color:#666; }}
.src {{ width:150px; color:#666; }}
.ow {{ width:34px; text-align:center; }}
.sta {{ width:74px; color:#8a6d1f; }}
.ev {{ width:88px; background:#fcfcfb; }}
.st {{ width:80px; font-weight:700; }}
.num {{ width:44px; text-align:right; }}
.dim {{ color:#777; }}
.foot {{ margin-top:10px; padding-top:6px; border-top:1px solid #ccc; font-size:7.5pt; color:#888; }}
</style></head><body>
<h1>投标工作台账</h1>
<div class="sub">{html.escape(src)}　·　五环节贯穿　·　指纹 {html.escape(fp)}　·　本表是后续所有环节的唯一真相源</div>

<div class="lead">
拆标识别出的每一条要求都发一个编号，<b>带着编号走完编写、补料、审核、终审</b>。谁能做、做到哪一步、证据在哪，全表可查。
编号规则：<b>R</b> 废标红线（人全责）· <b>S</b> 得分项计分点（AI 承担）· <b>Q</b> 资格取证（人提供原件）· <b>F</b> 固定格式件（客户已有，AI 只整理）。
</div>

<div class="cards">
  <div class="c"><div class="k">要求总数</div><div class="v">{total}</div><div class="u">全部带编号</div></div>
  <div class="c"><div class="k">AI 承担</div><div class="v" style="color:#1f6b3a">{ai}</div><div class="u">得分项方案正文</div></div>
  <div class="c"><div class="k">共同（AI 起草·人定数）</div><div class="v" style="color:#1f5f8a">{both}</div><div class="u">工期/承诺类</div></div>
  <div class="c"><div class="k">人承担（责任在投标人）</div><div class="v" style="color:#b3261e">{human}</div><div class="u">其中 {by_cat.get('废标红线',{}).get('n',0)} 条红线由 AI 列全定位·干活不担责</div></div>
  {cards}
</div>

<div class="two">
  <div>
    <h2>五环节负载</h2>
    <table><thead><tr><th>环节</th><th>条目</th><th>当前状态</th></tr></thead>
    <tbody>{''.join(stage_rows)}</tbody></table>
  </div>
  <div>
    <h2>状态机</h2>
    <table><tbody>
      <tr><td class="st">S 得分项</td><td class="dim">待编写 → 已编写 → 对标审核（AI）→ 人工终审</td></tr>
      <tr><td class="st">R 红线</td><td class="dim">待人工确认 → 已确认/已处理 → 审核复核</td></tr>
      <tr><td class="st">Q 取证</td><td class="dim">待提供原件 → 已提供 → 有效期核验 → 归位</td></tr>
      <tr><td class="st">F 格式件</td><td class="dim">待整理 → 已归位 → 排版终审</td></tr>
    </tbody></table>
  </div>
</div>

<h2>台账明细（{total} 条）</h2>
<table><thead><tr><th>编号</th><th>类别</th><th>要求内容</th><th>出处</th><th>责任</th><th>状态</th><th>证据位置</th></tr></thead>
<tbody>{body}</tbody></table>

<div class="foot">
出处列可回原文（段落号／表N·行M）。「证据位置」留空，由编写与补料环节逐条回填——未回填即视为未响应，审核环节按未响应计。<br>
本台账不判断是否废标，不预测评标委员会得分。生成工具：pipeline.py（纯规则，零依赖，同输入同输出）。
</div>
</body></html>"""


def main():
    if len(sys.argv) < 3:
        print('用法: pipeline.py <招标文件.docx> <scoring.json> [bom.json] [out前缀]'); sys.exit(1)
    docx, sc = sys.argv[1], sys.argv[2]
    bom = sys.argv[3] if len(sys.argv) > 3 else 'bom.json'
    pre = sys.argv[4] if len(sys.argv) > 4 else 'ledger'

    import hashlib
    fp = hashlib.sha256(open(docx, 'rb').read()).hexdigest()[:16]
    rows, m = build(docx, sc, bom)

    csv_path = pre + '.csv'
    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['编号', '类别', '要求内容', '出处', '类型', '责任', '状态', '证据位置', '备注'])
        for r in rows:
            w.writerow([r['id'], r['cat'], r['text'], r['src'], r['type'], r['owner'], r['state'], r['evidence'], ''])
    open(pre + '.html', 'w', encoding='utf-8').write(render(os.path.basename(docx), rows, m, stats(rows), fp))

    print('csv  ->', csv_path)
    print('html ->', pre + '.html')
    print(f'  要求 {len(rows)} 条：', '　'.join(f'{k} {v["n"]}' for k, v in stats(rows).items()))
    print(f'  责任：AI {sum(1 for r in rows if r["owner"]=="AI")} · 共同 {sum(1 for r in rows if r["owner"]=="共同")} · 人 {sum(1 for r in rows if r["owner"]=="人")}')


if __name__ == '__main__':
    main()
