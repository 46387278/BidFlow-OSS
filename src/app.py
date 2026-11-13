# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
投标工作台 · 服务端（单文件，零第三方依赖）

三个稳定输出：
  1. 需求雷达项目表   POST /api/radar
  2. 标书拆解四件套   POST /api/split   （红线档 / 方案骨架 / 要求台账 / 评分表 JSON）
  3. 技术方案初稿     POST /api/draft   （带 S 编号的 DOCX）

设计原则：
  · 零第三方依赖 —— 客户机器只需 Python 3.8+，不装任何包；
  · 数据不出门 —— 文件只落在本机 store/，不调用任何外部 API；
  · 同输入同输出 —— 全部是规则引擎，无模型参与；
  · 任务全留痕 —— jobs 表记每次输入指纹与产物，可回查。
"""
import os, sys, io, csv, json, sqlite3, time, uuid, datetime, shutil, subprocess, threading, platform
import urllib.parse, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

APP_VER = '1.1.1'
ROOT = os.path.dirname(os.path.abspath(__file__))      # src/
PKG = os.path.dirname(ROOT)                            # 包根目录
CORE = os.path.join(ROOT, 'core')
WEB = os.path.join(ROOT, 'web')
sys.path.insert(0, CORE)


def load_config():
    """读 config/config.json；没有就用默认值。缺项逐项回落，不整体失败。"""
    cfg = {'host': '127.0.0.1', 'port': 8080, 'data_dir': 'data',
           'store_dir': 'output', 'pdf_default': True}
    for name in ('config.json', 'config.example.json'):
        p = os.path.join(PKG, 'config', name)
        if os.path.isfile(p):
            try:
                cfg.update(json.load(open(p, encoding='utf-8')))
                break
            except Exception as e:
                print(f'[警告] 配置文件 {p} 读取失败，改用默认值：{e}')
    for k in ('data_dir', 'store_dir'):
        if not os.path.isabs(cfg[k]):
            cfg[k] = os.path.join(PKG, cfg[k])
    return cfg


CFG = load_config()
DATA = CFG['data_dir']
STORE = CFG['store_dir']
os.makedirs(DATA, exist_ok=True)
os.makedirs(STORE, exist_ok=True)


def data_file(name, fallback_name):
    """找数据文件：优先正式名，找不到退到示例名。

    为什么要有这一步：开源包里只带 *.example.* 文件（完整库是商业内容）。
    如果这里直接拼路径，开源版一跑雷达就 500 —— 而客户看到的应该是一句
    「当前用的是示例库，只有 6 条数据」，不是一个 Internal Server Error。
    """
    p = os.path.join(DATA, name)
    if os.path.isfile(p):
        return p
    alt = os.path.join(DATA, fallback_name)
    return alt if os.path.isfile(alt) else p


def blocks_file():
    return data_file('blocks.md', 'blocks.example.md')


def radar_file():
    return data_file('requirements.csv', 'requirements.example.csv')


def using_example(name):
    return not os.path.isfile(os.path.join(DATA, name))

import bid_engine as BE
import redline_engine as RE
import plan_engine as PE
import pipeline as PL
import writer as WR
import radar as RD

DB = os.path.join(STORE, 'jobs.db')
MAX_BODY = 80 * 1024 * 1024
_lock = threading.Lock()

def put(path, data):
    """产物原子写入：文本或字节都先落 .part，成功后原地替换；失败保留旧文件。"""
    if isinstance(data, str):
        data = data.encode('utf-8')
    tmp = path + '.part'
    try:
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path


CHROME_CANDIDATES = [
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
]


# ---------------- 任务台账 ----------------
def db():
    conn = sqlite3.connect(DB, timeout=20)
    conn.execute('''CREATE TABLE IF NOT EXISTS jobs(
        id TEXT PRIMARY KEY, kind TEXT, name TEXT, created TEXT,
        status TEXT, summary TEXT, outdir TEXT, ms INTEGER)''')
    return conn


def job_new(kind, name):
    jid = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:4]
    d = os.path.join(STORE, jid)
    os.makedirs(d, exist_ok=True)
    with _lock, db() as c:
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',
                  (jid, kind, name, datetime.datetime.now().isoformat(timespec='seconds'),
                   'running', '', d, 0))
    return jid, d


def job_done(jid, status, summary, ms):
    with _lock, db() as c:
        c.execute('UPDATE jobs SET status=?, summary=?, ms=? WHERE id=?',
                  (status, json.dumps(summary, ensure_ascii=False), ms, jid))


def job_get(jid):
    with db() as c:
        r = c.execute('SELECT id,kind,name,created,status,summary,outdir,ms FROM jobs WHERE id=?', (jid,)).fetchone()
    if not r:
        return None
    return {'id': r[0], 'kind': r[1], 'name': r[2], 'created': r[3],
            'status': r[4], 'summary': json.loads(r[5] or '{}'), 'outdir': r[6], 'ms': r[7]}


def job_list(n=30):
    with db() as c:
        rows = c.execute('SELECT id,kind,name,created,status,summary,outdir,ms FROM jobs ORDER BY created DESC LIMIT ?', (n,)).fetchall()
    return [{'id': r[0], 'kind': r[1], 'name': r[2], 'created': r[3], 'status': r[4],
             'summary': json.loads(r[5] or '{}'), 'ms': r[7]} for r in rows]


# ---------------- PDF（有 Chrome 就转，没有就只给 HTML）----------------
def chrome():
    for p in CHROME_CANDIDATES:
        if os.path.isfile(p):
            return p
    return shutil.which('google-chrome') or shutil.which('chromium')


def to_pdf(html_path):
    exe = chrome()
    if not exe:
        return None
    pdf = os.path.splitext(html_path)[0] + '.pdf'
    try:
        subprocess.run([exe, '--headless=new', '--disable-gpu', '--no-pdf-header-footer',
                        f'--print-to-pdf={pdf}', 'file:///' + html_path.replace('\\', '/')],
                       timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return pdf if os.path.isfile(pdf) and os.path.getsize(pdf) > 1000 else None
    except Exception:
        return None


# ---------------- 三个能力 ----------------
def run_split(docx_path, outdir, want_pdf=False):
    t0 = time.time()
    scoring = BE.build(docx_path)
    sc_json = os.path.join(outdir, 'scoring.json')
    put(sc_json, json.dumps(scoring, ensure_ascii=False, indent=1))

    paras = BE.load_doc(docx_path)['paras']

    # 1 红线档
    rl_rows = RE.dedup(RE.hits(paras))
    rl_html = os.path.join(outdir, '1-废标红线档.html')
    import hashlib
    fp = hashlib.sha256(open(docx_path, 'rb').read()).hexdigest()[:16]
    put(rl_html, RE.render(os.path.basename(docx_path), rl_rows, fp))

    # 2 方案骨架
    m = PE.build(sc_json)
    pl_html = os.path.join(outdir, '2-方案写作骨架.html')
    put(pl_html, PE.render(m))

    # 3 要求台账
    rows, m2 = PL.build(docx_path, sc_json, None)
    by = PL.stats(rows)
    lg_html = os.path.join(outdir, '3-要求台账.html')
    put(lg_html, PL.render(os.path.basename(docx_path), rows, m2, by, fp))
    import csv
    lg_csv = os.path.join(outdir, '3-要求台账.csv')
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['编号', '类别', '要求内容', '出处', '类型', '责任', '状态', '证据位置', '备注'])
    for r in rows:
        w.writerow([r['id'], r['cat'], r['text'], r['src'], r['type'], r['owner'], r['state'], '', ''])
    put(lg_csv, '\ufeff' + buf.getvalue())

    files = [rl_html, pl_html, lg_html, lg_csv, sc_json]
    if want_pdf:
        for h in (rl_html, pl_html, lg_html):
            p = to_pdf(h)
            if p:
                files.append(p)

    summary = {
        '段落数': len(paras),
        '评分项': scoring['scoring']['checks']['item_count'],
        '分值合计': scoring['scoring']['checks']['weight_sum'],
        '红线': len(rl_rows),
        '要求总数': len(rows),
        'AI承担': sum(1 for r in rows if r['owner'] == 'AI'),
        '人承担': sum(1 for r in rows if r['owner'] == '人'),
        '计分点': sum(len(i['sections']) for i in m['buckets']['方案']),
        '指纹': scoring['result_sha256'][:16],
        '环境': {'python': platform.python_version(), 'os': platform.platform(),
                'engine': scoring['engine']},
        '耗时ms': int((time.time() - t0) * 1000),
    }
    return files, summary, rows


def run_draft(job_id, meta):
    j = job_get(job_id)
    if not j:
        raise ValueError('任务不存在')
    sc = os.path.join(j['outdir'], 'scoring.json')
    if not os.path.isfile(sc):
        raise ValueError('该任务没有评分表，请先拆标')
    return WR.make_draft(sc, j['outdir'], '4-初稿', blocks_file(), meta)


def run_radar(region='', days=0, minamt=0):
    t0 = time.time()
    jid, d = job_new('radar', f'雷达 {region or "全库"} {days or "全部"}天')
    m = RD.scan(radar_file(), region, int(days or 0), float(minamt or 0))
    h = os.path.join(d, '需求雷达项目表.html')
    put(h, RD.render_html(m))
    c = RD.write_csv(m, os.path.join(d, '需求雷达项目表.csv'))
    p = to_pdf(h)
    files = [h, c] + ([p] if p else [])
    summary = {'库内总量': m['n'], '命中': len(m['rows']), '可行动': len(m['act']),
               '观察': len(m['watch']), '不跟': len(m['dead']),
               '耗时ms': int((time.time() - t0) * 1000)}
    if using_example('requirements.csv'):
        # 示例库的日期是写死的，过几个月全部超出新鲜度窗口，分档会逐渐归零。
        # 不说这一句，客户会以为系统坏了。
        summary['数据来源'] = '示例库（%d 条合成数据，日期固定，非真实项目）' % m['n']
    job_done(jid, 'done', summary, summary['耗时ms'])
    return jid, d, files, summary


# ---------------- HTTP ----------------
class H(BaseHTTPRequestHandler):
    server_version = 'BidFlow/' + APP_VER

    def log_message(self, fmt, *a):
        sys.stderr.write('[%s] %s\n' % (self.log_date_time_string(), fmt % a))

    # -- 工具 --
    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _bytes(self, b, ctype, name=None):
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        if name:
            self.send_header('Content-Disposition', "inline; filename*=UTF-8''" + urllib.parse.quote(name))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY:
            raise ValueError('文件超过 80MB 限制')
        return self.rfile.read(n) if n else b''

    def _file(self, path):
        if not os.path.isfile(path):
            return self._json({'ok': False, 'error': '文件不存在'}, 404)
        ext = os.path.splitext(path)[1].lower()
        ct = {'.html': 'text/html; charset=utf-8', '.csv': 'text/csv; charset=utf-8',
              '.json': 'application/json; charset=utf-8', '.pdf': 'application/pdf',
              '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
              '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8'}.get(ext, 'application/octet-stream')
        self._bytes(open(path, 'rb').read(), ct, os.path.basename(path))

    def _safe(self, *parts):
        """防路径穿越：只允许 store 下已登记任务的产物。"""
        base = os.path.realpath(STORE)
        p = os.path.realpath(os.path.join(base, *parts))
        return p if p.startswith(base + os.sep) else None

    # -- 路由 --
    def do_GET(self):
        # 浏览器/客户端会把中文文件名百分号编码，这里必须先还原，否则产物一律 404
        u = urllib.parse.urlparse(urllib.parse.unquote(self.path))
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ('/', '/index.html'):
                return self._file(os.path.join(WEB, 'index.html'))
            if u.path == '/api/health':
                return self._json({'ok': True, 'ver': APP_VER,
                                   'pdf': bool(chrome()),
                                   'data': os.path.isfile(radar_file()),
                                   'example_data': using_example('requirements.csv')})
            if u.path == '/api/jobs':
                return self._json({'ok': True, 'jobs': job_list()})
            if u.path.startswith('/files/'):
                rest = u.path[len('/files/'):].split('/')
                if len(rest) != 2:
                    return self._json({'ok': False, 'error': '路径不合法'}, 400)
                p = self._safe(rest[0], rest[1])
                if not p:
                    return self._json({'ok': False, 'error': '路径不合法'}, 400)
                return self._file(p)
            if u.path.startswith('/store/'):
                rest = u.path[len('/store/'):].split('/')
                p = self._safe(*rest)
                if not p:
                    return self._json({'ok': False, 'error': '路径不合法'}, 400)
                return self._file(p)
            return self._json({'ok': False, 'error': 'not found'}, 404)
        except Exception:
            traceback.print_exc()
            return self._json({'ok': False, 'error': '服务器内部错误'}, 500)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == '/api/split':
                return self.api_split(q)
            if u.path == '/api/draft':
                return self.api_draft()
            if u.path == '/api/radar':
                return self.api_radar(q)
            return self._json({'ok': False, 'error': 'not found'}, 404)
        except Exception as e:
            traceback.print_exc()
            return self._json({'ok': False, 'error': str(e) or '服务器内部错误'}, 500)

    # -- 接口 --
    def api_split(self, q):
        raw = self._body()
        if len(raw) < 1000:
            return self._json({'ok': False, 'error': '未收到文件或文件过小'}, 400)
        fn = urllib.parse.unquote(self.headers.get('X-Filename') or 'source.docx')
        if not fn.lower().endswith(('.docx', '.doc')):
            return self._json({'ok': False, 'error': '只支持 .docx（.doc 请先另存为 docx）'}, 400)
        jid, d = job_new('split', fn)
        path = os.path.join(d, 'source.docx')
        open(path, 'wb').write(raw)
        try:
            files, summary, rows = run_split(path, d, want_pdf=(q.get('pdf', ['0'])[0] == '1'))
            job_done(jid, 'done', summary, summary['耗时ms'])
            return self._json({'ok': True, 'job': jid,
                               'files': [{'name': os.path.basename(f),
                                          'url': f'/files/{jid}/' + urllib.parse.quote(os.path.basename(f)),
                                          'size': os.path.getsize(f)} for f in files],
                               'summary': summary})
        except Exception as e:
            traceback.print_exc()
            job_done(jid, 'failed', {'error': str(e)}, 0)
            return self._json({'ok': False, 'error': '拆标失败：' + str(e), 'job': jid}, 500)

    def api_draft(self):
        body = json.loads(self._body() or b'{}')
        jid = body.get('job')
        r = run_draft(jid, {'项目名称': body.get('name', ''), '投标人': body.get('bidder', '')})
        return self._json({'ok': True, 'job': jid,
                           'files': [{'name': os.path.basename(r['docx']),
                                      'url': f'/files/{jid}/' + urllib.parse.quote(os.path.basename(r['docx'])),
                                      'size': os.path.getsize(r['docx'])}],
                           'summary': {'计分点': r['n_points'], '已生成': r['n_gen'],
                                       '待填': r['n_todo']},
                           'cover': r['cover']})

    def api_radar(self, q):
        region = q.get('region', [''])[0]
        days = q.get('days', ['0'])[0]
        minamt = q.get('minamt', ['0'])[0]
        jid, d, files, summary = run_radar(region, days, minamt)
        return self._json({'ok': True, 'job': jid,
                           'files': [{'name': os.path.basename(f),
                                      'url': f'/files/{jid}/' + urllib.parse.quote(os.path.basename(f)),
                                      'size': os.path.getsize(f)} for f in files],
                           'summary': summary})


def main():
    port = int(CFG.get('port') or 8080)
    host = CFG.get('host') or '127.0.0.1'
    for i, a in enumerate(sys.argv):
        if a == '--port' and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
        if a == '--host' and i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
    if host not in ('127.0.0.1', 'localhost'):
        raise SystemExit('开源单机版仅支持本机监听，请将 host 设置为 127.0.0.1。')
    os.makedirs(STORE, exist_ok=True)
    # 僵尸任务清理：上次进程被强杀时，running 状态会永久留在台账里，重启时标为 interrupted
    with db() as c:
        n = c.execute("UPDATE jobs SET status='interrupted', summary=? WHERE status='running'",
                      (json.dumps({'error': '进程中断，产物可能不完整'}, ensure_ascii=False),)).rowcount
    if n:
        print(f' 清理中断任务 {n} 个（状态置 interrupted）')
    db().close()
    try:
        srv = ThreadingHTTPServer((host, port), H)
    except OSError as e:
        # 客户机器上最常见：端口被别的软件占了，或端口落在需要权限的区间
        print('=' * 56)
        print(f'[错误] 端口 {port} 起不来：{e}')
        print('')
        print('  可能原因：')
        print(f'   1) 这个端口已经被别的程序占用（常见：OA 客户端、钉钉、旧版服务）')
        print(f'   2) {port} 是需要管理员权限的端口')
        print('')
        print('  怎么查谁占了：在该目录打开命令行，执行')
        print(f'       netstat -ano | findstr :{port}')
        print('  怎么换端口（二选一）：')
        print(f'       python src\\app.py --port 8088')
        print(f'       或改 config\\config.json 里的 "port": 8088')
        print('  换完地址就变成 http://127.0.0.1:8088/')
        print('=' * 56)
        try:
            input('按回车退出...')
        except Exception:
            pass
        sys.exit(2)
    print('=' * 56)
    print(f' 投标工作台  v{APP_VER}   零依赖 · 数据不出门')
    print(f' 地址   http://{host}:{port}/')
    print(f' 数据   {DATA}')
    print(f' 产物   {STORE}')
    print(f' PDF    {"可用" if chrome() else "未检测到 Chrome/Edge，仅出 HTML"}')
    print('=' * 56)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')


if __name__ == '__main__':
    main()
