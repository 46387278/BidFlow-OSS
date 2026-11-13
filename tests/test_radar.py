# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
test_radar.py —— 需求雷达项目表验收（结果一）

断言：
  1 总量与分档：6 条样例库 → 可行动 4 / 观察 1 / 不跟 1
  2 字段完整：项目名称、地区、阶段、链接、发现日期不得为空；金额空值按未知计分不报错
  3 筛选正确：地区+金额双条件筛出来的行，逐行必须满足条件
  4 输出可用：CSV 表头齐全、行数与命中数一致、每行有评分依据
  5 可重复：固定基准日跑两次，结果完全一致

为什么必须固定基准日：
    打分含「新鲜度」（7 天内 +20 / 30 天内 +12 / 90 天内 +5）。
    如果基准日取运行当天，同一个库昨天跑和今天跑分档就会变，
    测试在 CI 上会隔几天红一次，且红得没有意义。所以 scan() 支持 as_of 注入，
    测试固定传 AS_OF，生产环境不传（默认今天）。

用法：python tests/test_radar.py
"""
import os
import sys
import csv
import io
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PKG, 'src', 'core'))

import radar as RD

CSV_PATH = os.path.join(PKG, 'data', 'requirements.example.csv')
AS_OF = '2026-09-10'          # 固定基准日：样例库的最后一条是 09-08，落在「7 天内」档
OK, FAIL = [], []


def check(name, got, want):
    if got == want:
        OK.append(name)
        print('  [PASS] %-34s %s' % (name, got))
    else:
        FAIL.append(name)
        print('  [FAIL] %-34s 期望 %s，实得 %s' % (name, want, got))


def main():
    print('=' * 62)
    print('test_radar · 需求雷达验收（基准日 %s，固定）' % AS_OF)
    print('=' * 62)

    m = RD.scan(CSV_PATH, as_of=AS_OF)
    print('\n[1/5] 总量与分档')
    check('库内总量', m['n'], 6)
    check('命中条数', len(m['rows']), 6)
    check('可行动（≥40）', len(m['act']), 4)
    check('观察（10–39）', len(m['watch']), 1)
    check('不跟（<10）', len(m['dead']), 1)
    print('       分档明细：可行动 %s' % [r['name'][:14] for r in m['act']])

    print('\n[2/5] 字段完整')
    rows = RD.load(CSV_PATH)
    for col in ('项目名称', '地区', '阶段', '链接', '发现日期'):
        empty = sum(1 for r in rows if not (r[col] or '').strip())
        check('空值 %s' % col, empty, 0)
    amt_unknown = sum(1 for r in m['rows'] if not str(r['amount']).strip())
    print('  [INFO] 金额待确认 %d 条（按未知计分，不参与金额档加分）' % amt_unknown)

    print('\n[3/5] 筛选正确性（示例市 + ≥100 万）')
    f = RD.scan(CSV_PATH, region='示例市', minamt=100, as_of=AS_OF)
    bad_region = [r['name'] for r in f['rows'] if '示例市' not in r['region']]
    bad_amt = [r['name'] for r in f['rows']
               if RD._num(r['amount']) is None or RD._num(r['amount']) < 100]
    check('地区不符条数', len(bad_region), 0)
    check('金额不符条数', len(bad_amt), 0)
    check('命中条数', len(f['rows']), 2)

    print('\n[4/5] 输出可用性')
    out = os.path.join(PKG, 'output', '_test_radar.csv')
    RD.write_csv(m, out)
    got = list(csv.reader(io.open(out, encoding='utf-8-sig')))
    check('CSV 表头列数', len(got[0]), 11)
    check('CSV 数据行数', len(got) - 1, len(m['rows']))
    check('CSV 行宽一致', len(set(len(r) for r in got)), 1)
    no_reason = [r for r in got[1:] if not r[8].strip()]
    check('缺评分依据行', len(no_reason), 0)
    html = RD.render_html(m)
    check('HTML 含三档标题',
          all(k in html for k in ('一、可行动', '二、观察', '三、不跟')), True)
    check('output 目录自动创建', os.path.isfile(out), True)
    os.remove(out)

    print('\n[5/5] 可重复性')
    m2 = RD.scan(CSV_PATH, as_of=AS_OF)
    sig1 = [(r['name'], r['score']) for r in m['rows']]
    sig2 = [(r['name'], r['score']) for r in m2['rows']]
    check('同基准日两次结果一致', sig1 == sig2, True)

    key = collections.Counter((r['项目名称'].strip(), r['地区'].strip()) for r in rows)
    check('完全同名同地区重复组', sum(1 for k, v in key.items() if v > 1), 0)

    print('\n' + '-' * 62)
    print('通过 %d 项，失败 %d 项' % (len(OK), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
