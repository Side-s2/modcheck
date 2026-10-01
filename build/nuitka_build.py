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


def build(*, onefile: bool = False, output_dir: Path = Path("dist"),
          keep_intermediate: bool = False) -> int:
    """调用 Nuitka 构建；返回子进程退出码。

    参数：
        onefile: 生成单文件产物（首次启动约 7 秒，见 README）。
        output_dir: 输出目录；构建前会清空，避免上次失败留下的空壳产物混淆验收。
        keep_intermediate: 保留 Nuitka 的中间目录（默认清掉，减少残留干扰）。
    """
    _clean_output(output_dir)
    env = dict(os.environ)
    env.setdefault("NUITKA_CACHE_DIR", str(ROOT / ".toolchain" / "nuitka-cache"))
    env.setdefault("TEMP", str(ROOT / ".toolchain" / "tmp"))
    env.setdefault("TMP", env["TEMP"])
    # src 布局：必须让 Nuitka 能找到 modcheck 包（否则报 failed to locate package）
    env["PYTHONPATH"] = str(ROOT / "src")
    # 注意：Nuitka **没有** --python-path 选项（那是 PyInstaller 的 --paths），
    # 让它找到 src 布局里的包只能靠 PYTHONPATH 环境变量 + --include-package。
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
    if not keep_intermediate:
        # 中间产物残留会让下一次构建偶发失败（实测报过 __constants.h 找不到）
        cmd.append("--remove-output")
    # 两种模式都要把产物名统一成 modcheck（否则 onefile 会叫 __main__.exe）
    cmd.append("--output-filename=modcheck")
    cmd.append(str(ROOT / "src" / "modcheck" / "__main__.py"))
    code = subprocess.call(cmd, cwd=str(ROOT), env=env)
    if code == 0:
        _fix_dist_name(Path(output_dir), onefile)
    return code


def _clean_output(output_dir: Path) -> None:
    """构建前清空输出目录（上一次失败的 0 字节产物最容易骗过验收）。"""
    import shutil

    target = Path(output_dir)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)


def _fix_dist_name(output_dir: Path, onefile: bool) -> None:
    """把 Nuitka 按入口脚本名生成的 __main__.dist 改成 modcheck（产物更好看）。"""
    import shutil

    auto = Path(output_dir) / "__main__.dist"
    wanted = Path(output_dir) / "modcheck"
    if auto.is_dir() and not wanted.exists():
        try:
            shutil.move(str(auto), str(wanted))
        except OSError:
            pass
    elif onefile:
        auto_exe = Path(output_dir) / "__main__.exe"
        wanted_exe = Path(output_dir) / "modcheck.exe"
        if auto_exe.is_file() and not wanted_exe.exists():
            try:
                shutil.move(str(auto_exe), str(wanted_exe))
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="使用 Nuitka 打包 modcheck")
    parser.add_argument("--onefile", action="store_true", help="生成单文件（首次启动较慢）")
    parser.add_argument("--output-dir", default="dist", help="输出目录")
    parser.add_argument("--keep-intermediate", action="store_true",
                        help="保留 Nuitka 中间目录（默认构建成功后清掉）")
    args = parser.parse_args(argv)
    return build(onefile=args.onefile, output_dir=Path(args.output_dir),
                 keep_intermediate=args.keep_intermediate)


if __name__ == "__main__":
    raise SystemExit(main())
