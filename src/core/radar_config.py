# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
import json
from pathlib import Path
import sys

CONFIG = Path(__file__).resolve().parents[2] / 'config'
NODES = ('预算立项', '采购意向', '招标公告', '招标结果公布')
STAGE_W_DEFAULT = dict(zip(NODES, (30, 25, 20, 5)))
DEFAULT_KEYWORDS = {'good': ['办公家具', '家具', '办公桌', '办公椅', '会议桌', '文件柜'], 'bad': ['维修', '保养', '租赁'], 'build': ['采购', '购置', '新建', '供货', '含安装', '配送'], 'service': ['维修', '保养', '租赁', '劳务', '物业'], 'good_weight': 15, 'stage_weights': {'预算立项': 30, '采购意向': 25, '招标公告': 20, '招标结果公布': 5}}
DEFAULT_SOURCES = {'sources': [{'name': 'ccgp', 'enabled': True, 'keywords': []}]}


def load_config(name, defaults, valid, hint):
    for suffix in ('.json', '.example.json'):
        try:
            raw = json.loads((CONFIG / (name + suffix)).read_text(encoding='utf-8-sig'))
            if not isinstance(raw, dict) or not valid(raw):
                continue
            if suffix == '.example.json':
                print(hint, file=sys.stderr)
            return {**defaults, **raw}
        except (OSError, ValueError):
            continue
    print(hint, file=sys.stderr)
    return defaults.copy()


def words(value):
    return isinstance(value, list) and all(isinstance(word, str) and word.strip()
                                           for word in value)


def valid_keywords(raw):
    stages = raw.get('stage_weights', {})
    return (all(words(raw.get(key, [])) for key in ('good', 'bad', 'build', 'service'))
            and type(raw.get('good_weight', 15)) is int
            and isinstance(stages, dict)
            and all(key in NODES and type(value) is int for key, value in stages.items()))


def keywords():
    values = load_config('keywords', DEFAULT_KEYWORDS, valid_keywords,
                         '未找到有效的 config/keywords.json，使用示例词表（办公家具）')
    values['stage_weights'] = {**STAGE_W_DEFAULT, **values['stage_weights']}
    return values


def valid_sources(raw):
    sources = raw.get('sources')
    return isinstance(sources, list) and all(
        isinstance(item, dict) and isinstance(item.get('name'), str)
        and type(item.get('enabled')) is bool and words(item.get('keywords', []))
        for item in sources)


def sources():
    return load_config('sources', DEFAULT_SOURCES, valid_sources,
                       '未找到有效的 config/sources.json，使用示例信源')['sources']
