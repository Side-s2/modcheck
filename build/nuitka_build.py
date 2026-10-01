"""Nuitka 打包脚本（T-22）。

实测约束（见 ENGINEERING_CONTRACT §1.2）：
  * 系统自带 MinGW gcc 8.1.0 会被 Nuitka 拒绝，必须允许它下载配套 winlibs-gcc；
  * --assume-yes-for-downloads **必须加**，否则 Nuitka 会交互式询问然后中止；
  * 缓存目录必须指向工作区内，否则写用户目录会被沙箱拒绝。

用法：
    python build/nuitka_build.py                 # standalone（推荐默认）
    python build/nuitka_build.py --onefile       # 单文件（首次启动约 7 秒，见 README）
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: 从分发包里彻底排除的开发期依赖
EXCLUDES = ("pytest", "_pytest", "unittest", "pydoc", "doctest", "pdb", "test")


def build(*, onefile: bool = False, output_dir: Path = Path("dist"), clean: bool = False) -> int:
    """调用 Nuitka 构建；返回子进程退出码。"""
    env = dict(os.environ)
    env.setdefault("NUITKA_CACHE_DIR", str(ROOT / ".toolchain" / "nuitka-cache"))
    env.setdefault("TEMP", str(ROOT / ".toolchain" / "tmp"))
    env.setdefault("TMP", env["TEMP"])
    cmd = [sys.executable, "-m", "nuitka",
           "--assume-yes-for-downloads",          # 必须：否则会交互式询问并中止
           "--onefile" if onefile else "--standalone",
           "--output-dir=" + str(output_dir),
           "--include-package=modcheck",
           "--company-name=modcheck",
           "--product-name=modcheck",
           "--file-version=0.1.0",
           "--product-version=0.1.0"]
    for name in EXCLUDES:
        cmd.append("--nofollow-import-to=" + name)
    if clean:
        cmd.append("--remove-output")
    if not onefile:
        cmd.append("--output-filename=modcheck")
    cmd.append(str(ROOT / "src" / "modcheck" / "__main__.py"))
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="使用 Nuitka 打包 modcheck")
    parser.add_argument("--onefile", action="store_true", help="生成单文件（首次启动较慢）")
    parser.add_argument("--output-dir", default="dist", help="输出目录")
    parser.add_argument("--clean", action="store_true", help="构建前清理中间产物")
    args = parser.parse_args(argv)
    return build(onefile=args.onefile, output_dir=Path(args.output_dir), clean=args.clean)


if __name__ == "__main__":
    raise SystemExit(main())
