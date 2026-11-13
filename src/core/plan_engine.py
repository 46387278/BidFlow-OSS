# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
方案骨架引擎 —— 从招标文件评分细则，反向生成技术方案的写作骨架。

定位：不生成方案正文，只回答三个问题——
  1. 这个方案一共要出现哪几个点？（漏一个丢几分，逐点可数）
  2. 每个点的素材从哪来？谁提供？AI 能不能写？
  3. 哪些分是"有没有"（必拿），哪些分是"好不好"（主观）？

全部确定性规则，零 AI 参与，同输入同输出。
输入：bid_engine.py 产出的评分项 JSON
输出：HTML（可转 PDF）
"""
import sys, os, re, json, html

CIRC = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮'
CIRC_RE = '[' + CIRC + ']'

# ---------- 分类：三类评分项，三种命运 ----------
# 表格类：逐条对表，机械，谁的活都能干
# 资质类：靠客户原件，AI 一个字不能编
# 方案类：真正要"写"的，也是主观分战场
def classify(name):
    n = name
    if re.search(r'偏离|响应表|响应情况|参数响应', n):
        return '表格'
    if re.search(r'业绩|诚信|证书|认证|团队|人员|网点|节能|环保产品|知识产权|服务能力|资质', n):
        return '资质'
    if re.search(r'方案|措施|设计|实施|运维|养护|应急|售后|保洁|培训|管理|计划|模式', n):
        return '方案'
    return '其他'


# ---------- 计分点抽取 ----------
# 两种写法都得认：① 圈号枚举（样本 A 式）／ 1. 2. 3. 阿拉伯枚举（样本 B 式）
# 组标题必须带冒号（"1、产品实施方案：" / "应急措施方案:"），否则会把上一条计分点误当组名
GROUP_RE = re.compile(r'(\d+[、.][^\s：:；。]{2,16}|[^\s：:，。；]{2,14}(?:方案|措施|清单|计划|模式))[：:]')
ENUM_NUM = re.compile(r'(?<![\d.])(\d{1,2})[.、]\s*([^；;。\d]{2,60})')
GUIDE = re.compile(r'(?:包含|包括|如下|以下|内容)[^：:。]{0,10}[：:]?')

def extract_points(rule):
    """从（一）评审内容段抽出计分点。返回 [{'sym','group','text','point_score'}]"""
    head = re.split(r'（二）|\(二\)', rule)[0]
    pts = []

    # 模式 A：圈号枚举
    for m in re.finditer(r'(' + CIRC_RE + r')([^' + CIRC + r']{2,120})', head):
        sym = m.group(1)
        # 切掉组尾的计分说明，只留这一条内容本身
        text = re.split(r'投标人提供|每拥有|以上内容|合计|最高得', m.group(2))[0].strip('；;。，,、 ')
        before = head[:m.start()]
        gs = GROUP_RE.findall(before)
        group = gs[-1].rstrip('：:') if gs else ''
        if re.search(r'综合|进行|根据|评审|评价|内容', group):
            group = ''
        sc = re.search(r'得\s*(\d+(?:\.\d+)?)\s*分', text)
        pts.append({'sym': sym, 'group': group, 'text': text,
                    'point_score': float(sc.group(1)) if sc else None})
    if pts:
        return pts

    # 模式 B：阿拉伯数字枚举（只在引导词之后找，避免把评分档位当计分点）
    g = GUIDE.search(head)
    seg = head[g.end():] if g else head
    for m in ENUM_NUM.finditer(seg):
        num, text = m.group(1), m.group(2).strip('；;。，,、 ')
        if re.search(r'得\s*\d+\s*分', text):
            continue
        pts.append({'sym': num + '.', 'group': '', 'text': text, 'point_score': None})
    if pts:
        return pts

    # 模式 C：括号内并列列举（真实招标文件最普遍的写法）
    #   「根据投标人的项目实施方案（应包含设备运输方案、安装调试方案、验收方案）进行评审」
    # 这类句子没有编号，但它把评委要看什么写在括号里了 —— 那就是计分点。
    # 不加这条规则，真实文件里 100% 的评分项都会退化成「须整段人工编写」。
    # 一份文件里常有多处「应包含…」（供货方案一处、安装方案一处），要全部收下并去重，
    # 只取第一处会漏掉一半内容。
    parts, seen = [], set()
    for m in re.finditer(r'[（(][^（()）]{0,120}?[)）]', head):
        seg = m.group(0)
        if not re.search(r'包含|包括|应含|至少含', seg):
            continue
        body = re.split(r'包含|包括|应含|至少含', seg, 1)[-1]
        body = body.strip('（()）：: ')
        for p in re.split(r'[、；;，,]', body):
            p = p.strip('；;。，, 、')
            # 「包括但不限于包含：产品质量承诺」这种套娃前缀要一层层剥掉，剥到没有为止
            for _ in range(3):
                q = re.sub(r'^(?:但不限于|不限于|还应包括|还应包含|包含|包括|等)[：:、]?', '', p).strip()
                if q == p:
                    break
                p = q
            p = re.sub(r'等$', '', p).strip()
            if 2 <= len(p) <= 40 and p not in seen:
                seen.add(p)
                parts.append(p)
    if len(parts) >= 2:
        for i, p in enumerate(parts, 1):
            pts.append({'sym': '%d)' % i, 'group': '', 'text': p, 'point_score': None})
    return pts


def scale_note(rule, weight):
    """细则内部按百分制打分、最终折算到权重的，必须写明，否则客户以为能拿到 100 分。"""
    nums = [int(x) for x in re.findall(r'(?:最高)?得\s*(\d{2,3})\s*分', rule)]
    if nums and max(nums) >= 60 and weight < 60:
        return f'细则内部按百分制打分，最终折算为 {weight:g} 分；下表「每点分值」是细则原值，不是实得分。'
    return ''


def extract_grades(rule):
    """综合评价档位：极合理X分 / 一般X分 / 不合理X分。"""
    tail = rule
    out = []
    for m in re.finditer(r'([^\s；;。，,①②③④⑤⑥⑦⑧⑨⑩]{2,24}?)的得\s*(\d+(?:\.\d+)?)\s*分', tail):
        label = m.group(1)
        if re.search(r'方案|条理|操作|响应|完整|合理', label):
            out.append((label.strip(), float(m.group(2))))
    # 去重保序
    seen, res = set(), []
    for a, b in out:
        if a not in seen:
            seen.add(a)
            res.append((a, b))
    return res


# ---------- 素材来源判断：这一节的东西从哪来 ----------
def material(point_text):
    t = point_text
    if re.search(r'效果图|平面图|施工图|图纸|渲染|三维|BIM|剖面图|立面图', t):
        return ('客户设计素材', '图纸/渲染图，AI 不生成，只用我方现有产品图', 0)
    if re.search(r'检测报告|检验报告|证书|认证|截图|说明书|证明文件|社保|执照|许可证', t):
        return ('客户资料原件', '原件扫描/官网可查，AI 一个字不能编', 0)
    if re.search(r'人员|团队|项目经理|工程师|配置表|名单', t):
        return ('客户资料原件', '人、证、社保三对齐，只能结构化', 0)
    if re.search(r'进度|工期|计划|节点|排产|供货', t):
        return ('AI 起草 + 人定数', '结构可写，天数与节点必须客户确认', 1)
    if re.search(r'承诺|保修|质保期|响应时间|赔偿', t):
        return ('AI 起草 + 人签字', '属于法律承诺，AI 给初值，人签才算', 1)
    if re.search(r'质量|保证|安全|环保|应急|保洁|维护|耗材|培训|管理|措施|流程|制度|标准|生产|组装|安装|施工|调试|包装|运输|配送|配置|选型', t):
        return ('AI 可写', '通用工艺与管理知识，配我方产品参数即可', 2)
    return ('待定', '逐单判断', 1)


# ---------- 主流程 ----------
def build(scoring_json_path):
    d = json.load(open(scoring_json_path, encoding='utf-8'))
    items = d['scoring']['items']
    src = d['source']['name']
    fp = d.get('result_sha256', '')[:16]

    buckets = {'方案': [], '表格': [], '资质': [], '其他': []}
    for it in items:
        k = classify(it['name'])
        it['kind'] = k
        it['points'] = extract_points(it.get('rule', '')) if k == '方案' else []
        it['grades'] = extract_grades(it.get('rule', '')) if k == '方案' else []
        it['scale'] = scale_note(it.get('rule', ''), it['weight']) if k == '方案' else ''
        buckets[k].append(it)

    total = round(sum(i['weight'] for i in items), 2)
    w = {k: round(sum(i['weight'] for i in v), 2) for k, v in buckets.items()}

    # 逐点建骨架
    for it in buckets['方案']:
        sec = []
        for p in it['points']:
            src_tag, desc, ai = material(p['text'])
            sec.append({
                'sym': p['sym'], 'text': p['text'], 'group': p['group'],
                'src': src_tag, 'desc': desc, 'ai': ai,
            })
        it['sections'] = sec
        it['n_points'] = len(sec)
        it['mech'] = sum(1 for s in sec if s['ai'] >= 1)   # 可写点数
        it['hard'] = sum(1 for s in sec if s['ai'] == 0)   # 只能取素材的点数

    return {'source': src, 'fingerprint': fp, 'items': items,
            'buckets': buckets, 'total': total, 'w': w}


# ---------- 渲染 ----------
def esc(s):
    return html.escape(str(s or ''))


AI_BADGE = {0: ('素材件', '#8a6d1f', '#fdf6e3'), 1: ('半写', '#1f5f8a', '#eaf3fa'), 2: ('可写', '#1f6b3a', '#eaf7ef')}


def render(m):
    w = m['w']
    rows = []
    for it in m['buckets']['方案']:
        secs = ''.join(
            f"<tr><td class='sym'>{esc(s['sym'])}</td>"
            f"<td class='tx'>{esc(s['text'][:110])}</td>"
            f"<td class='grp'>{esc(s['group'] or '—')}</td>"
            f"<td class='src'><b>{esc(s['src'])}</b><br><span class='dim'>{esc(s['desc'])}</span></td>"
            f"<td class='ai'><span class='badge' style=\"color:{AI_BADGE[s['ai']][1]};background:{AI_BADGE[s['ai']][2]}\">{AI_BADGE[s['ai']][0]}</span></td></tr>"
            for s in it['sections'])
        grades = ''.join(f"<li>{esc(a)} → <b>{b:g} 分</b></li>" for a, b in it['grades'])
        rows.append(f"""
        <div class="sec">
          <div class="sech"><span class="w">{it['weight']:g}</span>
            <span class="nm">{esc(it['name'])}</span>
            <span class="loc">{esc(it['locator'])}</span>
            <span class="cnt">{it['n_points']} 个计分点 · 素材件 {it['hard']} · 可写 {it['mech']}</span>
          </div>
          <table class="pts"><thead><tr><th>点</th><th>必须出现的内容（原文摘要）</th><th>所属子方案</th><th>素材从哪来</th><th>AI</th></tr></thead>
          <tbody>{secs or "<tr><td colspan=5 class='dim'>细则未给出逐点枚举，按原文整段响应</td></tr>"}</tbody></table>
          {('<div class="scale">※ ' + esc(it["scale"]) + '</div>') if it.get('scale') else ''}
          {('<div class="grades"><b>综合评价档位（主观分，靠图、靠针对性、靠结构）</b><ul>' + grades + '</ul></div>') if grades else ''}
        </div>""")

    other = []
    for k, label, note in [('表格', '逐条对表类', '机械活，但要一条件一证据，举证不齐按负偏离'),
                           ('资质', '原件取证类', '只做清单+有效期核对，一个字不能编')]:
        for it in m['buckets'][k]:
            other.append(f"<tr><td>{esc(it['name'])}</td><td class='w2'>{it['weight']:g}</td>"
                         f"<td>{label}</td><td class='dim'>{esc(note)}</td><td class='loc'>{esc(it['locator'])}</td></tr>")

    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>技术方案写作骨架 · {esc(m['source'])}</title>
<style>
@page {{ size: A4; margin: 16mm 13mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: "Songti SC","SimSun","Microsoft YaHei",serif; color:#1a1a1a; font-size:10.5pt; line-height:1.62; margin:0; }}
h1 {{ font-size:19pt; margin:0 0 4px; letter-spacing:.5px; }}
.sub {{ color:#666; font-size:9pt; margin-bottom:16px; }}
.lede {{ background:#f7f7f4; border-left:3px solid #333; padding:10px 13px; font-size:10pt; margin:0 0 18px; }}
.lede b {{ color:#000; }}
.acct {{ display:flex; gap:8px; margin:0 0 20px; }}
.card {{ flex:1; border:1px solid #ddd; padding:9px 11px; }}
.card .k {{ font-size:8.5pt; color:#777; }}
.card .v {{ font-size:17pt; font-weight:700; line-height:1.25; }}
.card .u {{ font-size:8.5pt; color:#999; }}
.hl {{ border-color:#2b2b2b; background:#fbfbf8; }}
h2 {{ font-size:12pt; margin:24px 0 10px; padding-bottom:5px; border-bottom:1px solid #333; }}
.sec {{ margin:0 0 16px; page-break-inside:avoid; }}
.sech {{ background:#2f2f2f; color:#fff; padding:6px 10px; display:flex; align-items:baseline; gap:9px; }}
.sech .w {{ font-size:15pt; font-weight:700; }}
.sech .nm {{ font-size:11pt; }}
.sech .loc {{ color:#aaa; font-size:8pt; }}
.sech .cnt {{ margin-left:auto; color:#ccc; font-size:8pt; }}
table {{ width:100%; border-collapse:collapse; font-size:9pt; }}
.pts th {{ background:#efefec; text-align:left; padding:4px 6px; border:1px solid #ddd; font-weight:600; font-size:8.5pt; }}
.pts td {{ border:1px solid #e3e3e0; padding:4px 6px; vertical-align:top; }}
.pts .sym {{ width:22px; text-align:center; font-size:11pt; color:#333; }}
.pts .grp {{ width:88px; color:#555; font-size:8.5pt; }}
.pts .src {{ width:150px; font-size:8.5pt; }}
.pts .ai {{ width:44px; text-align:center; }}
.badge {{ display:inline-block; padding:1px 5px; font-size:8pt; border-radius:2px; }}
.dim {{ color:#888; font-size:8.5pt; }}
.scale {{ color:#a15c00; font-size:8.5pt; padding:3px 2px 0; }}
.grades {{ background:#fdfaf3; border:1px solid #e8dfc8; padding:7px 11px; margin-top:6px; font-size:9pt; }}
.grades ul {{ margin:4px 0 0 16px; padding:0; }}
.grades li {{ margin:1px 0; }}
.other th {{ background:#efefec; text-align:left; padding:4px 6px; border:1px solid #ddd; font-size:8.5pt; }}
.other td {{ border:1px solid #e3e3e0; padding:4px 6px; }}
.other .w2 {{ width:42px; text-align:right; }}
.other .loc {{ width:78px; color:#888; font-size:8pt; }}
.foot {{ margin-top:22px; padding-top:9px; border-top:1px solid #ccc; font-size:8pt; color:#888; }}
</style></head><body>
<h1>技术方案写作骨架</h1>
<div class="sub">{esc(m['source'])}　·　依据招标文件评分细则逐点反推　·　结果指纹 {esc(m['fingerprint'])}</div>

<div class="lede">
这份骨架只回答一件事：<b>这个方案必须出现哪几个点、每个点谁来提供、漏一个丢几分。</b><br>
它不生成方案正文——因为方案分两半：<b>一半是"有没有"（数得清、可逐点对表、漏了就丢分）</b>，另一半是<b>"好不好"（40 分综合评价，靠图、靠针对性、靠结构）</b>。
先把"有没有"全部占满，再谈"好不好"。
</div>

<div class="acct">
  <div class="card hl"><div class="k">方案类（要写的）</div><div class="v">{w['方案']:g}</div><div class="u">分 · {len(m['buckets']['方案'])} 个评分项</div></div>
  <div class="card"><div class="k">表格类（逐条对表）</div><div class="v">{w['表格']:g}</div><div class="u">分 · {len(m['buckets']['表格'])} 项</div></div>
  <div class="card"><div class="k">原件取证类（不编）</div><div class="v">{w['资质']:g}</div><div class="u">分 · {len(m['buckets']['资质'])} 项</div></div>
  <div class="card"><div class="k">评分项合计</div><div class="v">{m['total']:g}</div><div class="u">不含价格分</div></div>
</div>

<h2>一、方案骨架（按评分项逐点展开）</h2>
{''.join(rows)}

<h2>二、其余评分项的处理方式</h2>
<table class="other"><thead><tr><th>评分项</th><th>分值</th><th>类型</th><th>做法</th><th>出处</th></tr></thead>
<tbody>{''.join(other) or '<tr><td colspan=5 class=dim>无</td></tr>'}</tbody></table>

<div class="foot">
口径：计分点抽取自招标文件评分细则原文「（一）评审内容」段；分值以原文为准。综合评价档位属主观分，不由点数决定。<br>
每点标注「素材件」＝须客户提供原件，AI 不生成；「半写」＝结构可写、数字须人确认；「可写」＝依我方产品与通用工艺即可成文。<br>
生成工具：plan_engine.py（纯规则，零依赖，同输入同输出）。
</div>
</body></html>"""


def main():
    if len(sys.argv) < 2:
        print('用法: plan_engine.py <scoring.json> [out.html]'); sys.exit(1)
    inp = sys.argv[1]
    base = os.path.splitext(os.path.basename(inp))[0]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(inp), 'plan_' + base + '.html')
    # 安全闸：绝不覆盖输入
    if os.path.abspath(out) == os.path.abspath(inp) or not out.lower().endswith('.html'):
        print('拒绝：输出必须是新的 .html，且不得与输入同路径'); sys.exit(2)
    m = build(inp)
    open(out, 'w', encoding='utf-8').write(render(m))
    print('html ->', out)
    for k, v in m['w'].items():
        print(f'  {k}: {v:g} 分 ({len(m["buckets"][k])} 项)')
    for it in m['buckets']['方案']:
        print(f'  [{it["name"]}] {it["weight"]:g}分 → {it["n_points"]} 个计分点（素材件 {it["hard"]} / 可写 {it["mech"]}）')


if __name__ == '__main__':
    main()
