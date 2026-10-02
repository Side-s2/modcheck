# -*- coding: utf-8 -*-
"""整理开源发布所需的文件到 publish/，并可选打一个源码包。

为什么要有这个脚本
------------------
publish/ 里的文档**都是副本**（README 要同时留在仓库根目录给 GitHub 看）。
手工复制迟早会不一致：改了 README，publish/ 里还是旧的 ——
而"发布页写着 A、仓库里写着 B"是最难被发现的一类问题。
所以 publish/ **一律由本脚本生成**：只改源文件，然后重跑一次。

用法：
    python build/make_publish.py              # 同步文档到 publish/
    python build/make_publish.py --source-zip  # 额外打一个源码 zip
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLISH = ROOT / "publish"

#: (源文件, publish 里的文件名, 说明)
DOCS = (
    ("README.md", "README.md", "发布门面：用途、两种版本、下载与快速上手"),
    ("LICENSE", "LICENSE", "GPL-3.0 全文"),
    ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md", "第三方组件与数据来源"),
    ("docs/TUTORIAL.md", "TUTORIAL.md", "面向新手的完整教程"),
    ("docs/RELEASE_CHECKLIST.md", "RELEASE_CHECKLIST.md", "发版步骤清单（含已知坑）"),
)

#: 源码包里要带上的目录与文件
SOURCE_ITEMS = ("src", "tests", "build", "docs", "assets",
                "pyproject.toml", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
                "modcheck.cmd", "modcheck.sh", ".gitignore")

#: 源码包里**必须排除**的东西（临时产物与打包输出）
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".toolchain", "dist", "dist-gui",
                "dist-standalone", "testresult", "publish"}
EXCLUDE_SUFFIX = (".pyc", ".pyo")


def sync_docs() -> list[str]:
    """把源文档复制进 publish/；返回做了哪些事（供调用方打印）。"""
    PUBLISH.mkdir(exist_ok=True)
    done = []
    for source, name, note in DOCS:
        src = ROOT / source
        if not src.is_file():
            done.append(f"  ⚠ 缺少 {source}（跳过）")
            continue
        shutil.copy2(src, PUBLISH / name)
        done.append(f"  ✅ {name:24s} ← {source}    （{note}）")
    return done


def version() -> str:
    """从 pyproject.toml 读版本号（不 import，避免依赖项目代码）。"""
    for line in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "0.0.0"


def make_source_zip() -> Path:
    """打一个源码 zip（给 GitHub Release 的 Source code 用）。"""
    target = PUBLISH / f"modcheck-{version()}-source.zip"
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in SOURCE_ITEMS:
            path = ROOT / item
            if path.is_file():
                zf.write(path, item)
                count += 1
            elif path.is_dir():
                for f in sorted(path.rglob("*")):
                    if not f.is_file():
                        continue
                    if any(part in EXCLUDE_DIRS for part in f.parts):
                        continue
                    if f.suffix in EXCLUDE_SUFFIX:
                        continue
                    zf.write(f, str(f.relative_to(ROOT)))
                    count += 1
    print(f"  已打包 {target.name}（{count} 个文件，{target.stat().st_size / 1024:.0f} KB）")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="整理开源发布文件")
    parser.add_argument("--source-zip", action="store_true", help="额外打一个源码 zip")
    args = parser.parse_args(argv)
    print("同步发布文档到 publish/：")
    for line in sync_docs():
        print(line)
    if args.source_zip:
        print("打包源码：")
        make_source_zip()
    print(f"\npublish/ 已就绪：{PUBLISH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
