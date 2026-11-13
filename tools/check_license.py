# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
check_license.py —— 许可证守卫

为什么需要这个脚本：
    Apache-2.0 要求再分发时保留版权与归属声明。但「保留」这件事
    靠人记是记不住的 —— fork 一次、复制一个文件、新建一个模块，
    头就丢了。这个脚本把它变成一条可执行的红线，CI 每次跑。

检查五件事：
    1. LICENSE 是 Apache-2.0 全文（不是一段摘要、不是占位符）
    2. NOTICE 存在，且含商标条款与归属声明
    3. 每个 .py 文件头有 SPDX 标识
    4. 版权主体与营业执照全称一字不差（COMPANY 常量）
    5. 仓库里没有残留的「许可证待定」类占位文件

用法：
    python tools/check_license.py

退出码：0 通过 / 1 不通过
"""
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SPDX = 'SPDX-License-Identifier: Apache-2.0'

# 版权主体必须与营业执照全称一字不差。
# 2026-10-19 项目主理人纠正过一次：我原先写的「有向空间 (XiangSpace)」是自造简称，
# 而「深圳市有向空间科技有限公司」这类写法是笔误。正确全称是下面这个。
# 这种错不该靠人记 —— 让脚本记，让 CI 拦。
COMPANY = '深圳有向空间设计工程有限公司'

LICENSE_MUST = [
    'Apache License',
    'Version 2.0, January 2004',
    'TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION',
    '6. Trademarks',
    'END OF TERMS AND CONDITIONS',
    'Copyright 2026 ' + COMPANY,
]
LICENSE_MIN_CHARS = 10000      # 官方全文 11358 字符，摘要版远小于此

NOTICE_MUST = ['BidFlow', '商标', 'Trademark', 'Copyright', COMPANY]

placeholder_names = ('LICENSE-决策待定', 'LICENSE-TBD', 'LICENSE-PENDING')


def read(path):
    with open(path, 'rb') as f:
        return f.read().decode('utf-8', 'replace')


def tracked_py():
    """优先问 git 要清单；不在 git 仓库里就退化为遍历。"""
    try:
        out = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True,
                             text=True, encoding='utf-8', timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            return [p for p in out.stdout.split() if p.endswith('.py')]
    except Exception:
        pass
    found = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git')]
        for f in files:
            if f.endswith('.py'):
                found.append(os.path.relpath(os.path.join(root, f), ROOT).replace('\\', '/'))
    return sorted(found)


def main():
    fails, warns = [], []

    # ---- 1. LICENSE ----
    lp = os.path.join(ROOT, 'LICENSE')
    if not os.path.isfile(lp):
        fails.append('缺少 LICENSE 文件')
    else:
        s = read(lp)
        for k in LICENSE_MUST:
            if k not in s:
                fails.append('LICENSE 缺少关键条款：%s' % k)
        if len(s) < LICENSE_MIN_CHARS:
            fails.append('LICENSE 只有 %d 字符，疑似摘要版而非全文（官方全文 11358）' % len(s))
        if 'Copyright 2026' not in s:
            warns.append('LICENSE 末尾没有版权行（建议保留，否则再分发时归属不明）')
        print('LICENSE  %d 字符  行数 %d' % (len(s), s.count('\n') + 1))

    # ---- 2. NOTICE ----
    np_ = os.path.join(ROOT, 'NOTICE')
    if not os.path.isfile(np_):
        fails.append('缺少 NOTICE 文件（Apache-2.0 第 4(d) 条要求随作品分发归属声明）')
    else:
        s = read(np_)
        for k in NOTICE_MUST:
            if k not in s:
                fails.append('NOTICE 缺少：%s' % k)
        print('NOTICE   %d 字符' % len(s))

    # ---- 3. 每个 .py 的 SPDX 头 + 版权主体 ----
    files = tracked_py()
    bad_spdx, bad_owner = [], []
    for p in files:
        full = os.path.join(ROOT, p)
        if not os.path.isfile(full):
            continue
        head = read(full)[:400]
        if SPDX not in head:
            bad_spdx.append(p)
        elif COMPANY not in head:
            bad_owner.append(p)
    print('Python   %d 个，缺 SPDX 头 %d 个，版权主体不符 %d 个'
          % (len(files), len(bad_spdx), len(bad_owner)))
    for p in bad_spdx:
        fails.append('缺 SPDX 头：%s' % p)
    for p in bad_owner:
        fails.append('版权主体不是「%s」：%s' % (COMPANY, p))

    # ---- 4. 占位文件 ----
    for root, dirs, fs in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git')]
        for f in fs:
            if any(f.startswith(x) for x in placeholder_names):
                fails.append('残留占位文件：%s（许可证已定，应删除）'
                             % os.path.relpath(os.path.join(root, f), ROOT))

    # ---- 结论 ----
    print('-' * 60)
    for w in warns:
        print('[提醒] ' + w)
    if fails:
        for f in fails:
            print('[失败] ' + f)
        print('结果：不通过（%d 项）' % len(fails))
        return 1
    print('结果：通过（LICENSE 全文 + NOTICE + %d 个 SPDX 头 + 版权主体一致）' % len(files))
    return 0


if __name__ == '__main__':
    sys.exit(main())
