# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
废标红线档 —— 拆完标书的第一份交付件。

定位（项目主理人 2026-10-19 11:37 定）：
  1. 拆完标书第一时间出这一档，排在方案骨架之前；
  2. 每条红线必须写明「谁做」；
  3. 废标红线不进 AI 责任范围——AI 只做列出、定位、提示，不做判断、不做承诺；
  4. AI 的责任区间只有得分项：实施方案 / 技术保障 / 总体设计 / 售后服务。

纯规则，零依赖，同输入同输出。输出 HTML（可转 PDF）。
"""
import sys, os, re, html, json


# ---------- 红线类型：靠原文关键词判定 ----------
# role: 人 = 事实/法律/签章/报价，AI 不碰；操作 = 系统操作；提示 = AI 可做的只有列出与核对
TYPES = [
    ('实质性条款（★）', r'★', '人',
     'AI 只把所有 ★ 条款逐条列全并标出处。是否负偏离、怎么响应、敢不敢签，由投标人判断并签字。'),
    ('投标无效（明示情形）', r'投标无效|按无效处理|视为无效|无效投标', '人',
     'AI 把原文列出，不改写、不推断后果。是否触发，以评标委员会认定为准。'),
    ('否决 / 废标', r'否决|废标|取消.{0,4}资格', '人',
     'AI 仅提示条款存在与位置。AI 不判断"会不会被废"，也不对结果作任何承诺。'),
    ('不予受理', r'不予受理|不予接受', '人',
     '同上。受理与否属采购人/代理机构职权。'),
    ('交货期 / 工期（不可负偏离）', r'不可负偏离|交货期|工期|日历日', '人',
     'AI 可把工期数字提取出来做提醒，但承诺值由投标人填、由投标人负责。'),
    ('报价约束（控制金额 / 低于成本）', r'控制金额|明显低于|低于成本|报价合理性', '人',
     '报价由投标人定价并签署。AI 不做成本判断、不代填价格。'),
    ('资格证明文件', r'资格要求|资格审查|证明文件|扫描件|执照|许可证|社保|财务', '人',
     '原件由投标人提供并核验有效期。AI 只做"清单齐不齐"的对照，不对真伪与有效性负责。'),
    ('签章 / 密封 / 加密解密', r'签章|盖章|公章|密封|加密|解密|CA|电子营业执照', '操作',
     '属投标人现场操作。AI 只提前列出必须完成的动作清单。'),
    ('证书有效性', r'证书.{0,12}有效|年审|cnca|社会组织政务服务平台', '人',
     'AI 提示去哪个官网查、查到什么状态算有效。查询与结论由投标人完成并留痕。'),
    ('目录节点 / 填报位置', r'目录中属于本节点|填写到其他节点|附件|正文.{0,6}公开', '人',
     'AI 可提示"这段该放正文还是附件"，最终填报位置由投标人确认。'),
    ('采购人监督 / 履约', r'监督|中止合同|损失由.{0,6}自负', '人',
     '履约阶段责任，与投标文件无关。AI 不介入。'),
]

DECL = [
    ('废标红线', '人（投标人）全责', '#b3261e', '#fdecea',
     '本条档内所有判定、承诺、签章、报价、原件，全部由投标人负责。AI 不判断是否构成废标，不承诺不废标。'),
    ('得分项内容', 'AI 承担（有边界）', '#1f6b3a', '#eaf7ef',
     '仅限：项目实施方案、技术保障措施、总体方案设计、售后服务方案。AI 出的每一段须可追溯到客户原件或我方产品资料，无来源不写。'),
    ('清单核对', 'AI 仅提示', '#8a6d1f', '#fdf6e3',
     'AI 可做的事只有三样：把条款列全、标出出处、对照客户资料清单看缺不缺。不下结论、不代替签字。'),
]


def load_paras(path):
    import bid_engine as B
    d = B.load_doc(path)
    return d['paras']


def hits(paras):
    out = []
    for i, s in enumerate(paras):
        for tname, pat, role, bound in TYPES:
            if re.search(pat, s):
                if len(s) < 12:
                    continue
                out.append({'idx': i, 'text': s.strip(), 'type': tname, 'role': role, 'bound': bound})
                break
    return out


def dedup(rows):
    """同类型同句去重，同类型限条数，保持原文顺序。"""
    seen, out, cnt = set(), [], {}
    for r in rows:
        k = (r['type'], r['text'][:40])
        if k in seen:
            continue
        seen.add(k)
        cnt[r['type']] = cnt.get(r['type'], 0) + 1
        if cnt[r['type']] > 6:
            continue
        out.append(r)
    return out


def render(src, rows, fp):
    groups = {}
    for r in rows:
        groups.setdefault(r['type'], []).append(r)

    body = []
    for tname, pat, role, bound in TYPES:
        g = groups.get(tname)
        if not g:
            continue
        badge = ('人全责', '#b3261e') if role == '人' else ('人操作', '#6b6b6b')
        items = ''.join(
            f"<tr><td class='loc'>段 {r['idx']}</td><td class='tx'>{html.escape(r['text'][:150])}</td></tr>"
            for r in g)
        body.append(f"""
        <div class="blk">
          <div class="bh"><span class="bt">{html.escape(tname)}</span>
            <span class="role" style="color:{badge[1]}">{badge[0]}</span>
            <span class="cnt">{len(g)} 处</span></div>
          <table class="rt">{items}</table>
          <div class="bound"><b>AI 边界：</b>{html.escape(bound)}</div>
        </div>""")

    decl = ''.join(
        f"""<div class="dc" style="border-left-color:{c};background:{bg}">
              <div class="dt" style="color:{c}">{html.escape(t)}　·　{html.escape(who)}</div>
              <div class="dd">{html.escape(txt)}</div></div>"""
        for t, who, c, bg, txt in DECL)

    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>废标红线档 · {html.escape(src)}</title>
<style>
@page {{ size:A4; margin:15mm 13mm; }}
body {{ font-family:"Songti SC","SimSun","Microsoft YaHei",serif; color:#1a1a1a; font-size:10pt; line-height:1.6; margin:0; }}
.top {{ border-top:3px solid #b3261e; padding-top:8px; }}
h1 {{ font-size:20pt; margin:0 0 3px; letter-spacing:1px; }}
.sub {{ color:#666; font-size:8.5pt; margin-bottom:12px; }}
.warn {{ background:#fdecea; border:1px solid #f0c4bf; padding:9px 12px; font-size:9.5pt; margin:0 0 14px; }}
.warn b {{ color:#b3261e; }}
h2 {{ font-size:11.5pt; margin:18px 0 8px; padding-bottom:4px; border-bottom:1px solid #333; }}
.dc {{ border-left:3px solid; padding:6px 11px; margin:0 0 6px; }}
.dt {{ font-size:9pt; font-weight:700; }}
.dd {{ font-size:8.8pt; color:#333; }}
.blk {{ margin:0 0 11px; page-break-inside:avoid; }}
.bh {{ background:#f2f2ef; padding:4px 8px; display:flex; align-items:baseline; gap:9px; border-left:3px solid #b3261e; }}
.bt {{ font-size:10.5pt; font-weight:700; }}
.role {{ font-size:8.5pt; font-weight:700; }}
.cnt {{ margin-left:auto; font-size:8pt; color:#888; }}
table.rt {{ width:100%; border-collapse:collapse; font-size:8.8pt; }}
table.rt td {{ border:1px solid #e3e3e0; padding:3px 6px; vertical-align:top; }}
.loc {{ width:52px; color:#999; font-size:8pt; white-space:nowrap; }}
.bound {{ font-size:8.5pt; color:#555; background:#fafaf8; padding:4px 8px; border:1px solid #eee; border-top:none; }}
.bound b {{ color:#b3261e; }}
.foot {{ margin-top:16px; padding-top:8px; border-top:1px solid #ccc; font-size:8pt; color:#888; }}
</style></head><body>
<div class="top">
<h1>废标红线档</h1>
<div class="sub">{html.escape(src)}　·　拆标第一件　·　出处为招标文件段落序号，可逐条回源　·　指纹 {html.escape(fp)}</div>
</div>

<div class="warn">
<b>责任声明（请先看这一条）：</b>本档只做「列出 + 定位 + 提示」，<b>不构成废标风险的判断与承诺</b>。
是否构成废标、是否实质性响应，由评标委员会认定；投标文件的事实、签章、报价、原件，全部由投标人负责。
AI 的责任区间不含本档任何一条——<b>AI 承担的是得分项内容（实施 / 保障 / 设计 / 售后），不是废标红线。</b>
</div>

<h2>一、三档责任划分</h2>
{decl}

<h2>二、废标红线清单（共 {len(rows)} 处）</h2>
{''.join(body) or '<div class="bound">未命中典型废标条款。仍须人工通读全文确认——漏检不等于没有。</div>'}

<div class="foot">
抽取口径：招标文件正文段落中命中「投标无效／废标／否决／★实质性条款／不可负偏离／资格证明／签章加密／证书有效」等表述者，按类型归并，每类最多列 6 条原文摘要。<br>
「段 N」＝原文段落序号，可直接回原文定位核对。本档不替代评标委员会认定，也不替代投标人签字确认。<br>
生成工具：redline_engine.py（纯规则，零依赖，同输入同输出）。
</div>
</body></html>"""


def main():
    if len(sys.argv) < 2:
        print('用法: redline_engine.py <招标文件.docx> [out.html]'); sys.exit(1)
    inp = sys.argv[1]
    base = os.path.splitext(os.path.basename(inp))[0]
    out = sys.argv[2] if len(sys.argv) > 2 else 'redline_' + base[:12] + '.html'
    if os.path.abspath(out) == os.path.abspath(inp) or not out.lower().endswith('.html'):
        print('拒绝：输出必须是新的 .html，且不得与输入同路径'); sys.exit(2)

    import hashlib
    fp = hashlib.sha256(open(inp, 'rb').read()).hexdigest()[:16]
    paras = load_paras(inp)
    rows = dedup(hits(paras))
    open(out, 'w', encoding='utf-8').write(render(os.path.basename(inp), rows, fp))
    print('html ->', out)
    print(f'  段落 {len(paras)} 条，红线 {len(rows)} 处')
    from collections import Counter
    for k, v in Counter(r['type'] for r in rows).most_common():
        print(f'    {v:>2}  {k}')


if __name__ == '__main__':
    main()
