# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""雷达战报生成器 —— 把 requirements.csv 变成一份人能看的清单。

设计口径（2026-11-09 项目主理人令）：
「需求雷达你交付给我的永远只有一件事，就是跑出来的列表」。
所以本脚本不解释系统、不汇报健康度，只回答一个问题：
**现在有哪些项目我还能投？**

分级规则：
  P0 装配式/整体吊装  → 与自有产品线直接对口
  P1 公厕/驿站/厕所   → 主营品类
  P2 环卫/垃圾/保洁   → 关联品类
过滤：截止日期 >= 今天（无截止日期的单独归入「待核」区，不混进可投区）
"""
import csv
import datetime
import html
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE, 'data', 'requirements.csv')
OVERRIDES = os.path.join(BASE, 'data', 'manual_overrides.json')
OUT_DIR = os.path.join(BASE, 'data', 'reports')

P0_KW = ('装配式', '整体吊装', '模块化', '预制')
P1_KW = ('公厕', '厕所', '驿站', '卫生间')
P2_KW = ('环卫', '垃圾', '保洁', '中转站', '收集点')

# 学校/医院/住宅内部厕所改造不是市政公厕生意——买家是一次性业主，
# 走的是小额装修包，跟装配式公厕产能无关。整类剔掉，否则清单被这类噪音淹没。
OUT_OF_SCOPE = ('学校', '幼儿园', '中学', '小学', '大学', '学院', '医院', '卫生服务中心',
                '宿舍', '教学楼', '办公楼', '餐厅', '实验',
                # 「驿站」是多义词：就业驿站、暖心驿站、快递驿站都不是公厕。
                # 「监督/运营/劳务」是买服务的，不是买设备的。这两类混进清单 = 清单不可信。
                '就业', '监督', '运营服务', '劳务', '暖心', '快递', '病房')

# 金额合理性闸门（2026-11-09 加）
# 实锤：库里出现「225808.00 万」「932600.71 万」——元被当成万元；
# 还有一批「2026.00 万」「2022.00 万」——年份被抓成金额。
# 数字错不可怕，把错数字端给老板看才可怕。所以出清单前过三道闸。
AMT_MIN = 0.5        # 低于 0.5 万元（5 千）不是工程标的
AMT_MAX = 50000.0    # 高于 5 亿，全国公厕单体项目不可能
YEAR_LIKE = {2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026, 2027, 2028}


def amt_ok(v):
    if v <= 0:
        return False
    if v < AMT_MIN or v > AMT_MAX:
        return False
    if float(v).is_integer() and int(v) in YEAR_LIKE:
        return False
    return True


def fnum(s):
    try:
        return float(str(s).replace(',', '').strip())
    except Exception:
        return 0.0


def parse_date(s):
    s = (s or '').strip()
    m = re.match(r'(20\d{2})-(\d{1,2})-(\d{1,2})', s)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        return None


def grade(name, cat):
    t = (name or '') + (cat or '')
    if any(k in t for k in OUT_OF_SCOPE):
        return ''
    if any(k in t for k in P0_KW):
        return 'P0'
    if any(k in t for k in P1_KW):
        return 'P1'
    if any(k in t for k in P2_KW):
        return 'P2'
    return ''


def load_overrides():
    """读人工校正台账。人工判断永远优先于机器采集——
    机器只知道公告怎么写，人知道生意走到哪一步了。"""
    if not os.path.exists(OVERRIDES):
        return []
    try:
        with open(OVERRIDES, encoding='utf-8') as f:
            return json.load(f).get('records') or []
    except Exception:
        return []


def match_override(item, rules):
    hay = (item.get('name') or '') + ' ' + (item.get('link') or '')
    for r in rules:
        k = (r.get('match') or '').strip()
        if k and k in hay:
            return r
    return None


def load():
    if not os.path.exists(CSV_PATH):
        return []
    with open(CSV_PATH, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


FINAL_STAGES = ('结果公告', '中标', '成交', '流标', '废标', '终止', '变更', '澄清', '更正', '已失效')


def is_final(stage, status):
    """已结束的公告（结果/流标/变更）不进可投区，也不进待核区——
    它们的时间点已经过去，混进来只会把清单撑成一堆噪音。"""
    t = (stage or '') + (status or '')
    return any(k in t for k in FINAL_STAGES)


def dedup(live, pending):
    """同项目多来源去重。

    实例：长治项目既是人工情报（232.57 万，备注全），又被 ccgp 抓到（0 万，无备注），
    两条同时出现在清单里就是笑话。

    做法：标题归一化后续相似度 ≥0.62 且省份相同 → 判同一项目，
    保留信息更全的那条（有金额优先、备注长优先）。
    之所以不上精确键：ccgp 标题前面常挂一段采购人（「长治市城市管理局公开招标…」），
    人工补录则不带，精确键必然对不上。
    """
    import difflib

    def norm(it):
        s = re.sub(r'[（(].*?[)）]', '', it['name'])
        s = re.sub(r'(公开招标|竞争性磋商|竞争性谈判|询价|采购|项目|公告|中标|成交|结果|的|工程|建设)', '', s)
        s = re.sub(r'[\s·、，,。.:：\-—_/]+', '', s)
        return s

    def prov(it):
        a = it['area'] or ''
        return a[:2]

    def weight(it):
        return (1 if it['amount'] > 0 else 0, len(it['note'] or ''), len(it['link'] or ''))

    pool = list(live) + list(pending)
    merged, used = [], set()
    for i, a in enumerate(pool):
        if i in used:
            continue
        group = [a]
        na = norm(a)
        for j in range(i + 1, len(pool)):
            if j in used:
                continue
            b = pool[j]
            if prov(a) != prov(b):
                continue
            nb = norm(b)
            if not na or not nb:
                continue
            if difflib.SequenceMatcher(None, na, nb).ratio() >= 0.62:
                group.append(b)
                used.add(j)
        used.add(i)
        merged.append(max(group, key=weight))

    live2 = [x for x in merged if x.get('left') is not None]
    pend2 = [x for x in merged if x.get('left') is None]
    return live2, pend2


def build(rows, today=None):
    today = today or datetime.date.today()
    OV = load_overrides()
    live, pending, settled = [], [], []
    for r in rows:
        g = grade(r.get('项目名称', ''), r.get('品类', ''))
        if not g:
            continue
        if is_final(r.get('阶段'), r.get('状态')):
            continue
        dl = parse_date(r.get('投标截止')) or parse_date(r.get('报名截止'))
        raw_amt = fnum(r.get('金额(万元)'))
        dirty = bool(raw_amt) and not amt_ok(raw_amt)
        item = {
            'grade': g,
            'name': (r.get('项目名称') or '').strip(),
            'area': (r.get('地区') or '').strip() or '—',
            'amount': 0.0 if dirty else raw_amt,
            'amount_raw': (r.get('金额(万元)') or '').strip(),
            'amt_dirty': dirty,
            'owner': (r.get('采购方') or '').strip() or '—',
            'cat': (r.get('品类') or '').strip() or '—',
            'link': (r.get('链接') or '').strip(),
            'deadline': dl,
            'status': (r.get('状态') or '').strip(),
            'stage': (r.get('阶段') or '').strip(),
            'note': (r.get('备注') or '').strip(),
            'found': (r.get('发现日期') or '').strip(),
            'pub': (r.get('公告日期') or '').strip(),
            'src': (r.get('来源网站') or '').strip(),
        }

        # 信息滞留在哪一天（2026-11-09 项目主理人指出的硬伤）
        # 花都那条挂着「待开标」，实际项目早已定标——根因是雷达只采招标公告、
        # 从不追结果公告，所以每条记录的「状态」永远停在抓取那天。
        # 现在把「这条信息是从哪份公告抄来的、多少天没动过」摆到明面上，
        # 让读者一眼看出该不该信，而不是让他以为系统知道最新进展。
        base = parse_date(item['pub']) or parse_date(item['found'])
        if base:
            item['stale'] = (today - base).days
        else:
            item['stale'] = None
        ov = match_override(item, OV)
        if ov:
            item['override'] = ov
            item['status'] = ov.get('status') or item['status']
            if ov.get('note'):
                item['note'] = (item['note'] + '\n【人工校正 ' + str(ov.get('at', '')) + '】'
                                + ov['note']) if item['note'] else '【人工校正】' + ov['note']
            if ov.get('over'):
                item['over'] = 0
                settled.append(item)
                continue

        if dl is None:
            pending.append(item)
        elif dl >= today:
            item['left'] = (dl - today).days
            # 截止日在未来、但公告已经很旧（>10 天没更新）→ 大概率已经开标或延期，
            # 只是结果没回填。仍留在可投区，但必须挂黄牌，不能让人以为还稳。
            if item['stale'] is not None and item['stale'] > 10:
                item['suspect'] = True
            live.append(item)
        else:
            # 截止日已过：项目已开标（或废标），结果未回填。
            # 这些不是垃圾——「谁中了、多少钱」是下一步商务动作的依据，
            # 所以单列一区，不从清单里消失。
            item['over'] = (today - dl).days
            settled.append(item)
    live, pending = dedup(live, pending)
    order = {'P0': 0, 'P1': 1, 'P2': 2}
    live.sort(key=lambda x: (order[x['grade']], x['left'], -x['amount']))
    pending.sort(key=lambda x: (order[x['grade']], -x['amount']))
    settled.sort(key=lambda x: (order[x['grade']], -x['amount']))
    return live, pending, settled


def money(v, dirty=False):
    if dirty:
        return '金额待核'
    if v <= 0:
        return '未公开'
    if v >= 10000:
        return '%.2f 亿' % (v / 10000.0)
    return '%.2f 万' % v


def esc(s):
    return html.escape(str(s or ''))


def card(it):
    left = it.get('left')
    urg = ''
    if left is not None:
        if left <= 3:
            urg = '<span class="tag red">剩 %d 天</span>' % left
        elif left <= 7:
            urg = '<span class="tag amber">剩 %d 天</span>' % left
        else:
            urg = '<span class="tag grey">剩 %d 天</span>' % left
    link = it['link']
    if link.startswith('http'):
        link_html = '<a class="go" href="%s" target="_blank" rel="noopener">打开原文 →</a>' % esc(link)
    else:
        link_html = '<span class="go muted">无直达链接</span>'
    if it.get('suspect'):
        urg += '<span class="tag suspect">公告已 %d 天未更新</span>' % (it['stale'] or 0)
    note = it['note']
    if len(note) > 260:
        note = note[:260] + '…'
    return '''
    <article class="card g{grade}">
      <div class="row1">
        <span class="badge {grade}">{grade}</span>
        {urg}
        <span class="area">{area}</span>
        <span class="amt">{amt}</span>
      </div>
      <h3>{name}</h3>
      <dl>
        <dt>采购方</dt><dd>{owner}</dd>
        <dt>品类</dt><dd>{cat}</dd>
        <dt>截止</dt><dd>{dl}</dd>
        <dt>来源</dt><dd class="dim">{src} · 发现 {found}</dd>
      </dl>
      {noteblock}
      <div class="foot">{link}</div>
    </article>'''.format(
        grade=it['grade'], urg=urg, area=esc(it['area']), amt=esc(money(it['amount'], it.get('amt_dirty'))),
        name=esc(it['name']), owner=esc(it['owner']), cat=esc(it['cat']),
        dl=(it['deadline'].strftime('%Y-%m-%d') + (' %s' % it['status'] if it['status'] else '')) if it['deadline'] else '未采集到',
        src=esc(it['src']), found=esc(it['found']),
        noteblock=('<p class="note">%s</p>' % esc(note)) if note else '',
        link=link_html,
    )


def render(live, pending, settled, total, today):
    p0 = sum(1 for x in live if x['grade'] == 'P0')
    week = sum(1 for x in live if x.get('left', 99) <= 7)
    rows_html = ''.join(card(x) for x in live) or '<p class="empty">当前没有截止日期未过的项目。</p>'
    pend_rows = ''.join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            esc(x['grade']), esc(x['name'])[:46], esc(money(x['amount'], x.get('amt_dirty'))), esc(x['area']))
        for x in pending[:15])
    pend_html = ''
    if pending:
        pend_html = '''
  <section>
    <h2>待核：无截止日期（%d 条，不混入可投区）</h2>
    <p class="hint">这批抓到了标题和金额，但详情页没解析出截止时间。共 %d 条，下表列出最值得看的 %d 条。字段缺失是采集缺陷，正在修。</p>
    <table class="tbl"><thead><tr><th>级</th><th>项目</th><th>金额</th><th>地区</th></tr></thead><tbody>%s</tbody></table>
  </section>''' % (len(pending), len(pending), min(15, len(pending)), pend_rows)

    # 已开标区：截止日已过但库里没有结果。
    # 这一区的存在本身就是一条诚实的自白——「我知道它开了，我不知道谁中了」。
    # 比让项目继续假装「待开标」有用得多：至少商务下一步知道该去打听结果。
    settled_rows = ''.join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            esc(x['grade']), esc(x['name'])[:48],
            '已定标' if x.get('override') else '%d 天前' % x.get('over', 0),
            esc(x['area']))
        for x in settled[:20])
    settled_html = ''
    if settled:
        settled_html = '''
  <section>
    <h2>已开标 · 结果未回填（%d 条）</h2>
    <p class="hint">这些项目投标截止日已过，雷达只知道「开了」，不知道「谁中了」——
    因为系统只采招标公告，还没有追结果公告的能力。这是当前最大的盲区，不是可以糊过去的地方。
    下表按对口度排，最值得打电话去问结果的在最上面。</p>
    <table class="tbl"><thead><tr><th>级</th><th>项目</th><th>已过</th><th>地区</th></tr></thead><tbody>%s</tbody></table>
  </section>''' % (len(settled), settled_rows)

    return '''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>需求雷达 · 可投清单 {date}</title>
<style>
:root{{--ink:#1a2b23;--ink2:#4a5f55;--dim:#8aa096;--line:#e2ece6;--bg:#f4faf6;--card:#ffffff;
--green:#1f8a5f;--green-l:#eaf7f0;--red:#c0392b;--amber:#b7791f;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.65 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1000px;margin:0 auto;padding:28px 20px 60px}}
header{{border-bottom:2px solid var(--green);padding-bottom:16px;margin-bottom:22px}}
h1{{font-size:22px;margin:0 0 6px;letter-spacing:.5px}}
.sub{{color:var(--dim);font-size:13px}}
.kpi{{display:flex;gap:12px;margin:20px 0 26px;flex-wrap:wrap}}
.kpi div{{flex:1;min-width:140px;background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:14px 16px}}
.kpi b{{display:block;font-size:26px;color:var(--green);line-height:1.2}}
.kpi span{{font-size:12px;color:var(--dim)}}
h2{{font-size:15px;margin:30px 0 12px;color:var(--ink2);font-weight:600;
padding-left:9px;border-left:3px solid var(--green)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px 18px;margin-bottom:12px}}
.card.gP0{{border-left:4px solid #1f8a5f}}
.card.gP1{{border-left:4px solid #6aa9c9}}
.card.gP2{{border-left:4px solid #c9c2a9}}
.row1{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}}
.badge{{font-size:11px;font-weight:700;padding:2px 7px;border-radius:4px;letter-spacing:.5px}}
.badge.P0{{background:#1f8a5f;color:#fff}}
.badge.P1{{background:#e8f2f7;color:#3d7c9b}}
.badge.P2{{background:#f5f2e6;color:#8a7f5c}}
.tag{{font-size:11px;padding:2px 7px;border-radius:4px}}
.tag.red{{background:#fdecea;color:var(--red)}}
.tag.amber{{background:#fdf3e0;color:var(--amber)}}
.tag.grey{{background:#eef4f0;color:var(--dim)}}
.tag.suspect{{background:#fff4e5;color:#a55a00;border:1px dashed #e0a458}}
.area,.amt{{font-size:12px;color:var(--ink2)}}
.amt{{margin-left:auto;font-weight:600;color:var(--green)}}
h3{{font-size:16px;margin:0 0 10px;line-height:1.45;font-weight:600}}
dl{{display:grid;grid-template-columns:64px 1fr;gap:4px 10px;margin:0;font-size:13px}}
dt{{color:var(--dim)}} dd{{margin:0;color:var(--ink2)}}
.dim{{color:var(--dim);font-size:12px}}
.note{{margin:10px 0 0;padding:9px 11px;background:var(--green-l);border-radius:7px;
font-size:12.5px;color:#3c5a4c;line-height:1.6}}
.foot{{margin-top:11px;text-align:right}}
.go{{font-size:12.5px;color:var(--green);text-decoration:none;border-bottom:1px solid #b7ddc9}}
.muted{{color:var(--dim);border:0}}
.tbl{{width:100%;border-collapse:collapse;font-size:12.5px;background:var(--card);
border:1px solid var(--line);border-radius:10px;overflow:hidden}}
.tbl th{{background:var(--green-l);text-align:left;padding:8px 10px;font-weight:600;color:var(--ink2)}}
.tbl td{{padding:7px 10px;border-top:1px solid var(--line)}}
.hint{{font-size:12.5px;color:var(--dim);margin:0 0 10px}}
.empty{{color:var(--dim);font-size:14px}}
footer{{margin-top:40px;padding-top:14px;border-top:1px solid var(--line);
font-size:12px;color:var(--dim)}}
</style></head><body><div class="wrap">
<header>
  <h1>需求雷达 · 今日可投清单</h1>
  <div class="sub">{date} · 数据源 requirements.csv（全库 {total} 条，其中公厕/环卫类已按截止日期筛过）</div>
</header>

<div class="kpi">
  <div><b>{nlive}</b><span>仍可投（截止未过）</span></div>
  <div><b>{p0}</b><span>装配式·直接对口</span></div>
  <div><b>{week}</b><span>7 天内截止</span></div>
  <div><b>{npending}</b><span>待核（缺截止日）</span></div>
  <div><b>{nsettled}</b><span>已开标·结果未回填</span></div>
</div>

<section>
  <h2>可投项目（{nlive} 条，按对口度→紧迫度排序）</h2>
  {rows}
</section>
{settled_block}{pend}

<footer>生成时间 {now} · 分级：P0 装配式/模块化｜P1 公厕驿站｜P2 环卫关联<br>
本清单只回答一个问题：现在还能投什么。已开标但结果没回填的项目单列一区，
不混进可投——宁可说「不知道谁中了」，也不假装它还开着。</footer>
</div></body></html>'''.format(
        date=today.strftime('%Y年%m月%d日'), total=total, nlive=len(live), p0=p0,
        week=week, npending=len(pending), rows=rows_html, pend=pend_html,
        nsettled=len(settled), settled_block=settled_html, now=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))


def main():
    rows = load()
    today = datetime.date.today()
    live, pending, settled = build(rows, today)
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, '可投清单-%s.html' % today.strftime('%Y%m%d'))
    open(out, 'w', encoding='utf-8').write(render(live, pending, settled, len(rows), today))
    print('已生成', out)
    print('可投 %d 条 / 待核 %d 条 / 已开标待回填 %d 条 / 全库 %d 条' % (len(live), len(pending), len(settled), len(rows)))
    for it in live:
        print('  [%s] 剩%2d天 %8.2f万 %s | %s' % (it['grade'], it.get('left', -1), it['amount'], it['area'], it['name'][:36]))
    return out


if __name__ == '__main__':
    sys.exit(0 if main() else 0)
