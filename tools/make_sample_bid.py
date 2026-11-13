#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
make_sample_bid.py —— 生成合成招标文件（零依赖，纯标准库）

为什么需要它：
    仓库里不能放真实政府采购文件（第三方版权、体积、以及验收基线会失去意义）。
    但引擎必须有输入才能跑测试。所以样本必须"可复现地生成"，而不是"上传一个二进制"。

    任何人 clone 仓库后执行：
        python tools/make_sample_bid.py
    就能得到一份结构与真实招标文件同构的假文件，用于回归测试。

它生成什么：
    data/sample/sample_bid.docx —— 虚构项目「示例市 A 片区公共卫生间采购项目」
    所有单位名、金额、编号均为虚构，与任何真实项目无关。

结构对齐真实文件的关键点：
    1. 评分表是 Word 表格（引擎靠表头关键词识别，不是靠标题）
    2. ★ 实质性条款散落在正文段落里（引擎按正则扫描全文）
    3. 分值合计 100（引擎会校验合计，对不上会标 fail）
"""
import os
import zipfile

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

CT = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>'''

RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''

STYLES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Times New Roman" w:eastAsia="宋体" w:hAnsi="Times New Roman"/>
<w:sz w:val="21"/><w:szCs w:val="21"/>
</w:rPr></w:rPrDefault></w:docDefaults>
</w:styles>'''


def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def para(text, size=21, bold=False, align=None, indent=420):
    ppr = '<w:pPr>'
    if align:
        ppr += '<w:jc w:val="%s"/>' % align
    if indent:
        ppr += '<w:ind w:firstLine="%d"/>' % indent
    ppr += '<w:spacing w:after="60" w:line="360" w:lineRule="auto"/></w:pPr>'
    rpr = ('<w:rPr><w:rFonts w:ascii="Times New Roman" w:eastAsia="宋体" '
           'w:hAnsi="Times New Roman"/>%s<w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr>'
           % ('<w:b/>' if bold else '', size, size))
    return '<w:p>%s<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (ppr, rpr, esc(text))


def cell(text, w, bold=False):
    return ('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/>'
            '<w:vAlign w:val="center"/></w:tcPr>%s</w:tc>'
            % (w, para(text, 20, bold, indent=0)))


def table(rows, widths, header=True):
    border = ''.join('<w:%s w:val="single" w:sz="4" w:space="0" w:color="808080"/>' % b
                     for b in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
    out = ['<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblBorders>%s</w:tblBorders>'
           '<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>%s</w:tblGrid>'
           % (sum(widths), border, ''.join('<w:gridCol w:w="%d"/>' % w for w in widths))]
    for i, row in enumerate(rows):
        is_head = header and i == 0
        out.append('<w:tr>%s</w:tr>' % ''.join(
            cell(c, widths[j], is_head) for j, c in enumerate(row)))
    out.append('</w:tbl>')
    out.append(para('', indent=0))  # 表后空段，避免与下文粘连
    return ''.join(out)


# ---------------------------------------------------------------- 正文内容
TITLE = '示例市 A 片区公共卫生间采购项目'
DOCNO = 'SAMPLE-2026-001'

SCORE_ROWS = [
    ['评分因素', '分值', '评分标准'],
    ['投标报价', '30',
     '满足招标文件要求且投标价格最低的投标报价为评标基准价，其价格分为满分。'
     '其他投标人的价格分按照公式计算：投标报价得分＝（评标基准价／投标报价）×30。'
     '报价超过项目控制金额的，投标无效。'],
    ['生产及组装模式', '8',
     '生产及组装模式：①工厂预制率不低于百分之七十，得3分；'
     '②提供完整部品清单并标注型号，得3分；③提供出厂检验记录样张，得2分。'],
    ['供货进度计划', '6',
     '供货进度计划：①排产、运输、到场、安装四阶段节点齐全，得3分；'
     '②附赶工预案与责任分工，得3分。'],
    ['质量保证措施', '6',
     '质量保证措施：①材料进场检验标准明确，得2分；'
     '②过程质量控制有责任人与检查频次，得2分；③成品保护措施具体，得2分。'],
    ['安装施工方案', '8',
     '安装施工方案：①现场勘察结论针对本项目六个点位，得2分；'
     '②基础处理与吊装就位工序清晰，得2分；③水电接驳与调试交付有节点，得2分；'
     '④附平面布置图，得2分。'],
    ['售后服务方案', '10',
     '售后服务方案：①质保期满足两年，得4分；②每增加一年加1分，最高加2分；'
     '③承诺两小时响应，得2分；④承诺二十四小时到场，得2分。'],
    ['应急保障措施', '6',
     '应急保障措施：①突发故障处置流程，得2分；②恶劣天气应对措施，得2分；'
     '③应急物料配置清单，得2分。'],
    ['项目人员配备', '6',
     '项目人员配备：①项目负责人具有中级及以上职称，得2分；'
     '②配备专职安全员，得2分；③安装班组不少于六人，得2分。'
     '须提供证书及社保缴纳证明扫描件。'],
    ['类似业绩', '10',
     '类似业绩：近三年同类项目业绩，每提供一项得2分，最高得10分。'
     '须提供合同关键页及验收证明扫描件，原件备查。'],
    ['环保与职业健康', '5',
     '环保与职业健康：①提供材料环保检测报告，得3分；'
     '②提供职业病防护用品配置清单，得2分。'],
    ['技术培训与交付', '5',
     '技术培训与交付：①培训方案含对象、课时、教材、考核，得3分；'
     '②提供交付资料清单，得2分。'],
]


def build_body(variant='a'):
    b = []
    add = b.append
    if variant == 'b':
        return _build_variant_b()
    add(para(TITLE, 32, True, 'center', 0))
    add(para('招标文件', 28, True, 'center', 0))
    add(para('项目编号：%s' % DOCNO, 22, False, 'center', 0))
    add(para('（本文件为 BidFlow 开源仓库的合成测试样本，全部内容虚构）',
             18, False, 'center', 0))

    add(para('第一章  招标公告', 26, True, indent=0))
    add(para('1.1 项目名称：%s。' % TITLE))
    add(para('1.2 项目编号：%s。' % DOCNO))
    add(para('1.3 采购人：示例市城市环境服务中心（虚构单位）。'))
    add(para('1.4 项目地点：示例市 A 片区，共 6 个点位。'))
    add(para('1.5 采购内容：装配式公共卫生间 6 座，含基础施工、'
             '水电接驳、设备安装与调试交付。'))
    add(para('1.6 项目控制金额：人民币叁佰捌拾万元整（￥3,800,000.00）。'
             '投标报价超过控制金额的，投标无效。'))
    add(para('1.7 交货期：合同签订后 60 日历日内完成全部点位交付并验收合格，'
             '交货期不可负偏离。'))
    add(para('1.8 投标截止时间：2026 年 11 月 20 日 09:30（北京时间）。'
             '逾期送达的投标文件不予受理。'))

    add(para('第二章  投标人资格要求', 26, True, indent=0))
    add(para('2.1 具有独立承担民事责任的能力，提供有效的营业执照扫描件。'))
    add(para('2.2 具有良好的商业信誉和健全的财务会计制度，'
             '提供上一年度财务审计报告或银行资信证明。'))
    add(para('2.3 有依法缴纳税收和社会保障资金的良好记录，'
             '提供近三个月社保缴纳证明。'))
    add(para('2.4 参加本次采购活动前三年内，在经营活动中没有重大违法记录，'
             '提供书面声明。'))
    add(para('2.5 本项目不接受联合体投标，不允许分包、转包。'))
    add(para('2.6 投标人未按要求提供上述资格证明文件的，按无效投标处理。'))

    add(para('第三章  投标人须知', 26, True, indent=0))
    add(para('3.1 投标有效期：自投标截止之日起 90 日历日。'
             '投标有效期不足 90 日历日的，视为无效投标。'))
    add(para('3.2 投标保证金：人民币柒万元整（￥70,000.00），'
             '须于投标截止时间前从投标人基本账户转出，'
             '未按规定缴纳投标保证金的，其投标文件不予受理。'))
    add(para('3.3 投标文件正本一份、副本四份，采用 A4 纸双面打印，'
             '胶装成册，不得采用活页装订。'))
    add(para('3.4 投标文件须密封包装，封口处加盖投标人公章，'
             '并在封套上标明项目名称、项目编号、投标人名称。'
             '未按要求密封和标记的，不予受理。'))
    add(para('3.5 投标文件须由法定代表人或其授权代表签字并加盖公章。'
             '授权代表签字的，须同时提交法定代表人授权委托书原件。'
             '未按要求签字盖章的，按无效投标处理。'))
    add(para('3.6 投标人提供虚假材料谋取中标的，取消其中标资格，'
             '并报监管部门处理，投标保证金不予退还。'))
    add(para('3.7 中标人应在中标通知书发出之日起 30 日内与采购人签订合同，'
             '无正当理由逾期不签订的，取消中标资格。'))
    add(para('3.8 投标人应自行踏勘项目现场，因未踏勘导致的方案偏差由投标人自行承担，'
             '采购人不承担由此产生的任何损失。'))
    add(para('3.9 投标文件电子版须与纸质正本一致，'
             '不一致时以纸质正本为准。'))
    add(para('3.10 投标人须在投标文件目录对应节点填报相应内容，'
             '填写到其他节点导致评标委员会无法查找的，后果由投标人自负。'))

    add(para('第四章  评标办法', 26, True, indent=0))
    add(para('4.1 本项目采用综合评分法，总分 100 分，其中价格分 30 分，技术及商务分 70 分。'))
    add(para('4.2 评标委员会按下表逐项打分，各评分项得分保留两位小数。'))
    add(table(SCORE_ROWS, [2600, 1000, 5400]))
    add(para('4.3 投标文件未实质上响应招标文件要求的，评标委员会有权否决其投标。'))
    add(para('4.4 评标过程中发现投标报价明显低于成本的，'
             '评标委员会有权要求投标人书面说明并提供证明材料，'
             '不能证明其报价合理性的，按无效投标处理。'))

    add(para('第五章  技术要求', 26, True, indent=0))
    add(para('5.1 单座卫生间建筑面积不小于 12 平方米，'
             '男女厕位比例不低于 1:1.5，须设置无障碍厕位 1 个。'))
    add(para('5.2 主体结构采用装配式钢结构，工厂预制率不低于 70%。'))
    add(para('5.3 外墙板采用镀铝锌钢板，厚度不小于 0.8 毫米，'
             '涂层附着力不低于 1 级。'))
    add(para('5.4 屋面防水等级不低于Ⅱ级，防水层设计使用年限不低于 10 年。'))
    add(para('5.5 洁具采用节水型产品，单次冲水量不大于 4.5 升。'))
    add(para('5.6 配置智能监测终端，可采集异味、温湿度、客流数据，'
             '数据接口须开放并支持对接采购人现有管理平台。'))
    add(para('5.7 ★ 主要材料（钢板、洁具、防水材料）须提供第三方检测机构出具的'
             '有效检测报告，报告须在有效期内且与投标产品型号一致。'
             '未提供或提供不全的，按无效投标处理。'))
    add(para('5.8 ★ 投标产品须提供省级及以上质量监督检验机构出具的整体性能检测报告。'))
    add(para('5.9 投标人须提供卫生间平面布置图与立面效果图，'
             '图纸须标注主要尺寸。'))

    add(para('第六章  商务要求', 26, True, indent=0))
    add(para('6.1 质保期：自整体验收合格之日起不少于 2 年。'
             '质保期低于 2 年的，按无效投标处理。'))
    add(para('6.2 质保期内出现故障，中标人须 2 小时内响应，24 小时内到场处理。'))
    add(para('6.3 质保期内同一部件累计维修 3 次仍不能正常使用的，'
             '中标人须免费更换该部件。'))
    add(para('6.4 中标人须在项目所在地设有售后服务网点或承诺中标后 30 日内设立，'
             '未设立的视为不响应商务要求。'))
    add(para('6.5 ★ 付款方式：合同签订后支付 30%，到货验收后支付 50%，'
             '整体验收合格后支付 15%，质保期满支付 5%。'
             '不响应本付款方式的，按无效投标处理。'))
    add(para('6.6 履约保证金：合同金额的 5%，于合同签订前缴纳。'))
    add(para('6.7 中标人须购买建筑工程一切险及第三者责任险，'
             '保险费用由中标人承担。'))

    add(para('第七章  合同主要条款', 26, True, indent=0))
    add(para('7.1 因中标人原因导致工期延误的，每延误一日按合同金额的 0.5‰ 支付违约金，'
             '累计不超过合同金额的 5%。'))
    add(para('7.2 采购人有权对中标人的生产过程进行监督，'
             '发现不符合要求的，有权要求整改；拒不整改的，采购人有权中止合同。'))
    add(para('7.3 因中标人产品质量问题造成人身伤害或财产损失的，'
             '由中标人承担全部责任。'))

    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1440" w:right="1134" w:bottom="1440" w:left="1134" '
            'w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document %s><w:body>%s%s</w:body></w:document>'
            % (NS, ''.join(b), sect))


# ------------------------------------------------------- 变体 B（结构故意不同）
# 目的：证明引擎不是只对一份文件调参。B 与 A 有四处结构差异：
#   1. 评分表 5 列（A 是 3 列）—— 走 len(header) >= 5 的明细分支
#   2. 计分点用「1. 2. 3.」阿拉伯枚举（A 用 ①②③）
#   3. 总分 70（A 是 100）—— 验证非百分制文件不会被误判
#   4. 表头写「评审因素 / 标准分 / 评分细则」（A 写「评分因素 / 分值 / 评分标准」）
SCORE_B = [
    ['序号', '评审因素', '标准分', '评分细则', '备注'],
    ['1', '投标报价', '30',
     '满足要求且报价最低者为基准价，得分＝（基准价／投标报价）×30。售价超控制价者无效。', ''],
    ['2', '实施方案', '10',
     '实施方案：1.预制率不低于七成，得4分；2.部品清单完整，得3分；3.工序图清晰，得3分。', ''],
    ['3', '安装方案', '8',
     '安装方案：1.基础处理措施，得4分；2.吊装方案有计算书，得4分。', ''],
    ['4', '售后与运维', '10',
     '售后与运维：1.质保两年，得5分；2.响应时间两小时，得3分；3.驻点承诺，得2分。', ''],
    ['5', '质量措施', '6',
     '质量措施：1.检验标准，得3分；2.责任分工，得3分。', ''],
    ['6', '类似业绩', '6',
     '近三年同类业绩每项得2分，最高6分，须附合同关键页。', ''],
]


def _build_variant_b():
    b = []
    add = b.append
    add(para('示例市 B 片区智慧驿站采购项目', 32, True, 'center', 0))
    add(para('招标文件', 28, True, 'center', 0))
    add(para('项目编号：SAMPLE-2026-002', 22, False, 'center', 0))
    add(para('（合成测试样本·结构与样本 A 不同，用于验证引擎泛化能力）',
             18, False, 'center', 0))

    add(para('第一章  项目概况', 26, True, indent=0))
    add(para('1.1 项目名称：示例市 B 片区智慧驿站采购项目。'))
    add(para('1.2 采购人：示例市市政设施管理处（虚构单位）。'))
    add(para('1.3 采购数量：智慧驿站 4 座，含土建基础与设备集成。'))
    add(para('1.4 项目控制金额：人民币贰佰叁拾万元整（￥2,300,000.00）。'
             '投标报价高于控制金额的，按无效投标处理。'))
    add(para('1.5 工期：合同签订后 45 日历日内完成交付，工期不可负偏离。'))
    add(para('1.6 投标文件递交截止时间：2026 年 12 月 05 日 14:00。'
             '逾期送达或未按要求密封的投标文件不予受理。'))

    add(para('第二章  资格条件', 26, True, indent=0))
    add(para('2.1 投标人须具有建筑工程施工总承包三级及以上资质，提供资质证书扫描件。'))
    add(para('2.2 提供有效的安全生产许可证。'))
    add(para('2.3 项目负责人须具有二级及以上注册建造师执业资格，'
             '并提供近三个月社保缴纳证明。'))
    add(para('2.4 未提供上述资格证明文件或证书不在有效期内的，按无效投标处理。'))

    add(para('第三章  投标须知', 26, True, indent=0))
    add(para('3.1 投标有效期：自投标截止之日起 60 日历日，不足者视为无效投标。'))
    add(para('3.2 投标保证金：人民币肆万元整（￥40,000.00），'
             '须从投标人基本账户转出，未缴纳者不予受理。'))
    add(para('3.3 投标文件须胶装成册、逐页编制页码，活页装订的按无效投标处理。'))
    add(para('3.4 投标文件须加盖公章并由法定代表人签字。'
             '委托代理人签字的，须附授权委托书原件，否则按无效投标处理。'))
    add(para('3.5 投标人须自行踏勘现场，未踏勘导致的方案偏差由投标人自负。'))
    add(para('3.6 中标人须在收到中标通知书后 15 日内签订合同，逾期取消中标资格。'))

    add(para('第四章  评审办法', 26, True, indent=0))
    add(para('4.1 本项目采用综合评分法，总分 70 分。'))
    add(para('4.2 评审因素及分值如下表。'))
    add(table(SCORE_B, [700, 2400, 1000, 4200, 900]))
    add(para('4.3 评标委员会发现投标文件未实质响应评审因素的，有权否决其投标。'))
    add(para('4.4 投标报价明显低于成本的，评标委员会有权要求书面说明，'
             '不能证明合理性的按无效投标处理。'))

    add(para('第五章  技术规格', 26, True, indent=0))
    add(para('5.1 单座驿站建筑面积不小于 9 平方米，含自助服务区与设备间。'))
    add(para('5.2 主体为装配式钢结构，构件均为工厂预制，现场螺栓连接。'))
    add(para('5.3 ★ 钢结构构件须提供材质证明书与焊缝探伤报告，缺一按无效投标处理。'))
    add(para('5.4 屋面系统防水等级不低于Ⅱ级。'))
    add(para('5.5 配置智能门禁与环境监测终端，接口协议须开放。'))
    add(para('5.6 ★ 投标产品须提供整体性能检测报告，报告在有效期内。'))

    add(para('第六章  商务条款', 26, True, indent=0))
    add(para('6.1 质保期不少于 2 年，低于 2 年的按无效投标处理。'))
    add(para('6.2 质保期内接到故障通知后 2 小时响应、24 小时到场。'))
    add(para('6.3 中标人须在本地设有服务网点或承诺中标后 20 日内设立。'))
    add(para('6.4 付款方式：验收合格后支付 95%，质保期满支付 5%。'))
    add(para('6.5 因中标人原因延误工期的，每日按合同金额 1‰ 计违约金，上限 5%。'))

    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1440" w:right="1134" w:bottom="1440" w:left="1134" '
            'w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document %s><w:body>%s%s</w:body></w:document>'
            % (NS, ''.join(b), sect))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    out_dir = os.path.join(root, 'data', 'sample')
    os.makedirs(out_dir, exist_ok=True)
    made = []
    for variant, fname in (('a', 'sample_bid.docx'), ('b', 'sample_bid_b.docx')):
        out = os.path.join(out_dir, fname)
        tmp = out + '.part'
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(zipfile.ZipInfo('[Content_Types].xml', (2026, 1, 1, 0, 0, 0)), CT)
            z.writestr(zipfile.ZipInfo('_rels/.rels', (2026, 1, 1, 0, 0, 0)), RELS)
            z.writestr(zipfile.ZipInfo('word/styles.xml', (2026, 1, 1, 0, 0, 0)), STYLES)
            z.writestr(zipfile.ZipInfo('word/document.xml', (2026, 1, 1, 0, 0, 0)), build_body(variant))
        os.replace(tmp, out)
        made.append((fname, os.path.getsize(out)))
    for fname, size in made:
        print('已生成: data/sample/%s (%d 字节)' % (fname, size))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
