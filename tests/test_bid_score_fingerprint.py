# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from core.bid_engine import find_scoring


def main():
    fixture = Path(__file__).with_name('fixtures') / 'bid_score_01.json'
    table = json.loads(fixture.read_text(encoding='utf-8'))
    result = find_scoring({'tables': [table]})
    items = result['items']
    observed = (len(items), sum(item['weight'] for item in items),
                [item.get('locator') for item in items])
    expected = (2, 100.0, ['表0·行2', '表0·行3'])
    passed = observed == expected
    print('[%s] BID-SCORE-01 expected=%r observed=%r' %
          ('PASS' if passed else 'FAIL', expected, observed))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
