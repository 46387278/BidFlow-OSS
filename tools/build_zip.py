#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
build_zip.py —— 打发布包

为什么不用「右键压缩」：
    1. 必须保证顶层只有一个目录（否则客户解压后文件散落一地）
    2. 必须排除运行痕迹（output/ 里的旧产物、config.json、jobs.db、__pycache__）
    3. 必须包含生成的样本 docx —— 仓库里 .gitignore 掉了它们，
       但发布包必须带，否则客户拿到包跑不了测试
    4. 打完要能报出 sha256，方便和客户核对

用法：
    python tools/make_sample_bid.py
    python tools/build_zip.py [输出路径]

退出码：0 成功 / 1 失败
"""
import os
import sys
import zipfile
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOP = os.path.basename(ROOT)

SKIP_DIRS = {'__pycache__', '.git', '.github', '.idea', '.vscode', 'issues', 'advisor_out'}
SKIP_FILES = {'config/config.json', 'output/jobs.db', 'requirements.txt.bak'}


def should_skip(rel, name):
    if name.endswith(('.pyc', '.pyo', '.part', '.log')):
        return True
    if rel in SKIP_FILES:
        return True
    # output/ 只留说明文件，别的都是跑出来的
    if rel.startswith('output/') and rel != 'output/README.txt':
        return True
    return False


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), TOP + '.zip')

    sample = os.path.join(ROOT, 'data', 'sample', 'sample_bid.docx')
    if not os.path.isfile(sample):
        print('[错误] 缺少样本。先执行：python tools/make_sample_bid.py')
        return 1

    if os.path.exists(out):
        os.remove(out)

    n, skipped = 0, []
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, ROOT).replace('\\', '/')
                if should_skip(rel, f):
                    skipped.append(rel)
                    continue
                z.write(full, TOP + '/' + rel)
                n += 1

    z = zipfile.ZipFile(out)
    bad = z.testzip()
    tops = sorted({x.split('/')[0] for x in z.namelist()})
    has_sample = any(x.endswith('sample_bid.docx') for x in z.namelist())
    has_bat = [x for x in z.namelist() if x.endswith('.bat')]
    z.close()

    size = os.path.getsize(out)
    sha = hashlib.sha256(open(out, 'rb').read()).hexdigest()

    print('输出      : %s' % out)
    print('文件数    : %d' % n)
    print('大小      : %.2f MB' % (size / 1048576))
    print('顶层      : %s（必须只有 1 个）' % tops)
    print('坏条目    : %s' % bad)
    print('含样本    : %s' % has_sample)
    print('含批处理  : %s' % has_bat)
    print('sha256    : %s' % sha)
    print('已排除    : %d 个（%s...）' % (len(skipped), ', '.join(skipped[:4])))

    ok = (bad is None and len(tops) == 1 and has_sample and len(has_bat) >= 2)
    if not ok:
        print('\n[失败] 包结构不符合要求，见上面几行')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
