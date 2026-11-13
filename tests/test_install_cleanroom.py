# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""
test_install_cleanroom.py —— 干净机器装机测试（A 测试）

和 test_split / test_draft / test_radar 的区别：
    那三个测「功能对不对」，本脚本测「换一台没装过的机器能不能起来」。
    它故意不复用当前工程目录的任何东西——每次从 zip 全新解压到一个空目录，
    再在这个目录里跑。这样 output/、config/config.json、jobs.db 这些
    「本机跑久了自然就有」的东西全部不存在，才能暴露真实装机问题。

覆盖 7 关：
    K1  展开 zip：文件数对不对、有没有顶层目录、干净目录里是否真的没有 output/
    K2  无 Python：start.bat 是否给人话报错并退出码 1（不卡死、不弹窗刷屏）
    K3  自检：self_check.bat 在干净目录跑，是否 ALL PASS 且退出码 0
    K4  启服务：端口能否起来、首页能否打开
    K5  拆标接口：POST 真招标文件，产物是否落盘
    K6  雷达接口：干净目录无 output/ 时是否自动建目录
    K7  写稿接口：POST 出 docx，是否可解压、S 编号是否连续

用法:
    python tests\test_install_cleanroom.py <zip路径>
    python tests\test_install_cleanroom.py            # 默认用包根目录同级 zip

退出码: 0 全过 / 1 有失败
"""
import os
import sys
import csv
import json
import time
import shutil
import socket
import zipfile
import tempfile
import subprocess
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
DEFAULT_ZIP = os.path.join(os.path.dirname(PKG), os.path.basename(PKG) + '.zip')
PORT = 8099
BASE = 'http://127.0.0.1:%d' % PORT

OK, FAIL = [], []
LOG = []


def rec(name, passed, detail=''):
    (OK if passed else FAIL).append(name)
    print('  [%s] %-34s %s' % ('PASS' if passed else 'FAIL', name, detail))
    LOG.append((name, passed, detail))


def decode_out(raw):
    """批处理按 GBK 写、按 GBK 输出（chcp 936）。先按 GBK 解，乱码再退回 UTF-8。"""
    s = raw.decode('gbk', 'replace')
    if '\ufffd' in s or '锟' in s:
        s2 = raw.decode('utf-8', 'replace')
        if s2.count('\ufffd') < s.count('\ufffd'):
            return s2
    return s


def run(cmd, cwd, env=None, timeout=180):
    e = os.environ.copy()
    if env is not None:
        e = env
    p = subprocess.run(cmd, cwd=cwd, env=e, stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    return p.returncode, decode_out(p.stdout)


def port_free(port):
    s = socket.socket()
    try:
        return s.connect_ex(('127.0.0.1', port)) != 0
    finally:
        s.close()


def _bat_encoding_ok(work):
    """批处理里若有中文，文件必须是 GBK；UTF-8 中文 bat 会被 cmd 按 ANSI 误读而崩坏。"""
    for name in ('start.bat', 'self_check.bat'):
        p = os.path.join(work, name)
        if not os.path.isfile(p):
            return False
        raw = open(p, 'rb').read()
        try:
            raw.decode('ascii')
            continue                     # 纯 ASCII 无所谓编码
        except Exception:
            pass
        try:
            raw.decode('gbk')
        except Exception:
            return False                 # 无法按 GBK 解 = 不是 GBK
    return True


def post_json(path, payload, timeout=120):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode('utf-8'))


def get(path, timeout=30):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.status, r.read()


def main():
    zpath = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ZIP
    print('=' * 64)
    print(' 安装测试 · 干净机器装机（每一关都在全新解压目录里跑）')
    print(' zip: %s' % zpath)
    print('=' * 64)
    if not os.path.isfile(zpath):
        print('[FATAL] zip 不存在：%s' % zpath)
        return 1

    sandbox = tempfile.mkdtemp(prefix='bidflow_clean_')
    # zip 自带一个顶层目录（BidFlow-OSS/ 或 BidFlow_v1.0/），解到 sandbox 后
    # 工作目录是 sandbox\<顶层目录名>。这里不写死名字，K1 里按实际顶层算。
    work = sandbox
    print('沙箱目录: %s\n' % sandbox)
    proc = None
    try:
        # ---------- K1 展开 ----------
        print('[K1] 展开 zip（模拟客户第一次解压）')
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()
            tops = sorted({n.split('/')[0] for n in names if n.strip('/')})
            # zipfile 不记录目录条目，判顶层只能看所有名字是否共享同一前缀
            has_topdir = len(tops) == 1 and tops[0] not in ('src', 'docs', 'config', 'data', 'tests')
            rec('zip 无坏文件', z.testzip() is None, '')
            z.extractall(sandbox)
        # 有顶层目录 → 工作目录是 sandbox\<顶层>；没有 → 就是 sandbox 本身
        work = os.path.join(sandbox, tops[0]) if has_topdir else sandbox
        files = sum(len(f) for _, _, f in os.walk(work))
        rec('文件数 ≥ 28', files >= 28, '实测 %d' % files)
        rec('zip 带顶层目录', has_topdir,
            '实测顶层=%s' % (tops[0] + '/' if has_topdir else tops))
        # 包里带 output/README.txt 占位（免得客户面对不存在的目录），但要确认没有跑过的痕迹
        outdir = os.path.join(work, 'output')
        dirty = []
        if os.path.isdir(outdir):
            dirty = [x for x in os.listdir(outdir) if x != 'README.txt']
        rec('干净目录无运行痕迹', not dirty, 'output 内非 README 项: %s' % dirty)
        rec('干净目录无 config.json', not os.path.exists(os.path.join(work, 'config', 'config.json')), '')
        rec('批处理为 GBK 编码', True if _bat_encoding_ok(work) else False,
            '' if _bat_encoding_ok(work) else 'UTF-8 中文 bat 会被 cmd 拆坏')

        # ---------- K2 无 Python ----------
        if os.name != 'nt':
            print('[SKIP] 后续安装测试需要 Windows cmd.exe')
            return 2
        print('\n[K2] 无 Python 时双击 start.bat')
        bare = {'PATH': r'C:\Windows\System32;C:\Windows', 'SystemRoot': r'C:\Windows',
                'TEMP': os.environ.get('TEMP', r'C:\Windows\Temp'),
                'USERPROFILE': os.environ.get('USERPROFILE', '')}
        rc, out = run(['cmd', '/c', 'start.bat'], work, env=bare, timeout=60)
        rec('退出码 = 1', rc == 1, '实测 %d' % rc)
        rec('提示里出现中文"错误"', '错误' in out, '')
        rec('提示里出现 python.org', 'python.org' in out, '')
        rec('提示里点明勾选 PATH', 'PATH' in out and ('勾选' in out or 'Add' in out), '')

        # ---------- K3 自检 ----------
        print('\n[K3] 干净目录跑 self_check.bat')
        rc, out = run(['cmd', '/c', 'self_check.bat'], work, timeout=300)
        rec('自检退出码 = 0', rc == 0, '实测 %d' % rc)
        rec('自检 ALL PASS', 'ALL PASS' in out,
            '' if 'ALL PASS' in out else [l for l in out.splitlines() if 'FAIL' in l][:3])
        rec('自检自动建出 output/', os.path.isdir(os.path.join(work, 'output')), '')

        # ---------- K4 起服务 ----------
        print('\n[K4] 启动服务')
        if not port_free(PORT):
            rec('端口 %d 空闲' % PORT, False, '被占用，换端口重跑')
            return 1
        env = os.environ.copy()
        proc = subprocess.Popen([sys.executable, os.path.join('src', 'app.py'), '--port', str(PORT)],
                                cwd=work, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        up = False
        for _ in range(40):
            time.sleep(0.5)
            if not port_free(PORT):
                up = True
                break
            if proc.poll() is not None:
                break
        rec('端口 %d 起来' % PORT, up, '')
        if not up:
            tail = (proc.stdout.read() or b'').decode('utf-8', 'replace')[-600:]
            print('    服务输出尾部:\n%s' % tail)
            return 1
        try:
            st, body = get('/')
            rec('首页 200', st == 200, '实测 %d，%d 字节' % (st, len(body)))
            rec('首页含界面标题', 'BidFlow' in body.decode('utf-8', 'replace') or '投标' in body.decode('utf-8', 'replace'), '')
        except Exception as e:
            rec('首页 200', False, repr(e))

        # ---------- K5 拆标 ----------
        print('\n[K5] 拆标接口（真招标文件，文件走 body）')
        sample = os.path.join(work, 'data', 'sample', 'sample_bid.docx')
        jid = None
        try:
            with open(sample, 'rb') as fh:
                raw = fh.read()
            req = urllib.request.Request(BASE + '/api/split', data=raw,
                                         headers={'X-Filename': 'sample_bid.docx',
                                                  'Content-Type': 'application/octet-stream'})
            with urllib.request.urlopen(req, timeout=180) as r:
                j = json.loads(r.read().decode('utf-8'))
            rec('拆标 ok', j.get('ok') is True, '')
            jid = j.get('job')
            s = j.get('summary') or {}
            rec('拆标出评分表', bool(s.get('分值合计') or s.get('评分项数')),
                '摘要=%s' % json.dumps(s, ensure_ascii=False)[:110])
            fl = j.get('files') or []
            rec('拆标产物 ≥3 个', len(fl) >= 3, '实测 %d' % len(fl))
            rec('产物全部存在', all(os.path.isfile(os.path.join(work, 'output', jid, f['name'])) for f in fl),
                '')
        except Exception as e:
            rec('拆标 ok', False, repr(e))

        # ---------- K6 雷达 ----------
        print('\n[K6] 雷达接口（query 参数）')
        try:
            req = urllib.request.Request(BASE + '/api/radar?region=&days=0&minamt=0',
                                         data=b'', method='POST')
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.loads(r.read().decode('utf-8'))
            rec('雷达 ok', j.get('ok') is True, '')
            s = j.get('summary') or {}
            rec('雷达有分档数', bool(s), '摘要=%s' % json.dumps(s, ensure_ascii=False)[:110])
            rec('雷达产物存在', all(os.path.isfile(os.path.join(work, 'output', j.get('job', ''), f['name']))
                                 for f in (j.get('files') or [])), '')
        except Exception as e:
            rec('雷达 ok', False, repr(e))

        # ---------- K7 写稿 ----------
        print('\n[K7] 写稿接口（依赖 K5 的 job）')
        if not jid:
            rec('写稿 ok', False, 'K5 未拿到 job，跳过')
        else:
            try:
                st, j = post_json('/api/draft', {'job': jid, 'name': '装机测试项目', 'bidder': '测试投标人'})
                rec('写稿 ok', j.get('ok') is True, '')
                fl = j.get('files') or []
                docx = [f for f in fl if f.get('name', '').endswith('.docx')]
                rec('产出 docx', bool(docx), str([f['name'] for f in fl]))
                if docx:
                    p = os.path.join(work, 'output', jid, docx[0]['name'])
                    z2 = zipfile.ZipFile(p)
                    xml = z2.read('word/document.xml').decode('utf-8', 'replace')
                    import re
                    sn = [int(x) for x in re.findall(r'S-(\d{3})', xml)]
                    uniq = sorted(set(sn))
                    rec('S 编号连续', bool(uniq) and uniq == list(range(1, len(uniq) + 1)),
                        '共 %d 节' % len(uniq))
                    s = j.get('summary') or {}
                    rec('写稿摘要齐全', all(k in s for k in ('计分点', '已生成', '待填')),
                        json.dumps(s, ensure_ascii=False))
            except Exception as e:
                rec('写稿 ok', False, repr(e))

        # ---------- K8 中文 + 空格路径 ----------
        print('\n[K8] 中文 + 空格路径（D:\\投标工作\\2026年\\BidFlow v1.0\\ 这类）')
        cn = os.path.join(sandbox, '投标工作', '2026年', 'BidFlow v1.0')
        try:
            shutil.copytree(work, cn)
            rcx, outx = run(['cmd', '/c', 'self_check.bat'], cn, timeout=300)
            rec('中文空格路径自检', rcx == 0 and 'ALL PASS' in outx,
                'rc=%d' % rcx)
        except Exception as e:
            rec('中文空格路径自检', False, repr(e))

        # ---------- K9 端口被占用 ----------
        print('\n[K9] 端口被别的程序占用')
        occupy = socket.socket()
        try:
            # 不写死 8080：测试机上 8080 常常正被真服务占着（比如开发者自己那套在跑），
            # 那样「占端口」这一步就先失败，报出来的红跟被测程序一点关系没有。
            # 向系统要一个空闲端口，再把它占住，测的才是「端口冲突」这件事本身。
            occupy.bind(('127.0.0.1', 0))
            busy = occupy.getsockname()[1]
            occupy.listen(1)
            p2 = subprocess.run([sys.executable, os.path.join('src', 'app.py'), '--port', str(busy)],
                                cwd=work, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=40)
            o2 = decode_out(p2.stdout)
            friendly = any(k in o2 for k in ('端口', '占用', '被占', '换一个'))
            rec('端口冲突给人话提示', p2.returncode != 0 and friendly,
                'rc=%d 尾部=%s' % (p2.returncode, o2.strip().splitlines()[-1][:90] if o2.strip() else ''))
        except subprocess.TimeoutExpired:
            rec('端口冲突给人话提示', False, '进程未退出（卡住）')
        except Exception as e:
            rec('端口冲突给人话提示', False, repr(e))
        finally:
            occupy.close()

        # ---------- K10 配置被手改坏 ----------
        print('\n[K10] config.json 被客户手改坏（起服务时应中文警告并回落默认值）')
        cfgp = os.path.join(work, 'config', 'config.json')
        try:
            open(cfgp, 'w', encoding='utf-8').write('{ 这不是合法 json ,,,')
            p4 = subprocess.Popen([sys.executable, '-u', os.path.join('src', 'app.py'), '--port', '8091'],
                                  cwd=work, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            time.sleep(4)
            alive = p4.poll() is None
            p4.terminate()
            try:
                raw4 = p4.communicate(timeout=10)[0]
            except Exception:
                p4.kill()
                raw4 = b''
            o4 = decode_out(raw4 or b'')
        except Exception as e:
            o4, alive = '', False
            rec('坏配置有中文警告', False, repr(e))
        finally:
            try:
                os.remove(cfgp)
            except Exception:
                pass
        rec('坏配置有中文警告', '警告' in o4, '首行=%s' % (o4.strip().splitlines()[0][:90] if o4.strip() else '无输出'))
        rec('坏配置仍能启动', alive and '地址' in o4, '进程存活=%s' % alive)

        # ---------- K11 Python 3.8 语法兼容 ----------
        print('\n[K11] Python 3.8 语法兼容（手册承诺 3.8+）')
        import ast
        bad = []
        for root, _, fs in os.walk(os.path.join(work, 'src')):
            for f in fs:
                if not f.endswith('.py'):
                    continue
                fp = os.path.join(root, f)
                try:
                    ast.parse(open(fp, encoding='utf-8').read(), filename=fp, feature_version=(3, 8))
                except SyntaxError as e:
                    bad.append('%s:%s' % (f, e.lineno))
        rec('全部源码符合 3.8 语法', not bad, '不符=%s' % bad[:4])

        # ---------- K12 并发三任务 ----------
        print('\n[K12] 并发（三个人同时拆标）')
        import threading
        results = []

        def _one(i):
            try:
                with open(sample, 'rb') as fh:
                    rq = urllib.request.Request(BASE + '/api/split', data=fh.read(),
                                                headers={'X-Filename': 'c%d.docx' % i,
                                                         'Content-Type': 'application/octet-stream'})
                with urllib.request.urlopen(rq, timeout=180) as r:
                    jj = json.loads(r.read().decode('utf-8'))
                results.append((jj.get('ok'), (jj.get('summary') or {}).get('红线')))
            except Exception as e:
                results.append((False, repr(e)))

        ts = [threading.Thread(target=_one, args=(i,)) for i in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        rec('3 个并发全部成功', len(results) == 3 and all(r[0] for r in results),
            '结果=%s' % results)
        rec('并发结果一致', len({str(r[1]) for r in results}) <= 1,
            '红线数=%s' % [r[1] for r in results])

        # ---------- K13 Windows 自带的假 python 别名 ----------
        print('\n[K13] Windows 自带假 python 别名（where 找得到、一执行就报错）')
        wa = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'WindowsApps')
        if not os.path.isdir(wa):
            rec('假别名不被误判为已装', True, '本机无 WindowsApps 目录，跳过（等价无 Python，K2 已覆盖）')
        else:
            env13 = {'PATH': r'C:\Windows\System32;C:\Windows;' + wa,
                     'SystemRoot': r'C:\Windows',
                     'TEMP': os.environ.get('TEMP', ''),
                     'USERPROFILE': os.environ.get('USERPROFILE', ''),
                     'LOCALAPPDATA': os.environ.get('LOCALAPPDATA', '')}
            rc13, o13 = run(['cmd', '/c', 'start.bat'], work, env=env13, timeout=90)
            rec('假别名不被误判为已装', rc13 == 1 and '没有可用的 Python' in o13,
                'rc=%d 首行=%s' % (rc13, o13.strip().splitlines()[0][:70] if o13.strip() else ''))
            rec('假别名场景给补救提示', 'WindowsApps' in o13, '')

    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()
        print('\n' + '=' * 64)
        print(' 结果：通过 %d 项，失败 %d 项' % (len(OK), len(FAIL)))
        if FAIL:
            for f in FAIL:
                print('   FAIL - %s' % f)
        else:
            print('  RESULT: ALL PASS' if os.name == 'nt' else '  RESULT: Windows 装机未执行')
        print('=' * 64)
        print('沙箱保留供排查: %s' % sandbox)
        try:
            open(os.path.join(sandbox, 'result.json'), 'w', encoding='utf-8').write(
                json.dumps([{'item': n, 'pass': p, 'detail': d} for n, p, d in LOG],
                           ensure_ascii=False, indent=1))
        except Exception:
            pass
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
