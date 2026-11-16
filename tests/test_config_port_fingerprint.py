# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request


def check_start(launcher_only=False):
    test_id = 'WIN-START-01' if launcher_only else 'CONFIG-PORT-01'
    if os.name != 'nt':
        print('[SKIP] %s: requires Windows cmd.exe' % test_id)
        return

    source = Path(__file__).resolve().parents[1]
    system32 = Path(os.environ['SystemRoot']) / 'System32'
    comspec = str(system32 / 'cmd.exe')
    env = dict(os.environ, BIDFLOW_NONINTERACTIVE='1', COMSPEC=comspec)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    with tempfile.TemporaryDirectory(prefix='bidflow-fingerprint-') as temporary:
        work = Path(temporary)
        for directory in ('config', 'src'):
            shutil.copytree(source / directory, work / directory)
        shutil.copy2(source / 'start.bat', work)
        if launcher_only:
            launcher = shutil.which('py.exe')
            assert launcher, 'Windows Python launcher py.exe is required'
            shutil.copy2(launcher, work / 'py.exe')
            env['PATH'] = os.pathsep.join((str(work), str(system32)))
            assert not shutil.which('python.exe', path=env['PATH'])

        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        (work / 'config' / 'config.json').write_text(
            json.dumps({'port': port}), encoding='utf-8')

        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen([comspec, '/d', '/c', 'start.bat'],
                                       cwd=work, env=env, stdout=output,
                                       stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        with opener.open('http://127.0.0.1:%d/api/health' % port,
                                         timeout=1) as response:
                            assert response.status == 200
                            print('[PASS] %s: HTTP %d at configured port %d' %
                                  (test_id, response.status, port))
                            return
                    except OSError:
                        time.sleep(0.25)
                output.seek(0)
                raise AssertionError('%s: port=%d, process status=%r, output=%s' %
                                     (test_id, port, process.poll(),
                                      output.read().decode('gbk', errors='replace')))
            finally:
                if process.poll() is None:
                    subprocess.run([str(system32 / 'taskkill.exe'), '/PID',
                                    str(process.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=10)
                    process.wait(timeout=10)


if __name__ == '__main__':
    check_start()
