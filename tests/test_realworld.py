# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""真实招标文件表头形态的回归测试。

2026-11-13 拿广东政采 2026102309「装配式公共厕所采购项目」真机验收时，
拆解结果里评分项 12 个、分值合计 100.0 —— 但那是在补了「两列表头」和
「分值写在名称里」两条规则之后。补之前是 0 项、0 分：整张评分表被当成正文吃掉了。

这个文件把那天的表结构固定下来：以后谁改 find_scoring，这里先红。
不需要真文档，直接喂表格结构就行 —— find_scoring 只依赖 doc['tables']。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from core.bid_engine import find_scoring          # noqa: E402
from core.plan_engine import extract_points, classify  # noqa: E402

# 真实文件里的原样结构：表头两列（合并单元格），数据行三列，分值写在名称括号里
REAL_TABLE = [
    ['评审因素', '评审标准'],
    ['分值构成', '商务部分15.0分技术部分50.0分'],
    ['技术部分', '技术参数响应程度1 (6.0分)', '根据各投标人对《第二章 采购需求》中具体技术参数的响应情况评审。'],
    ['技术部分', '技术参数响应程度2 (24.0分)', '根据投标人所投产品对采购需求的响应程度评审。'],
    ['技术部分', '项目实施方案 (5.0分)', '根据投标人的项目实施方案（应包含设备运输方案、安装方案、工作内容、技术及安全文明措施、人员安排）进行评审。'],
    ['技术部分', '产品质量保证措施 (5.0分)', '根据投标人的质量保证措施（包括但不限于包含：产品质量承诺、质量保障、赔偿措施）进行评审。'],
    ['技术部分', '产品维修保养管理措施 (5.0分)', '（1）措施完善科学的得5分；（2）措施完整的得3分；（3）措施较差的得1分。'],
    ['技术部分', '供货、安装方案 (5.0分)', '根据投标人的供货方案（应包含供货时间安排、供货方式）及安装调试方案（应包含安装调试计划、安装步骤、人员安排）进行评审。'],
    ['商务部分', '管理认证 (6.0分)', '具有有效的质量管理体系认证证书的得6分。'],
    ['商务部分', '综合信用评价 (5.0分)', '综合信用评价得分=综合信用评价得分×5%。'],
    ['价格部分', '投标报价得分 (30.0分)', '投标报价得分＝（评标基准价/投标报价）×价格分。'],
    ['价格部分', '质保期承诺 (3.0分)', '在满足招标文件所有质保要求基础上，承诺每增加一年得1分。'],
    ['', '客户评价 (3.0分)', '提供客户出具的满意评价证明的得分。'],
    ['', '同类项目业绩 (3.0分)', '自2023年1月1日以来同类项目业绩，每提供一个得1分。'],
]

PASS = FAIL = 0


def check(name, got, want, note=''):
    global PASS, FAIL
    ok = got == want
    if ok:
        PASS += 1
        print('  [PASS] %-28s %s' % (name, got))
    else:
        FAIL += 1
        print('  [FAIL] %-28s 期望 %s 实得 %s %s' % (name, want, got, note))


print('=' * 62)
print('test_realworld · 真实表头形态回归')
print('=' * 62)

print('\n[1/3] 两列表头 + 分值写在名称里')
sc = find_scoring({'tables': [REAL_TABLE]})
items = sc['items']
check('评分项数', len(items), 12)
check('分值合计', round(sc['checks']['weight_sum'], 2), 100.0)
check('合计等于100', sc['checks']['weight_sum_is_100'], True)
check('每条都有出处', sc['checks']['has_locator'], True)
check('名称无空值', all(i['name'] for i in items), True)

print('\n[2/3] 分值确实是从名称里取的')
w = {i['name']: i['weight'] for i in items}
check('技术参数响应程度1', w.get('技术参数响应程度1 (6.0分)'), 6.0)
check('技术参数响应程度2', w.get('技术参数响应程度2 (24.0分)'), 24.0)
check('投标报价得分', w.get('投标报价得分 (30.0分)'), 30.0)

print('\n[3/3] 括号内并列列举 → 计分点')
plan_items = [i for i in items if classify(i['name']) == '方案']
check('方案类评分项数', len(plan_items), 4)
by_name = {i['name']: len(extract_points(i['rule'])) for i in plan_items}
check('项目实施方案 计分点', by_name.get('项目实施方案 (5.0分)'), 5)
check('供货安装方案 计分点', by_name.get('供货、安装方案 (5.0分)'), 5)
check('维修保养(分档题) 计分点', by_name.get('产品维修保养管理措施 (5.0分)'), 0,
      '分档打分的题不该被拆成计分点')
pts = extract_points('（包括但不限于包含：产品质量承诺、质量保障、赔偿措施）')
check('套娃前缀已剥离', pts[0]['text'] if pts else '', '产品质量承诺')

print('\n' + '-' * 62)
print('通过 %d 项，失败 %d 项' % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
