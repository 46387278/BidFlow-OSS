# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""从本地需求表生成 HTML 和 CSV，采用与工作台相同的评分。"""
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from core.radar import render_html, scan, write_csv


def main():
    data = ROOT / 'data'
    source = data / 'requirements.csv'
    if not source.exists():
        print('需求库不存在。请先导入公告 JSONL。', file=sys.stderr)
        return 2
    result = scan(source)
    reports = data / 'reports'
    reports.mkdir(parents=True, exist_ok=True)
    output = reports / ('radar-' + date.today().isoformat())
    output.with_suffix('.html').write_text(render_html(result), encoding='utf-8')
    write_csv(result, output.with_suffix('.csv'))
    print('需求雷达：%d 条，HTML 和 CSV 已写入 %s' % (len(result['rows']), reports))
    return 0


if __name__ == '__main__':
    sys.exit(main())
