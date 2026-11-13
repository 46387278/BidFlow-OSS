# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""金额与截止时间解析（项目主理人 2026-11-05：采购意向与招标公告必须有金额）。

法规依据（金额为何一定能拿到）：
  · 政府采购意向：财库〔2020〕10号 —— 公开内容法定包含「采购项目名称、采购需求概况、
    预算金额、预计采购时间」，预算金额是必公开项。
  · 工程招标公告：招标投标法实施条例第27条 —— 招标人设有最高投标限价的，
    应当在招标文件中明确最高投标限价或其计算方法；深圳建工公告正文即列「本次发包工程估价」。
所以：意向/招标阶段取不到金额 = 异常，必须显式记为 missing，不得静默留空。

单位口径：统一换算为「万元」，保留两位小数（与 requirements.csv 金额(万元) 一致）。
取值优先级（先限价后预算，投标最关心能报多少）：
  意向：预算金额
  政采招标：最高限价 ＞ 项目预算/预算金额 ＞ 采购预算
  建工招标：本次发包工程估价 ＞ 招标控制价 ＞ 计划总投资（总投资仅作兜底并标注）
  结果公告：成交金额/中标金额
排除项：保证金、代理服务费、报名费、工本费（这些不是项目金额）。
"""
import re

# 金额关键词 -> 类型权重（数字越大优先级越高）
KEYS = [
    ('最高限价', '最高限价', 90),
    ('最高投标限价', '最高限价', 90),
    ('招标控制价', '最高限价', 88),
    ('本次发包工程估价', '工程估价', 85),
    ('合同估算价', '工程估价', 84),
    ('项目预算', '预算', 70),
    ('预算金额', '预算', 70),
    ('采购预算', '预算', 68),
    ('成交金额', '成交价', 60),
    ('中标金额', '中标价', 60),
    ('计划总投资', '总投资', 30),
]

# 命中这些词的区间视为噪声（不是项目金额）
NOISE = ('保证金', '代理服务费', '服务费', '报名费', '工本费', '履约保证金',
         '投标保证金', '预算金额的', '百分之', '费率', '单价')

NUM = r'([0-9][0-9,，]*(?:\.[0-9]+)?)'
UNIT = r'\s*(万元|万|元)?'


def _to_wan(num, unit):
    """数字+单位 -> 万元。无单位时按上下文默认（正文多为「元」）。
    合理性防线：>1000 亿（1e7 万元）视作编号误判，拒绝。"""
    try:
        v = float(num.replace(',', '').replace('，', ''))
    except ValueError:
        return None
    if unit in ('万元', '万'):
        w = v
    elif unit == '元':
        w = v / 10000.0
    else:
        w = v
    if w <= 0 or w > 1e7:
        return None
    return round(w, 2)


def _clean(text):
    t = re.sub(r'<script.*?</script>', ' ', text or '', flags=re.S)
    t = re.sub(r'<style.*?</style>', ' ', t, flags=re.S)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = t.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\s+', ' ', t)


def parse_amount(text, stage=''):
    """从正文/结构化文本提金额。

    返回 (amount_wan_str, amount_type, amount_raw)
      amount_wan_str: '209.07' 或 ''（取不到）
      amount_type: '最高限价'/'预算'/'工程估价'/'成交价'/'总投资'/''
      amount_raw: 命中的原始片段，供人工核对
    取不到返回 ('', '', '')
    """
    t = _clean(text)
    if not t:
        return '', '', ''
    # 结构化优先：预算金额（元）: 2,090,680.000
    m = re.search(r'预算金额\s*[（(]?\s*(元|万元)?\s*[)）]?\s*[:：]\s*' + NUM + UNIT, t)
    if m:
        # group1=括号内单位, group2=数字, group3=数字后单位
        unit = m.group(3) or m.group(1) or '元'
        v = _to_wan(m.group(2), unit if unit in ('元', '万元', '万') else '元')
        if v is not None:
            return ('%.2f' % v), '预算', m.group(0)[:60]

    cands = []
    for kw, typ, w in KEYS:
        for m in re.finditer(re.escape(kw), t):
            seg = t[m.start():m.start() + 90]
            # 允许中间有冒号、人民币、约、为等连接
            mm = re.search(r'[:：]?\s*(?:人民币|RMB|¥)?\s*(?:约|为|共计)?\s*' + NUM + UNIT, seg)
            if not mm:
                continue
            ctx = t[max(0, m.start() - 12):m.start()]
            if any(n in ctx or n in seg[:40] for n in NOISE):
                continue
            unit = mm.group(2) or '元'   # 无单位时，政采正文默认「元」
            v = _to_wan(mm.group(1), unit)
            if v is None or v <= 0:
                continue
            cands.append((w, v, typ, seg[:60]))
            break
    if not cands:
        return '', '', ''
    cands.sort(key=lambda x: -x[0])
    w, v, typ, raw = cands[0]
    return ('%.2f' % v), typ, raw


def parse_deadline(text):
    """从正文提投标截止/递交截止时间。取不到返回 ''（不猜）。"""
    t = _clean(text)
    pats = [
        r'(?:投标|响应|递交|提交)[^。；]{0,12}截止(?:时间|日期)[^0-9]{0,10}'
        r'(20\d\d)[-年/.](\d{1,2})[-月/.](\d{1,2})日?',
        r'(?:开标|投标截止)[^0-9]{0,12}(20\d\d)[-年/.](\d{1,2})[-月/.](\d{1,2})',
        r'截止时间[：: ]*(20\d\d)[-年/.](\d{1,2})[-月/.](\d{1,2})',
    ]
    for p in pats:
        m = re.search(p, t)
        if m:
            y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return '%s-%02d-%02d' % (y, mo, d)
    # 结构化：2026年11月20日 09:30
    m = re.search(r'(?:投标文件递交截止时间|响应文件提交截止时间)[^0-9]{0,12}'
                  r'(20\d\d)年(\d{1,2})月(\d{1,2})日', t)
    if m:
        return '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3)))
    return ''
