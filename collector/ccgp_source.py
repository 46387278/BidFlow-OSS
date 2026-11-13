# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""中国政府采购网公开检索和公告解析。"""
import datetime
import re
import time
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

BASE = 'http://search.ccgp.gov.cn/bxsearch'
MIN_GAP = 90          # 秒；两次请求最小间隔，低于此值实测必被封
MAX_REQ = 6           # 单次跑批最多请求数（含分页），超额直接停手

# 标题里出现即算对口（用于二次过滤，防止「公厕保洁服务」这类非工程标的混进来）
BUILD_KW = ('新建', '改建', '改造', '建设', '采购', '购置', '提升', '增设', '装配式', '驿站')
SERVICE_KW = ('保洁', '清运', '管养', '运维', '劳务', '物业', '粪便处理', '服务')

_last = [0.0]


class Blocked(RuntimeError):
    """IP 已被 ccgp 限流。"""


def search_url(kw, page=1, days=7):
    end = time.localtime()
    start = time.localtime(time.time() - days * 86400)
    q = {
        'searchtype': '1', 'page_index': str(page), 'bidSort': '0',
        'buyerName': '', 'projectId': '', 'pinMu': '0', 'bidType': '0',
        'dbselect': 'bidx', 'kw': kw,
        'start_time': time.strftime('%Y:%m:%d', start),
        'end_time': time.strftime('%Y:%m:%d', end),
        'timeType': '6', 'displayZone': '', 'zoneId': '', 'pppStatus': '0',
        'agentName': '',
    }
    return BASE + '?' + urllib.parse.urlencode(q)


def _fetch(url, timeout=30):
    gap = _last[0] + MIN_GAP - time.time()
    if gap > 0:
        time.sleep(gap)
    _last[0] = time.time()
    op = urllib.request.build_opener()
    hdrs = {'User-Agent': UA, 'Referer': 'http://www.ccgp.gov.cn/',
            'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9'}
    body = op.open(urllib.request.Request(url, headers=hdrs), timeout=timeout) \
             .read().decode('utf-8', 'ignore')
    if '访问过于频繁' in body or '频繁访问' in body:
        raise Blocked('ccgp 限流：访问过于频繁')
    if len(body) < 8000:
        raise Blocked('ccgp 返回异常短页（%d 字节），按限流处理' % len(body))
    return body


def _strip(s):
    s = re.sub(r'<font[^>]*>|</font>', '', s or '')
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace('&nbsp;', ' ').replace('\u200d', '').replace('&amp;', '&')
    return re.sub(r'\s+', ' ', s).strip()


def _province_of(span_text):
    m = re.search(r'\|\s*([\u4e00-\u9fa5]{2,8})\s*(?:\||<|$)', span_text)
    return m.group(1) if m else ''


def parse(html, kw=''):
    """把搜索页解析成条目列表。改版时只需要调这一个函数。"""
    out = []
    # 条目块：<li> <a href="...">title</a> <p>摘要</p> <span>时间|采购人|代理|<strong>类型</strong>|省份</span>
    blocks = re.split(r'</li>', html)
    for blk in blocks:
        m = re.search(r'<a[^>]+href="(https?://www\.ccgp\.gov\.cn/cggg/[^"]+)"[^>]*>(.*?)</a>', blk, re.S)
        if not m:
            continue
        url, title = m.group(1), _strip(m.group(2))
        if not title:
            continue
        desc = ''
        pm = re.search(r'</a>\s*<p[^>]*>(.*?)</p>', blk, re.S)
        if pm:
            desc = _strip(pm.group(1))
        span = ''
        sm = re.search(r'<span>(.*?)</span>', blk, re.S)
        if sm:
            span = sm.group(1)
        pub = ''
        tm = re.search(r'(20\d{2})\.(\d{1,2})\.(\d{1,2})', span)
        if tm:
            pub = '%s-%02d-%02d' % (tm.group(1), int(tm.group(2)), int(tm.group(3)))
        owner = ''
        om = re.search(r'采购人[：:]\s*([^|<]+)', span)
        if om:
            owner = _strip(om.group(1))
        agent = ''
        am = re.search(r'代理机构[：:]\s*([^|<]+)', span)
        if am:
            agent = _strip(am.group(1))
        ntype = ''
        nm = re.search(r'<strong[^>]*>\s*([^<]{2,12})\s*</strong>', span)
        if nm:
            ntype = _strip(nm.group(1))
        area = ''
        am2 = re.findall(r'\|\s*([\u4e00-\u9fa5]{2,8})\s*(?=<\||<br|\s*\||$)', _strip(span))
        if am2:
            area = am2[0]
        out.append({
            'kw': kw, 'url': url, 'title': title, 'desc': desc,
            'pub': pub, 'owner': owner, 'agent': agent,
            'notice_type': ntype, 'area': area, 'span': _strip(span),
        })
    # 去重（同一公告可能被多个关键词命中）
    seen, uniq = set(), []
    for x in out:
        if x['url'] in seen:
            continue
        seen.add(x['url'])
        uniq.append(x)
    return uniq


def classify(title):
    """返回 (stage, relevant)。

    对口判定顺序很关键（2026-11-09 修）：
    先看有没有工程/设备动作词（建设、改造、购置、装配式…），有就是对口；
    没有才看服务词（保洁、清运、管养…），命中即判服务类。
    早先版本把「采购」放进对口词，结果「公厕保洁服务的采购公告」被误判成对口标的——
    这类标的是每年几十万的劳务合同，跟装配式设备生意无关。
    """
    t = title or ''
    if any(k in t for k in ('中标', '成交', '结果')):
        stage = '结果公告'
    elif any(k in t for k in ('废标', '流标', '终止', '失败')):
        stage = '流标/废标公告'
    elif any(k in t for k in ('意向', '需求公示', '采购计划')):
        stage = '采购意向'
    elif any(k in t for k in ('变更', '更正', '澄清', '答疑')):
        stage = '变更/澄清公告'
    else:
        stage = '招标公告'
    hard = ('新建', '改建', '改造', '建设', '购置', '提升', '增设', '装配式',
            '驿站', '采购项目', '设备采购', '材料采购')
    if any(k in t for k in hard):
        relevant = True
    elif any(k in t for k in SERVICE_KW):
        relevant = False
    elif '采购' in t:
        relevant = True
    else:
        relevant = True
    return stage, relevant


def parse_dl(text):
    """从摘要里提递交/开标截止日期。

    ccgp 摘要的写法是「并于2026-11-20 13:30（北京时间）前提交响应文件」，
    标签剥离后常粘成「2026-11-2013:30」，所以日期正则只认到日，时分不取。
    """
    t = (text or '').replace('\u200d', '')
    pats = [
        r'(?:于|至)\s*(20\d\d)[-年./](\d{1,2})[-月./](\d{1,2})\s*日?[^。；]{0,12}?前',
        r'(?:递交|提交|响应|投标|开标)[^。；]{0,14}?(20\d\d)[-年./](\d{1,2})[-月./](\d{1,2})',
        r'截止[^0-9]{0,10}(20\d\d)[-年./](\d{1,2})[-月./](\d{1,2})',
    ]
    for p in pats:
        m = re.search(p, t)
        if m:
            y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return '%s-%02d-%02d' % (y, mo, d)
    return ''


def fetch(keywords=('公厕',), days=7, pages=1, on_item=None, log=print):
    """按关键词串行检索。返回统计与条目。

    任何一次请求被判定限流，立即停手（不再重试，越试封越久）。
    """
    req = 0
    items, errs = [], []
    prev_month = None
    for kw in keywords:
        for p in range(1, pages + 1):
            if req >= MAX_REQ:
                log('已达单次请求上限 %d，停止' % MAX_REQ)
                return items, errs, req
            try:
                html = _fetch(search_url(kw, p, days))
                req += 1
            except Blocked as e:
                errs.append('%s p%d: %s' % (kw, p, e))
                log('限流，停止请求：%s' % e)
                return items, errs, req
            except Exception as e:
                errs.append('%s p%d: %s' % (kw, p, str(e)[:60]))
                req += 1
                continue
            got = parse(html, kw)
            log('  %s 第%d页 → %d 条' % (kw, p, len(got)))
            if not got:
                break
            for x in got:
                items.append(x)
            if on_item:
                for x in got:
                    on_item(x)
    return items, errs, req


if __name__ == '__main__':
    import sys
    kws = sys.argv[1:] or ['公厕']
    its, errs, n = fetch(keywords=kws, days=7, pages=1)
    print('请求 %d 次，条目 %d，错误 %s' % (n, len(its), errs))
    for x in its[:20]:
        st, rel = classify(x['title'])
        print('[%s]%s %s | %s | %s' % (x['area'], st, x['pub'], x['owner'][:12], x['title'][:50]))
