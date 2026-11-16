# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
"""手动运行或交给 Windows 任务计划程序执行的公开公告采集入口。"""

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from core.radar_config import keywords, sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keywords", nargs="*")
    parser.add_argument("--input", type=Path, help="导入本地公告 JSONL")
    parser.add_argument("--configured", action="store_true", help="按配置中的词表联机采集")
    args = parser.parse_args()
    if not (args.input or args.keywords or args.configured):
        parser.error("请提供检索词、--configured 或 --input")
    settings = keywords()

    collector = Path(__file__).resolve().parent
    if args.input:
        command = [str(collector / "ingest.py"), str(args.input.resolve())]
    else:
        adapters = [item for item in sources() if item["enabled"]]
        if not adapters:
            parser.error("没有启用的信源")
        for item in adapters:
            name = item["name"]
            if not name.isidentifier():
                parser.error("信源标识无效")
            adapter = collector / (name + "_collect.py")
            if not adapter.is_file():
                parser.error("未安装信源适配器：" + name)
            terms = args.keywords or item.get("keywords") or settings["good"][:3]
            if not terms:
                parser.error("请配置检索词或从命令行提供检索词")
            result = subprocess.run([sys.executable, str(adapter), *terms])
            if result.returncode:
                return result.returncode
        command = None

    if command:
        result = subprocess.run([sys.executable, *command])
        if result.returncode:
            return result.returncode
    return subprocess.run(
        [sys.executable, str(collector / "radar_brief.py")]
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
