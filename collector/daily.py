# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""手动运行或交给 Windows 任务计划程序执行的公开公告采集入口。"""

import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keywords", nargs="*", default=["公厕"])
    parser.add_argument("--input", type=Path, help="导入本地公告 JSONL")
    args = parser.parse_args()

    collector = Path(__file__).resolve().parent
    if args.input:
        command = [str(collector / "ingest.py"), str(args.input.resolve())]
    else:
        command = [str(collector / "ccgp_collect.py"), *args.keywords]

    result = subprocess.run([sys.executable, *command])
    if result.returncode:
        return result.returncode
    return subprocess.run(
        [sys.executable, str(collector / "radar_brief.py")]
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
