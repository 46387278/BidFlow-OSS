# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
需求雷达（结果一）—— 把需求库扫成一张可看的项目表。

边界要说清：采集在库外（人工或外部脚本入库），本模块只做
  过滤 → 打分排序 → 出表。
不承诺实时抓取，不承诺全网覆盖。
"""
import os, csv, io, re, datetime, html

from .radar_config import keywords

NODES = ('预算立项', '采购意向', '招标公告', '招标结果公布')


def _as_date(v):
    """接受 date / 'YYYY-MM-DD' / None，统一成 date。None → 今天。"""
    if v is None:
        return datetime.date.today()
    if isinstance(v, datetime.date):
        return v
    return _date(str(v)) or datetime.date.today()

def _num(s):
    m = re.search(r'(\d+(?:\.\d+)?)', str(s or ''))
    return float(m.group(1)) if m else None


def _date(s):
    m = re.search(r'(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})', str(s or ''))
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def load(csv_path):
    with io.open(csv_path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def score(row, as_of=None, settings=None):
    """打分。as_of 可注入基准日 —— 新鲜度权重依赖「今天」，不注入则测试
    跨天必失败，CI 上表现为随机红。"""
    now = _as_date(as_of)
    pts, why = 0, []
    st = (row.get('阶段') or '').strip()
    settings = keywords() if settings is None else settings
    weight = settings['stage_weights'].get(st, 0)
    deadline = _date(row.get('投标截止'))
    # 临近截止的公告介入窗口较短。
    if st == '招标公告' and deadline and (deadline - now).days < 15:
        weight = 10
    pts += weight
    if weight:
        why.append(f'阶段{st}{weight:+d}')

    amt = _num(row.get('金额(万元)'))
    if amt is not None and amt > 0:
        w = 25 if amt >= 200 else 15 if amt >= 100 else 8 if amt >= 50 else 0
        pts += w
        if w:
            why.append(f'{amt:g}万{w:+d}')

    d = _date(row.get('发现日期'))
    if d:
        age = (now - d).days
        w = 20 if age <= 7 else 12 if age <= 30 else 5 if age <= 90 else 0
        pts += w
        if w:
            why.append(f'{age}天前{w:+d}')

    name = row.get('项目名称') or ''
    weight = settings['good_weight']
    if any(word in name for word in settings['bad']):
        pts -= weight
        why.append(f'过滤词{-weight:+d}')
    elif any(word in name for word in settings['good']):
        pts += weight
        why.append(f'品类对口{weight:+d}')

    return pts, '·'.join(why)


def scan(csv_path, region='', days=0, minamt=0, limit=200, as_of=None):
    rows = load(csv_path)
    now = _as_date(as_of)
    out = []
    settings = keywords()
    for r in rows:
        if region and region not in (r.get('地区') or ''):
            continue
        d = _date(r.get('发现日期'))
        if days and (not d or (now - d).days > days):
            continue
        amt = _num(r.get('金额(万元)'))
        if minamt and (amt is None or amt < minamt):
            continue
        s, why = score(r, now, settings)
        stage = (r.get('阶段') or '').strip()
        node = NODES.index(stage) + 1 if stage in NODES else 0
        out.append({
            'score': s, 'why': why,
            'stage': stage if node else '判不出',
            'node': node, 'status': r.get('状态') or '',
            'region': r.get('地区') or '',
            'name': r.get('项目名称') or '',
            'buyer': r.get('采购方') or '',
            'amount': r.get('金额(万元)') or '',
            'kind': r.get('品类') or '',
            'date': r.get('发现日期') or '',
            'link': r.get('链接') or '',
            'note': r.get('备注') or '',
        })
    out.sort(key=lambda x: (-x['score'], x['name']))
    out = out[:limit]

    act = [x for x in out if x['score'] >= 40]
    watch = [x for x in out if 10 <= x['score'] < 40]
    dead = [x for x in out if x['score'] < 10]
    return {'rows': out, 'n': len(rows), 'act': act, 'watch': watch, 'dead': dead,
            'filters': {'region': region, 'days': days, 'minamt': minamt},
            'as_of': now.isoformat()}


def render_html(m, title='需求雷达项目表'):
    f = m['filters']
    cond = '　'.join(x for x in [
        f'地区含「{f["region"]}」' if f['region'] else '',
        f'近 {f["days"]} 天' if f['days'] else '',
        f'金额 ≥ {f["minamt"]} 万' if f['minamt'] else '',
    ] if x) or '全库'

    def source_link(url):
        if not url:
            return '—'
        return f'<a href="{html.escape(url)}" target=_blank>原件</a>'

    def table(rows, empty):
        if not rows:
            return f'<div class="empty">{empty}</div>'
        body = ''.join(
            f"<tr><td class='sc'>{r['score']}</td><td class='nm'>{html.escape(r['name'])}</td>"
            f"<td class='rg'>{html.escape(r['region'])}</td><td class='am'>{html.escape(r['amount'])}</td>"
            f"<td class='st'>{html.escape(r['stage'])}</td><td>{r['node']}</td><td>{html.escape(r['status'])}</td><td class='wh'>{html.escape(r['why'])}</td>"
            f"<td class='lk'>{source_link(r['link'])}</td></tr>"
            for r in rows)
        return (f"<table><thead><tr><th>评分</th><th>项目</th><th>地区</th><th>金额(万)</th>"
                f"<th>阶段</th><th>node</th><th>状态</th><th>评分依据</th><th>来源</th></tr></thead><tbody>{body}</tbody></table>")

    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{html.escape(title)}</title><style>
@page {{ size:A4 landscape; margin:12mm 10mm; }}
body {{ font-family:"Songti SC","SimSun","Microsoft YaHei",serif; font-size:9pt; color:#1a1a1a; margin:0; line-height:1.5; }}
h1 {{ font-size:17pt; margin:0 0 3px; }}
.sub {{ color:#666; font-size:8pt; margin-bottom:10px; }}
.cards {{ display:flex; gap:8px; margin:0 0 12px; }}
.c {{ flex:1; border:1px solid #ddd; padding:7px 10px; }}
.c .k {{ font-size:8pt; color:#777; }} .c .v {{ font-size:16pt; font-weight:700; }} .c .u {{ font-size:7.5pt; color:#999; }}
h2 {{ font-size:10.5pt; margin:14px 0 5px; padding-bottom:3px; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; font-size:8pt; }}
th {{ background:#efefec; text-align:left; padding:3px 5px; border:1px solid #ddd; font-size:7.5pt; }}
td {{ border:1px solid #e6e6e3; padding:3px 5px; vertical-align:top; }}
.sc {{ width:40px; text-align:right; font-weight:700; }}
.rg {{ width:50px; }} .am {{ width:62px; }} .st {{ width:56px; }} .wh {{ width:150px; color:#777; font-size:7.5pt; }} .lk {{ width:44px; }}
.empty {{ color:#999; font-size:9pt; padding:8px 2px; }}
.foot {{ margin-top:12px; padding-top:6px; border-top:1px solid #ccc; font-size:7.5pt; color:#888; }}
</style></head><body>
<h1>{html.escape(title)}</h1>
<div class="sub">筛选：{html.escape(cond)}　·　生成时间 {datetime.datetime.now():%Y-%m-%d %H:%M}</div>
<div class="cards">
  <div class="c"><div class="k">库内总量</div><div class="v">{m['n']}</div><div class="u">条</div></div>
  <div class="c"><div class="k">本期命中</div><div class="v">{len(m['rows'])}</div><div class="u">条</div></div>
  <div class="c"><div class="k">可行动（≥40）</div><div class="v" style="color:#b3261e">{len(m['act'])}</div><div class="u">条</div></div>
  <div class="c"><div class="k">观察（10–39）</div><div class="v" style="color:#8a6d1f">{len(m['watch'])}</div><div class="u">条</div></div>
  <div class="c"><div class="k">不跟（&lt;10）</div><div class="v" style="color:#888">{len(m['dead'])}</div><div class="u">条</div></div>
</div>
<h2>一、可行动</h2>{table(m['act'], '本期无可行动项目。')}
<h2>二、观察</h2>{table(m['watch'], '无。')}
<h2>三、低分项目</h2>{table(m['dead'][:30], '无。')}
<div class="foot">
评分口径：介入窗口＋金额＋公告新鲜度＋品类词表。<br>
本表只做筛选与排序，不对项目真实性、可投性作判断；金额「待确认」者按未知计分。来源链接可逐条回原件核对。
</div></body></html>"""


def write_csv(m, path):
    # 防御：干净解压的包里没有 output 目录（zip 不打包空目录），必须自己建
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['评分', '项目名称', '地区', '金额(万元)', '阶段', 'node', '状态', '品类', '采购方',
                    '发现日期', '评分依据', '链接', '备注'])
        for r in m['rows']:
            w.writerow([r['score'], r['name'], r['region'], r['amount'], r['stage'], r['node'], r['status'],
                        r['kind'], r['buyer'], r['date'], r['why'], r['link'], r['note']])
    return path
