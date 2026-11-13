# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
极简 DOCX 生成器 —— 只用标准库（zipfile + 手写 OOXML），零依赖。

用途：把标书初稿写成客户能直接打开的 Word。
只支持四种块：h1 / h2 / h3 / p / note（提示块）。
"""
import zipfile, os

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

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def _run(text, size=21, bold=False, color=None, font='宋体'):
    rpr = f'<w:rPr><w:rFonts w:ascii="Times New Roman" w:eastAsia="{font}" w:hAnsi="Times New Roman"/>'
    if bold:
        rpr += '<w:b/>'
    if color:
        rpr += f'<w:color w:val="{color}"/>'
    rpr += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr>'
    return f'<w:r>{rpr}<w:t xml:space="preserve">{_esc(text)}</w:t></w:r>'


def _para(inner, align=None, indent=0, space_before=0, space_after=60, shade=None):
    ppr = '<w:pPr>'
    if align:
        ppr += f'<w:jc w:val="{align}"/>'
    if indent:
        ppr += f'<w:ind w:firstLine="{indent}"/>'
    if shade:
        ppr += f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>'
    ppr += f'<w:spacing w:before="{space_before}" w:after="{space_after}" w:line="360" w:lineRule="auto"/>'
    ppr += '</w:pPr>'
    return f'<w:p>{ppr}{inner}</w:p>'


def render(blocks, title=None):
    """blocks: [(kind, text)]，kind ∈ h1/h2/h3/p/note/pagebreak"""
    body = []
    if title:
        body.append(_para(_run(title, 32, True), align='center', space_after=240))
    for kind, text in blocks:
        if kind == 'h1':
            body.append(_para(_run(text, 30, True), space_before=240, space_after=120))
        elif kind == 'h2':
            body.append(_para(_run(text, 26, True), space_before=180, space_after=100))
        elif kind == 'h3':
            body.append(_para(_run(text, 23, True), space_before=120, space_after=80))
        elif kind == 'note':
            body.append(_para(_run(text, 19, False, 'A15C00', '仿宋'), shade='FDF6E3'))
        elif kind == 'pagebreak':
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        else:
            body.append(_para(_run(text, 21), indent=420))

    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1440" w:right="1134" w:bottom="1440" w:left="1134" '
            'w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>')
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document {NS}><w:body>{"".join(body)}{sect}</w:body></w:document>')
    return doc


def _zi(name):
    """固定时间戳 + 固定压缩方式的 zip 条目。

    为什么非要固定：zip 默认把「当前时间」写进每个条目，于是同样的内容
    每次生成出来的字节都不同，result_sha256 就跟着变。
    写成 1980-01-01（zip 纪元起点），同一输入才真的「同样的字节出」。
    """
    zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o600 << 16
    return zi


def write(blocks, path, title=None):
    """原子写入：先写 .part 临时文件，成功后原地替换。
    失败时保留旧文件不动，不会留下半份 docx 冒充成品。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.part'
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(_zi('[Content_Types].xml'), CT)
            z.writestr(_zi('_rels/.rels'), RELS)
            z.writestr(_zi('word/styles.xml'), STYLES)
            z.writestr(_zi('word/document.xml'), render(blocks, title))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path
